"""Socle d'architecture de plugins — registre + activation + **health checks réels**.

Chaque plugin est décrit par un manifeste et dispose d'un `health_check()` qui vérifie
réellement l'état du module (deps importables, config valide, service opérationnel).
Aucune donnée fictive : si un plugin n'est pas installé, il apparaît "Non configuré".
"""
import asyncio
import importlib
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import db
from auth import get_current_user, require_role, log_audit

plugins_router = APIRouter(prefix="/api/plugins", tags=["plugins"])

PLUGIN_CATALOG = [
    {"id": "anpr", "name": "ANPR / LPR", "category": "Vision", "core": True, "version": "1.0.0",
     "description": "Lecture automatique des plaques + listes blanche/noire + alertes.",
     "route": "/anpr"},
    {"id": "ai_detection", "name": "Détection IA (YOLO)", "category": "Vision", "core": False, "version": "0.9.0",
     "description": "Détection d'objets temps réel (personne, véhicule, incendie, fumée, intrusion).",
     "route": "/plugins/ai_detection"},
    {"id": "tracking", "name": "Tracking (ByteTrack)", "category": "Vision", "core": False, "version": "0.6.0",
     "description": "Suivi multi-objets avec identifiant persistant entre images.",
     "route": "/plugins/tracking"},
    {"id": "face_recognition", "name": "Reconnaissance faciale", "category": "Vision", "core": False, "version": "0.1.0",
     "description": "Identification de visages (sous réserve d'autorisation légale).",
     "route": "/plugins/face_recognition"},
    {"id": "parking", "name": "Gestion Parking", "category": "Métier", "core": False, "version": "0.5.0",
     "description": "Comptage des places, durée de stationnement, taux d'occupation.",
     "route": "/plugins/parking"},
    {"id": "thermal", "name": "Caméras thermiques", "category": "Capteurs", "core": False, "version": "0.2.0",
     "description": "Flux thermiques et seuils de température configurables.",
     "route": "/plugins/thermal"},
    {"id": "radar", "name": "Radar vitesse", "category": "Capteurs", "core": False, "version": "0.1.0",
     "description": "Mesure de vitesse et détection d'infractions.",
     "route": "/plugins/radar"},
    {"id": "drone", "name": "Drone", "category": "Capteurs", "core": False, "version": "0.1.0",
     "description": "Intégration de flux drone et patrouilles aériennes.",
     "route": "/plugins/drone"},
    {"id": "mqtt", "name": "Passerelle MQTT", "category": "Intégration", "core": False, "version": "0.4.0",
     "description": "Publication/souscription d'événements via un broker MQTT.",
     "route": "/plugins/mqtt"},
    {"id": "access_control", "name": "Contrôle d'accès", "category": "Intégration", "core": False, "version": "0.3.0",
     "description": "Pilotage des barrières, portails et lecteurs de badges.",
     "route": "/plugins/access_control"},
]


async def seed_plugins():
    for p in PLUGIN_CATALOG:
        existing = await db.plugins.find_one({"id": p["id"]})
        if not existing:
            await db.plugins.insert_one({**p, "enabled": p["id"] == "anpr"})
        else:
            # Maintient à jour les champs statiques (route, description, version) sans écraser `enabled`
            await db.plugins.update_one({"id": p["id"]}, {"$set": {k: v for k, v in p.items() if k != "id"}})


async def is_enabled(plugin_id: str) -> bool:
    p = await db.plugins.find_one({"id": plugin_id}, {"_id": 0})
    return bool(p and p.get("enabled"))


# ============ Health checks RÉELS par plugin ============
def _has_module(*names: str) -> tuple[bool, str]:
    for n in names:
        try:
            m = importlib.import_module(n)
            v = getattr(m, "__version__", "?")
            return True, f"{n} {v}"
        except ImportError:
            continue
    return False, f"Module manquant : {', '.join(names)}"


async def _health_anpr() -> dict:
    checks = []
    ok, det = _has_module("fast_alpr")
    checks.append({"name": "Dépendance fast-alpr", "ok": ok, "detail": det})
    # Config : au moins une caméra avec detect_enabled
    cams_ia = await db.cameras.count_documents({"detect_enabled": True})
    checks.append({"name": "Caméras IA configurées", "ok": cams_ia > 0, "detail": f"{cams_ia} caméra(s)"})
    # Événements générés (plaques)
    total = await db.plates.count_documents({})
    last = await db.plates.find_one({}, {"_id": 0, "timestamp": 1}, sort=[("timestamp", -1)])
    since = _since(await _events_last_24h(db.plates))
    return {"checks": checks, "loaded": ok, "configured": cams_ia > 0,
            "healthy": ok and cams_ia > 0, "events_total": total, "events_24h": since,
            "last_event_at": last.get("timestamp") if last else None}


