"""Application Celery — tâches asynchrones MG-VMS."""
from celery import Celery

from app.core.config import get_settings

_s = get_settings()

celery_app = Celery(
    "mgvms",
    broker=_s.CELERY_BROKER_URL,
    backend=_s.CELERY_RESULT_BACKEND,
    include=["app.tasks.jobs"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "purge-old-recordings": {"task": "app.tasks.jobs.purge_old_recordings", "schedule": 3600.0},
        "compute-storage-usage": {"task": "app.tasks.jobs.compute_storage_usage", "schedule": 600.0},
    },
)
