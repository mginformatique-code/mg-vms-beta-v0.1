"""Tâches Celery : rétention, usage stockage, exports, notifications."""
import json
import logging
from datetime import datetime, timedelta, timezone

import redis
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Recording, StorageVolume
from app.tasks.celery_app import celery_app

logger = logging.getLogger("tasks")
_s = get_settings()

# Les workers Celery sont synchrones ; psycopg3 gère sync et async avec le même dialecte.
_sync_engine = create_engine(_s.DATABASE_URL, pool_pre_ping=True)


@celery_app.task
def purge_old_recordings(retention_days: int = 30) -> int:
    """Supprime les enregistrements clos plus anciens que la rétention."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    with Session(_sync_engine) as db:
        result = db.execute(
            delete(Recording).where(Recording.status == "closed", Recording.end_ts < cutoff)
        )
        db.commit()
        logger.info("Purge enregistrements : %s supprimés", result.rowcount)
        return result.rowcount


@celery_app.task
def compute_storage_usage() -> None:
    """Recalcule l'espace utilisé par volume à partir des enregistrements."""
    with Session(_sync_engine) as db:
        volumes = db.scalars(select(StorageVolume)).all()
        for vol in volumes:
            total = db.scalar(
                select(func.coalesce(func.sum(Recording.size_bytes), 0))
                .where(Recording.storage_volume_id == vol.id)
            )
            db.execute(
                update(StorageVolume).where(StorageVolume.id == vol.id)
                .values(used_gb=round(total / 1024**3, 2))
            )
        db.commit()


@celery_app.task
def dispatch_notification(payload: dict) -> None:
    """Pousse une notification vers le service de notifications (file Redis)."""
    r = redis.from_url(_s.REDIS_URL)
    r.rpush("mgvms:notifications", json.dumps(payload, default=str))
