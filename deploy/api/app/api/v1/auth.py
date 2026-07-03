"""Authentification : login, refresh, logout, me, reset mot de passe, anti brute-force."""
import secrets
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import audit, get_current_user
from app.core.config import get_settings
from app.core.security import (
    create_access_token, create_refresh_token, decode_token,
    hash_password, verify_password,
)
from app.db.session import get_db
from app.models import LoginAttempt, PasswordResetToken, User
from app.schemas import LoginIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookies(response: Response, access: str, refresh: str) -> None:
    s = get_settings()
    response.set_cookie("access_token", access, httponly=True, secure=True, samesite="lax",
                        max_age=s.ACCESS_TOKEN_MINUTES * 60, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True, samesite="lax",
                        max_age=s.REFRESH_TOKEN_DAYS * 86400, path="/")


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    s = get_settings()
    email = body.email.lower()
    identifier = f"{request.client.host if request.client else 'unknown'}:{email}"
    now = datetime.now(timezone.utc)

    attempt = await db.scalar(select(LoginAttempt).where(LoginAttempt.identifier == identifier))
    if attempt and attempt.locked_until and attempt.locked_until > now:
        raise HTTPException(429, "Compte temporairement verrouillé. Réessayez plus tard.")

    user = await db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(body.password, user.password_hash):
        if attempt is None:
            attempt = LoginAttempt(identifier=identifier, attempts=0)
            db.add(attempt)
        attempt.attempts += 1
        if attempt.attempts >= s.LOGIN_MAX_ATTEMPTS:
            attempt.locked_until = now + timedelta(minutes=s.LOGIN_LOCKOUT_MINUTES)
            attempt.attempts = 0
        await db.commit()
        raise HTTPException(401, "Identifiants invalides")
    if not user.active:
        raise HTTPException(403, "Compte désactivé")

    await db.execute(delete(LoginAttempt).where(LoginAttempt.identifier == identifier))
    await audit(db, user, "login", ip=request.client.host if request.client else None)

    access, refresh = create_access_token(user.id, user.email), create_refresh_token(user.id)
    _set_cookies(response, access, refresh)
    return TokenOut(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenOut)
async def refresh_token(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("refresh_token")
    if not token:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        token = body.get("refresh_token")
    if not token:
        raise HTTPException(401, "Jeton de rafraîchissement manquant")
    try:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise HTTPException(401, "Type de jeton invalide")
    except pyjwt.PyJWTError:
        raise HTTPException(401, "Jeton invalide ou expiré")
    user = await db.scalar(select(User).where(User.id == payload["sub"]))
    if not user or not user.active:
        raise HTTPException(401, "Utilisateur introuvable")
    access, refresh = create_access_token(user.id, user.email), create_refresh_token(user.id)
    _set_cookies(response, access, refresh)
    return TokenOut(access_token=access, refresh_token=refresh)


@router.post("/logout")
async def logout(response: Response, user: User = Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"detail": "Déconnecté"}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


@router.post("/forgot-password")
async def forgot_password(body: ForgotIn, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    if user:
        token = secrets.token_urlsafe(32)
        db.add(PasswordResetToken(token=token, user_id=user.id,
                                  expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        await db.commit()
        # Le lien est relayé au service de notifications (email) via Celery.
        from app.tasks.jobs import dispatch_notification
        dispatch_notification.delay({"type": "password_reset", "email": user.email, "token": token})
    return {"detail": "Si le compte existe, un email a été envoyé."}


@router.post("/reset-password")
async def reset_password(body: ResetIn, db: AsyncSession = Depends(get_db)):
    prt = await db.scalar(select(PasswordResetToken).where(PasswordResetToken.token == body.token))
    if not prt or prt.used or prt.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Jeton invalide ou expiré")
    user = await db.scalar(select(User).where(User.id == prt.user_id))
    user.password_hash = hash_password(body.new_password)
    prt.used = True
    await db.commit()
    return {"detail": "Mot de passe mis à jour"}