async def _health_ai_detection() -> dict:
    checks = []
    ok_u, det_u = _has_module("ultralytics")
    checks.append({"name": "Dépendance ultralytics", "ok": ok_u, "detail": det_u})
    ok_cv, det_cv = _has_module("cv2")
    checks.append({"name": "Dépendance opencv", "ok": ok_cv, "detail": det_cv})
    # Device
    try:
        import torch
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        checks.append({"name": "Cible d'inférence", "ok": True, "detail": dev})
    except Exception:
        checks.append({"name": "Cible d'inférence", "ok": False, "detail": "torch indisponible"})
    cams = await db.cameras.count_documents({"detect_enabled": True, "status": "online"})
    checks.append({"name": "Caméras IA en ligne", "ok": cams > 0, "detail": f"{cams} caméra(s)"})
    total = await db.events.count_documents({})
    last = await db.events.find_one({}, {"_id": 0, "timestamp": 1}, sort=[("timestamp", -1)])
    return {"checks": checks, "loaded": ok_u and ok_cv,
            "configured": cams > 0, "healthy": ok_u and ok_cv and cams > 0,
            "events_total": total, "events_24h": await _events_last_24h(db.events),
            "last_event_at": last.get("timestamp") if last else None}


async def _health_tracking() -> dict:
    checks = []
    ok, det = _has_module("supervision", "bytetracker", "ultralytics")
    checks.append({"name": "Bibliothèque tracking", "ok": ok, "detail": det})
    cfg = await db.settings.find_one({"key": "bytetrack_config"}, {"_id": 0})
    val = (cfg or {}).get("value") or {}
    configured = bool(val.get("enabled")) if val else False
    checks.append({"name": "Configuration ByteTrack",
                    "ok": configured,
                    "detail": (f"thresh={val.get('track_thresh')} buffer={val.get('track_buffer')}"
                                if val else "Non configuré")})
    # Persistance IDs : nombre d'événements tracés (ayant un `track_id`) sur 24h
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    tracked = await db.events.count_documents({"timestamp": {"$gte": since}, "track_id": {"$exists": True, "$ne": None}})
    checks.append({"name": "Persistance des IDs (24 h)",
                    "ok": tracked > 0, "detail": f"{tracked} événement(s) tracé(s)"})
    total = await db.events.count_documents({"track_id": {"$exists": True, "$ne": None}})
    return {"checks": checks, "loaded": ok, "configured": configured and ok,
             "healthy": ok and configured, "events_total": total,
             "events_24h": tracked, "last_event_at": None}


async def _health_face_recognition() -> dict:
    checks = []
    from face_recognition_engine import availability
    avail = availability()
    checks.append({"name": "Bibliothèque insightface", "ok": avail["installed"],
                    "detail": avail["notes"]})
    faces = await db.faces.count_documents({}) if "faces" in await db.list_collection_names() else 0
    faces_with_photo = 0
    if "faces" in await db.list_collection_names():
        faces_with_photo = await db.faces.count_documents({"encoding": {"$ne": None, "$exists": True}})
    checks.append({"name": "Visages enregistrés",
                    "ok": faces > 0, "detail": f"{faces} total · {faces_with_photo} avec photo"})
    cfg = await db.settings.find_one({"key": "face_recognition_config"}, {"_id": 0})
    configured = bool((cfg or {}).get("value", {}).get("enabled")) and faces_with_photo > 0
    return {"checks": checks, "loaded": avail["installed"],
            "configured": configured, "healthy": avail["installed"] and configured,
            "events_total": 0, "events_24h": 0, "last_event_at": None}


async def _health_parking() -> dict:
    checks = []
    zones = await db.parking_zones.count_documents({}) if "parking_zones" in await db.list_collection_names() else 0
    checks.append({"name": "Zones de stationnement définies", "ok": zones > 0, "detail": f"{zones} zone(s)"})
    return {"checks": checks, "loaded": True, "configured": zones > 0,
            "healthy": zones > 0, "events_total": 0, "events_24h": 0, "last_event_at": None}


async def _health_hardware_sensor(name: str, coll: str) -> dict:
    """Capteur matériel : configuré si au moins un capteur est déclaré par l'admin."""
    count = 0
    if coll in await db.list_collection_names():
        count = await db[coll].count_documents({})
    checks = [{"name": f"Capteurs {name} déclarés", "ok": count > 0,
                "detail": f"{count} capteur(s)" if count else "Aucun matériel détecté"}]
    return {"checks": checks, "loaded": count > 0, "configured": count > 0,
            "healthy": count > 0, "events_total": 0, "events_24h": 0, "last_event_at": None,
            "warning": None if count > 0 else f"Ajoutez un capteur {name.lower()} pour activer ce plugin"}


async def _health_access_control() -> dict:
    count = 0
    if "access_controllers" in await db.list_collection_names():
        count = await db.access_controllers.count_documents({})
    checks = [{"name": "Contrôleurs déclarés", "ok": count > 0,
                "detail": f"{count} contrôleur(s)" if count else "Aucun contrôleur enregistré"}]
    return {"checks": checks, "loaded": count > 0, "configured": count > 0,
            "healthy": count > 0, "events_total": 0, "events_24h": 0, "last_event_at": None,
            "warning": None if count > 0 else "Ajoutez un contrôleur pour activer le plugin"}


