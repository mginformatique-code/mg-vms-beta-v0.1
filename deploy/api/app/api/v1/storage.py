"""Volumes de stockage (local/S3) et occupation."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import StorageVolume
from app.schemas import VolumeIn, VolumeOut

router = APIRouter(prefix="/storage", tags=["storage"], dependencies=[Depends(require_admin)])


@router.get("/volumes", response_model=list[VolumeOut])
async def list_volumes(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(StorageVolume))).all()


@router.post("/volumes", response_model=VolumeOut, status_code=201)
async def create_volume(body: VolumeIn, db: AsyncSession = Depends(get_db)):
    volume = StorageVolume(**body.model_dump())
    db.add(volume)
    await db.commit()
    await db.refresh(volume)
    return volume


@router.patch("/volumes/{volume_id}", response_model=VolumeOut)
async def update_volume(volume_id: UUID, body: VolumeIn, db: AsyncSession = Depends(get_db)):
    volume = await db.get(StorageVolume, volume_id)
    if not volume:
        raise HTTPException(404, "Volume introuvable")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(volume, key, value)
    await db.commit()
    await db.refresh(volume)
    return volume


@router.delete("/volumes/{volume_id}", status_code=204)
async def delete_volume(volume_id: UUID, db: AsyncSession = Depends(get_db)):
    volume = await db.get(StorageVolume, volume_id)
    if not volume:
        raise HTTPException(404, "Volume introuvable")
    await db.delete(volume)
    await db.commit()
