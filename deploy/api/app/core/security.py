"""Hachage bcrypt + JWT (access/refresh) — MG-VMS."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: UUID | str, email: str) -> str:
    s = get_settings()
    payload = {
        "sub": str(user_id),
        "email": email,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, s.JWT_SECRET, algorithm=s.JWT_ALGORITHM)


def create_refresh_token(user_id: UUID | str) -> str:
    s = get_settings()
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=s.REFRESH_TOKEN_DAYS),
    }
    return jwt.encode(payload, s.JWT_SECRET, algorithm=s.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.JWT_SECRET, algorithms=[s.JWT_ALGORITHM])
