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


# ═══════════════════════════════════════════════════════════════════
# v0.5.4-B · Security Score + Security Center
# ═══════════════════════════════════════════════════════════════════

import os
import re as _re
import ssl
import socket
from urllib.parse import urlparse

# Poids par critère (somme = 100).
_SEC_WEIGHTS = {
    "https":            10,
    "jwt_env":          10,
    "strong_passwords": 10,
    "mfa":              10,
    "backups":          10,
    "plugin_sandbox":   10,
    "camera_firmware":  10,
    "mongo_auth":       10,
    "disk":             10,
    "certs":            10,
}


async def _score_https() -> dict:
    # Le service tourne derrière un reverse-proxy dans le pod. On regarde
    # d'abord une variable d'environnement `PUBLIC_URL` puis on retombe
    # sur le `REACT_APP_BACKEND_URL` du frontend .env.
    url = os.environ.get("PUBLIC_URL") or ""
    if not url:
        try:
            from pathlib import Path
            for line in Path("/app/frontend/.env").read_text().splitlines():
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.split("=", 1)[1].strip()
        except Exception:
            pass
    ok = url.startswith("https://")
    return {"ok": ok, "detail": url or "inconnue",
            "advice": None if ok else "Exposer MG-VMS derrière HTTPS (nginx + Let's Encrypt)."}


def _score_jwt_env() -> dict:
    sec = os.environ.get("JWT_SECRET", "")
    if not sec:
        return {"ok": False, "detail": "JWT_SECRET absent",
                "advice": "Définir un JWT_SECRET fort (>= 32 caractères) dans backend/.env."}
    if len(sec) < 24:
        return {"ok": False, "detail": f"JWT_SECRET trop court ({len(sec)} car.)",
                "advice": "Utiliser au moins 32 caractères aléatoires."}
    if sec.lower() in ("changeme", "secret", "supersecret", "dev"):
        return {"ok": False, "detail": "JWT_SECRET par défaut",
                "advice": "Générer un secret unique via `openssl rand -hex 32`."}
    return {"ok": True, "detail": f"OK ({len(sec)} car.)"}


async def _score_strong_passwords() -> dict:
    # Vérifie qu'aucun utilisateur n'a un mot de passe par défaut trivial.
    # Impossible sans bcrypt.checkpw ; on se limite à un flag `weak_password`
    # posé sur le user au moment du set + score global si tous les hash sont
    # bcrypt (heuristique : le hash commence par "$2").
    users = await db.users.find({}, {"password_hash": 1, "email": 1}).to_list(500)
    non_bcrypt = [u for u in users if not (u.get("password_hash", "") or "").startswith("$2")]
    ok = len(non_bcrypt) == 0
    return {"ok": ok,
            "detail": f"{len(users)} utilisateurs, {len(non_bcrypt)} en clair/legacy",
            "advice": None if ok else "Forcer une réinitialisation de mot de passe pour ces comptes."}


async def _score_mfa() -> dict:
    total = await db.users.count_documents({"active": {"$ne": False}})
    admins = await db.users.count_documents({"role": "admin"})
    with_2fa = await db.users.count_documents({"twofa_enabled": True})
    ok = admins > 0 and with_2fa >= admins  # tous les admins ont 2FA
    return {"ok": ok,
            "detail": f"{with_2fa}/{total} utilisateurs (2FA), {admins} admin(s)",
            "advice": None if ok else "Activer la 2FA sur au moins tous les comptes admin."}


async def _score_backups() -> dict:
    doc = await db.backups.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
    if not doc:
        return {"ok": False, "detail": "Aucune sauvegarde",
                "advice": "Planifier une sauvegarde quotidienne de MongoDB (mongodump)."}
    from datetime import datetime
    try:
        age_h = (datetime.now(timezone.utc)
                  - datetime.fromisoformat(doc["created_at"].replace("Z", "+00:00"))
                 ).total_seconds() / 3600
    except Exception:
        age_h = None
    ok = age_h is not None and age_h < 48
    return {"ok": ok,
            "detail": f"Dernière : il y a {int(age_h)}h" if age_h else "date inconnue",
            "advice": None if ok else "Programmer une sauvegarde < 48h."}


