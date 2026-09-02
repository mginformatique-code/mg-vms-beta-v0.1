"""v3.22 · Bus Redis pub/sub — chantier séparation pipeline IA / serveur API.

Le pipeline IA (ai_engine.py, pipeline_v2/*) appelait jusqu'ici directement
les fonctions broadcast_* de realtime.py, qui touchent en mémoire les
connexions WebSocket vivantes du process API (ConnectionManager.active).
Ça ne survit pas à une séparation en process/conteneurs distincts.

Étape 1 du chantier : tout passe désormais par Redis pub/sub plutôt que
par un appel Python direct — realtime.py reste l'API publique (aucun
appelant, pipeline ou routes HTTP, n'a besoin de changer), mais en
interne broadcast_alert/broadcast_ai_detections publient ici, et un
nouveau redis_bridge_loop() (dans realtime.py) s'y abonne pour livrer
aux WebSockets. Le tout tourne encore dans un seul conteneur pour
l'instant — le point est de valider le transport en conditions réelles
avant de scinder pour de vrai.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger("redis_bus")

CHANNEL_ALERTS = "mgvms:alerts"
CHANNEL_AI_DETECTIONS = "mgvms:ai_detections"

_client: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        _client = aioredis.from_url(url, decode_responses=True)
    return _client


async def publish_alert(alert: dict) -> None:
    payload = {k: v for k, v in alert.items() if k != "_id"}
    try:
        await get_redis().publish(CHANNEL_ALERTS, json.dumps(payload, default=str))
    except Exception:
        logger.exception("redis_bus: échec publish alert (Redis indisponible ?)")


async def publish_ai_detections(camera_id: str, site_id: str, payload: dict) -> None:
    msg = {"camera_id": camera_id, "site_id": site_id, **payload}
    try:
        await get_redis().publish(CHANNEL_AI_DETECTIONS, json.dumps(msg, default=str))
    except Exception:
        logger.exception("redis_bus: échec publish ai_detections (Redis indisponible ?)")
