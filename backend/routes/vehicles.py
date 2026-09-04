"""MG-VMS v0.6 · Smart ANPR History — Vehicle Timeline API.

Cette route agrège la collection ``plates`` sans jamais modifier le
pipeline OCR ni les endpoints ``/api/plates`` existants.

Endpoints (tous read-only) :

  GET  /api/vehicles                           liste agrégée (cartes)
  GET  /api/vehicles/{plate}                   fiche complète
  GET  /api/vehicles/{plate}/passages          galerie paginée
  GET  /api/vehicles/{plate}/heatmap           by_hour[24] + by_dow[7]
  GET  /api/vehicles/{plate}/cameras           passages par caméra
  GET  /api/vehicles/{plate}/journey           transitions caméra→caméra
  GET  /api/vehicles/{plate}/habits            présence habituelle
  GET  /api/vehicles/{plate}/identity          stub v0.6 (préparation v0.7)
  GET  /api/vehicles/passage/{id}/thumb        image binaire JPEG (base64→bytes)

Le champ ``list_status`` (watchlist) et le moteur OCR ne sont **pas**
modifiés — cette couche est purement additive.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from statistics import mean
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import require_permission, require_role, log_audit
from database import db

logger = logging.getLogger("routes.vehicles")

vehicles_router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════
def _majority(values: list) -> Optional[str]:
    """Retourne la valeur la plus fréquente, en ignorant None/empty."""
    filtered = [v for v in values if v]
    if not filtered:
        return None
    return Counter(filtered).most_common(1)[0][0]


def _iso_to_dt(iso: str) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════
# v3.17 · Fusion des plaques quasi-identiques (variantes OCR)
# ═══════════════════════════════════════════════════════════════════
# Une même plaque physique peut être lue différemment d'un passage à
# l'autre (confusion OCR sur un caractère : M/N/H, 0/O, 8/B...), surtout
# quand le suivi perd puis reprend le même véhicule en quelques secondes —
# chaque reprise déclenche une lecture OCR indépendante. Sans fusion, la
# page Véhicules affichait 3 fiches pour 1 seule voiture.
#
# Approche en 2 phases, volontairement PRUDENTE (contexte vidéosurveillance —
# une fusion à tort peut faire disparaître le passage d'un VRAI second
# véhicule d'une recherche) :
#   1. Regroupement EXACT (comme avant) — sans limite de temps : la même
#      plaque vue à des heures d'écart reste une seule fiche.
#   2. Fusion des groupes exacts entre eux, UNIQUEMENT si deux variantes
#      sont à distance d'édition ≤ 1 ET ont été vues sur la MÊME caméra à
#      moins de `_PLATE_MERGE_WINDOW_SEC` d'intervalle. Le format des
#      plaques françaises n'a pas de somme de contrôle : deux vrais
#      véhicules PEUVENT avoir des plaques à 1 caractère près. Exiger la
#      même caméra + une fenêtre courte rend cette collision quasi
#      impossible tout en couvrant le cas réel visé ici.
_PLATE_MERGE_WINDOW_SEC = 120
_PLATE_MERGE_MAX_DISTANCE = 1


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > _PLATE_MERGE_MAX_DISTANCE + 1:
        return max(la, lb)  # trop loin pour être sous le seuil, évite le calcul complet
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * lb
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]


class _UnionFind:
    def __init__(self, items):
        self.parent = {x: x for x in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _deletion_variants(s: str):
    """Toutes les chaînes obtenues en supprimant UN caractère de `s`.

    Base de l'index ci-dessous (technique dite « SymSpell ») : si deux
    plaques sont à distance d'édition ≤ 1, alors soit elles sont
    identiques, soit l'une est l'autre moins un caractère (insertion/
    suppression), soit elles ont la même longueur et ne diffèrent que
    par UNE substitution — dans ce dernier cas, supprimer cette position
    dans les DEUX donne la même chaîne. Dans les trois cas, les deux
    plaques partagent donc au moins une clé (elles-mêmes ou une de leurs
    variantes à un caractère près), qui sert d'index.
    """
    return (s[:i] + s[i + 1:] for i in range(len(s)))


def _cluster_plate_groups(passages: dict[str, list[tuple[str, datetime]]]) -> list[list[str]]:
    """Regroupe des plaques exactes entre elles selon la règle ci-dessus.

    Args:
        passages: plaque exacte -> liste de (camera_id, timestamp) pour
            CHAQUE lecture (pas juste un résumé) — nécessaire pour vérifier
            la fenêtre de temps par caméra.
    Returns:
        Liste de groupes ; chaque groupe est une liste de plaques exactes
        à fusionner en une seule fiche.

    v3.17 · Première version : comparaison de toutes les paires de plaques
    de longueur voisine. Mesuré en conditions réelles (1477 plaques
    distinctes, quasi toutes à 7 caractères — format français) : 9,5 s,
    inutilisable pour une route HTTP. La quasi-totalité des plaques tombant
    dans le MÊME seau de longueur, ce filtre ne réduisait presque rien.
    Remplacé par l'index de suppression ci-dessus : la comparaison réelle
    (Levenshtein) ne s'exécute plus que sur les rares candidats qui
    partagent déjà une clé, pas sur toutes les paires. Même résultat,
    < 50 ms mesuré sur le même jeu de données.
    """
    plates = list(passages.keys())
    uf = _UnionFind(plates)

    index: dict[str, list[str]] = {}
    for p in plates:
        index.setdefault(p, []).append(p)
        for v in _deletion_variants(p):
            index.setdefault(v, []).append(p)

    for p1 in plates:
        cams1 = passages[p1]
        keys = [p1] if not p1 else [p1] + list(_deletion_variants(p1))
        seen_candidates: set[str] = set()
        for key in keys:
            for p2 in index.get(key, ()):
                if p2 == p1 or p2 in seen_candidates:
                    continue
                seen_candidates.add(p2)
                if uf.find(p1) == uf.find(p2):
                    continue
                if _levenshtein(p1, p2) > _PLATE_MERGE_MAX_DISTANCE:
                    continue  # collision de clé sans être réellement proche (rare)
                linked = any(
                    cam1 == cam2 and abs((t1 - t2).total_seconds()) <= _PLATE_MERGE_WINDOW_SEC
                    for cam1, t1 in cams1 for cam2, t2 in passages[p2]
                )
                if linked:
                    uf.union(p1, p2)

    clusters: dict[str, list[str]] = {}
    for p in plates:
        clusters.setdefault(uf.find(p), []).append(p)
    return list(clusters.values())


# ═══════════════════════════════════════════════════════════════════
# v3.18 · Fusion manuelle (identités véhicule) — pas de calcul de
# similarité, 100% déterministe et contrôlée par un humain.
# ═══════════════════════════════════════════════════════════════════
# Contexte : une tentative de fusion AUTOMATIQUE par similarité d'image
# (dHash sur le crop véhicule) a été testée puis abandonnée ce soir — sur
# les données réelles, le signal n'était pas assez discriminant (une
# caméra chargée produisait des groupes de centaines de plaques
# distinctes fusionnées à tort, quel que soit le seuil ou l'algorithme de
# liaison essayé). Zéro risque de faux positif avec cette approche-ci
# puisque c'est un opérateur qui choisit explicitement les fiches à
# fusionner (bouton dans l'UI), pas un calcul.
#
# `POST /vehicles/identities` (plus bas) existait déjà mais n'était
# raccordé à AUCUN endroit — créer une identité n'avait jusqu'ici aucun
# effet visible sur la liste principale. On la branche ici : deux groupes
# de plaques qui partagent une plaque au sein d'une même identité
# fusionnent en une seule fiche, au même titre qu'une fusion textuelle.
async def _merge_by_identity(groups: list[list[str]]) -> list[list[str]]:
    identities = await db.vehicle_identities.find({}, {"_id": 0, "plates": 1}).to_list(2000)
    if not identities:
        return groups
    plate_to_group: dict[str, int] = {}
    for gi, group in enumerate(groups):
        for p in group:
            plate_to_group[p] = gi
    uf = _UnionFind(list(range(len(groups))))
    for ident in identities:
        member_groups = {plate_to_group[p] for p in (ident.get("plates") or []) if p in plate_to_group}
        member_groups = list(member_groups)
        for k in range(1, len(member_groups)):
            uf.union(member_groups[0], member_groups[k])
    merged: dict[int, list[str]] = {}
    for gi, group in enumerate(groups):
        merged.setdefault(uf.find(gi), []).extend(group)
    return list(merged.values())


def _to_hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


async def _base_match(user: dict, plate_filter: Optional[str] = None,
                       camera_id: Optional[str] = None,
                       date_from: Optional[str] = None,
                       date_to: Optional[str] = None) -> dict:
    """Construit le $match Mongo standard (avec site_scope)."""
    q: dict = {}
    if plate_filter:
        q["plate"] = {"$regex": plate_filter.upper().replace(" ", ""), "$options": "i"}
    if camera_id:
        q["camera_id"] = camera_id
    if date_from or date_to:
        rng = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["timestamp"] = rng
    # site_scope respecte l'appartenance de l'utilisateur.
    try:
        from routers import site_scope
        site_scope(q, user)
    except Exception:
        pass
    return q


async def _plate_or_404(plate: str, user: dict) -> str:
    """Normalise + vérifie qu'au moins une lecture existe pour cette plaque."""
    normalized = plate.upper().replace(" ", "").replace("-", "")
    q = await _base_match(user)
    q["plate"] = {"$regex": normalized, "$options": "i"}
    count = await db.plates.count_documents(q)
    if count == 0:
        raise HTTPException(status_code=404,
                            detail={"error": "vehicle_not_found",
                                    "message": f"Aucune lecture pour la plaque '{plate}'"})
    return normalized


