"""Enregistrements : timeline, liste filtrée par caméra/période."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db
from app.models import Recording, User
from app.schemas import RecordingOut

router = APIRouter(prefix="/recordings", tags=["recordings"])


@router.get("", response_model=list[RecordingOut])
async def list_recordings(
    camera_id: UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(200, le=1000),
    user: User = Depends(require_permission("view_recordings")),
    db: AsyncSession = Depends(get_db),
):
    query = select(Recording).order_by(Recording.start_ts.desc()).limit(limit)
    if camera_id:
        query = query.where(Recording.camera_id == camera_id)
    if start:
        query = query.where(Recording.start_ts >= start)
    if end:
        query = query.where(Recording.start_ts <= end)
    return (await db.scalars(query)).all()


@router.get("/timeline/{camera_id}")
async def timeline(camera_id: UUID, day: datetime,
                   user: User = Depends(require_permission("view_recordings")),
                   db: AsyncSession = Depends(get_db)):
    """Segments d'une journée pour l'affichage timeline (24h)."""
    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start.replace(hour=23, minute=59, second=59)
    rows = (await db.scalars(
        select(Recording)
        .where(Recording.camera_id == camera_id,
               Recording.start_ts <= day_end,
               (Recording.end_ts.is_(None)) | (Recording.end_ts >= day_start))
        .order_by(Recording.start_ts)
    )).all()
    return {
        "camera_id": str(camera_id),
        "day": day_start.date().isoformat(),
        "segments": [
            {"id": str(r.id), "start": r.start_ts.isoformat(),
             "end": r.end_ts.isoformat() if r.end_ts else None, "status": r.status}
            for r in rows
        ],
    }


@router.delete("/{recording_id}", status_code=204)
async def delete_recording(recording_id: UUID,
                           user: User = Depends(require_permission("export_files")),
                           db: AsyncSession = Depends(get_db)):
    rec = await db.get(Recording, recording_id)
    if not rec:
        raise HTTPException(404, "Enregistrement introuvable")
    await db.delete(rec)
    await db.commit()