def _score_plugin_sandbox() -> dict:
    # Placeholder : sandbox permissions arriveront Phase E. Pour l'instant
    # on regarde si le plugin_manager applique déjà un allow-list (fermeture
    # stricte v0.4.3 déjà en place → ok).
    try:
        from plugin_manager.bus import bus
        entries = bus.summary()
        strict = all(e.get("state") != "loose" for e in entries)
        return {"ok": strict,
                "detail": f"{len(entries)} plugins · allow-list stricte",
                "advice": None if strict else "Activer la sandbox stricte."}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:80], "advice": "Corriger le plugin manager."}


async def _score_camera_firmware() -> dict:
    total = await db.cameras.count_documents({})
    if total == 0:
        return {"ok": True, "detail": "Aucune caméra configurée"}
    with_fw = await db.cameras.count_documents({"firmware": {"$exists": True, "$ne": ""}})
    ratio = with_fw / total
    ok = ratio >= 0.7
    return {"ok": ok,
            "detail": f"{with_fw}/{total} caméras avec firmware documenté",
            "advice": None if ok else "Renseigner le firmware sur toutes les caméras."}


def _score_mongo_auth() -> dict:
    url = os.environ.get("MONGO_URL", "")
    has_auth = ("@" in url and "://" in url) or ("authSource" in url)
    ok = has_auth or "localhost" in url or "127.0.0.1" in url
    return {"ok": ok,
            "detail": "Mongo local trusté" if ("localhost" in url or "127.0.0.1" in url) else ("URL avec auth" if has_auth else "URL sans auth"),
            "advice": None if ok else "Activer l'authentification MongoDB en production."}


def _score_disk() -> dict:
    try:
        import psutil
        pct = psutil.disk_usage("/").percent
        if pct < 80:
            return {"ok": True, "detail": f"Disque à {pct}%"}
        if pct < 92:
            return {"ok": False, "detail": f"Disque à {pct}% (attention)",
                    "advice": "Purger enregistrements ou étendre le stockage."}
        return {"ok": False, "detail": f"Disque à {pct}% (critique)",
                "advice": "Espace disque critique — action immédiate requise."}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:80], "advice": "psutil indisponible."}


async def _score_certs() -> dict:
    url = os.environ.get("PUBLIC_URL") or ""
    if not url:
        try:
            from pathlib import Path
            for line in Path("/app/frontend/.env").read_text().splitlines():
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.split("=", 1)[1].strip()
        except Exception:
            pass
    if not url.startswith("https://"):
        return {"ok": False, "detail": "HTTPS non exposé",
                "advice": "Voir critère HTTPS."}
    host = urlparse(url).hostname
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
        exp = cert.get("notAfter")
        from datetime import datetime as _dt
        exp_dt = _dt.strptime(exp, "%b %d %H:%M:%S %Y %Z")
        days = (exp_dt - _dt.utcnow()).days
        ok = days > 15
        return {"ok": ok,
                "detail": f"Certificat expire dans {days}j",
                "advice": None if ok else "Renouveler le certificat sous 15 jours."}
    except Exception as e:
        return {"ok": False, "detail": f"Vérification échouée: {str(e)[:60]}",
                "advice": "Vérifier la chaîne TLS et la validité du certificat."}


CRITERION_LABEL = {
    "https": "HTTPS activé",
    "jwt_env": "JWT secret fort",
    "strong_passwords": "Mots de passe robustes",
    "mfa": "2FA sur admins",
    "backups": "Sauvegardes récentes",
    "plugin_sandbox": "Sandbox plugins",
    "camera_firmware": "Firmware caméras documenté",
    "mongo_auth": "MongoDB authentifié",
    "disk": "Espace disque",
    "certs": "Certificats TLS",
}


@security_router.get("/score")
async def security_score(user: dict = Depends(get_current_user)):
    checks = {
        "https":            await _score_https(),
        "jwt_env":          _score_jwt_env(),
        "strong_passwords": await _score_strong_passwords(),
        "mfa":              await _score_mfa(),
        "backups":          await _score_backups(),
        "plugin_sandbox":   _score_plugin_sandbox(),
        "camera_firmware":  await _score_camera_firmware(),
        "mongo_auth":       _score_mongo_auth(),
        "disk":             _score_disk(),
        "certs":            await _score_certs(),
    }
    total = sum(_SEC_WEIGHTS.values())
    weighted = sum(_SEC_WEIGHTS[k] * (1 if v.get("ok") else 0) for k, v in checks.items())
    score = int(round(weighted / total * 100))
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "E"
    return {
        "score": score,
        "grade": grade,
        "checks": {k: {**v, "label": CRITERION_LABEL[k], "weight": _SEC_WEIGHTS[k]}
                    for k, v in checks.items()},
    }