# v3.19 · La page Véhicules (chip « Plaques ») paginait déjà côté
# affichage (60 tuiles + bouton "Charger plus"), mais CÔTÉ SERVEUR chaque
# requête — y compris chaque clic "Charger plus" sur la MÊME liste —
# relisait toute la collection filtrée et refaisait tout le clustering
# Python depuis zéro. Mesuré en conditions réelles (10 402 plaques, 14
# caméras) : ~1 s par requête, identique pour offset=0 ou offset=60,
# c'est ce qui rendait le menu "long à charger". Le clustering ne dépend
# que du filtre (q/camera_id/date_from/date_to), pas de l'offset : on met
# donc en cache la liste complète déjà triée pendant quelques secondes —
# le premier chargement paie le coût une fois, tous les "Charger plus"
# qui suivent dans la foulée deviennent une simple slice en mémoire.
_LIST_CACHE_TTL_S = 8.0
_list_cache: dict[str, tuple[float, int, list[dict]]] = {}


def _list_cache_key(match: dict) -> str:
    return json.dumps(match, sort_keys=True, default=str)


# ═══════════════════════════════════════════════════════════════════
# 1. Liste agrégée — /api/vehicles
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("")
async def list_vehicles(
    q: Optional[str] = Query(None, description="Substring plaque"),
    camera_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_permission("read_plates")),
):
    """Liste agrégée des véhicules détectés (une entrée par plaque, plaques
    quasi-identiques fusionnées — voir `_cluster_plate_groups`)."""
    match = await _base_match(user, plate_filter=q, camera_id=camera_id,
                                date_from=date_from, date_to=date_to)

    cache_key = _list_cache_key(match)
    cached = _list_cache.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < _LIST_CACHE_TTL_S:
        total, items = cached[1], cached[2]
        page = items[offset:offset + limit]
        return {"total": total, "count": len(page), "items": page}

    # v3.17 · La fusion de plaques proches (OCR) nécessite de connaître
    # chaque lecture individuelle (caméra + horodatage), pas seulement un
    # résumé par plaque exacte — le regroupement se fait donc côté Python.
    # `to_list(8000)` borne le coût : au-delà, il faudra matérialiser les
    # clusters dans une tâche de fond plutôt que les recalculer à la volée
    # à chaque requête (la base fait ~2000 plaques au 2026-08-26 — large
    # marge pour l'instant).
    # v3.17 · PAS de has_frame/has_vehicle/has_plate ici (contrairement à
    # /passages plus bas, qui filtre une SEULE plaque). Mesuré : même
    # projetés uniquement pour en calculer la longueur (jamais renvoyés),
    # référencer frame_thumb/vehicle_crop/plate_crop oblige MongoDB à
    # décompresser ces champs (jusqu'à ~700 Ko chacun) pour CHAQUE document
    # scanné — 2349 ms pour 2888 lectures contre 28 ms sans. Cette liste
    # parcourt potentiellement TOUTE la collection (pas une seule plaque) :
    # le coût qui était acceptable là-bas explose ici. `preview_thumb_ids`
    # inclut donc les 3 derniers ids sans ce filtre (le pire cas est une
    # vignette occasionnellement vide, déjà géré côté affichage).
    #
    # ⚠ Ce correctif avait déjà été appliqué et vérifié (2349ms -> 28ms) une
    # première fois ce soir, mais seulement patché à chaud sans commit — il
    # a été perdu au redéploiement suivant. Committé cette fois.
    raw = await db.plates.find(match, {
        "_id": 0, "id": 1, "plate": 1, "camera_id": 1, "timestamp": 1,
        "confidence": 1, "vehicle_make": 1, "vehicle_model": 1,
        "vehicle_color": 1, "vehicle_type": 1, "list_status": 1,
    }).sort("timestamp", -1).to_list(8000)

    passages: dict[str, list[tuple[str, datetime]]] = {}
    by_plate: dict[str, list[dict]] = {}
    for d in raw:
        dt = _iso_to_dt(d.get("timestamp")) or datetime.now(timezone.utc)
        p = d["plate"]
        passages.setdefault(p, []).append((d.get("camera_id"), dt))
        by_plate.setdefault(p, []).append(d)

    groups = _cluster_plate_groups(passages)
    groups = await _merge_by_identity(groups)

    total = 0
    items = []
    for group in groups:
        docs = [d for p in group for d in by_plate[p]]
        docs.sort(key=lambda d: d.get("timestamp") or "", reverse=True)  # plus récent d'abord
        conf_list = [d["confidence"] for d in docs if isinstance(d.get("confidence"), (int, float))]

        # Plaque canonique = la variante à la MEILLEURE confiance moyenne
        # (plus fiable qu'une simple majorité : une erreur OCR répétée ne
        # doit pas l'emporter sur une lecture nette mais rare).
        per_variant: dict[str, list[float]] = {}
        for d in docs:
            per_variant.setdefault(d["plate"], []).append(d.get("confidence") or 0.0)
        canonical = max(per_variant.items(), key=lambda kv: (mean(kv[1]), len(kv[1])))[0]

        preview = docs[:3]
        best = preview[0] if preview else None
        cameras = {d.get("camera_id") for d in docs if d.get("camera_id")}

        total += 1
        items.append({
            "plate": canonical,
            "passages_count": len(docs),
            "first_seen": docs[-1].get("timestamp") if docs else None,
            "last_seen": docs[0].get("timestamp") if docs else None,
            "cameras_count": len(cameras),
            "vehicle_make": _majority([d.get("vehicle_make") for d in docs]),
            "vehicle_model": _majority([d.get("vehicle_model") for d in docs]),
            "vehicle_color": _majority([d.get("vehicle_color") for d in docs]),
            "vehicle_type": _majority([d.get("vehicle_type") for d in docs]),
            "avg_confidence": round(mean(conf_list), 3) if conf_list else None,
            "best_thumb_id": (best or {}).get("id"),
            "preview_thumb_ids": [p["id"] for p in preview],
            "list_status": docs[0].get("list_status") or "none" if docs else "none",
            # Traçabilité : variantes OCR fusionnées dans cette fiche, hors
            # la canonique — utile pour un futur affichage ("lu aussi : ...").
            "plate_variants": sorted(v for v in per_variant if v != canonical),
        })
    items.sort(key=lambda it: it.get("last_seen") or "", reverse=True)
    _list_cache[cache_key] = (now, total, items)
    if len(_list_cache) > 200:  # garde-fou : évite une fuite mémoire si beaucoup de filtres distincts
        oldest_key = min(_list_cache, key=lambda k: _list_cache[k][0])
        _list_cache.pop(oldest_key, None)
    page = items[offset:offset + limit]
    return {"total": total, "count": len(page), "items": page}


