"""Diffusion temps réel : WebSocket local + pub/sub Redis (multi-instances)."""
import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import WebSocket

from app.core.config import get_settings

logger = logging.getLogger("ws")
CHANNEL = "mgvms:events"


class WSManager:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self._redis: aioredis.Redis | None = None

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        """Publie sur Redis ; chaque instance relaie à ses clients locaux."""
        r = await self._get_redis()
        await r.publish(CHANNEL, json.dumps(message, default=str))

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
        return self._redis

    async def run_subscriber(self) -> None:
        r = await self._get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(CHANNEL)
        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            dead = []
            for ws in self.clients:
                try:
                    await ws.send_text(msg["data"])
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.disconnect(ws)


manager = WSManager()


def start_subscriber() -> asyncio.Task:
    return asyncio.create_task(manager.run_subscriber())
