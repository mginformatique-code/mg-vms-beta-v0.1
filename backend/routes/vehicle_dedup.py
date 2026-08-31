"""v3.20 · Détection de doublons véhicule assistée par Qwen.

Constaté en réel (31/08) : 24 830 paires de plaques à distance d'édition
2-3 ne sont jamais fusionnées automatiquement (`_cluster_plate_groups`
dans vehicles.py ne fusionne qu'à distance ≤1, même caméra, fenêtre de
2 minutes — trop strict pour capter un même véhicule lu différemment
d'un jour/d'une caméra à l'autre). Exemple réel : une plaque fragmentée
en au moins 8 variantes (112 lectures sur la principale).

Le modèle configuré (qwen3:1.7b) est texte SEUL — pas de vision, donc
pas de comparaison d'images de véhicule directe. On compare à la place
les attributs déjà extraits par le pipeline IA (marque/modèle/couleur/
type, majoritaires par plaque) : Qwen raisonne sur la plausibilité d'une
confusion OCR (ex. 0/O, 1/I, 5/S) ET la cohérence visuelle déjà connue,
sans nouvelle dépendance (même modèle, même intégration que smart_search.py).

Tâche PÉRIODIQUE (jamais dans le chemin chaud de l'IA) + suggestions
soumises à validation manuelle — jamais de fusion automatique. Réutilise
`POST /vehicles/identities` (mécanisme déjà en place, déjà utilisé pour
GS550PX/GS550RX) pour la fusion effective une fois acceptée.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_permission, require_role, log_audit
from database import db

logger = logging.getLogger("routes.vehicle_dedup")

vehicle_dedup_router = APIRouter(prefix="/api/vehicles/dedup", tags=["vehicle-dedup"])

_MAX_DISTANCE = 3
_MAX_CANDIDATES_PER_RUN = 25
_BATCH_INTERVAL_HOURS = 24
# v3.20 · Constaté en réel : deux lectures du MÊME véhicule réel (même
# caméra, 17s d'écart, crops visuellement identiques confirmés) donnaient
# "TR1351G" et "CG16598" — textuellement sans aucun rapport (l'OCR a
# complètement raté, pas une simple confusion de caractère). La
# comparaison par distance d'édition seule ne peut structurellement pas
# capter ce cas. Fenêtre de proximité temporelle, même caméra, réutilise
# le seuil déjà établi ailleurs (`_PLATE_MERGE_WINDOW_SEC` dans
# vehicles.py) pour rester cohérent avec la notion existante de "même
# passage".
_TIME_PROXIMITY_WINDOW_SEC = 120


def _levenshtein(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > _MAX_DISTANCE:
        return 99
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (ca != cb))
            prev = cur
    return dp[-1]


def _majority(values: list) -> str | None:
    vv = [v for v in values if v]
    if not vv:
        return None
    return max(set(vv), key=vv.count)


async def _plate_stats(plate: str) -> dict:
    docs = await db.plates.find(
        {"plate": plate},
        {"_id": 0, "vehicle_make": 1, "vehicle_model": 1, "vehicle_color": 1, "vehicle_type": 1, "timestamp": 1},
    ).to_list(500)
    return {
        "plate": plate,
        "count": len(docs),
        "make": _majority([d.get("vehicle_make") for d in docs]),
        "model": _majority([d.get("vehicle_model") for d in docs]),
        "color": _majority([d.get("vehicle_color") for d in docs]),
        "type": _majority([d.get("vehicle_type") for d in docs]),
        "last_seen": max((d.get("timestamp") or "" for d in docs), default=None),
    }


async def _already_linked_plates() -> set[str]:
    linked: set[str] = set()
    async for ident in db.vehicle_identities.find({}, {"_id": 0, "plates": 1}):
        linked.update(ident.get("plates") or [])
    return linked


async def _already_suggested_pairs() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    async for s in db.dedup_suggestions.find({}, {"_id": 0, "plate_a": 1, "plate_b": 1}):
        pairs.add(tuple(sorted((s["plate_a"], s["plate_b"]))))
    return pairs


async def _find_text_similarity_candidates(counts: dict[str, int], plates: list[str],
                                             seen_pairs: set[tuple[str, str]]) -> list[tuple[str, str, int, str]]:
    """Source 1 : plaques textuellement proches (confusion OCR sur un
    caractère ou deux — le cas le plus fréquent)."""
    candidates: list[tuple[str, str, int, str]] = []
    seen_this_run: set[tuple[str, str]] = set()
    for i, p1 in enumerate(plates):
        for p2 in plates[i + 1:]:
            key = tuple(sorted((p1, p2)))
            if key in seen_pairs or key in seen_this_run:
                continue
            if abs(len(p1) - len(p2)) > 2:
                continue
            d = _levenshtein(p1, p2)
            if 1 <= d <= _MAX_DISTANCE:
                seen_this_run.add(key)
                candidates.append((p1, p2, counts[p1] + counts[p2], "texte proche"))
    return candidates


async def _find_time_proximity_candidates(counts: dict[str, int], linked: set[str],
                                            seen_pairs: set[tuple[str, str]]) -> list[tuple[str, str, int, str]]:
    """Source 2 · v3.20 : plaques vues sur la MÊME caméra à quelques
    secondes/minutes d'écart, quel que soit le texte — capte les échecs
    OCR sévères (lecture totalement différente, pas juste un caractère)
    qu'une comparaison de texte seule ne peut pas voir. Confirmé sur un
    cas réel (crops identiques, plaques "TR1351G" vs "CG16598", 17s
    d'écart, même caméra)."""
    rows = []
    async for row in db.plates.find(
        {}, {"_id": 0, "plate": 1, "camera_id": 1, "timestamp": 1}
    ).sort([("camera_id", 1), ("timestamp", 1)]).to_list(20000):
        if row.get("plate") in linked:
            continue
        rows.append(row)

    candidates: list[tuple[str, str, int, str]] = []
    seen_this_run: set[tuple[str, str]] = set()
    for i, r1 in enumerate(rows):
        t1 = _iso_to_ts(r1.get("timestamp"))
        if t1 is None:
            continue
        for r2 in rows[i + 1:]:
            if r2["camera_id"] != r1["camera_id"]:
                break  # trié par caméra puis temps — plus rien à voir sur cette caméra
            t2 = _iso_to_ts(r2.get("timestamp"))
            if t2 is None or (t2 - t1) > _TIME_PROXIMITY_WINDOW_SEC:
                break  # trié par temps — au-delà de la fenêtre, inutile de continuer
            if r1["plate"] == r2["plate"]:
                continue
            key = tuple(sorted((r1["plate"], r2["plate"])))
            if key in seen_pairs or key in seen_this_run:
                continue
            seen_this_run.add(key)
            candidates.append((r1["plate"], r2["plate"],
                                counts.get(r1["plate"], 1) + counts.get(r2["plate"], 1),
                                "même caméra, quelques secondes d'écart"))
    return candidates


def _iso_to_ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


async def _find_candidates(limit: int = _MAX_CANDIDATES_PER_RUN) -> list[tuple[str, str, int, str]]:
    """Paires (plate_a, plate_b, poids, origine) triées par poids
    décroissant (poids = lectures cumulées des deux plaques — priorise
    les fragments les plus significatifs). Deux sources combinées : texte
    proche (OCR légèrement faux) + même caméra/moment (OCR très faux)."""
    counts: dict[str, int] = {}
    async for row in db.plates.aggregate([{"$group": {"_id": "$plate", "n": {"$sum": 1}}},
                                            {"$match": {"n": {"$gte": 2}}}]):
        counts[row["_id"]] = row["n"]

    linked = await _already_linked_plates()
    seen_pairs = await _already_suggested_pairs()
    plates = [p for p in counts if p not in linked]

    text_candidates = await _find_text_similarity_candidates(counts, plates, seen_pairs)
    seen_pairs = seen_pairs | {tuple(sorted((c[0], c[1]))) for c in text_candidates}
    time_candidates = await _find_time_proximity_candidates(counts, linked, seen_pairs)

    candidates = text_candidates + time_candidates
    candidates.sort(key=lambda c: -c[2])
    return candidates[:limit]


async def _ask_qwen_same_vehicle(a: dict, b: dict) -> dict:
    from routes.llm_settings import get_active_llm_config
    cfg = await get_active_llm_config()
    if not cfg:
        raise HTTPException(status_code=503, detail={"code": "DEDUP_LLM_NOT_CONFIGURED",
                                                        "message": "LLM non configuré (Administration → LLM)."})
    import httpx
    # v3.20 · Constaté en test réel : un schéma avec un champ `boolean` et
    # aucun message système laisse qwen3:1.7b répondre en PROSE LIBRE malgré
    # `"format"` (contrairement à smart_search.py, qui s'appuie sur des
    # `enum` stricts + un message système explicite). Reproduit le même
    # remède ici : enum string au lieu de boolean, message système qui
    # épelle le schéma en clair EN PLUS du paramètre `format` — confirmé en
    # test direct, réponse JSON conforme à chaque essai après ce changement.
    schema = {
        "type": "object",
        "properties": {
            "same_vehicle": {"type": "string", "enum": ["oui", "non"]},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["same_vehicle", "confidence", "reason"],
    }
    system = (
        "Tu es un comparateur de plaques ANPR. Réponds UNIQUEMENT avec un objet "
        "JSON valide respectant EXACTEMENT ce schéma : "
        '{"same_vehicle": "oui"|"non", "confidence": nombre entre 0 et 1, '
        '"reason": texte court}. Aucun texte hors JSON.'
    )
    prompt = (
        "Deux plaques lues par un système ANPR pourraient être le MÊME véhicule "
        "mal lu deux fois (confusions OCR courantes : 0/O, 1/I, 5/S, 8/B, 2/Z). "
        f"Plaque A: \"{a['plate']}\" ({a['count']} lectures, marque={a['make']}, "
        f"modèle={a['model']}, couleur={a['color']}, type={a['type']}).\n"
        f"Plaque B: \"{b['plate']}\" ({b['count']} lectures, marque={b['make']}, "
        f"modèle={b['model']}, couleur={b['color']}, type={b['type']}).\n"
        "Est-ce probablement le même véhicule ? Base ton jugement sur la "
        "plausibilité de la confusion OCR ET la cohérence marque/modèle/couleur "
        "(des attributs différents sur les deux plaques est un signal FORT que "
        "ce sont deux véhicules distincts, pas le même mal lu)."
    )
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "think": False,
        "format": schema,
        "stream": False,
    }
    url = f"{cfg['base_url']}/api/chat/completions"
    async with httpx.AsyncClient(timeout=25.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()
    raw = (body["choices"][0]["message"]["content"] or "").strip()
    if "<think>" in raw:
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    parsed = json.loads(raw)
    return {
        "same_vehicle": parsed.get("same_vehicle") == "oui",
        "confidence": parsed.get("confidence"),
        "reason": parsed.get("reason", ""),
    }


async def _run_dedup_batch(limit: int = _MAX_CANDIDATES_PER_RUN) -> int:
    candidates = await _find_candidates(limit)
    created = 0
    for plate_a, plate_b, _weight in candidates:
        try:
            a = await _plate_stats(plate_a)
            b = await _plate_stats(plate_b)
            verdict = await _ask_qwen_same_vehicle(a, b)
        except Exception:
            logger.exception("vehicle_dedup: échec comparaison %s / %s", plate_a, plate_b)
            continue
        doc = {
            "id": str(uuid.uuid4()),
            "plate_a": plate_a,
            "plate_b": plate_b,
            "stats_a": a,
            "stats_b": b,
            "same_vehicle": bool(verdict.get("same_vehicle")),
            "confidence": verdict.get("confidence"),
            "reason": verdict.get("reason", ""),
            # v3.20 · Toute paire comparée est enregistrée (pour ne jamais la
            # redemander à Qwen le lendemain), mais seules celles jugées
            # "même véhicule" passent en "pending" — visibles pour révision.
            # Sinon l'interface proposerait de fusionner des paires que le
            # modèle vient lui-même de juger différentes.
            "status": "pending" if verdict.get("same_vehicle") else "auto_rejected",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.dedup_suggestions.insert_one(doc)
        if doc["status"] == "pending":
            created += 1
    return created


async def dedup_batch_loop() -> None:
    """Tourne une fois toutes les `_BATCH_INTERVAL_HOURS` — jamais dans le
    chemin chaud de l'IA, purement en tâche de fond."""
    while True:
        await asyncio.sleep(_BATCH_INTERVAL_HOURS * 3600)
        try:
            n = await _run_dedup_batch()
            if n:
                logger.info("vehicle_dedup: %s suggestion(s) générée(s)", n)
        except Exception:
            logger.exception("vehicle_dedup: erreur boucle dedup_batch_loop")


@vehicle_dedup_router.post("/run")
async def run_now(user: dict = Depends(require_role("admin"))):
    n = await _run_dedup_batch()
    await log_audit(user, "vehicle_dedup_run", f"{n} suggestion(s)")
    return {"created": n}


@vehicle_dedup_router.get("/suggestions")
async def list_suggestions(status: str = "pending",
                            user: dict = Depends(require_permission("read_plates"))):
    q = {} if status == "all" else {"status": status}
    docs = await db.dedup_suggestions.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"count": len(docs), "items": docs}


class SuggestionDecision(BaseModel):
    name: str = ""


@vehicle_dedup_router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion(suggestion_id: str, body: SuggestionDecision = SuggestionDecision(),
                             user: dict = Depends(require_permission("read_plates"))):
    sugg = await db.dedup_suggestions.find_one({"id": suggestion_id}, {"_id": 0})
    if not sugg:
        raise HTTPException(404, "Suggestion introuvable")
    now = datetime.now(timezone.utc).isoformat()
    plates = sorted({sugg["plate_a"], sugg["plate_b"]})
    doc = {
        "id": str(uuid.uuid4()),
        "name": (body.name or plates[0]).strip(),
        "plates": plates,
        "vehicle_make": sugg["stats_a"].get("make") or sugg["stats_b"].get("make"),
        "vehicle_color": sugg["stats_a"].get("color") or sugg["stats_b"].get("color"),
        "vehicle_type": sugg["stats_a"].get("type") or sugg["stats_b"].get("type"),
        "notes": f"Fusion suggérée par Qwen ({sugg.get('reason', '')[:200]})",
        "created_by": user.get("email"),
        "created_at": now,
        "updated_at": now,
    }
    await db.vehicle_identities.insert_one(doc.copy())
    await db.dedup_suggestions.update_one(
        {"id": suggestion_id},
        {"$set": {"status": "accepted", "reviewed_by": user.get("email"), "reviewed_at": now}},
    )
    from routes.vehicles import _list_cache
    _list_cache.clear()
    await log_audit(user, "vehicle_dedup_accepted", f"{plates[0]} + {plates[1]}")
    doc.pop("_id", None)
    return doc


@vehicle_dedup_router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(suggestion_id: str,
                             user: dict = Depends(require_permission("read_plates"))):
    now = datetime.now(timezone.utc).isoformat()
    res = await db.dedup_suggestions.update_one(
        {"id": suggestion_id},
        {"$set": {"status": "rejected", "reviewed_by": user.get("email"), "reviewed_at": now}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Suggestion introuvable")
    return {"ok": True}