# ═══════════════════════════════════════════════════════════════════
# 1b. Vehicle Identities (cross-plate matching · v0.7)
# ═══════════════════════════════════════════════════════════════════
class IdentityBody(BaseModel):
    name: str = ""
    plates: list[str]
    vehicle_make: Optional[str] = None
    vehicle_color: Optional[str] = None
    vehicle_type: Optional[str] = None
    notes: Optional[str] = ""


@vehicles_router.get("/anpr-log/top")
async def anpr_log_top_vehicles(
    limit: int = Query(200, ge=1, le=1000),
    user: dict = Depends(require_permission("read_plates")),
):
    """v3.31 · Menu Journaux → Log ANPR : tableau des véhicules les plus
    lus, toutes caméras confondues (dans la portée du site de
    l'utilisateur), triés par nombre d'occurrences décroissant. Demande
    explicite : un tableau, rien de plus — pas de graphique/agrégat
    visuel, juste la liste triée."""
    match = await _base_match(user)
    pipeline = [
        {"$match": match},
        {"$sort": {"timestamp": 1}},  # pour que $last reflète bien la lecture la plus récente
        {"$group": {
            "_id": "$plate",
            "occurrences": {"$sum": 1},
            "cameras": {"$addToSet": "$camera_id"},
            "last_seen": {"$max": "$timestamp"},
            "vehicle_color": {"$last": "$vehicle_color"},
            "vehicle_type": {"$last": "$vehicle_type"},
        }},
        {"$sort": {"occurrences": -1}},
        {"$limit": limit},
    ]
    rows = await db.plates.aggregate(pipeline).to_list(limit)
    items = [{
        "plate": r["_id"],
        "occurrences": r["occurrences"],
        "cameras_count": len(r.get("cameras") or []),
        "last_seen": r.get("last_seen"),
        "vehicle_color": r.get("vehicle_color") or "",
        "vehicle_type": r.get("vehicle_type") or "",
    } for r in rows]
    return {"count": len(items), "items": items}


@vehicles_router.get("/identities")
async def list_identities(user: dict = Depends(require_permission("read_plates"))):
    """Liste toutes les identités véhicule (regroupement cross-plate)."""
    docs = await db.vehicle_identities.find({}, {"_id": 0}).sort("updated_at", -1) \
                                       .to_list(length=500)
    return {"count": len(docs), "items": docs}


@vehicles_router.post("/identities")
async def create_identity(body: IdentityBody,
                           user: dict = Depends(require_permission("read_plates"))):
    """Crée une identité véhicule cross-plate."""
    import uuid as _uuid
    plates = sorted({_norm_plate(p) for p in body.plates if p})
    if len(plates) < 1:
        raise HTTPException(status_code=400,
                            detail={"error": "empty_plates",
                                    "message": "Au moins une plaque est requise."})
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(_uuid.uuid4()),
        "name": (body.name or plates[0]).strip(),
        "plates": plates,
        "vehicle_make": body.vehicle_make,
        "vehicle_color": body.vehicle_color,
        "vehicle_type": body.vehicle_type,
        "notes": body.notes or "",
        "created_by": user.get("email"),
        "created_at": now,
        "updated_at": now,
    }
    await db.vehicle_identities.insert_one(doc.copy())
    doc.pop("_id", None)
    _list_cache.clear()  # une fusion/création d'identité change le regroupement affiché
    return doc


@vehicles_router.get("/identities/{identity_id}")
async def get_identity(identity_id: str,
                        user: dict = Depends(require_permission("read_plates"))):
    doc = await db.vehicle_identities.find_one({"id": identity_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail={"error": "identity_not_found"})
    # Statistiques agrégées sur toutes les plaques de l'identité
    match = await _base_match(user)
    match["plate"] = {"$in": doc.get("plates", [])}
    stats_pipe = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "passages_count": {"$sum": 1},
            "cameras": {"$addToSet": "$camera_id"},
            "first_seen": {"$min": "$timestamp"},
            "last_seen": {"$max": "$timestamp"},
        }},
    ]
    stat = (await db.plates.aggregate(stats_pipe).to_list(1)) or [{}]
    s = stat[0]
    doc["stats"] = {
        "passages_count": s.get("passages_count", 0),
        "cameras_count": len(s.get("cameras") or []),
        "first_seen": s.get("first_seen"),
        "last_seen": s.get("last_seen"),
    }
    return doc


@vehicles_router.delete("/identities/{identity_id}")
async def delete_identity(identity_id: str,
                           user: dict = Depends(require_permission("read_plates"))):
    res = await db.vehicle_identities.delete_one({"id": identity_id})
    return {"ok": True, "deleted": res.deleted_count}


class BulkDeleteBody(BaseModel):
    plates: list[str]
    confirm: bool = False


@vehicles_router.post("/bulk-delete")
async def bulk_delete_vehicles(body: BulkDeleteBody,
                                user: dict = Depends(require_role("admin"))):
    """v3.20 · Suppression définitive d'une ou plusieurs fiches véhicule —
    lectures ANPR (les images sont stockées en base64 DANS ces documents,
    voir CHANGELOG v3.15 : les supprimer supprime aussi les miniatures,
    pas de fichier séparé à nettoyer), plus toute référence dans les
    identités fusionnées / validations / suggestions de doublon. Admin
    uniquement + confirmation explicite requise (irréversible)."""
    plates = sorted({(_norm_plate(p) if p else "") for p in body.plates if p})
    if not plates:
        raise HTTPException(400, "Au moins une plaque est requise")
    if not body.confirm:
        raise HTTPException(400, {"code": "CONFIRM_REQUIRED",
                                    "message": "Confirmation requise (confirm: true) — suppression définitive."})

    plates_result = await db.plates.delete_many({"plate": {"$in": plates}})

    # Retire ces plaques des identités fusionnées existantes ; supprime
    # l'identité entière si elle ne contient plus aucune plaque restante.
    async for ident in db.vehicle_identities.find({"plates": {"$in": plates}}, {"_id": 0, "id": 1, "plates": 1}):
        remaining = [p for p in ident["plates"] if p not in plates]
        if remaining:
            await db.vehicle_identities.update_one({"id": ident["id"]}, {"$set": {"plates": remaining}})
        else:
            await db.vehicle_identities.delete_one({"id": ident["id"]})

    await db.plate_validations.delete_many(
        {"$or": [{"canonical_plate": {"$in": plates}}, {"variants": {"$in": plates}}]}
    )
    await db.dedup_suggestions.delete_many(
        {"$or": [{"plate_a": {"$in": plates}}, {"plate_b": {"$in": plates}}]}
    )
    _list_cache.clear()
    await log_audit(user, "vehicle_bulk_deleted", ", ".join(plates), str(plates_result.deleted_count))
    return {"ok": True, "plates": plates, "reads_deleted": plates_result.deleted_count}


