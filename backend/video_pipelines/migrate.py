"""video-pipeline-v2 · Migration douce du modèle caméra.

`stream_mode` + `live_preview_source` (2 champs concurrents) → champ UNIQUE
`stream_pipeline` ∈ {direct_rtsp, mjpeg, mediamtx}. Défaut : mediamtx.
Mapping : direct_rtsp→direct_rtsp · go2rtc→mediamtx · auto→mediamtx.
Idempotente — exécutée à chaque démarrage backend.
"""
import logging

from database import db

from .base import PIPELINES, _LEGACY_MAP, DEFAULT_PIPELINE

logger = logging.getLogger("video.migrate")


async def migrate_stream_pipeline() -> int:
    n = 0
    async for cam in db.cameras.find({}, {"_id": 0, "id": 1, "stream_pipeline": 1,
                                           "stream_mode": 1}):
        # Démos : MJPEG (affichage fiable dans tous les environnements —
        # WebRTC nécessite des ports ICE/UDP joignables depuis le navigateur).
        if cam["id"].startswith("demo-") or cam["id"].startswith("demo_"):
            if (cam.get("stream_pipeline") or "") != "mjpeg":
                await db.cameras.update_one({"id": cam["id"]},
                                             {"$set": {"stream_pipeline": "mjpeg"},
                                              "$unset": {"live_preview_source": ""}})
                n += 1
            continue
        if (cam.get("stream_pipeline") or "").lower() in PIPELINES:
            continue
        legacy = (cam.get("stream_mode") or "auto").lower()
        target = _LEGACY_MAP.get(legacy, DEFAULT_PIPELINE)
        await db.cameras.update_one(
            {"id": cam["id"]},
            {"$set": {"stream_pipeline": target},
             "$unset": {"live_preview_source": ""}})
        n += 1
        logger.info("migration stream_pipeline: %s (%s → %s)", cam["id"], legacy, target)
    if n:
        logger.info("migration stream_pipeline terminée : %d caméra(s)", n)
    return n
