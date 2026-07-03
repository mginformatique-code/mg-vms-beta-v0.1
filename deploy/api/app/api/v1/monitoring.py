"""Monitoring : statistiques globales + métriques Prometheus."""
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Camera, Event, Recording, Site, User

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/stats")
async def stats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cameras_total = await db.scalar(select(func.count(Camera.id)))
    cameras_online = await db.scalar(select(func.count(Camera.id)).where(Camera.status == "online"))
    sites = await db.scalar(select(func.count(Site.id)))
    events_24h = await db.scalar(
        select(func.count(Event.id)).where(Event.ts >= func.now() - func.make_interval(0, 0, 0, 1))
    )
    recording_active = await db.scalar(
        select(func.count(Recording.id)).where(Recording.status == "recording")
    )
    return {
        "cameras": {"total": cameras_total, "online": cameras_online,
                    "offline": cameras_total - cameras_online},
        "sites": sites,
        "events_24h": events_24h,
        "recordings_active": recording_active,
    }


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def metrics(db: AsyncSession = Depends(get_db)):
    """Exposition Prometheus (scrapé par le service prometheus du compose)."""
    cameras_online = await db.scalar(select(func.count(Camera.id)).where(Camera.status == "online"))
    cameras_total = await db.scalar(select(func.count(Camera.id)))
    lines = [
        "# HELP mgvms_cameras_online Caméras en ligne",
        "# TYPE mgvms_cameras_online gauge",
        f"mgvms_cameras_online {cameras_online}",
        "# HELP mgvms_cameras_total Caméras totales",
        "# TYPE mgvms_cameras_total gauge",
        f"mgvms_cameras_total {cameras_total}",
    ]
    return "\n".join(lines) + "\n"