# ═══════════════════════════════════════════════════════════════════
# 1c. Smart Search (langage naturel → filtres) · v0.7
# ═══════════════════════════════════════════════════════════════════
class SmartSearchBody(BaseModel):
    query: str


@vehicles_router.post("/smart-search")
async def smart_search(body: SmartSearchBody,
                        user: dict = Depends(require_permission("read_plates"))):
    """Traduit une requête en langage naturel en filtres structurés et exécute
    la recherche. Utilise Claude Sonnet 5 via Emergent LLM Key pour le parsing.

    Exemples de requêtes utilisateur :
      · « trouve moi la plaque AA-123-CD ce matin »
      · « voitures rouges hier »
      · « camions passés à l'entrée nord entre 8h et 10h »
    """
    import os
    import json
    import uuid as _uuid
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    q_text = (body.query or "").strip()
    if not q_text:
        raise HTTPException(status_code=400,
                            detail={"error": "empty_query", "message": "Requête vide"})

    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        # v1.0-rc4 · Code normalisé + 503 (service indisponible, pas 500).
        raise HTTPException(status_code=503,
                            detail={"code": "SMART_SEARCH_LLM_NOT_CONFIGURED",
                                    "error": "no_llm_key",
                                    "message": "La recherche IA n'est pas configurée sur ce serveur. "
                                               "Ajouter EMERGENT_LLM_KEY dans deploy-app/.env."})

    system = (
        "Tu es un parseur qui convertit une requête utilisateur en JSON strict "
        "pour filtrer une base de lectures ANPR (plaques d'immatriculation). "
        "Réponds UNIQUEMENT avec un objet JSON valide, aucun texte autre.\n\n"
        "Schéma :\n"
        "{\n"
        '  "plate": string|null,          // fragment de plaque\n'
        '  "colors": [string],            // ex: ["rouge","noir"] (français ou anglais)\n'
        '  "makes": [string],             // marques\n'
        '  "types": [string],             // "voiture", "camion", "moto", "bus"\n'
        '  "date_from": "YYYY-MM-DD"|null,\n'
        '  "date_to":   "YYYY-MM-DD"|null,\n'
        '  "time_from": "HH:MM"|null,\n'
        '  "time_to":   "HH:MM"|null,\n'
        '  "camera_hint": string|null,    // nom/mot-clé caméra si présent\n'
        '  "person_description": string|null  // si la requête concerne une personne\n'
        "}\n\n"
        f"Date courante : {datetime.now(timezone.utc).date().isoformat()}.\n"
        "« ce matin » = 06:00-12:00 aujourd'hui. « hier » = date - 1. « cette semaine » = 7 derniers jours."
    )

    try:
        chat = LlmChat(api_key=key, session_id=f"smart-search-{_uuid.uuid4().hex[:8]}",
                        system_message=system).with_model("anthropic", "claude-sonnet-5")
        raw = await chat.send_message(UserMessage(text=q_text))
    except Exception as e:
        logger.warning("smart-search LLM failed: %s", e)
        raise HTTPException(status_code=502,
                            detail={"error": "llm_error", "message": str(e)[:200]})

    # Nettoyage de la réponse LLM (peut contenir ```json ... ```)
    txt = (raw or "").strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.startswith("json"):
            txt = txt[4:].strip()
    try:
        filters = json.loads(txt)
    except Exception:
        raise HTTPException(status_code=502,
                            detail={"error": "llm_parse_error",
                                    "message": "Impossible d'interpréter la réponse du LLM.",
                                    "raw": txt[:300]})

    # ── Exécute la recherche depuis les filtres extraits ──
    match = await _base_match(user)
    if filters.get("plate"):
        match["plate"] = {"$regex": _norm_plate(filters["plate"]), "$options": "i"}
    if filters.get("colors"):
        # Traduction FR→EN basique + case-insensitive
        color_map = {"rouge": "red", "noir": "black", "blanc": "white", "bleu": "blue",
                     "vert": "green", "jaune": "yellow", "gris": "gray", "argent": "silver",
                     "orange": "orange", "marron": "brown"}
        colors_all = set()
        for c in filters["colors"]:
            if not c: continue
            colors_all.add(c.lower())
            mapped = color_map.get(c.lower())
            if mapped: colors_all.add(mapped)
            # Reverse : si l'user a écrit "red", ajouter "rouge"
            for fr, en in color_map.items():
                if en == c.lower(): colors_all.add(fr)
        regex = "|".join([f"^{c}$" for c in colors_all])
        match["vehicle_color"] = {"$regex": regex, "$options": "i"}
    if filters.get("makes"):
        regex = "|".join([f"^{m}$" for m in filters["makes"] if m])
        if regex: match["vehicle_make"] = {"$regex": regex, "$options": "i"}
    if filters.get("types"):
        # types courants FR→EN
        type_map = {"voiture": "car", "camion": "truck", "moto": "motorcycle", "bus": "bus"}
        types_all = set()
        for t in filters["types"]:
            if not t: continue
            types_all.add(t.lower())
            mapped = type_map.get(t.lower())
            if mapped: types_all.add(mapped)
            for fr, en in type_map.items():
                if en == t.lower(): types_all.add(fr)
        regex = "|".join([f"^{t}$" for t in types_all])
        match["vehicle_type"] = {"$regex": regex, "$options": "i"}
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    time_from = filters.get("time_from") or "00:00"
    time_to = filters.get("time_to") or "23:59"
    if date_from or date_to:
        rng = {}
        if date_from:
            rng["$gte"] = f"{date_from}T{time_from}:00"
        if date_to:
            rng["$lte"] = f"{date_to}T{time_to}:59.999Z"
        match["timestamp"] = rng
    if filters.get("camera_hint"):
        # Match sur le nom de caméra (regex insensible)
        match["camera_name"] = {"$regex": filters["camera_hint"], "$options": "i"}

    # Agrégat par plaque comme dans /vehicles (top 30)
    pipe = [
        {"$match": match},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id": "$plate",
            "passages_count": {"$sum": 1},
            "last_seen":  {"$first": "$timestamp"},
            "first_seen": {"$last":  "$timestamp"},
            "cameras":    {"$addToSet": "$camera_id"},
            "makes":      {"$push": "$vehicle_make"},
            "models":     {"$push": "$vehicle_model"},
            "colors":     {"$push": "$vehicle_color"},
            "types":      {"$push": "$vehicle_type"},
            "best":       {"$first": "$id"},
        }},
        {"$sort": {"last_seen": -1}},
        {"$limit": 30},
    ]
    docs = await db.plates.aggregate(pipe).to_list(30)
    items = [{
        "plate": d["_id"],
        "passages_count": d["passages_count"],
        "first_seen": d.get("first_seen"),
        "last_seen": d.get("last_seen"),
        "cameras_count": len(d.get("cameras") or []),
        "vehicle_make": _majority(d.get("makes") or []),
        "vehicle_model": _majority(d.get("models") or []),
        "vehicle_color": _majority(d.get("colors") or []),
        "vehicle_type": _majority(d.get("types") or []),
        "best_thumb_id": d.get("best"),
    } for d in docs]

    return {
        "query": q_text,
        "filters": filters,
        "count": len(items),
        "items": items,
    }


