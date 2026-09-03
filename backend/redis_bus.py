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
import uuid
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


# v3.25 · Étape 2c séparation pipeline/API — canal de commandes API → pipeline.
# File Redis (BLPOP), pas pub/sub : un pub/sub perd le message si le
# publish arrive avant que le SUBSCRIBE soit acquitté par Redis ; une file
# BLPOP n'a pas cette course — le message attend dans la liste jusqu'à ce
# qu'un consommateur le dépile, RPC ou fire-and-forget.
QUEUE_PIPELINE_COMMANDS = "mgvms:pipeline:commands"


async def send_pipeline_command(cmd: str, payload: Optional[dict] = None,
                                 timeout: float = 2.5) -> Optional[dict]:
    """API-side · RPC commande → pipeline, avec réponse synchrone.

    Retourne la réponse (dict) du pipeline, ou None si Redis est
    indisponible / le pipeline ne répond pas dans `timeout` secondes —
    à l'appelant de replier sur l'appel Python direct historique dans ce
    cas (voir chaque endpoint migré), jamais de 500 pour ça.
    """
    cid = uuid.uuid4().hex
    reply_key = f"mgvms:pipeline:reply:{cid}"
    msg = json.dumps({"cmd": cmd, "payload": payload or {}, "reply_key": reply_key}, default=str)
    try:
        r = get_redis()
        await r.rpush(QUEUE_PIPELINE_COMMANDS, msg)
        res = await r.blpop(reply_key, timeout=timeout)
        if res is None:
            logger.warning("redis_bus: pas de réponse pipeline pour %s (timeout %.1fs)", cmd, timeout)
            return None
        _, raw = res
        return json.loads(raw)
    except Exception:
        logger.exception("redis_bus: échec send_pipeline_command(%s)", cmd)
        return None


async def send_pipeline_signal(signal: str, payload: Optional[dict] = None) -> None:
    """API-side · notification fire-and-forget (pas de réponse attendue).

    Utilisé par les endpoints qui appellent aujourd'hui directement les
    signal_* de ai_engine (dirty flags in-process) — voir les 4 call sites
    dans routers.py. L'appel Python direct historique RESTE en place à
    chaque site (garantie zéro régression tant que pipeline et API
    partagent le même process) ; ce publish est un best-effort en plus,
    qui deviendra le SEUL mécanisme une fois le pipeline dans un autre
    process.
    """
    try:
        msg = json.dumps({"signal": signal, "payload": payload or {}}, default=str)
        await get_redis().rpush(QUEUE_PIPELINE_COMMANDS, msg)
    except Exception:
        logger.exception("redis_bus: échec send_pipeline_signal(%s)", signal)
