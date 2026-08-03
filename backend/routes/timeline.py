"""Route module — Timeline avancée (P5, Feb 2026).

Retourne un flux unifié d'événements sur une fenêtre temporelle :
- Événements IA / plugin (`db.events`)
- Alertes (`db.alerts`)
- Plaques ANPR (`db.plates`)
- Enregistrements segments (`db.recordings`)

Utile pour construire une timeline multi-caméras scrubable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from auth import require_permission
from database import db

timeline_router = APIRouter(prefix="/api", tags=["timeline"])


@timeline_router.get("/timeline")
async def get_timeline(
    since: str | None = Query(None, description="ISO timestamp (défaut : -24h)"),
    until: str | None = Query(None, description="ISO timestamp (défaut : now)"),
    camera_ids: str | None = Query(None, description="CSV d'IDs de caméras"),
    layers: str = Query("events,alerts,plates,recordings",
                         description="CSV parmi events, alerts, plates, recordings"),
    limit_per_layer: int = Query(500, ge=1, le=5000),
    user: dict = Depends(require_permission("view_live")),
):
    """Flux unifié pour la timeline multi-caméras."""
    now = datetime.now(timezone.utc)
    since_iso = since or (now - timedelta(hours=24)).isoformat()
    until_iso = until or now.isoformat()
    cams = [c.strip() for c in (camera_ids or "").split(",") if c.strip()]
    layer_set = {l.strip() for l in layers.split(",") if l.strip()}

    q_time = {"$gte": since_iso, "$lte": until_iso}
    q_cam = {"camera_id": {"$in": cams}} if cams else {}
    out: dict[str, list[dict[str, Any]]] = {}

    if "events" in layer_set:
        docs = await db.events.find(
            {"timestamp": q_time, **q_cam},
            {"_id": 0, "thumbnail": 0}
        ).sort("timestamp", -1).limit(limit_per_layer).to_list(limit_per_layer)
        out["events"] = [{
            "kind": "event", "id": d.get("id"), "timestamp": d.get("timestamp"),
            "camera_id": d.get("camera_id"), "camera_name": d.get("camera_name"),
            "label": d.get("type") or "event", "severity": d.get("severity"),
            "message": d.get("message"),
            "detectors": d.get("detectors"), "trackers": d.get("trackers"),
            "plugin": d.get("plugin"),
        } for d in docs]

    if "alerts" in layer_set:
        docs = await db.alerts.find(
            {"timestamp": q_time, **q_cam}, {"_id": 0}
        ).sort("timestamp", -1).limit(limit_per_layer).to_list(limit_per_layer)
        out["alerts"] = [{
            "kind": "alert", "id": d.get("id"), "timestamp": d.get("timestamp"),
            "camera_id": d.get("camera_id"), "camera_name": d.get("camera_name"),
            "label": d.get("type") or "alert", "severity": d.get("severity") or "high",
            "message": d.get("message") or d.get("reason"),
            "acknowledged": d.get("acknowledged"),
        } for d in docs]

    if "plates" in layer_set:
        docs = await db.plates.find(
            {"timestamp": q_time, **q_cam},
            {"_id": 0, "vehicle_crop": 0, "plate_crop": 0, "frame_thumb": 0}
        ).sort("timestamp", -1).limit(limit_per_layer).to_list(limit_per_layer)
        out["plates"] = [{
            "kind": "plate", "id": d.get("id"), "timestamp": d.get("timestamp"),
            "camera_id": d.get("camera_id"), "camera_name": d.get("camera_name"),
            "label": d.get("plate"), "confidence": d.get("confidence"),
            "list_status": d.get("list_status"),
            "engine": d.get("engine", "fast-alpr"),
            "severity": ("critical" if d.get("list_status") == "black"
                          else "info" if d.get("list_status") == "white" else "low"),
        } for d in docs]

    if "recordings" in layer_set:
        # Un segment recouvre une plage — utile pour matérialiser les "coupures"
        docs = await db.recordings.find(
            {"start": {"$gte": since_iso, "$lte": until_iso}, **q_cam},
            {"_id": 0, "path": 0}
        ).sort("start", -1).limit(limit_per_layer).to_list(limit_per_layer)
        out["recordings"] = [{
            "kind": "recording", "id": d.get("id"),
            "timestamp": d.get("start"), "end": d.get("end"),
            "camera_id": d.get("camera_id"), "camera_name": d.get("camera_name"),
            "label": "segment", "duration_sec": d.get("duration_sec"),
        } for d in docs]

    total = sum(len(v) for v in out.values())
    return {
        "since": since_iso, "until": until_iso, "cameras": cams,
        "layers": list(layer_set), "counts": {k: len(v) for k, v in out.items()},
        "total": total, **out,
    }