# ═══════════════════════════════════════════════════════════════════
# 2. Fiche véhicule — /api/vehicles/{plate}
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}")
async def vehicle_detail(plate: str,
                          user: dict = Depends(require_permission("read_plates"))):
    normalized = await _plate_or_404(plate, user)
    match = await _base_match(user)
    match["plate"] = {"$regex": normalized, "$options": "i"}

    pipeline = [
        {"$match": match},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id": "$plate",
            "passages_count": {"$sum": 1},
            "last_seen":  {"$first": "$timestamp"},
            "first_seen": {"$last":  "$timestamp"},
            "cameras":    {"$addToSet": "$camera_id"},
            "makes":      {"$push": "$vehicle_make"},
            "models":     {"$push": "$vehicle_model"},
            "colors":     {"$push": "$vehicle_color"},
            "types":      {"$push": "$vehicle_type"},
            "confidences": {"$push": "$confidence"},
            "best_thumb_id": {"$first": "$id"},
            "engines":    {"$addToSet": "$engine"},
            "watch": {"$first": "$list_status"},
        }},
    ]
    docs = await db.plates.aggregate(pipeline).to_list(1)
    d = docs[0]
    conf = [c for c in (d.get("confidences") or []) if isinstance(c, (int, float))]

    # Durée moyenne de présence (approx : temps entre 1re et dernière passe par jour).
    daily_pipeline = [
        {"$match": match},
        {"$sort": {"timestamp": 1}},
        {"$project": {"day": {"$substr": ["$timestamp", 0, 10]}, "ts": "$timestamp"}},
        {"$group": {"_id": "$day",
                    "first": {"$min": "$ts"}, "last": {"$max": "$ts"}}},
    ]
    daily = await db.plates.aggregate(daily_pipeline).to_list(length=None)
    durations_min = []
    for row in daily:
        a = _iso_to_dt(row["first"])
        b = _iso_to_dt(row["last"])
        if a and b and b > a:
            durations_min.append((b - a).total_seconds() / 60.0)
    avg_visit = int(round(mean(durations_min))) if durations_min else None

    # v3.19 · La fiche affichait toujours la plaque demandée dans l'URL,
    # jamais la plaque canonique validée via le bloc "Consensus
    # multi-plugins" (POST /vehicles/{plate}/validate, table
    # plate_validations) — le titre restait donc figé sur l'ancienne
    # variante même après validation. `vehicle_validate_plate` prévoyait
    # déjà explicitement ce raccordement ("les endpoints consommateurs
    # peuvent l'utiliser pour ré-écrire la plaque affichée") mais rien ne
    # le faisait. On résout ici la plaque canonique si la plaque demandée
    # est elle-même canonique OU listée comme variante validée.
    display_plate = d["_id"]
    val_doc = await db.plate_validations.find_one(
        {"$or": [{"canonical_plate": normalized}, {"variants": normalized}]},
        {"_id": 0, "canonical_plate": 1},
    )
    if val_doc and val_doc.get("canonical_plate"):
        display_plate = val_doc["canonical_plate"]

    return {
        "plate": display_plate,
        "passages_count": d["passages_count"],
        "first_seen": d.get("first_seen"),
        "last_seen": d.get("last_seen"),
        "cameras_count": len(d.get("cameras") or []),
        "avg_confidence": round(mean(conf), 3) if conf else None,
        "vehicle_make": _majority(d.get("makes") or []),
        "vehicle_model": _majority(d.get("models") or []),
        "vehicle_color": _majority(d.get("colors") or []),
        "vehicle_type": _majority(d.get("types") or []),
        "avg_visit_duration_min": avg_visit,
        "best_thumb_id": d.get("best_thumb_id"),
        "engines": [e for e in (d.get("engines") or []) if e],
        "list_status": d.get("watch") or "none",
    }


# ═══════════════════════════════════════════════════════════════════
# 3. Galerie chronologique — /passages
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}/passages")
async def vehicle_passages(plate: str,
                            limit: int = Query(50, ge=1, le=200),
                            offset: int = Query(0, ge=0),
                            user: dict = Depends(require_permission("read_plates"))):
    normalized = await _plate_or_404(plate, user)
    q = await _base_match(user)
    q["plate"] = {"$regex": normalized, "$options": "i"}

    total = await db.plates.count_documents(q)
    # v3.13 · Cette liste ne renvoie que des booléens `has_*` — inutile de
    # rapatrier les images pour tester si elles sont vides. MongoDB calcule
    # le booléen côté serveur (expressions autorisées en projection depuis
    # la 4.4) : on passait de ~800 Ko à quelques octets par document.
    docs = await db.plates.find(q, {
        "_id": 0, "id": 1, "timestamp": 1, "camera_id": 1, "camera_name": 1,
        "confidence": 1, "engine": 1, "direction": 1,
        "has_frame": {"$gt": [{"$strLenCP": {"$ifNull": ["$frame_thumb", ""]}}, 0]},
        "has_vehicle": {"$gt": [{"$strLenCP": {"$ifNull": ["$vehicle_crop", ""]}}, 0]},
        "has_plate": {"$gt": [{"$strLenCP": {"$ifNull": ["$plate_crop", ""]}}, 0]},
    }).sort("timestamp", -1).skip(offset).limit(limit).to_list(limit)

    items = []
    for p in docs:
        items.append({
            "id": p.get("id"),
            "timestamp": p.get("timestamp"),
            "camera_id": p.get("camera_id"),
            "camera_name": p.get("camera_name"),
            "confidence": p.get("confidence"),
            "engine": p.get("engine") or "fast-alpr",
            "direction": p.get("direction"),
            "has_frame": bool(p.get("has_frame")),
            "has_vehicle": bool(p.get("has_vehicle")),
            "has_plate": bool(p.get("has_plate")),
        })
    return {"total": total, "count": len(items), "offset": offset, "items": items}


# ═══════════════════════════════════════════════════════════════════
# 4. Heatmap — /heatmap
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}/heatmap")
async def vehicle_heatmap(plate: str,
                           user: dict = Depends(require_permission("read_plates"))):
    normalized = await _plate_or_404(plate, user)
    q = await _base_match(user)
    q["plate"] = {"$regex": normalized, "$options": "i"}

    by_hour = [0] * 24
    by_dow = [0] * 7  # 0 = Lundi
    docs = await db.plates.find(q, {"timestamp": 1, "_id": 0}).to_list(length=None)
    for d in docs:
        dt = _iso_to_dt(d.get("timestamp"))
        if not dt:
            continue
        by_hour[dt.hour] += 1
        # Python weekday() : Monday=0
        by_dow[dt.weekday()] += 1

    return {
        "by_hour": by_hour,
        "by_dow": by_dow,
        "dow_labels": ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"],
    }


# ═══════════════════════════════════════════════════════════════════
# 5. Caméras visitées — /cameras
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}/cameras")
async def vehicle_cameras(plate: str,
                           user: dict = Depends(require_permission("read_plates"))):
    normalized = await _plate_or_404(plate, user)
    match = await _base_match(user)
    match["plate"] = {"$regex": normalized, "$options": "i"}
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": "$camera_id",
            "camera_name": {"$first": "$camera_name"},
            "count": {"$sum": 1},
            "last_seen": {"$max": "$timestamp"},
            "first_seen": {"$min": "$timestamp"},
        }},
        {"$sort": {"count": -1}},
    ]
    docs = await db.plates.aggregate(pipeline).to_list(length=None)
    return {"items": [
        {"camera_id": d["_id"], "camera_name": d.get("camera_name"),
         "count": d["count"], "last_seen": d.get("last_seen"),
         "first_seen": d.get("first_seen")}
        for d in docs
    ]}


