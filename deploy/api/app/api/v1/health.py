"""Health check : liveness + readiness (DB + Redis)."""
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/")
async def liveness():
    return {"service": "mg-vms-api", "status": "ok"}


@router.get("/health")
async def readiness(db: AsyncSession = Depends(get_db)):
    checks = {"database": "ok", "redis": "ok"}
    status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        checks["database"] = "error"
        status = "degraded"
    try:
        r = aioredis.from_url(get_settings().REDIS_URL)
        await r.ping()
        await r.aclose()
    except Exception:
        checks["redis"] = "error"
        status = "degraded"
    return {"status": status, "checks": checks}
