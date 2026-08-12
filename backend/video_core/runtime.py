"""Video Core · monitoring runtime (Mongo collection `camera_runtime`).

Contrat :
    {
      camera_id,     status,        fps,          codec,
      decoder,       gpu,           latency_ms,   last_frame,
      viewers,       recorder,      ai,           updated_at
    }
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("video_core.runtime")


async def upsert_runtime(camera_id: str, **fields) -> None:
    """Upsert idempotent d'un document runtime. Champs ignorés si None."""
    from database import db
    payload = {"camera_id": camera_id,
               "updated_at": datetime.now(timezone.utc).isoformat()}
    for k, v in fields.items():
        if v is not None:
            payload[k] = v
    await db.camera_runtime.update_one(
        {"camera_id": camera_id}, {"$set": payload}, upsert=True)


async def runtime_snapshot(camera_id: str) -> Optional[dict]:
    from database import db
    doc = await db.camera_runtime.find_one({"camera_id": camera_id}, {"_id": 0})
    return doc


async def mark_offline(camera_id: str, reason: str = "") -> None:
    await upsert_runtime(camera_id, status="offline", last_error=reason)
