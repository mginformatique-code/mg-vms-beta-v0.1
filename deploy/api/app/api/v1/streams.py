"""Flux vidéo : profils main/sub, URLs de lecture WebRTC/HLS (go2rtc)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_permission, require_tech
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Stream, User
from app.schemas import StreamIn, StreamOut

router = APIRouter(prefix="/streams", tags=["streams"])


@router.get("", response_model=list[StreamOut])
async def list_streams(camera_id: UUID | None = None, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    query = select(Stream)
    if camera_id:
        query = query.where(Stream.camera_id == camera_id)
    return (await db.scalars(query)).all()


@router.post("", response_model=StreamOut, status_code=201)
async def create_stream(body: StreamIn, user: User = Depends(require_tech), db: AsyncSession = Depends(get_db)):
    stream = Stream(**body.model_dump())
    db.add(stream)
    await db.commit()
    await db.refresh(stream)
    return stream


@router.delete("/{stream_id}", status_code=204)
async def delete_stream(stream_id: UUID, user: User = Depends(require_tech), db: AsyncSession = Depends(get_db)):
    stream = await db.get(Stream, stream_id)
    if not stream:
        raise HTTPException(404, "Flux introuvable")
    await db.delete(stream)
    await db.commit()


@router.get("/{stream_id}/play")
async def play_urls(stream_id: UUID, user: User = Depends(require_permission("view_live")),
                    db: AsyncSession = Depends(get_db)):
    """URLs de lecture temps réel. Les utilisateurs sans `stream_hd` reçoivent le profil sub (SD)."""
    stream = await db.get(Stream, stream_id)
    if not stream:
        raise HTTPException(404, "Flux introuvable")
    if stream.profile == "main" and user.role.level > 1 and not (user.permissions or {}).get("stream_hd", False):
        sub = await db.scalar(select(Stream).where(Stream.camera_id == stream.camera_id, Stream.profile == "sub"))
        if sub:
            stream = sub
    gw = get_settings().STREAM_GATEWAY_URL
    name = f"cam_{stream.camera_id}_{stream.profile}"
    return {
        "stream_id": str(stream.id),
        "profile": stream.profile,
        "webrtc": f"{gw}/api/webrtc?src={name}",
        "hls": f"{gw}/api/stream.m3u8?src={name}",
        "mse": f"{gw}/api/ws?src={name}",
    }
