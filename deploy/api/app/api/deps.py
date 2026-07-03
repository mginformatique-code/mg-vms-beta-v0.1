"""Dépendances FastAPI : utilisateur courant, rôles, permissions granulaires, audit."""
import jwt as pyjwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models import AuditLog, User

ROLE_ADMIN = 1
ROLE_TECH = 2
ROLE_OPERATOR = 3


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(401, "Non authentifié")
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(401, "Type de jeton invalide")
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, "Jeton expiré")
    except pyjwt.InvalidTokenError:
        raise HTTPException(401, "Jeton invalide")
    user = await db.scalar(select(User).where(User.id == payload["sub"]))
    if not user or not user.active:
        raise HTTPException(401, "Utilisateur introuvable ou désactivé")
    return user


def require_role(max_level: int):
    async def dep(user: User = Depends(get_current_user)) -> User:
        if user.role.level > max_level:
            raise HTTPException(403, "Droits insuffisants")
        return user
    return dep


require_admin = require_role(1)
require_tech = require_role(2)


def require_permission(permission: str):
    async def dep(user: User = Depends(get_current_user)) -> User:
        if user.role.level == 1:  # admin : toutes permissions
            return user
        if not (user.permissions or {}).get(permission, False):
            raise HTTPException(403, f"Permission requise : {permission}")
        return user
    return dep


async def audit(db: AsyncSession, user: User | None, action: str, target: str | None = None,
                details: str | None = None, ip: str | None = None) -> None:
    db.add(AuditLog(
        user_id=user.id if user else None,
        user_email=user.email if user else None,
        action=action, target=target, details=details, ip=ip,
    ))
    await db.commit()
