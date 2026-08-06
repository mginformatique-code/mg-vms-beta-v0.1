"""Route module — Security Center (v0.5.4 · Phase A).

Gestion des sessions utilisateur et du timeout configurable.

Endpoints (prefix `/api/security/`) :
  - `GET /sessions`               — liste les sessions actives de l'utilisateur
  - `DELETE /sessions/{jti}`      — révoque une session (déconnexion à distance)
  - `POST /sessions/revoke-others` — révoque toutes les autres sessions
  - `GET /timeout`                — configuration timeout actuelle
  - `PUT /timeout`                — met à jour le timeout (admin)

Une session révoquée reste 30 jours dans Mongo pour l'affichage puis expire
naturellement (TTL possible en v2). Le check `revoked=True` est fait dans
`auth.get_current_user` sur chaque requête (coût : 1 lookup indexé).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import get_current_user, get_jwt_secret, JWT_ALGORITHM, require_role, log_audit
from database import db

security_router = APIRouter(prefix="/api/security", tags=["security"])

# Valeurs supportées côté UI (heures). L'utilisateur peut aussi entrer une
# valeur custom, bornée [0.25, 24].
SESSION_HOURS_OPTIONS = [0.25, 0.5, 1, 4, 8, 12, 24]


class TimeoutInput(BaseModel):
    session_hours: float = Field(..., ge=0.25, le=24.0)


def _current_jti(request: Request) -> Optional[str]:
    """Extrait le `jti` du token de la requête courante (sans re-vérifier
    la signature — get_current_user l'a déjà fait)."""
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM],
                              options={"verify_exp": False})
        return payload.get("jti")
    except Exception:
        return None


def _client_ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() \
        or (request.client.host if request.client else "?")


@security_router.get("/sessions")
async def list_sessions(request: Request, user: dict = Depends(get_current_user)):
    cur_jti = _current_jti(request)
    docs = await db.sessions.find(
        {"user_id": user["id"], "revoked": {"$ne": True}}, {"_id": 0}
    ).sort("last_seen_at", -1).to_list(50)
    for d in docs:
        d["current"] = (d.get("jti") == cur_jti)
    return {"items": docs, "current_jti": cur_jti}


@security_router.delete("/sessions/{jti}")
async def revoke_session(jti: str, request: Request, user: dict = Depends(get_current_user)):
    sess = await db.sessions.find_one({"jti": jti}, {"_id": 0})
    if not sess:
        raise HTTPException(status_code=404, detail="Session introuvable")
    # Un utilisateur ne peut révoquer que ses propres sessions (sauf admin)
    if sess["user_id"] != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Interdit")
    await db.sessions.update_one({"jti": jti}, {"$set": {"revoked": True,
        "revoked_at": datetime.now(timezone.utc).isoformat()}})
    await log_audit(user, "session_revoked", sess.get("email", ""),
                     f"jti={jti[:8]}", _client_ip(request))
    return {"ok": True, "revoked": jti}


@security_router.post("/sessions/revoke-others")
async def revoke_other_sessions(request: Request, user: dict = Depends(get_current_user)):
    cur_jti = _current_jti(request)
    r = await db.sessions.update_many(
        {"user_id": user["id"], "revoked": {"$ne": True}, "jti": {"$ne": cur_jti}},
        {"$set": {"revoked": True,
                    "revoked_at": datetime.now(timezone.utc).isoformat()}},
    )
    await log_audit(user, "sessions_revoked_others", user.get("email", ""),
                     f"count={r.modified_count}", _client_ip(request))
    return {"ok": True, "revoked_count": r.modified_count}


@security_router.get("/timeout")
async def get_timeout(user: dict = Depends(get_current_user)):
    doc = await db.settings.find_one({"id": "security"}, {"_id": 0}) or {}
    return {
        "session_hours": float(doc.get("session_hours", 8)),
        "options": SESSION_HOURS_OPTIONS,
    }


@security_router.put("/timeout")
async def set_timeout(
    payload: TimeoutInput,
    request: Request,
    user: dict = Depends(require_role("admin")),
):
    await db.settings.update_one(
        {"id": "security"},
        {"$set": {"session_hours": payload.session_hours,
                    "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    await log_audit(user, "session_timeout_changed", user.get("email", ""),
                     f"hours={payload.session_hours}", _client_ip(request))
    return {"ok": True, "session_hours": payload.session_hours}
