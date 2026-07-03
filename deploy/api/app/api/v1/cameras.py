"""Caméras : CRUD, découverte ONVIF (déléguée au service ffmpeg), PTZ."""
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import audit, get_current_user, require_permission, require_tech
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Camera, User, UserSite
from app.schemas import CameraIn, CameraOut, CameraUpdate

router = APIRouter(prefix="/cameras", tags=["cameras"])


async def _accessible(db: AsyncSession, user: User, camera: Camera) -> bool:
    if user.role.level == 1:
        return True
    return bool(await db.scalar(
        select(UserSite).where(UserSite.user_id == user.id, UserSite.site_id == camera.site_id)
    ))


@router.get("", response_model=list[CameraOut])
async def list_cameras(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = select(Camera).order_by(Camera.name)
    if user.role.level > 1:
        query = query.join(UserSite, UserSite.site_id == Camera.site_id).where(UserSite.user_id == user.id)
    return (await db.scalars(query)).all()


@router.post("", response_model=CameraOut, status_code=201)
async def create_camera(body: CameraIn, user: User = Depends(require_tech), db: AsyncSession = Depends(get_db)):
    camera = Camera(**body.model_dump())
    db.add(camera)
    await db.commit()
    await db.refresh(camera)
    await audit(db, user, "camera.create", target=str(camera.id), details=camera.name)
    return camera


@router.get("/{camera_id}", response_model=CameraOut)
async def get_camera(camera_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    camera = await db.get(Camera, camera_id)
    if not camera or not await _accessible(db, user, camera):
        raise HTTPException(404, "Caméra introuvable")
    return camera


@router.patch("/{camera_id}", response_model=CameraOut)
async def update_camera(camera_id: UUID, body: CameraUpdate, user: User = Depends(require_tech),
                        db: AsyncSession = Depends(get_db)):
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(404, "Caméra introuvable")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(camera, key, value)
    await db.commit()
    await db.refresh(camera)
    return camera


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(camera_id: UUID, user: User = Depends(require_tech), db: AsyncSession = Depends(get_db)):
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(404, "Caméra introuvable")
    await db.delete(camera)
    await db.commit()
    await audit(db, user, "camera.delete", target=str(camera_id))


@router.post("/discover")
async def discover_onvif(user: User = Depends(require_tech)):
    """Lance une découverte ONVIF WS-Discovery via le service ffmpeg."""
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{s.STREAM_GATEWAY_URL}/api/onvif/discover")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError:
        raise HTTPException(502, "Service de découverte ONVIF indisponible")


@router.post("/{camera_id}/ptz")
async def ptz_command(camera_id: UUID, command: dict,
                      user: User = Depends(require_permission("ptz_control")),
                      db: AsyncSession = Depends(get_db)):
    """Relaye une commande PTZ (pan/tilt/zoom/preset) au service ffmpeg/ONVIF."""
    camera = await db.get(Camera, camera_id)
    if not camera or not await _accessible(db, user, camera):
        raise HTTPException(404, "Caméra introuvable")
    if not camera.ptz_enabled:
        raise HTTPException(400, "PTZ non supporté par cette caméra")
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{s.STREAM_GATEWAY_URL}/api/ptz/{camera_id}", json=command)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError:
        raise HTTPException(502, "Service PTZ indisponible")
