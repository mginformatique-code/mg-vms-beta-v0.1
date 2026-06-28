import os
import jwt
import bcrypt
import pyotp
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
import uuid

from database import db

JWT_ALGORITHM = "HS256"
ROLES = ["admin", "technician", "client", "readonly", "guest"]

# Role hierarchy: higher = more privileges
ROLE_LEVEL = {"guest": 0, "readonly": 1, "client": 2, "technician": 3, "admin": 4}

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=8),
        "type": "access",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "role": user.get("role", "guest"),
        "twofa_enabled": user.get("twofa_enabled", False),
        "active": user.get("active", True),
        "created_at": user.get("created_at"),
        "site_ids": user.get("site_ids", []),
    }


async def get_current_user(request: Request) -> dict:
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_role(min_role: str):
    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if ROLE_LEVEL.get(user.get("role", "guest"), 0) < ROLE_LEVEL[min_role]:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker


# ---------- Schemas ----------
class LoginInput(BaseModel):
    email: EmailStr
    password: str
    totp_code: Optional[str] = None


class RegisterInput(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "client"


class TwoFAVerify(BaseModel):
    code: str


# ---------- Audit helper ----------
async def log_audit(user: Optional[dict], action: str, target: str = "", details: str = "", ip: str = ""):
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user["id"] if user else None,
        "user_email": user["email"] if user else "system",
        "action": action,
        "target": target,
        "details": details,
        "ip": ip,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ---------- Endpoints ----------
@auth_router.post("/login")
async def login(data: LoginInput, request: Request, response: Response):
    email = data.email.lower()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    ip = request.client.host if request.client else ""
    if not user or not verify_password(data.password, user["password_hash"]):
        await log_audit(None, "login_failed", email, "Invalid credentials", ip)
        raise HTTPException(status_code=401, detail="Email ou mot de passe invalide")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Compte désactivé")

    if user.get("twofa_enabled"):
        if not data.totp_code:
            return {"requires_2fa": True}
        totp = pyotp.TOTP(user["twofa_secret"])
        if not totp.verify(data.totp_code, valid_window=1):
            raise HTTPException(status_code=401, detail="Code 2FA invalide")

    access = create_access_token(user["id"], user["email"], user["role"])
    refresh = create_refresh_token(user["id"])
    response.set_cookie("access_token", access, httponly=True, secure=False, samesite="lax", max_age=28800, path="/")
    await log_audit(user, "login", email, "Connexion réussie", ip)
    return {"access_token": access, "refresh_token": refresh, "user": public_user(user)}


@auth_router.post("/register")
async def register(data: RegisterInput, current: dict = Depends(require_role("admin"))):
    email = data.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email déjà utilisé")
    role = data.role if data.role in ROLES else "client"
    user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "password_hash": hash_password(data.password),
        "name": data.name,
        "role": role,
        "twofa_enabled": False,
        "twofa_secret": None,
        "active": True,
        "site_ids": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user)
    await log_audit(current, "user_created", email, f"Rôle: {role}")
    return public_user(user)


@auth_router.post("/refresh")
async def refresh_token(request: Request):
    token = request.cookies.get("refresh_token")
    body_token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        body_token = auth_header[7:]
    token = token or body_token
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        access = create_access_token(user["id"], user["email"], user["role"])
        return {"access_token": access}
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@auth_router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return public_user(user)


@auth_router.post("/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    await log_audit(user, "logout", user["email"])
    return {"ok": True}


@auth_router.post("/2fa/setup")
async def setup_2fa(user: dict = Depends(get_current_user)):
    secret = pyotp.random_base32()
    await db.users.update_one({"id": user["id"]}, {"$set": {"twofa_secret": secret, "twofa_enabled": False}})
    uri = pyotp.TOTP(secret).provisioning_uri(name=user["email"], issuer_name="MG-VMS")
    return {"secret": secret, "otpauth_uri": uri}


@auth_router.post("/2fa/verify")
async def verify_2fa(data: TwoFAVerify, user: dict = Depends(get_current_user)):
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    secret = fresh.get("twofa_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="2FA non initialisé")
    if not pyotp.TOTP(secret).verify(data.code, valid_window=1):
        raise HTTPException(status_code=401, detail="Code invalide")
    await db.users.update_one({"id": user["id"]}, {"$set": {"twofa_enabled": True}})
    await log_audit(user, "2fa_enabled", user["email"])
    return {"ok": True}


@auth_router.post("/2fa/disable")
async def disable_2fa(user: dict = Depends(get_current_user)):
    await db.users.update_one({"id": user["id"]}, {"$set": {"twofa_enabled": False, "twofa_secret": None}})
    await log_audit(user, "2fa_disabled", user["email"])
    return {"ok": True}
