"""Canaux de notification (email/discord/telegram/webhook) + test d'envoi."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import NotificationChannel
from app.schemas import ChannelIn, ChannelOut
from app.tasks.jobs import dispatch_notification

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_admin)])


@router.get("/channels", response_model=list[ChannelOut])
async def list_channels(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(NotificationChannel))).all()


@router.post("/channels", response_model=ChannelOut, status_code=201)
async def create_channel(body: ChannelIn, db: AsyncSession = Depends(get_db)):
    channel = NotificationChannel(**body.model_dump())
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.patch("/channels/{channel_id}", response_model=ChannelOut)
async def update_channel(channel_id: UUID, body: ChannelIn, db: AsyncSession = Depends(get_db)):
    channel = await db.get(NotificationChannel, channel_id)
    if not channel:
        raise HTTPException(404, "Canal introuvable")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(channel, key, value)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel(channel_id: UUID, db: AsyncSession = Depends(get_db)):
    channel = await db.get(NotificationChannel, channel_id)
    if not channel:
        raise HTTPException(404, "Canal introuvable")
    await db.delete(channel)
    await db.commit()


@router.post("/channels/{channel_id}/test")
async def test_channel(channel_id: UUID, db: AsyncSession = Depends(get_db)):
    channel = await db.get(NotificationChannel, channel_id)
    if not channel:
        raise HTTPException(404, "Canal introuvable")
    dispatch_notification.delay({
        "type": "test", "channel_type": channel.type, "channel_config": channel.config,
        "title": "MG-VMS — Test", "message": "Notification de test envoyée avec succès.",
    })
    return {"detail": "Notification de test envoyée (file d'attente)"}