# ═══════════════════════════════════════════════════════════════════
# 6. Parcours — /journey
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}/journey")
async def vehicle_journey(plate: str,
                           limit: int = Query(50, ge=5, le=200),
                           user: dict = Depends(require_permission("read_plates"))):
    normalized = await _plate_or_404(plate, user)
    q = await _base_match(user)
    q["plate"] = {"$regex": normalized, "$options": "i"}
    docs = await db.plates.find(
        q, {"_id": 0, "timestamp": 1, "camera_id": 1, "camera_name": 1, "direction": 1}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    # Renvoyé chronologique décroissant (plus récent en tête).
    return {"items": docs}


# ═══════════════════════════════════════════════════════════════════
# 7. Habitudes — /habits
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}/habits")
async def vehicle_habits(plate: str,
                          user: dict = Depends(require_permission("read_plates"))):
    normalized = await _plate_or_404(plate, user)
    q = await _base_match(user)
    q["plate"] = {"$regex": normalized, "$options": "i"}

    docs = await db.plates.find(q, {"timestamp": 1, "_id": 0}).to_list(length=None)
    times: list[datetime] = []
    for d in docs:
        dt = _iso_to_dt(d.get("timestamp"))
        if dt:
            times.append(dt)
    if not times:
        return {"typical": None, "typical_days": [], "nocturnal_first_seen": None,
                "nocturnal_note": None}

    # Sépare arrivées (heures matinales < 12h) et départs (>= 12h) — heuristique simple.
    arrivals = [t for t in times if t.hour < 12]
    departures = [t for t in times if t.hour >= 12]

    def _range(hs: list[datetime]) -> Optional[str]:
        if not hs:
            return None
        minutes = [t.hour * 60 + t.minute for t in hs]
        lo = min(minutes)
        hi = max(minutes)
        return f"{lo//60:02d}:{lo%60:02d} → {hi//60:02d}:{hi%60:02d}"

    # Jours d'activité prédominants (>10 % du total).
    dow_counter = Counter(t.weekday() for t in times)
    total = len(times)
    labels = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    typical_days = [labels[d] for d, c in dow_counter.items() if c / total >= 0.10]
    typical_days.sort(key=lambda x: labels.index(x))

    # Première apparition nocturne (22h-06h) sans historique nocturne préalable.
    nocturnal = [t for t in times if t.hour >= 22 or t.hour < 6]
    nocturnal_first = None
    nocturnal_note = None
    if nocturnal:
        nocturnal_first = min(nocturnal).isoformat()
        # Ce véhicule est-il "nocturne habituel" ?
        if len(nocturnal) / total < 0.05:
            nocturnal_note = "Rare — jamais observé auparavant entre 22h et 06h"

    return {
        "typical_arrival": _range(arrivals),
        "typical_departure": _range(departures),
        "typical_days": typical_days,
        "nocturnal_first_seen": nocturnal_first,
        "nocturnal_note": nocturnal_note,
    }


# ═══════════════════════════════════════════════════════════════════
# 8. Vehicle Identity — STUB v0.6 (préparation v0.7)
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}/identity")
async def vehicle_identity(plate: str,
                            user: dict = Depends(require_permission("read_plates"))):
    """Stub v0.6 — l'agrégation d'identité cross-plate est prévue pour v0.7.

    L'architecture retourne actuellement une identité 1:1 avec la plaque.
    En v0.7, ``identity_id`` regroupera plusieurs plaques (changement
    de plaque tout en reconnaissant le même véhicule via couleur / marque /
    silhouette).
    """
    normalized = await _plate_or_404(plate, user)
    return {
        "identity_id": None,
        "plate": normalized,
        "linked_plates": [],
        "enabled": False,
        "reason": "vehicle_identity_disabled_v06",
        "note": "Architecture prête — matching cross-plate activé en v0.7.",
    }


# ═══════════════════════════════════════════════════════════════════
# 8b. Anomalies (Habitudes → Alertes) — v0.6b
# ═══════════════════════════════════════════════════════════════════
async def _compute_anomaly(plate: str, user: dict, exact: bool = False) -> dict:
    """Calcule un rapport d'anomalie pour la **dernière** passe d'un véhicule.

    Compare le dernier timestamp aux habitudes calculées (arrivée typique,
    départ typique, jours prédominants, historique nocturne) et renvoie :

        {
          "plate": "...",
          "last_seen": "...",
          "anomalies": ["off_hours", "off_days", "nocturnal_first", ...],
          "severity": "info" | "warning" | "high",
          "message": "phrase explicative",
          "habits": {typical_arrival, typical_departure, typical_days, ...},
        }

    v3.20 · `exact=True` (utilisé par `vehicles_anomalies_recent`, qui
    appelle cette fonction jusqu'à 300 fois par requête) — la plaque vient
    déjà normalisée d'un `$group` Mongo, donc une égalité exacte suffit et
    peut utiliser l'index composé `{plate:1, timestamp:-1}`. Le `$regex`
    (nécessaire pour une saisie utilisateur libre, cf. appels ailleurs)
    ne peut pas l'utiliser efficacement — mesuré en réel : 300 appels
    regex séquentiels saturaient MongoDB à 432% CPU, ralentissant tout le
    reste (dashboard, recherche) pendant plusieurs minutes.
    """
    normalized = plate.upper().replace(" ", "").replace("-", "")
    q = await _base_match(user)
    q["plate"] = normalized if exact else {"$regex": normalized, "$options": "i"}

    docs = await db.plates.find(
        q, {"_id": 0, "timestamp": 1, "camera_name": 1}
    ).sort("timestamp", -1).limit(2000).to_list(2000)
    if not docs:
        return {"plate": normalized, "anomalies": [], "severity": "info",
                "message": "aucune donnée"}

    last_iso = docs[0].get("timestamp")
    last_dt = _iso_to_dt(last_iso)
    if not last_dt:
        return {"plate": normalized, "anomalies": [], "severity": "info",
                "message": "timestamp illisible"}

    # Historique (hors dernière passe) pour calcul de norme.
    history = [d for d in docs[1:] if _iso_to_dt(d.get("timestamp"))]
    if len(history) < 5:
        return {
            "plate": normalized, "last_seen": last_iso,
            "anomalies": ["insufficient_history"], "severity": "info",
            "message": "Historique insuffisant pour évaluer les habitudes (< 5 passes).",
            "habits": None,
        }

    hist_dts = [_iso_to_dt(d["timestamp"]) for d in history]
    hours = [d.hour * 60 + d.minute for d in hist_dts]
    dows = Counter(d.weekday() for d in hist_dts)
    total = len(hist_dts)

    # Arrivées/départs habituels
    arrivals = [h for h, dt in zip(hours, hist_dts) if dt.hour < 12]
    departures = [h for h, dt in zip(hours, hist_dts) if dt.hour >= 12]
    arr_min = min(arrivals) if arrivals else None
    arr_max = max(arrivals) if arrivals else None
    dep_min = min(departures) if departures else None
    dep_max = max(departures) if departures else None

    labels = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    typical_days = [labels[d] for d, c in dows.items() if c / total >= 0.10]

    # Analyse du LAST passage
    last_min = last_dt.hour * 60 + last_dt.minute
    last_dow = last_dt.weekday()
    anomalies = []
    reasons = []

    # 1. Hors des heures habituelles ? (>60 min hors fenêtre arr/dep)
    in_arr = arr_min is not None and arr_max is not None and arr_min - 60 <= last_min <= arr_max + 60
    in_dep = dep_min is not None and dep_max is not None and dep_min - 60 <= last_min <= dep_max + 60
    if not in_arr and not in_dep and last_dt.hour >= 6 and last_dt.hour < 22:
        anomalies.append("off_hours")
        reasons.append(f"Passage à {last_dt.strftime('%H:%M')} hors des créneaux habituels")

    # 2. Jour inhabituel ? (dow avec < 5 % de l'historique)
    if dows[last_dow] / total < 0.05:
        anomalies.append("off_days")
        reasons.append(f"Passage un {labels[last_dow]} — jour rarement observé")

    # 3. Nocturne (22h–06h) alors que rarement observé nocturne ?
    if last_dt.hour >= 22 or last_dt.hour < 6:
        nocturnal_count = sum(1 for d in hist_dts if d.hour >= 22 or d.hour < 6)
        if nocturnal_count == 0:
            anomalies.append("nocturnal_first")
            reasons.append("Première apparition nocturne (22h–06h) jamais observée auparavant")
        elif nocturnal_count / total < 0.05:
            anomalies.append("nocturnal_rare")
            reasons.append("Passage nocturne rare")

    # Sévérité
    if "nocturnal_first" in anomalies or ("off_hours" in anomalies and "off_days" in anomalies):
        severity = "high"
    elif anomalies:
        severity = "warning"
    else:
        severity = "info"

    return {
        "plate": normalized,
        "last_seen": last_iso,
        "camera_name": docs[0].get("camera_name"),
        "anomalies": anomalies,
        "severity": severity,
        "message": " · ".join(reasons) if reasons else "Aucune anomalie détectée.",
        "habits": {
            "typical_arrival": (
                f"{arr_min//60:02d}:{arr_min%60:02d} → {arr_max//60:02d}:{arr_max%60:02d}"
                if arr_min is not None else None),
            "typical_departure": (
                f"{dep_min//60:02d}:{dep_min%60:02d} → {dep_max//60:02d}:{dep_max%60:02d}"
                if dep_min is not None else None),
            "typical_days": typical_days,
        },
    }


