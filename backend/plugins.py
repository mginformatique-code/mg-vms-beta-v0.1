"""Socle d'architecture de plugins — registre + activation dynamique.

Chaque plugin est décrit par un manifeste (catalogue ci-dessous). L'état d'activation
est persisté en base (collection `plugins`). Le cœur du logiciel interroge `is_enabled()`
pour conditionner les fonctionnalités modulaires (ANPR, IA, parking, thermique, etc.).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import db
from auth import get_current_user, require_role, log_audit

plugins_router = APIRouter(prefix="/api/plugins", tags=["plugins"])

PLUGIN_CATALOG = [
    {"id": "anpr", "name": "ANPR / LPR", "category": "Vision", "core": True, "version": "1.0.0",
     "description": "Lecture automatique des plaques + listes blanche/noire + alertes."},
    {"id": "ai_detection", "name": "Détection IA (YOLO)", "category": "Vision", "core": False, "version": "0.9.0",
     "description": "Détection d'objets temps réel (personne, véhicule, incendie, fumée, intrusion)."},
    {"id": "tracking", "name": "Tracking (ByteTrack)", "category": "Vision", "core": False, "version": "0.6.0",
     "description": "Suivi multi-objets avec identifiant persistant entre images."},
    {"id": "face_recognition", "name": "Reconnaissance faciale", "category": "Vision", "core": False, "version": "0.1.0",
     "description": "Identification de visages (sous réserve d'autorisation légale)."},
    {"id": "parking", "name": "Gestion Parking", "category": "Métier", "core": False, "version": "0.5.0",
     "description": "Comptage des places, durée de stationnement, taux d'occupation."},
    {"id": "thermal", "name": "Caméras thermiques", "category": "Capteurs", "core": False, "version": "0.2.0",
     "description": "Flux thermiques et seuils de température configurables."},
    {"id": "radar", "name": "Radar vitesse", "category": "Capteurs", "core": False, "version": "0.1.0",
     "description": "Mesure de vitesse et détection d'infractions."},
    {"id": "drone", "name": "Drone", "category": "Capteurs", "core": False, "version": "0.1.0",
     "description": "Intégration de flux drone et patrouilles aériennes."},
    {"id": "mqtt", "name": "Passerelle MQTT", "category": "Intégration", "core": False, "version": "0.4.0",
     "description": "Publication/souscription d'événements via un broker MQTT."},
    {"id": "access_control", "name": "Contrôle d'accès", "category": "Intégration", "core": False, "version": "0.3.0",
     "description": "Pilotage des barrières, portails et lecteurs de badges."},
]


async def seed_plugins():
    for p in PLUGIN_CATALOG:
        if not await db.plugins.find_one({"id": p["id"]}):
            await db.plugins.insert_one({**p, "enabled": p["id"] == "anpr"})


async def is_enabled(plugin_id: str) -> bool:
    p = await db.plugins.find_one({"id": plugin_id}, {"_id": 0})
    return bool(p and p.get("enabled"))


class PluginToggle(BaseModel):
    enabled: bool


@plugins_router.get("")
async def list_plugins(user: dict = Depends(get_current_user)):
    return await db.plugins.find({}, {"_id": 0}).to_list(100)


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
