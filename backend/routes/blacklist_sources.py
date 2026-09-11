"""MG-VMS — Sources de blacklist externes (v3.73).

Gros chantier "ANPR : Blacklists externes" (voir docs.mg-vms.com/Chantiers) —
première tranche livrée : connexion générique à une ou plusieurs sources
externes de plaques blacklistées (API REST JSON, fichier CSV distant, ou
webhook poussé par le tiers), synchronisation automatique programmable,
normalisation, écriture dans `db.watchlist` (la MÊME collection que la
liste manuelle déjà existante — aucune duplication de logique de
comparaison : `routers.py::maybe_blacklist_alert` compare déjà chaque
plaque détectée à `db.watchlist` et déclenche déjà alerte + notification,
peu importe qui a ajouté l'entrée).

Hors périmètre de cette tranche (explicite, à faire dans une passe
suivante si demandé) : enrichissement contextuel par Qwen — l'infra de
comparaison déterministe + synchronisation externe est le socle sur
lequel cet enrichissement viendrait se greffer ensuite (même pattern que
`vehicle_anomaly_ai.py::_ask_qwen_narrate`).

Chaque entrée `db.watchlist` créée par une source externe porte
`source: "external:<source_id>"` — ne touche jamais aux entrées ajoutées
manuellement ou par une AUTRE source (import CSV manuel compris, qui ne
pose pas ce champ). Une plaque qui disparaît de la source lors d'une
synchronisation ultérieure est retirée UNIQUEMENT si elle porte ce même
tag source (jamais une entrée manuelle qui aurait la même plaque).
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import require_role, get_current_user, log_audit
from crypto_utils import encrypt_secret, decrypt_secret
from database import db

logger = logging.getLogger("blacklist_sources")

blacklist_sources_router = APIRouter(prefix="/api/blacklist-sources", tags=["blacklist-sources"])

_KINDS = ("rest_json", "csv_url", "webhook")
_AUTH_TYPES = ("none", "api_key", "bearer", "basic")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_plate(raw: str) -> str:
    return (raw or "").upper().replace(" ", "").replace("-", "").strip()


class BlacklistSourceInput(BaseModel):
    name: str
    kind: str = Field(pattern="^(rest_json|csv_url|webhook)$")
    url: str = ""  # ignoré pour kind="webhook" (MG-VMS reçoit, n'appelle personne)
    http_method: str = "GET"
    auth_type: str = Field(default="none", pattern="^(none|api_key|bearer|basic)$")
    auth_header_name: str = "X-API-Key"  # utilisé seulement si auth_type == api_key
    auth_key: str = ""      # clé API ou token bearer — chiffré au repos
    auth_username: str = ""  # basique
    auth_password: str = ""  # basique — chiffré au repos
    json_plate_path: str = "plates"  # ex. "data.items[].plate" (voir _extract_json_plates)
    csv_column: str = "plate"
    sync_interval_minutes: int = Field(default=60, ge=5, le=1440)
    enabled: bool = True


def _public_source(doc: dict) -> dict:
    """Ne renvoie jamais les secrets en clair — seulement s'ils sont configurés."""
    doc = dict(doc)
    doc.pop("_id", None)
    doc.pop("synced_plates", None)
    doc["has_auth_key"] = bool(doc.pop("auth_key", ""))
    doc["has_auth_password"] = bool(doc.pop("auth_password", ""))
    doc.pop("webhook_secret", None)
    return doc


@blacklist_sources_router.get("")
async def list_sources(user: dict = Depends(require_role("admin"))):
    rows = await db.blacklist_sources.find({}, {"_id": 0}).sort("name", 1).to_list(500)
    return [_public_source(r) for r in rows]


