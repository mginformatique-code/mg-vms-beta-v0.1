"""Route module — Dashboard (stats + timeseries).
Extrait de `routers.py` (P1 modularisation, Feb 2026).
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends

from auth import allowed_sites, get_current_user, site_scope
from database import db
from realtime import metrics_snapshot

dashboard_router = APIRouter(prefix="/api", tags=["dashboard"])


@dashboard_router.get("/dashboard/stats")
async def dashboard_stats(user: dict = Depends(get_current_user)):
    sf = site_scope({}, user)  # {} for admin/tech, {site_id:{$in:[...]}} otherwise
    allowed = allowed_sites(user)
    total_cams = await db.cameras.count_documents(sf)
    online = await db.cameras.count_documents({**sf, "status": "online"})
    sites = await db.sites.count_documents({} if allowed is None else {"id": {"$in": allowed}})
    events_today = await db.events.count_documents({
        **sf, "timestamp": {"$gte": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()}
    })
    alerts_active = await db.alerts.count_documents({**sf, "acknowledged": False})
    plates_today = await db.plates.count_documents({
        **sf, "timestamp": {"$gte": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()}
    })
    return {
        "cameras_total": total_cams,
        "cameras_online": online,
        "cameras_offline": total_cams - online,
        "sites": sites,
        "events_today": events_today,
        "alerts_active": alerts_active,
        "plates_today": plates_today,
        "system": await metrics_snapshot(),
    }


@dashboard_router.get("/dashboard/timeseries")
async def dashboard_timeseries(user: dict = Depends(get_current_user)):
    """Séries horaires réelles (agrégation Mongo des dernières 24 h)."""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=24)).isoformat()

    async def hourly_counts(coll) -> dict:
        pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {"_id": {"$substr": ["$timestamp", 0, 13]}, "count": {"$sum": 1}}},
        ]
        return {row["_id"]: row["count"] async for row in coll.aggregate(pipeline)}

    ev, pl, al = await hourly_counts(db.events), await hourly_counts(db.plates), await hourly_counts(db.alerts)
    points = []
    for i in range(24):
        t = now - timedelta(hours=23 - i)
        key = t.strftime("%Y-%m-%dT%H")
        points.append({
            "time": t.strftime("%H:00"),
            "events": ev.get(key, 0),
            "plates": pl.get(key, 0),
            "alerts": al.get(key, 0),
        })
    # v3.21 · Sans $match, ce group scannait TOUTE la collection events (243k+
    # documents et en croissance continue) à chaque chargement du dashboard —
    # mesuré en prod : 508s. Le reste de cet endpoint est explicitement borné
    # aux dernières 24h (voir docstring) ; le breakdown ne l'était pas, seul
    # oubli. Borné à `since` comme le reste : utilise l'index composé
    # {type:1, timestamp:-1} déjà en place, retombe à quelques ms.
    breakdown = []
    cursor = db.events.aggregate([
        {"$match": {"timestamp": {"$gte": since}}},
        {"$group": {"_id": "$type", "count": {"$sum": 1}}},
    ])
    async for row in cursor:
        breakdown.append({"name": row["_id"], "value": row["count"]})
    return {"hourly": points, "breakdown": breakdown}