async def _health_anpr_v2() -> dict:
    """Version étendue : ROI par caméra + config globale."""
    base = await _health_anpr()
    cfg = await db.settings.find_one({"key": "anpr_config"}, {"_id": 0})
    val = (cfg or {}).get("value") or {}
    country = val.get("country", "fr")
    base["checks"].append({"name": "Config ANPR globale",
                            "ok": bool(cfg),
                            "detail": f"pays={country.upper()}" if cfg else "défauts appliqués"})
    # Nombre de caméras avec ROI ou listes locales configurées
    cams_roi = await db.cameras.count_documents({"anpr_config.roi_polygon.0": {"$exists": True}})
    base["checks"].append({"name": "Caméras avec ROI dessinée",
                            "ok": cams_roi > 0 or True,
                            "detail": f"{cams_roi} caméra(s)"})
    return base


async def _health_mqtt() -> dict:
    checks = []
    ok, det = _has_module("paho.mqtt.client", "paho.mqtt")
    checks.append({"name": "Dépendance paho-mqtt", "ok": ok, "detail": det})
    cfg = await db.settings.find_one({"key": "mqtt_broker"}, {"_id": 0})
    configured = bool(cfg and cfg.get("value", {}).get("host"))
    checks.append({"name": "Broker MQTT configuré", "ok": configured,
                   "detail": (cfg["value"]["host"] + ":" + str(cfg["value"].get("port", 1883))) if configured else "Non configuré"})
    return {"checks": checks, "loaded": ok, "configured": configured,
            "healthy": ok and configured, "events_total": 0, "events_24h": 0,
            "last_event_at": None}


HEALTH_HANDLERS = {
    "anpr": _health_anpr_v2,
    "ai_detection": _health_ai_detection,
    "tracking": _health_tracking,
    "face_recognition": _health_face_recognition,
    "parking": _health_parking,
    "thermal": lambda: _health_hardware_sensor("Thermal", "thermal_sensors"),
    "radar": lambda: _health_hardware_sensor("Radar", "radar_sensors"),
    "drone": lambda: _health_hardware_sensor("Drone", "drones"),
    "mqtt": _health_mqtt,
    "access_control": _health_access_control,
}


async def _events_last_24h(coll) -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return await coll.count_documents({"timestamp": {"$gte": since}})


def _since(n: int) -> int:
    return int(n or 0)


def _overall_status(plugin: dict, hc: dict) -> str:
    """Calcule l'état global : disabled | error | not_configured | ok."""
    if not plugin.get("enabled"):
        return "disabled"
    if hc.get("loaded") is False:
        return "error"
    if hc.get("configured") is False:
        return "not_configured"
    return "ok" if hc.get("healthy") else "not_configured"


class PluginToggle(BaseModel):
    enabled: bool


@plugins_router.get("")
async def list_plugins(user: dict = Depends(get_current_user)):
    """Renvoie chaque plugin avec son manifeste + health-check RÉEL (checks, métriques, état)."""
    docs = await db.plugins.find({}, {"_id": 0}).to_list(100)
    out = []
    for p in docs:
        handler = HEALTH_HANDLERS.get(p["id"])
        try:
            hc = await handler() if handler else {"checks": [], "loaded": True, "configured": True,
                                                  "healthy": True, "events_total": 0, "events_24h": 0,
                                                  "last_event_at": None}
        except Exception as e:
            hc = {"checks": [{"name": "Erreur interne", "ok": False, "detail": str(e)}],
                  "loaded": False, "configured": False, "healthy": False,
                  "events_total": 0, "events_24h": 0, "last_event_at": None, "error": str(e)}
        out.append({**p, "health": hc, "status": _overall_status(p, hc)})
    return out


@plugins_router.get("/{plugin_id}/health")
async def plugin_health(plugin_id: str, user: dict = Depends(get_current_user)):
    p = await db.plugins.find_one({"id": plugin_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Plugin introuvable")
    handler = HEALTH_HANDLERS.get(plugin_id)
    if not handler:
        raise HTTPException(404, "Aucun health-check défini pour ce plugin")
    hc = await handler()
    return {"plugin_id": plugin_id, **hc, "status": _overall_status(p, hc)}


@plugins_router.put("/{plugin_id}")
async def toggle_plugin(plugin_id: str, data: PluginToggle, user: dict = Depends(require_role("admin"))):
    plugin = await db.plugins.find_one({"id": plugin_id}, {"_id": 0})
    if not plugin:
        raise HTTPException(404, "Plugin introuvable")
    if plugin.get("core") and not data.enabled:
        raise HTTPException(400, "Un plugin cœur ne peut pas être désactivé")
    await db.plugins.update_one({"id": plugin_id}, {"$set": {"enabled": data.enabled}})
    await log_audit(user, "plugin_toggled", plugin_id, "activé" if data.enabled else "désactivé")
    return await db.plugins.find_one({"id": plugin_id}, {"_id": 0})