@blacklist_sources_router.get("/{source_id}")
async def get_source(source_id: str, user: dict = Depends(require_role("admin"))):
    doc = await db.blacklist_sources.find_one({"id": source_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Source introuvable")
    out = _public_source(doc)
    if doc.get("kind") == "webhook":
        out["webhook_url"] = f"/api/blacklist-sources/webhook/{source_id}"
        out["webhook_secret"] = doc.get("webhook_secret", "")
    return out


@blacklist_sources_router.post("")
async def create_source(body: BlacklistSourceInput, user: dict = Depends(require_role("admin"))):
    doc = body.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = _now_iso()
    doc["synced_plates"] = []
    doc["last_sync_at"] = None
    doc["last_sync_status"] = None
    doc["last_sync_count"] = 0
    doc["last_sync_error"] = None
    if doc["auth_key"]:
        doc["auth_key"] = encrypt_secret(doc["auth_key"])
    if doc["auth_password"]:
        doc["auth_password"] = encrypt_secret(doc["auth_password"])
    if doc["kind"] == "webhook":
        doc["webhook_secret"] = uuid.uuid4().hex
    await db.blacklist_sources.insert_one(dict(doc))
    await log_audit(user, "blacklist_source_created", doc["name"])
    return await get_source(doc["id"], user)


@blacklist_sources_router.put("/{source_id}")
async def update_source(source_id: str, body: BlacklistSourceInput, user: dict = Depends(require_role("admin"))):
    existing = await db.blacklist_sources.find_one({"id": source_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Source introuvable")
    patch = body.model_dump()
    # v3.73 · Un champ secret laissé vide dans le formulaire d'édition
    # signifie "ne pas changer" (jamais renvoyé en clair au frontend après
    # coup) — seule une valeur NON vide déclenche un rechiffrement.
    if patch["auth_key"]:
        patch["auth_key"] = encrypt_secret(patch["auth_key"])
    else:
        patch["auth_key"] = existing.get("auth_key", "")
    if patch["auth_password"]:
        patch["auth_password"] = encrypt_secret(patch["auth_password"])
    else:
        patch["auth_password"] = existing.get("auth_password", "")
    await db.blacklist_sources.update_one({"id": source_id}, {"$set": patch})
    await log_audit(user, "blacklist_source_updated", patch["name"])
    return await get_source(source_id, user)


@blacklist_sources_router.delete("/{source_id}")
async def delete_source(source_id: str, user: dict = Depends(require_role("admin"))):
    existing = await db.blacklist_sources.find_one({"id": source_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Source introuvable")
    # Retire du watchlist les entrées posées par cette source (jamais les autres).
    await db.watchlist.delete_many({"source": f"external:{source_id}"})
    plates = existing.get("synced_plates") or []
    if plates:
        await db.plates.update_many(
            {"plate": {"$in": plates}, "list_status": "black"},
            {"$set": {"list_status": "none"}},
        )
    await db.blacklist_sources.delete_one({"id": source_id})
    await log_audit(user, "blacklist_source_deleted", existing.get("name", source_id))
    return {"ok": True}


def _extract_json_plates(obj, path: str) -> list[str]:
    """Chemin simplifié type ``data.items[].plate`` : segments séparés par
    ``.``, un segment se terminant par ``[]`` itère une liste à ce point.
    Volontairement minimal (pas un vrai JSONPath) — suffisant pour les
    formats REST habituels (``{"plates": [...]}``, ``{"data": {"items": [{"plate": "..."}]}}``)."""
    segments = [s for s in path.split(".") if s]
    current = [obj]
    for seg in segments:
        is_list = seg.endswith("[]")
        key = seg[:-2] if is_list else seg
        nxt = []
        for item in current:
            if not isinstance(item, dict):
                continue
            val = item.get(key)
            if val is None:
                continue
            if is_list:
                if isinstance(val, list):
                    nxt.extend(val)
            else:
                nxt.append(val)
        current = nxt
    out = []
    for v in current:
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict) and "plate" in v:
            out.append(str(v["plate"]))
    return out


def _auth_kwargs(source: dict) -> dict:
    kwargs: dict = {"headers": {}}
    auth_type = source.get("auth_type", "none")
    if auth_type == "api_key":
        header = source.get("auth_header_name") or "X-API-Key"
        kwargs["headers"][header] = decrypt_secret(source.get("auth_key", ""))
    elif auth_type == "bearer":
        kwargs["headers"]["Authorization"] = f"Bearer {decrypt_secret(source.get('auth_key', ''))}"
    elif auth_type == "basic":
        kwargs["auth"] = (source.get("auth_username", ""), decrypt_secret(source.get("auth_password", "")))
    return kwargs


async def _fetch_plates(source: dict) -> list[str]:
    kwargs = _auth_kwargs(source)
    async with httpx.AsyncClient(timeout=20) as client:
        method = (source.get("http_method") or "GET").upper()
        resp = await client.request(method, source["url"], **kwargs)
        resp.raise_for_status()
        if source["kind"] == "rest_json":
            data = resp.json()
            raw = _extract_json_plates(data, source.get("json_plate_path") or "plates")
        else:  # csv_url
            text = resp.text
            reader = csv.DictReader(io.StringIO(text))
            column = source.get("csv_column") or "plate"
            raw = [row.get(column, "") for row in reader]
    return [_normalize_plate(p) for p in raw if _normalize_plate(p)]


async def sync_source(source: dict) -> dict:
    """Synchronise UNE source — jamais bloquant pour les autres (appelant
    attrape déjà les exceptions, voir blacklist_sync_loop)."""
    source_id = source["id"]
    tag = f"external:{source_id}"
    try:
        new_plates = set(await _fetch_plates(source))
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:200]}"
        logger.warning("blacklist_sources: échec sync %s (%s) — %s", source["name"], source_id, err)
        await db.blacklist_sources.update_one(
            {"id": source_id},
            {"$set": {"last_sync_at": _now_iso(), "last_sync_status": "error", "last_sync_error": err}},
        )
        return {"ok": False, "error": err}

    old_plates = set(source.get("synced_plates") or [])
    added = new_plates - old_plates
    removed = old_plates - new_plates

    for plate in added:
        existing = await db.watchlist.find_one({"plate": plate}, {"_id": 0, "id": 1, "source": 1})
        if existing and existing.get("source") and existing.get("source") != tag:
            # Déjà géré par une AUTRE source ou ajouté manuellement — ne
            # jamais écraser une entrée qui n'appartient pas à cette source.
            continue
        if existing:
            await db.watchlist.update_one({"id": existing["id"]}, {"$set": {
                "list_type": "black", "source": tag, "source_name": source["name"],
            }})
        else:
            await db.watchlist.insert_one({
                "id": str(uuid.uuid4()), "plate": plate, "list_type": "black",
                "reason": f"Source externe : {source['name']}",
                "source": tag, "source_name": source["name"],
                "created_at": _now_iso(),
            })
        await db.plates.update_many({"plate": plate}, {"$set": {"list_status": "black"}})

    for plate in removed:
        existing = await db.watchlist.find_one({"plate": plate}, {"_id": 0, "id": 1, "source": 1})
        if existing and existing.get("source") == tag:
            await db.watchlist.delete_one({"id": existing["id"]})
            await db.plates.update_many({"plate": plate}, {"$set": {"list_status": "none"}})

    await db.blacklist_sources.update_one(
        {"id": source_id},
        {"$set": {
            "synced_plates": sorted(new_plates), "last_sync_at": _now_iso(),
            "last_sync_status": "ok", "last_sync_count": len(new_plates), "last_sync_error": None,
        }},
    )
    if added or removed:
        logger.info("blacklist_sources: %s synchronisé — +%d/-%d (total %d)",
                    source["name"], len(added), len(removed), len(new_plates))
    return {"ok": True, "added": len(added), "removed": len(removed), "total": len(new_plates)}


@blacklist_sources_router.post("/{source_id}/sync-now")
async def sync_now(source_id: str, user: dict = Depends(require_role("admin"))):
    source = await db.blacklist_sources.find_one({"id": source_id}, {"_id": 0})
    if not source:
        raise HTTPException(404, "Source introuvable")
    if source["kind"] == "webhook":
        raise HTTPException(400, "Une source webhook reçoit les plaques en direct — aucune synchronisation manuelle possible")
    result = await sync_source(source)
    await log_audit(user, "blacklist_source_sync_now", source["name"])
    return result


class WebhookBody(BaseModel):
    plate: Optional[str] = None
    plates: Optional[list[str]] = None


@blacklist_sources_router.post("/webhook/{source_id}")
async def webhook_ingest(source_id: str, body: WebhookBody, token: str = Query(...)):
    """Endpoint PUBLIC (pas d'auth utilisateur MG-VMS — le tiers qui pousse
    n'a pas de compte) — protégé par le secret unique généré à la création
    de la source, à passer en `?token=`."""
    source = await db.blacklist_sources.find_one({"id": source_id, "kind": "webhook"}, {"_id": 0})
    if not source or source.get("webhook_secret") != token:
        raise HTTPException(404, "Source introuvable")
    if not source.get("enabled", True):
        raise HTTPException(403, "Source désactivée")
    incoming = set()
    if body.plate:
        incoming.add(_normalize_plate(body.plate))
    for p in (body.plates or []):
        incoming.add(_normalize_plate(p))
    incoming.discard("")
    if not incoming:
        raise HTTPException(400, "Aucune plaque fournie (`plate` ou `plates`)")

    tag = f"external:{source_id}"
    known = set(source.get("synced_plates") or [])
    added = incoming - known
    for plate in added:
        existing = await db.watchlist.find_one({"plate": plate}, {"_id": 0, "id": 1, "source": 1})
        if existing and existing.get("source") and existing.get("source") != tag:
            continue
        if existing:
            await db.watchlist.update_one({"id": existing["id"]}, {"$set": {
                "list_type": "black", "source": tag, "source_name": source["name"],
            }})
        else:
            await db.watchlist.insert_one({
                "id": str(uuid.uuid4()), "plate": plate, "list_type": "black",
                "reason": f"Source externe (webhook) : {source['name']}",
                "source": tag, "source_name": source["name"], "created_at": _now_iso(),
            })
        await db.plates.update_many({"plate": plate}, {"$set": {"list_status": "black"}})

    await db.blacklist_sources.update_one(
        {"id": source_id},
        {"$set": {"synced_plates": sorted(known | incoming), "last_sync_at": _now_iso(),
                  "last_sync_status": "ok", "last_sync_count": len(known | incoming), "last_sync_error": None}},
    )
    return {"ok": True, "added": len(added)}


async def blacklist_sync_loop() -> None:
    """Boucle de fond — même pattern que anomaly_ai_batch_loop (tick régulier,
    chaque source resynchronisée seulement quand son intervalle est écoulé)."""
    while True:
        try:
            sources = await db.blacklist_sources.find(
                {"enabled": True, "kind": {"$in": ["rest_json", "csv_url"]}}, {"_id": 0}
            ).to_list(200)
            now = datetime.now(timezone.utc)
            for source in sources:
                last = source.get("last_sync_at")
                interval = timedelta(minutes=source.get("sync_interval_minutes", 60))
                due = True
                if last:
                    try:
                        due = (now - datetime.fromisoformat(last)) >= interval
                    except Exception:
                        due = True
                if due:
                    await sync_source(source)
        except Exception:
            logger.exception("blacklist_sync_loop: erreur inattendue")
        await asyncio.sleep(60)
