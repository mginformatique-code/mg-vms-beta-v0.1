"""Temps réel : métriques système (psutil), WebSocket, broadcast d'événements."""
import json
import logging
import os
import time
import asyncio
import jwt
import psutil
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from database import db
from auth import JWT_ALGORITHM, get_jwt_secret
from redis_bus import get_redis, publish_alert as _publish_alert, \
    publish_ai_detections as _publish_ai_detections, CHANNEL_ALERTS, CHANNEL_AI_DETECTIONS

realtime_router = APIRouter(prefix="/api")
logger = logging.getLogger("realtime")

_last_net = {"t": None, "bytes": 0}


def metrics_snapshot() -> dict:
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory().percent
    try:
        storage = psutil.disk_usage("/").percent
    except Exception:
        storage = 0
    temperature = 0
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            first = next(iter(temps.values()))
            if first:
                temperature = round(first[0].current)
    except Exception:
        temperature = 0
    net = psutil.net_io_counters()
    now = time.time()
    total_bytes = net.bytes_sent + net.bytes_recv
    mbps = 0
    if _last_net["t"] is not None:
        dt = now - _last_net["t"]
        if dt > 0:
            mbps = round((total_bytes - _last_net["bytes"]) * 8 / 1e6 / dt, 1)
    _last_net["t"] = now
    _last_net["bytes"] = total_bytes
    try:
        uptime_days = int((now - psutil.boot_time()) / 86400)
    except Exception:
        uptime_days = 0
    # GPU (NVIDIA via NVML — fallback silencieux sur CPU-only)
    gpu_data = {"available": False}
    try:
        from gpu import gpu_summary
        gpu_data = gpu_summary()
    except Exception:
        pass
    return {
        "cpu": round(cpu), "ram": round(ram), "storage": round(storage),
        "temperature": temperature, "bandwidth_mbps": mbps, "uptime_days": uptime_days,
        "gpu": gpu_data,
    }


class ConnectionManager:
    def __init__(self):
        self.active = {}  # websocket -> user dict

    async def connect(self, ws: WebSocket, user: dict):
        await ws.accept()
        self.active[ws] = user

    def disconnect(self, ws: WebSocket):
        self.active.pop(ws, None)

    async def broadcast(self, message: dict, predicate=None):
        dead = []
        for ws, user in list(self.active.items()):
            if predicate and not predicate(user):
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


def _can_see(user: dict, site_id: str) -> bool:
    if user.get("role") in ("admin", "technician"):
        return True
    return site_id in (user.get("site_ids") or [])


async def broadcast_alert(alert: dict):
    """v3.22 · Publie sur Redis plutôt que de toucher `manager` en direct —
    voir redis_bus.py. Appelants inchangés (pipeline IA ET routes HTTP),
    la livraison réelle se fait dans redis_bridge_loop() ci-dessous."""
    await _publish_alert(alert)


async def broadcast_camera_status(camera: dict):
    # Appelé uniquement depuis routers.py (process API) — pas concerné par
    # la séparation pipeline/API, reste en appel direct.
    await manager.broadcast({"type": "camera_status", "data": {
        "id": camera.get("id"), "name": camera.get("name"),
        "status": camera.get("status"), "site_id": camera.get("site_id"),
    }}, predicate=lambda u: _can_see(u, camera.get("site_id", "")))


async def broadcast_ai_detections(camera_id: str, site_id: str, payload: dict):
    """Diffuse aux clients autorisés les détections IA d'une caméra (overlay Live).
    v3.22 · Publie sur Redis — voir broadcast_alert ci-dessus."""
    await _publish_ai_detections(camera_id, site_id, payload)


async def _deliver_alert(payload: dict):
    await manager.broadcast({"type": "alert", "data": payload},
                            predicate=lambda u: _can_see(u, payload.get("site_id", "")))


async def _deliver_ai_detections(msg: dict):
    await manager.broadcast({"type": "ai_detections", "data": msg},
                            predicate=lambda u: _can_see(u, msg.get("site_id", "")))


async def redis_bridge_loop():
    """v3.22 · Pont Redis → WebSocket local. Tourne dans le process qui
    détient les connexions WS (ConnectionManager) ; consomme ce que publient
    broadcast_alert/broadcast_ai_detections — potentiellement depuis un
    AUTRE process une fois le pipeline IA séparé du serveur API. Reconnexion
    automatique si Redis devient injoignable (ne doit jamais faire planter
    le process API)."""
    while True:
        try:
            r = get_redis()
            pubsub = r.pubsub()
            await pubsub.subscribe(CHANNEL_ALERTS, CHANNEL_AI_DETECTIONS)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                except Exception:
                    continue
                if message["channel"] == CHANNEL_ALERTS:
                    await _deliver_alert(data)
                elif message["channel"] == CHANNEL_AI_DETECTIONS:
                    await _deliver_ai_detections(data)
        except Exception:
            logger.exception("redis_bridge_loop: connexion Redis perdue, reconnexion dans 3s")
            await asyncio.sleep(3)


async def _auth_ws(token: str):
    if not token:
        return None
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
    except Exception:
        return None


@realtime_router.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str = ""):
    user = await _auth_ws(token)
    if not user:
        await ws.close(code=1008)
        return
    await manager.connect(ws, user)
    try:
        await ws.send_json({"type": "metrics", "data": metrics_snapshot()})
        while True:
            await ws.receive_text()  # keepalive
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


async def metrics_broadcaster():
    while True:
        await asyncio.sleep(5)
        if manager.active:
            await manager.broadcast({"type": "metrics", "data": metrics_snapshot()})