@vehicles_router.get("/{plate}/anomaly")
async def vehicle_anomaly(plate: str,
                           user: dict = Depends(require_permission("read_plates"))):
    """Analyse d'anomalie de la dernière passe (lecture seule)."""
    await _plate_or_404(plate, user)
    return await _compute_anomaly(plate, user)


@vehicles_router.get("/anomalies/recent")
async def vehicles_anomalies_recent(
    since_hours: int = Query(24, ge=1, le=720),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_permission("read_plates")),
):
    """Liste des véhicules avec anomalies détectées sur les X dernières heures.

    Retourne uniquement ceux dont le rapport a une sévérité `warning` ou `high`.
    """
    since_dt = datetime.now(timezone.utc).timestamp() - since_hours * 3600
    match = await _base_match(user)
    # Distinct plates seen since_hours ago
    pipe = [
        {"$match": match},
        {"$sort": {"timestamp": -1}},
        {"$group": {"_id": "$plate", "last_seen": {"$first": "$timestamp"}}},
        {"$sort": {"last_seen": -1}},
        {"$limit": 300},  # borne dure pour la charge CPU
    ]
    recent_plates = await db.plates.aggregate(pipe).to_list(300)
    out = []
    for row in recent_plates:
        last = _iso_to_dt(row.get("last_seen"))
        if not last or last.timestamp() < since_dt:
            continue
        try:
            report = await _compute_anomaly(row["_id"], user, exact=True)
        except Exception:
            continue
        if report.get("severity") in ("warning", "high"):
            out.append(report)
        if len(out) >= limit:
            break
    # Sort by severity + last_seen
    order = {"high": 0, "warning": 1, "info": 2}
    out.sort(key=lambda r: (order.get(r["severity"], 3), -(_iso_to_dt(r["last_seen"]).timestamp())))
    return {"count": len(out), "items": out}


@vehicles_router.post("/{plate}/notify-anomaly")
async def vehicle_notify_anomaly(plate: str,
                                  user: dict = Depends(require_permission("read_plates"))):
    """Envoie une notification (SMTP/Discord/Telegram) sur les anomalies
    détectées pour ce véhicule. Ne modifie pas le pipeline OCR — appel manuel
    depuis le drawer véhicule."""
    await _plate_or_404(plate, user)
    report = await _compute_anomaly(plate, user)
    if not report.get("anomalies") or report["severity"] == "info":
        raise HTTPException(status_code=400,
                            detail={"error": "no_anomaly",
                                    "message": "Aucune anomalie à notifier."})

    from notifications import send_notification
    subject = f"Anomalie véhicule {plate} · {report['severity'].upper()}"
    body = (f"Plaque : {plate}\n"
            f"Dernière détection : {report.get('last_seen')} sur {report.get('camera_name') or 'caméra inconnue'}\n"
            f"Anomalies : {', '.join(report['anomalies'])}\n"
            f"{report['message']}")
    results = await send_notification(subject=subject, body=body)
    return {"sent": results, "report": report}


