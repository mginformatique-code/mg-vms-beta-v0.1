"""Gestion des utilisateurs (réservée à l'administrateur) + permissions granulaires."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import audit, require_admin
from app.core.security import hash_password
from app.db.session import get_db
from app.models import User, UserSite
from app.schemas import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(User).order_by(User.created_at))).all()


@router.post("", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if await db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "Email déjà utilisé")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password),
                name=body.name, role_id=body.role_id, permissions=body.permissions)
    db.add(user)
    await db.flush()
    for site_id in body.site_ids:
        db.add(UserSite(user_id=user.id, site_id=site_id))
    await db.commit()
    await db.refresh(user)
    await audit(db, admin, "user.create", target=str(user.id), details=user.email)
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: UUID, body: UserUpdate, admin: User = Depends(require_admin),
                      db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    data = body.model_dump(exclude_unset=True)
    if "password" in data:
        user.password_hash = hash_password(data.pop("password"))
    site_ids = data.pop("site_ids", None)
    for key, value in data.items():
        setattr(user, key, value)
    if site_ids is not None:
        await db.execute(delete(UserSite).where(UserSite.user_id == user.id))
        for site_id in site_ids:
            db.add(UserSite(user_id=user.id, site_id=site_id))
    await db.commit()
    await db.refresh(user)
    await audit(db, admin, "user.update", target=str(user.id))
    return user


@router.patch("/{user_id}/permissions", response_model=UserOut)
async def update_permissions(user_id: UUID, permissions: dict, admin: User = Depends(require_admin),
                             db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    user.permissions = {**(user.permissions or {}), **permissions}
    await db.commit()
    await db.refresh(user)
    await audit(db, admin, "user.permissions", target=str(user.id), details=str(permissions))
    return user


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    if user.id == admin.id:
        raise HTTPException(400, "Impossible de supprimer son propre compte")
    await db.delete(user)
    await db.commit()
    await audit(db, admin, "user.delete", target=str(user_id))
