"""Route module — Smart Zones CRUD + test action (P3, Feb 2026)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from auth import require_permission, log_audit
from database import db
from smart_zones import SmartZoneInput, ZoneAction, new_zone_doc
from smart_zones.actuators import dispatch_action, ACTUATORS
from smart_zones.engine import engine

smart_zones_router = APIRouter(prefix="/api", tags=["smart-zones"])


@smart_zones_router.get("/smart-zones")
async def list_smart_zones(camera_id: str | None = None,
                            user: dict = Depends(require_permission("view_live"))):
    q = {}
    if camera_id:
        q["camera_id"] = camera_id
    zones = await db.smart_zones.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"zones": zones, "count": len(zones)}


@smart_zones_router.get("/smart-zones/{zone_id}")
async def get_smart_zone(zone_id: str, user: dict = Depends(require_permission("view_live"))):
    zone = await db.smart_zones.find_one({"id": zone_id}, {"_id": 0})
    if not zone:
        raise HTTPException(404, "Zone introuvable")
    return zone


@smart_zones_router.post("/smart-zones")
async def create_smart_zone(data: SmartZoneInput,
                             user: dict = Depends(require_permission("technician"))):
    cam = await db.cameras.find_one({"id": data.camera_id}, {"_id": 0, "id": 1, "name": 1})
    if not cam:
        raise HTTPException(400, f"Caméra {data.camera_id} introuvable")
    doc = new_zone_doc(data)
    await db.smart_zones.insert_one(dict(doc))
    engine.invalidate_cache()
    await log_audit(user, "smart_zone_created", data.name, data.camera_id)
    return doc


@smart_zones_router.put("/smart-zones/{zone_id}")
async def update_smart_zone(zone_id: str, data: SmartZoneInput,
                             user: dict = Depends(require_permission("technician"))):
    patch = {
        "name": data.name,
        "camera_id": data.camera_id,
        "enabled": data.enabled,
        "polygon": data.polygon,
        "detect": data.detect.model_dump(),
        "trigger_on": data.trigger_on,
        "actions": [a.model_dump() for a in data.actions],
    }
    r = await db.smart_zones.update_one({"id": zone_id}, {"$set": patch})
    if r.matched_count == 0:
        raise HTTPException(404, "Zone introuvable")
    engine.invalidate_cache()
    await log_audit(user, "smart_zone_updated", data.name)
    zone = await db.smart_zones.find_one({"id": zone_id}, {"_id": 0})
    return zone


@smart_zones_router.delete("/smart-zones/{zone_id}")
async def delete_smart_zone(zone_id: str,
                             user: dict = Depends(require_permission("technician"))):
    r = await db.smart_zones.delete_one({"id": zone_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Zone introuvable")
    engine.invalidate_cache()
    await log_audit(user, "smart_zone_deleted", zone_id)
    return {"ok": True}


@smart_zones_router.get("/smart-zones/actuators/available")
async def list_actuators(user: dict = Depends(require_permission("view_live"))):
    """Liste des types d'actions disponibles pour la UI."""
    return {
        "actuators": [
            {"type": "webhook", "label": "Webhook HTTP",
             "fields": ["url", "method (POST)", "headers (dict)", "body (any)"]},
            {"type": "mqtt", "label": "MQTT publish",
             "fields": ["broker", "port (1883)", "topic", "payload", "username?", "password?", "tls?"]},
            {"type": "home_assistant", "label": "Home Assistant service",
             "fields": ["base_url", "token", "service (light.turn_on)", "data"]},
            {"type": "tuya", "label": "Tuya Cloud device",
             "fields": ["access_id", "access_secret", "device_id", "commands", "region (eu)"]},
            {"type": "plugin", "label": "Plugin EventConsumer",
             "fields": ["plugin_name (ex: telegram-notifier)", "message", "data"]},
            {"type": "tts", "label": "Text-to-speech (via plugin)",
             "fields": ["text", "voice?", "language?", "plugin_name (tts-notifier)"]},
        ],
    }


@smart_zones_router.post("/smart-zones/{zone_id}/test-action/{action_index}")
async def test_action(zone_id: str, action_index: int,
                       user: dict = Depends(require_permission("technician"))):
    """Déclenche manuellement l'action `action_index` d'une zone — pour tester la config."""
    zone = await db.smart_zones.find_one({"id": zone_id}, {"_id": 0})
    if not zone:
        raise HTTPException(404, "Zone introuvable")
    actions = zone.get("actions") or []
    if action_index >= len(actions):
        raise HTTPException(400, f"index {action_index} hors bornes (max {len(actions)})")
    from datetime import datetime, timezone
    context = {
        "zone_name": zone["name"],
        "zone_id": zone["id"],
        "camera_id": zone["camera_id"],
        "event_kind": "test",
        "track_id": "test-track",
        "class": "test-class",
        "confidence": 0.99,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    result = await dispatch_action(actions[action_index], context)
    await log_audit(user, "smart_zone_test_action", zone["name"], str(action_index))
    return {"context": context, "result": result}