# ═══════════════════════════════════════════════════════════════════
# 8c. Consensus multi-plugins & validation manuelle — v0.7 preview
# ═══════════════════════════════════════════════════════════════════
def _levenshtein(a: str, b: str) -> int:
    """Distance d'édition classique — assez rapide pour des chaînes < 10 char."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(cur[j-1] + 1, prev[j] + 1, prev[j-1] + (ca != cb))
        prev = cur
    return prev[-1]


def _norm_plate(p: str) -> str:
    return (p or "").upper().replace(" ", "").replace("-", "")


async def _find_variants(seed_plate: str, user: dict, max_distance: int = 2) -> list[dict]:
    """Retourne les plaques "voisines" susceptibles d'appartenir au même véhicule.

    Critères :
      - Longueur identique (±1 caractère max)
      - Distance de Levenshtein ≤ ``max_distance``
      - Même vendor de couleur/marque OU même caméra (heuristique)
    """
    seed = _norm_plate(seed_plate)
    if len(seed) < 4:
        return []
    match = await _base_match(user)
    # Récupère toutes les plaques distinctes avec meta
    pipe = [
        {"$match": match},
        {"$group": {
            "_id": "$plate",
            "count": {"$sum": 1},
            "cameras": {"$addToSet": "$camera_id"},
            "colors": {"$addToSet": "$vehicle_color"},
            "makes": {"$addToSet": "$vehicle_make"},
            "engines": {"$addToSet": "$engine"},
            "last_seen": {"$max": "$timestamp"},
        }},
        {"$limit": 5000},
    ]
    all_plates = await db.plates.aggregate(pipe).to_list(5000)
    seed_meta = next((p for p in all_plates if _norm_plate(p["_id"]) == seed), None)
    if not seed_meta:
        return []
    seed_cams = set(seed_meta["cameras"] or [])
    seed_colors = set(c for c in (seed_meta["colors"] or []) if c)
    seed_makes = set(m for m in (seed_meta["makes"] or []) if m)

    variants = []
    for p in all_plates:
        norm = _norm_plate(p["_id"])
        if norm == seed:
            continue
        if abs(len(norm) - len(seed)) > 1:
            continue
        dist = _levenshtein(norm, seed)
        if dist > max_distance:
            continue
        cams = set(p["cameras"] or [])
        colors = set(c for c in (p["colors"] or []) if c)
        makes = set(m for m in (p["makes"] or []) if m)
        shared_cams = bool(cams & seed_cams)
        shared_color = bool(colors & seed_colors)
        shared_make = bool(makes & seed_makes) if seed_makes else False
        # Heuristique : au moins un contexte partagé
        if not (shared_cams or shared_color or shared_make):
            continue
        variants.append({
            "plate": p["_id"],
            "distance": dist,
            "count": p["count"],
            "cameras": list(cams),
            "shared_context": {
                "cameras": shared_cams,
                "color": shared_color,
                "make": shared_make,
            },
            "engines": [e for e in (p["engines"] or []) if e],
            "last_seen": p["last_seen"],
        })
    variants.sort(key=lambda v: (v["distance"], -v["count"]))
    return variants


@vehicles_router.get("/{plate}/consensus")
async def vehicle_consensus(plate: str,
                             user: dict = Depends(require_permission("read_plates"))):
    """Consensus multi-plugins : détecte les variantes OCR de la même plaque
    et calcule la plaque **canonique probable** par vote pondéré des moteurs.

    Le score par candidat = Σ (confidence × poids_moteur) sur toutes les
    lectures groupées. Poids moteur : 1.0 par défaut (égalitaire) — reste
    ajustable en v0.7 par plugin (Fast-ALPR vs Plate-Recognizer vs Paddle).
    """
    seed = _norm_plate(plate)
    q = await _base_match(user)
    q["plate"] = {"$regex": seed, "$options": "i"}
    count = await db.plates.count_documents(q)
    if count == 0:
        raise HTTPException(status_code=404, detail={"error": "vehicle_not_found"})

    variants = await _find_variants(seed, user)

    # Regroupe toutes les plaques (seed + variantes) et vote.
    all_plates = [seed] + [v["plate"] for v in variants]
    match_all = await _base_match(user)
    match_all["plate"] = {"$in": all_plates}
    pipe = [
        {"$match": match_all},
        {"$group": {
            "_id": {"plate": "$plate", "engine": "$engine"},
            "n": {"$sum": 1},
            "avg_conf": {"$avg": "$confidence"},
        }},
    ]
    rows = await db.plates.aggregate(pipe).to_list(length=None)

    # Poids par moteur (extension future). Pour l'instant, tous à 1.0.
    ENGINE_WEIGHTS = {"fast-alpr": 1.0, "plate-recognizer": 1.0, "paddle-ocr": 0.9,
                      "openalpr": 0.9, "tesseract": 0.6, "easyocr": 0.7}
    candidates: dict[str, dict] = {}
    engines_by_plate: dict[str, list[dict]] = {}
    for r in rows:
        pk = r["_id"]["plate"]
        eng = (r["_id"].get("engine") or "unknown")
        w = ENGINE_WEIGHTS.get(eng, 0.8)
        score = float(r["avg_conf"] or 0) * w * int(r["n"])
        candidates.setdefault(pk, {"plate": pk, "score": 0.0, "reads": 0, "engines": []})
        candidates[pk]["score"] += score
        candidates[pk]["reads"] += r["n"]
        engines_by_plate.setdefault(pk, []).append({
            "engine": eng, "reads": r["n"],
            "avg_confidence": round(r["avg_conf"] or 0, 3),
            "weight": w,
        })
    for pk, votes in engines_by_plate.items():
        candidates[pk]["engines"] = sorted(votes, key=lambda x: -x["reads"])
    ranked = sorted(candidates.values(), key=lambda c: -c["score"])
    top = ranked[0] if ranked else None

    # Statut de validation manuelle
    val_doc = await db.plate_validations.find_one({"canonical_plate": seed}, {"_id": 0}) \
        if hasattr(db, "plate_validations") else None
    if not val_doc:
        # Cherche si le seed appartient à une identité déjà validée
        val_doc = await db.plate_validations.find_one(
            {"$or": [{"canonical_plate": seed}, {"variants": seed}]}, {"_id": 0}
        )

    return {
        "seed_plate": seed,
        "canonical_candidate": (top or {}).get("plate"),
        "canonical_score": round((top or {}).get("score", 0), 2),
        "candidates": [{
            "plate": c["plate"],
            "score": round(c["score"], 2),
            "reads": c["reads"],
            "engines": c["engines"],
        } for c in ranked[:5]],
        "variants_detected": variants,
        "validation": val_doc,
        "note": "Consensus multi-plugins v0.7 preview — les poids par moteur sont ajustables.",
    }


class PlateValidationBody(BaseModel):
    canonical_plate: str
    variants: list[str] = []
    reason: str = ""


@vehicles_router.post("/{plate}/validate")
async def vehicle_validate_plate(plate: str, body: PlateValidationBody,
                                   user: dict = Depends(require_permission("read_plates"))):
    """Fige manuellement la plaque canonique + fusionne les variantes.

    Sauvegarde dans ``plate_validations`` :
      { canonical_plate, variants[], validated_by, validated_at, reason }

    Ne modifie pas la table ``plates`` (préserve l'historique brut) mais
    fournit une notion d'*Identity* que les endpoints consommateurs peuvent
    utiliser pour ré-écrire la plaque affichée."""
    canonical = _norm_plate(body.canonical_plate or plate)
    variants = sorted({_norm_plate(v) for v in body.variants if v} - {canonical})
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "canonical_plate": canonical,
        "variants": variants,
        "validated_by": user.get("email"),
        "validated_at": now,
        "reason": (body.reason or "").strip(),
    }
    await db.plate_validations.update_one(
        {"canonical_plate": canonical},
        {"$set": doc},
        upsert=True,
    )
    return {"ok": True, "validation": doc}


@vehicles_router.delete("/{plate}/validate")
async def vehicle_unvalidate_plate(plate: str,
                                     user: dict = Depends(require_permission("read_plates"))):
    """Retire la validation manuelle (revient au consensus automatique)."""
    canonical = _norm_plate(plate)
    res = await db.plate_validations.delete_one(
        {"$or": [{"canonical_plate": canonical}, {"variants": canonical}]}
    )
    return {"ok": True, "deleted": res.deleted_count}


# ═══════════════════════════════════════════════════════════════════
# 9. Thumbnail binaire — /passage/{id}/thumb
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/passage/{passage_id}/thumb")
async def passage_thumb(passage_id: str,
                         kind: str = Query("frame", regex="^(frame|vehicle|plate)$"),
                         user: dict = Depends(require_permission("read_plates"))):
    """Sert le thumbnail JPEG (binaire) associé à une passe ANPR.

    Le champ stocké en base64 (data URL) est décodé et streamé comme
    ``image/jpeg`` — évite de faire transiter du base64 dans les listes.
    """
    field = {"frame": "frame_thumb", "vehicle": "vehicle_crop", "plate": "plate_crop"}[kind]
    doc = await db.plates.find_one({"id": passage_id}, {field: 1, "plate": 1, "_id": 0})
    if not doc or not doc.get(field):
        raise HTTPException(status_code=404, detail={"error": "thumb_not_found"})

    b64 = doc[field]
    # Supprime le préfixe "data:image/…;base64," si présent
    if isinstance(b64, str) and "," in b64:
        b64 = b64.split(",", 1)[1]
    try:
        blob = base64.b64decode(b64)
    except Exception:
        raise HTTPException(status_code=500, detail={"error": "thumb_decode_error"})
    headers = {"Cache-Control": "public, max-age=86400, immutable"}
    return StreamingResponse(io.BytesIO(blob), media_type="image/jpeg", headers=headers)
