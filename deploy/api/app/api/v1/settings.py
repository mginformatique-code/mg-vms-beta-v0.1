"""Paramètres système (clé/valeur JSONB, admin)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import Setting
from app.schemas import SettingIn, SettingOut

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[SettingOut])
async def list_settings(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Setting))).all()


@router.get("/{key}", response_model=SettingOut)
async def get_setting(key: str, db: AsyncSession = Depends(get_db)):
    setting = await db.get(Setting, key)
    if not setting:
        raise HTTPException(404, "Paramètre introuvable")
    return setting


@router.put("/{key}", response_model=SettingOut)
async def upsert_setting(key: str, body: SettingIn, db: AsyncSession = Depends(get_db)):
    setting = await db.get(Setting, key)
    if setting:
        setting.value = body.value
    else:
        setting = Setting(key=key, value=body.value)
        db.add(setting)
    await db.commit()
    await db.refresh(setting)
    return setting


@router.delete("/{key}", status_code=204)
async def delete_setting(key: str, db: AsyncSession = Depends(get_db)):
    setting = await db.get(Setting, key)
    if not setting:
        raise HTTPException(404, "Paramètre introuvable")
    await db.delete(setting)
    await db.commit()
