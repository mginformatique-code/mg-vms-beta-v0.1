"""Événements (mouvement, intrusion, franchissement de ligne, ANPR...) + diffusion WebSocket."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_tech
from app.db.session import get_db
from app.models import Event, User
from app.schemas import EventIn, EventOut
from app.ws import manager

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventOut])
async def list_events(
    type: str | None = None,
    camera_id: UUID | None = None,
    site_id: UUID | None = None,
    severity: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(100, le=1000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Event).order_by(Event.ts.desc()).limit(limit)
    if type:
        query = query.where(Event.type == type)
    if camera_id:
        query = query.where(Event.camera_id == camera_id)
    if site_id:
        query = query.where(Event.site_id == site_id)
    if severity:
        query = query.where(Event.severity == severity)
    if start:
        query = query.where(Event.ts >= start)
    if end:
        query = query.where(Event.ts <= end)
    return (await db.scalars(query)).all()


@router.post("", response_model=EventOut, status_code=201)
async def create_event(body: EventIn, user: User = Depends(require_tech), db: AsyncSession = Depends(get_db)):
    """Ingestion d'événements (utilisé aussi par ai-engine / network-monitor via compte service)."""
    event = Event(**body.model_dump())
    db.add(event)
    await db.commit()
    await db.refresh(event)
    await manager.broadcast({"kind": "event", "payload": {
        "id": str(event.id), "type": event.type, "severity": event.severity,
        "camera_id": str(event.camera_id) if event.camera_id else None,
        "ts": event.ts.isoformat(),
    }})
    return event


@router.post("/{event_id}/ack", response_model=EventOut)
async def acknowledge(event_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Événement introuvable")
    event.acknowledged = True
    await db.commit()
    await db.refresh(event)
    return event
