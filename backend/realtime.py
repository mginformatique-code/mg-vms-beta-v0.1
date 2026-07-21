"""Temps réel : métriques système (psutil), WebSocket, broadcast d'événements."""
import os
import time
import asyncio
import jwt
import psutil
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from database import db
from auth import JWT_ALGORITHM, get_jwt_secret

realtime_router = APIRouter(prefix="/api")

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
    return {
        "cpu": round(cpu), "ram": round(ram), "storage": round(storage),
        "temperature": temperature, "bandwidth_mbps": mbps, "uptime_days": uptime_days,
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
    payload = {k: v for k, v in alert.items() if k != "_id"}
    await manager.broadcast({"type": "alert", "data": payload},
                            predicate=lambda u: _can_see(u, payload.get("site_id", "")))


async def broadcast_camera_status(camera: dict):
    await manager.broadcast({"type": "camera_status", "data": {
        "id": camera.get("id"), "name": camera.get("name"),
        "status": camera.get("status"), "site_id": camera.get("site_id"),
    }}, predicate=lambda u: _can_see(u, camera.get("site_id", "")))


async def broadcast_ai_detections(camera_id: str, site_id: str, payload: dict):
    """Diffuse aux clients autorisés les détections IA d'une caméra (overlay Live)."""
    await manager.broadcast({"type": "ai_detections", "data": {
        "camera_id": camera_id, "site_id": site_id, **payload,
    }}, predicate=lambda u: _can_see(u, site_id or ""))


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
