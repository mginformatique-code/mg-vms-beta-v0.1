"""v3.27 · Historique des sessions de stationnement.

Demande explicite : "l'info doit être fiable, par ex prise de photo ->
voiture présente -> input bdd 'voiture AA999ZZ présente en stationnement
depuis le 01.01.2026 -> vu sur la caméra rue 5 min -> 3h après -> véhicule
en stationnement depuis XXh -> véhicule repart -> stationnement fini à 19h
-> vu à la caméra rue en train de rouler'" — un vrai journal PERSISTANT
avec photo à l'arrivée et au départ.

Design — ne duplique PAS le calcul d'immobilité déjà en place et déjà
corrigé contre les faux positifs (smart_zones/engine.py::track_plate_dwell,
dérivé de la position bbox réelle du tracker, publié dans le snapshot Redis
toutes les 3s, lu par GET /vehicles/{plate}/parking-status). Ce module se
contente d'observer les TRANSITIONS de cet état live (parked False→True =
arrivée, True→False = départ) et de les persister avec une photo réelle à
chaque bout — l'état live actuel restait jusqu'ici purement en mémoire
process, remis à zéro à chaque redémarrage du pipeline, sans aucun journal
consultable après coup.

Validation marque/couleur (demande explicite, suite au cas réel AX217EM —
plaque "attracteur" où l'OCR confond plusieurs vrais véhicules distincts
sous le même texte, déjà détecté par ailleurs comme "plaque suspecte") : à
chaque confirmation d'une session en cours, la marque/couleur de la lecture
la plus récente (déjà déterminées par les plugins vision couleur/marque)
sont comparées à celles capturées à l'arrivée. Un désaccord (les deux non
nulles et différentes) signifie très probablement que ce n'est PLUS le même
véhicule réel sous cette plaque — la session en cours est close immédiatement
et une nouvelle démarre, plutôt que de mélanger deux présences réelles
différentes sous une seule durée de stationnement incohérente.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from auth import require_permission
from database import db

logger = logging.getLogger("routes.parking_sessions")

parking_sessions_router = APIRouter(prefix="/api/vehicles", tags=["parking-sessions"])

_POLL_INTERVAL_S = 20


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


async def _representative_plate_reading(plate: str, near_iso: str | None, prefer_after: bool) -> dict | None:
    """id d'une lecture réelle avec photo pour illustrer une transition —
    la plus proche possible de `near_iso` avant (arrivée) ou après (départ,
    pour montrer le véhicule "reparti" — éventuellement sur une autre
    caméra, comme décrit dans la demande)."""
    query: dict = {"plate": plate, "vehicle_crop": {"$exists": True, "$ne": None}}
    sort_dir = 1 if prefer_after else -1
    if near_iso:
        query["timestamp"] = {"$gte": near_iso} if prefer_after else {"$lte": near_iso}
    doc = await db.plates.find(query, {"_id": 0, "id": 1}).sort("timestamp", sort_dir).limit(1).to_list(1)
    if doc:
        return doc[0]
    # Repli : rien trouvé dans le sens voulu (ex. aucune lecture après le
    # départ pour l'instant) — la lecture la plus récente disponible reste
    # préférable à aucune photo du tout.
    doc = await db.plates.find(
        {"plate": plate, "vehicle_crop": {"$exists": True, "$ne": None}}, {"_id": 0, "id": 1},
    ).sort("timestamp", -1).limit(1).to_list(1)
    return doc[0] if doc else None


async def _recent_vehicle_attributes(plate: str, camera_id: str) -> dict:
    """Marque/couleur de la lecture la plus récente pour cette plaque sur
    cette caméra — sert à valider qu'une session en cours correspond
    toujours au même véhicule réel (voir docstring de module)."""
    doc = await db.plates.find_one(
        {"plate": plate, "camera_id": camera_id},
        {"_id": 0, "vehicle_make": 1, "vehicle_color": 1},
        sort=[("timestamp", -1)],
    )
    return {"make": (doc or {}).get("vehicle_make"), "color": (doc or {}).get("vehicle_color")}


def _attributes_conflict(a: dict, b: dict) -> bool:
    for key in ("make", "color"):
        if a.get(key) and b.get(key) and a[key] != b[key]:
            return True
    return False


async def _close_session(session_id: str, plate: str, camera_id: str, near_iso: str | None) -> None:
    photo = await _representative_plate_reading(plate, near_iso, prefer_after=True)
    await db.parking_sessions.update_one(
        {"id": session_id},
        {"$set": {"departed_at": _iso(datetime.now(timezone.utc)),
                   "departure_plate_reading_id": (photo or {}).get("id"),
                   "status": "completed"}},
    )
    logger.info("parking_sessions: session terminée %s @ %s", plate, camera_id)


async def _open_session(plate: str, cam_id: str, cam: dict | None, arrived_at: str, attrs: dict) -> None:
    photo = await _representative_plate_reading(plate, arrived_at, prefer_after=False)
    await db.parking_sessions.insert_one({
        "id": str(uuid.uuid4()),
        "plate": plate,
        "camera_id": cam_id,
        "camera_name": (cam or {}).get("name"),
        "site_id": (cam or {}).get("site_id"),
        "site_name": (cam or {}).get("site_name"),
        "arrived_at": arrived_at,
        "arrival_plate_reading_id": (photo or {}).get("id"),
        "vehicle_make": attrs.get("make"),
        "vehicle_color": attrs.get("color"),
        "last_confirmed_at": _iso(datetime.now(timezone.utc)),
        "duration_seconds": 0,
        "departed_at": None,
        "departure_plate_reading_id": None,
        "status": "ongoing",
        "created_at": _iso(datetime.now(timezone.utc)),
    })
    logger.info("parking_sessions: nouvelle session %s @ %s", plate, cam_id)


async def _sync_parking_sessions() -> None:
    """Un passage : compare l'état dwell live (snapshot pipeline) aux
    sessions "ongoing" déjà enregistrées, crée/clôt ce qu'il faut."""
    from pipeline_snapshot import get_snapshot
    snap = await get_snapshot()
    if snap is None:
        return
    cameras_dwell = (snap.get("parking") or {}).get("cameras") or {}

    live_keys = set()
    for cam_id, plates in cameras_dwell.items():
        for plate, st in plates.items():
            if not st.get("parked"):
                continue
            live_keys.add((plate, cam_id))
            existing = await db.parking_sessions.find_one(
                {"plate": plate, "camera_id": cam_id, "status": "ongoing"}, {"_id": 0})
            attrs = await _recent_vehicle_attributes(plate, cam_id)
            if existing and _attributes_conflict(
                    {"make": existing.get("vehicle_make"), "color": existing.get("vehicle_color")}, attrs):
                # Marque/couleur incohérentes avec l'arrivée — probable
                # attracteur OCR (plaque partagée par plusieurs véhicules
                # réels distincts) : on ne prolonge PAS la session, on la
                # clôt et on en ouvre une nouvelle pour ce "nouveau" véhicule.
                await _close_session(existing["id"], plate, cam_id, existing.get("last_confirmed_at"))
                cam = await db.cameras.find_one({"id": cam_id}, {"_id": 0, "name": 1, "site_id": 1, "site_name": 1})
                await _open_session(plate, cam_id, cam, st["first_seen"], attrs)
            elif existing:
                await db.parking_sessions.update_one(
                    {"id": existing["id"]},
                    {"$set": {"last_confirmed_at": _iso(datetime.now(timezone.utc)),
                               "duration_seconds": st["dwell_seconds"],
                               # Complète marque/couleur si absentes à l'arrivée
                               # (vision AI pas encore passée à ce moment-là).
                               **({"vehicle_make": attrs["make"]} if attrs["make"] and not existing.get("vehicle_make") else {}),
                               **({"vehicle_color": attrs["color"]} if attrs["color"] and not existing.get("vehicle_color") else {})}},
                )
            else:
                cam = await db.cameras.find_one({"id": cam_id}, {"_id": 0, "name": 1, "site_id": 1, "site_name": 1})
                await _open_session(plate, cam_id, cam, st["first_seen"], attrs)

    # Clôture des sessions "ongoing" dont la plaque/caméra n'est plus "parked"
    async for sess in db.parking_sessions.find(
            {"status": "ongoing"}, {"_id": 0, "id": 1, "plate": 1, "camera_id": 1, "last_confirmed_at": 1}):
        if (sess["plate"], sess["camera_id"]) in live_keys:
            continue
        await _close_session(sess["id"], sess["plate"], sess["camera_id"], sess.get("last_confirmed_at"))


async def parking_sessions_loop() -> None:
    """Tâche de fond permanente — pas un plugin IA, aucun interrupteur
    dédié (même statut que le dwell live lui-même : fonctionnalité native)."""
    await asyncio.sleep(60)
    while True:
        try:
            await _sync_parking_sessions()
        except Exception:
            logger.exception("parking_sessions: erreur boucle de synchronisation")
        await asyncio.sleep(_POLL_INTERVAL_S)


@parking_sessions_router.get("/{plate}/parking-sessions")
async def list_parking_sessions(plate: str, limit: int = 30,
                                 user: dict = Depends(require_permission("read_plates"))):
    from routes.vehicles import _plate_or_404, _resolve_plate_family
    normalized = await _plate_or_404(plate, user)
    family = list(await _resolve_plate_family(normalized))
    docs = await db.parking_sessions.find(
        {"plate": {"$in": family}}, {"_id": 0},
    ).sort("arrived_at", -1).limit(limit).to_list(limit)
    return {"count": len(docs), "items": docs}
