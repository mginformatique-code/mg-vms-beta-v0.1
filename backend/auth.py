import os
import jwt
import bcrypt
import pyotp
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from pymongo import ReturnDocument
from typing import Optional, List
import uuid

from database import db

JWT_ALGORITHM = "HS256"
ROLES = ["admin", "technician", "client", "readonly", "guest"]

# Role hierarchy: higher = more privileges
ROLE_LEVEL = {"guest": 0, "readonly": 1, "client": 2, "technician": 3, "admin": 4}

# Granular per-user permissions (gérées uniquement par l'admin)
# v0.5.5.d · Élargi pour couvrir tous les modules produit (RBAC Phase D).
PERMISSIONS = [
    # Vidéo & lecture
    "view_live", "view_recordings", "read_plates", "stream_hd", "ptz_control",
    "export_files",
    # Gestion (admin / technicien)
    "manage_cameras", "manage_sites", "manage_users", "manage_plugins",
    "manage_workflows", "manage_settings",
    # Audit & sécurité
    "view_audit_log", "access_security_center",
]

# Métadonnées d'affichage pour l'UI RBAC (groupes + labels FR).
PERMISSION_META = {
    "view_live":              {"group": "video",    "label": "Visionnage temps réel"},
    "view_recordings":        {"group": "video",    "label": "Lecture des enregistrements"},
    "read_plates":            {"group": "video",    "label": "Lecture des plaques (ANPR)"},
    "stream_hd":              {"group": "video",    "label": "Affichage HD (sinon SD)"},
    "ptz_control":            {"group": "video",    "label": "Contrôle PTZ"},
    "export_files":           {"group": "video",    "label": "Export de fichiers"},
    "manage_cameras":         {"group": "manage",   "label": "Gérer les caméras"},
    "manage_sites":           {"group": "manage",   "label": "Gérer les sites/bâtiments"},
    "manage_users":           {"group": "manage",   "label": "Gérer les utilisateurs"},
    "manage_plugins":         {"group": "manage",   "label": "Gérer les plugins"},
    "manage_workflows":       {"group": "manage",   "label": "Gérer les workflows"},
    "manage_settings":        {"group": "manage",   "label": "Modifier les paramètres système"},
    "view_audit_log":         {"group": "security", "label": "Consulter le journal d'audit"},
    "access_security_center": {"group": "security", "label": "Accéder au Centre de sécurité"},
}

PERMISSION_GROUPS = [
    ("video",    "Vidéo & lecture"),
    ("manage",   "Gestion"),
    ("security", "Audit & sécurité"),
]

DEFAULT_PERMISSIONS = {
    "admin":      {p: True for p in PERMISSIONS},
    "technician": {p: True for p in PERMISSIONS},
    "client":     {
        "view_live": True, "view_recordings": True, "read_plates": True,
        "stream_hd": True, "ptz_control": True, "export_files": False,
        "manage_cameras": False, "manage_sites": False, "manage_users": False,
        "manage_plugins": False, "manage_workflows": False, "manage_settings": False,
        "view_audit_log": False, "access_security_center": False,
    },
    "readonly":   {
        "view_live": True, "view_recordings": True, "read_plates": False,
        "stream_hd": False, "ptz_control": False, "export_files": False,
        "manage_cameras": False, "manage_sites": False, "manage_users": False,
        "manage_plugins": False, "manage_workflows": False, "manage_settings": False,
        "view_audit_log": False, "access_security_center": False,
    },
    "guest":      {p: False for p in PERMISSIONS},
}


# v0.5.5.d · Cache in-memory des overrides RBAC (collection `role_permissions`).
# Invalidé lors des PUT /api/security/rbac. Lecture lazy à la première requête.
_ROLE_PERM_CACHE: dict = {}
_ROLE_PERM_CACHE_LOADED = False


async def _role_permissions_from_db() -> dict:
    """Retourne les overrides de rôles stockés en DB (peut être vide).

    Format : {role_name: {permission: bool, ...}, ...}
    """
    global _ROLE_PERM_CACHE, _ROLE_PERM_CACHE_LOADED
    if _ROLE_PERM_CACHE_LOADED:
        return _ROLE_PERM_CACHE
    try:
        doc = await db.role_permissions.find_one({"_id": "default"}, {"_id": 0})
    except Exception:
        doc = None
    _ROLE_PERM_CACHE = doc or {}
    _ROLE_PERM_CACHE_LOADED = True
    return _ROLE_PERM_CACHE


def _invalidate_role_perm_cache() -> None:
    """Force le rechargement de `_role_permissions_from_db` au prochain accès."""
    global _ROLE_PERM_CACHE_LOADED
    _ROLE_PERM_CACHE_LOADED = False


def effective_permissions_sync(user: dict, role_overrides: dict | None = None) -> dict:
    """Version synchrone — utilisée par les vues qui ont déjà chargé les overrides.

    Pattern pour éviter le coût d'un await à chaque `get_current_user` :
    - `effective_permissions()` (async) fait le lookup DB si nécessaire.
    - `effective_permissions_sync()` accepte les overrides pré-chargés.
    """
    role = user.get("role", "guest")
    if role == "admin":
        return {p: True for p in PERMISSIONS}
    base = dict(DEFAULT_PERMISSIONS.get(role, DEFAULT_PERMISSIONS["guest"]))
    # Applique les overrides de rôle (DB) par-dessus les valeurs par défaut.
    if role_overrides and role in role_overrides:
        for k, v in role_overrides[role].items():
            if k in PERMISSIONS and isinstance(v, bool):
                base[k] = v
    # Applique les overrides par utilisateur (le plus prioritaire).
    overrides = user.get("permissions") or {}
    for k, v in overrides.items():
        if k in PERMISSIONS and isinstance(v, bool):
            base[k] = v
    return base


async def effective_permissions_async(user: dict) -> dict:
    """Async version — charge les overrides de rôle depuis Mongo."""
    role_overrides = await _role_permissions_from_db()
    return effective_permissions_sync(user, role_overrides)


def effective_permissions(user: dict) -> dict:
    """Rétro-compatible : lookup DB si event-loop, sinon synchrone.

    - Ce chemin est utilisé pour construire ``public_user()`` renvoyé à la
      connexion. On tolère un léger lag après un `PUT /api/security/rbac` :
      la config effective se rafraîchit à la prochaine connexion (cache
      invalidé côté serveur, mais public_user est appelé une seule fois).
    """
    # Lecture non-bloquante depuis le cache. Si pas encore chargé, on
    # renvoie les DEFAULT_PERMISSIONS sans overrides — sera rechargé
    # lors du prochain lookup async naturellement.
    role_overrides = _ROLE_PERM_CACHE if _ROLE_PERM_CACHE_LOADED else None
    return effective_permissions_sync(user, role_overrides)


def has_permission(user: dict, perm: str) -> bool:
    if user.get("role") == "admin":
        return True
    return bool(effective_permissions(user).get(perm, False))

# Brute-force protection
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# v1.0-rc4.6 · Verrouillage PAR COMPTE (persistant, indépendant du lockout
# IP:email ci-dessus qui reste actif comme défense en profondeur).
MAX_ACCOUNT_ATTEMPTS = 5


def _is_main_admin(email: str) -> bool:
    """True si l'email correspond à ADMIN_EMAIL — non-déverrouillable via UI."""
    admin_email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    return bool(admin_email) and email.strip().lower() == admin_email


def _testing_mode() -> bool:
    """Bypass complet du verrou brute-force en mode test (env TESTING=1).

    Nécessaire pour les campagnes pytest parallèles où plusieurs tests tentent
    des connexions valides et invalides en rafale sans coordination.
    """
    return os.environ.get("TESTING", "").lower() in ("1", "true", "yes", "on")

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


def allowed_sites(user: dict):
    """None = accès à tous les sites (admin/technicien). Sinon liste des site_ids autorisés."""
    if user.get("role") in ("admin", "technician"):
        return None
    return user.get("site_ids", []) or []


def site_scope(query: dict, user: dict, field: str = "site_id") -> dict:
    sites = allowed_sites(user)
    if sites is not None:
        query[field] = {"$in": sites}
    return query



def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def create_access_token(user_id: str, email: str, role: str, hours: int = 8, jti: Optional[str] = None) -> str:
    """v0.5.4 · JWT enrichi d'un `jti` unique + durée configurable pour permettre
    la révocation par session (collection `sessions.revoked=True`) et le
    respect du timeout configurable côté Security Center."""
    import uuid as _uuid
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
        "iat": datetime.now(timezone.utc),
        "jti": jti or str(_uuid.uuid4()),
        "type": "access",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    import uuid as _uuid
    payload = {
        "sub": user_id,
        "jti": str(_uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "iat": datetime.now(timezone.utc),
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
        "permissions": effective_permissions(user),
        # v1.0-rc4.6 · État de verrouillage (comptes existants sans ces
        # champs → defaults sûrs, aucune migration nécessaire).
        "locked": bool(user.get("locked", False)),
        "failed_login_count": int(user.get("failed_login_count") or 0),
        "locked_at": user.get("locked_at"),
        "last_failed_login_at": user.get("last_failed_login_at"),
        "last_failed_login_ip": user.get("last_failed_login_ip"),
        "last_login_at": user.get("last_login_at"),
        "last_login_ip": user.get("last_login_ip"),
        "is_main_admin": _is_main_admin(user.get("email", "")),
    }


async def get_current_user(request: Request) -> dict:
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        # Fallback query param — utilisé pour les <a href> qui téléchargent (export CSV, MJPEG…)
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        # v0.5.4 · Vérifie que la session (jti) n'a pas été révoquée.
        jti = payload.get("jti")
        if jti and not _testing_mode():
            sess = await db.sessions.find_one({"jti": jti}, {"_id": 0})
            if sess and sess.get("revoked"):
                raise HTTPException(status_code=401, detail="Session révoquée")
            if sess:
                # Rafraîchit `last_seen_at` (best-effort, ne bloque pas la requête)
                try:
                    await db.sessions.update_one(
                        {"jti": jti},
                        {"$set": {"last_seen_at": datetime.now(timezone.utc).isoformat()}},
                    )
                except Exception:
                    pass
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


def require_permission(perm: str):
    """Dépendance d'autorisation granulaire (admin = bypass)."""
    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if not has_permission(user, perm):
            raise HTTPException(status_code=403, detail=f"Permission requise : {perm}")
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


class ForgotPasswordInput(BaseModel):
    email: EmailStr


class ResetPasswordInput(BaseModel):
    token: str
    new_password: str


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


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


async def _check_lockout(identifier: str):
    if _testing_mode():
        return
    rec = await db.login_attempts.find_one({"identifier": identifier})
    if rec and rec.get("locked_until"):
        if datetime.fromisoformat(rec["locked_until"]) > datetime.now(timezone.utc):
            remaining = int((datetime.fromisoformat(rec["locked_until"]) - datetime.now(timezone.utc)).total_seconds() // 60) + 1
            raise HTTPException(status_code=423, detail=f"Compte temporairement verrouillé. Réessayez dans {remaining} min.")


async def _register_failure(identifier: str) -> int:
    if _testing_mode():
        return 0
    rec = await db.login_attempts.find_one({"identifier": identifier})
    count = (rec["count"] + 1) if rec else 1
    update = {"identifier": identifier, "count": count, "last_at": datetime.now(timezone.utc).isoformat()}
    if count >= MAX_LOGIN_ATTEMPTS:
        update["locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
    await db.login_attempts.update_one({"identifier": identifier}, {"$set": update}, upsert=True)
    return count


async def _clear_attempts(identifier: str):
    await db.login_attempts.delete_one({"identifier": identifier})


# v1.0-rc4.6 · Verrouillage par compte (persistant, unlock explicite requis)
# ─────────────────────────────────────────────────────────────────────────
async def _account_track_failure(email: str, ip: str) -> dict:
    """Incrémente atomiquement le compteur d'échecs du compte ciblé.

    - Ne fait rien si l'utilisateur n'existe pas (évite l'énumération d'emails).
    - Verrouille le compte de façon PERSISTANTE lorsque failed_login_count ≥
      MAX_ACCOUNT_ATTEMPTS (aucun déverrouillage automatique — action admin
      requise via l'UI ou la CLI `mgvms-admin unlock-user`).
    - Journalise `account_locked` lors du basculement locked=False → True.

    Returns: dict {locked: bool, count: int, target_email: str} ou {} si user absent.
    """
    if _testing_mode():
        return {}
    now_iso = datetime.now(timezone.utc).isoformat()
    result = await db.users.find_one_and_update(
        {"email": email},
        {
            "$inc": {"failed_login_count": 1},
            "$set": {"last_failed_login_at": now_iso, "last_failed_login_ip": ip},
        },
        projection={"id": 1, "email": 1, "failed_login_count": 1, "locked": 1},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        return {}
    count = int(result.get("failed_login_count") or 0)
    was_locked = bool(result.get("locked"))
    just_locked = False
    if count >= MAX_ACCOUNT_ATTEMPTS and not was_locked:
        await db.users.update_one(
            {"id": result["id"]},
            {"$set": {"locked": True, "locked_at": now_iso}},
        )
        just_locked = True
        await log_audit(
            None, "account_locked", result.get("email", email),
            f"{count} tentatives consécutives", ip,
        )
    return {"locked": was_locked or just_locked, "count": count, "target_email": result.get("email", email)}


async def _account_track_success(user: dict, ip: str) -> None:
    """Reset compteur d'échecs + met à jour last_login_* sur connexion réussie.

    Ne touche PAS le flag `locked` (un compte verrouillé qui parviendrait à
    l'authentification — impossible en pratique car court-circuité en amont —
    doit rester verrouillé jusqu'à unlock explicite).
    """
    if _testing_mode():
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {
                "failed_login_count": 0,
                "last_login_at": now_iso,
                "last_login_ip": ip,
            }
        },
    )


# ---------- Endpoints ----------
@auth_router.post("/login")
async def login(data: LoginInput, request: Request, response: Response):
    email = data.email.lower()
    ip = _client_ip(request)
    identifier = f"{ip}:{email}"
    # ── Défense en profondeur #1 : rate-limit IP:email (auto 15 min) ────
    await _check_lockout(identifier)

    user = await db.users.find_one({"email": email}, {"_id": 0})

    # ── Défense en profondeur #2 : lockout compte PERSISTANT ────────────
    # Le message renvoyé reste volontairement générique pour ne pas révéler
    # (a) qu'un compte existe, (b) qu'il est verrouillé. L'audit trail suffit
    # pour l'admin. Un compte verrouillé refuse même le bon mot de passe.
    if user and user.get("locked"):
        await log_audit(None, "login_failed", email, "Compte verrouillé", ip)
        raise HTTPException(status_code=401, detail="Email ou mot de passe invalide")

    if not user or not verify_password(data.password, user["password_hash"]):
        # Rate-limit IP:email (existant)
        count_ip = await _register_failure(identifier)
        # Compteur PAR COMPTE (nouveau v1.0-rc4.6) — noop silencieux si user absent
        acct = await _account_track_failure(email, ip) if user else {}
        await log_audit(
            None, "login_failed", email,
            f"IP {count_ip}/{MAX_LOGIN_ATTEMPTS} · compte {acct.get('count', 0)}/{MAX_ACCOUNT_ATTEMPTS}",
            ip,
        )
        raise HTTPException(status_code=401, detail="Email ou mot de passe invalide")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Compte désactivé")

    if user.get("twofa_enabled"):
        if not data.totp_code:
            return {"requires_2fa": True}
        totp = pyotp.TOTP(user["twofa_secret"])
        # v0.5.4-C · Accepte aussi un code de récupération (jetable).
        used_recovery = False
        if not totp.verify(data.totp_code, valid_window=1):
            # Essai en tant que code de récupération
            hashes = user.get("twofa_recovery_hashes") or []
            match_idx = None
            for i, h in enumerate(hashes):
                try:
                    if bcrypt.checkpw(data.totp_code.strip().upper().encode(), h.encode()):
                        match_idx = i
                        break
                except Exception:
                    continue
            if match_idx is None:
                await _register_failure(identifier)
                raise HTTPException(status_code=401, detail="Code 2FA invalide")
            # Retire le code utilisé (usage unique)
            new_hashes = hashes[:match_idx] + hashes[match_idx + 1:]
            await db.users.update_one({"id": user["id"]},
                                       {"$set": {"twofa_recovery_hashes": new_hashes}})
            used_recovery = True

    await _clear_attempts(identifier)
    # v1.0-rc4.6 · Reset compteur PAR COMPTE + last_login_at/ip
    await _account_track_success(user, ip)
    # v0.5.4 · Session tracking + timeout configurable
    hours = await _get_session_hours()
    import uuid as _uuid
    jti = str(_uuid.uuid4())
    access = create_access_token(user["id"], user["email"], user["role"], hours=hours, jti=jti)
    refresh = create_refresh_token(user["id"])
    # Persiste la session pour affichage + révocation
    now_iso = datetime.now(timezone.utc).isoformat()
    exp_iso = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    await db.sessions.insert_one({
        "jti": jti, "user_id": user["id"], "email": user["email"],
        "created_at": now_iso, "last_seen_at": now_iso, "expires_at": exp_iso,
        "ip": ip, "user_agent": request.headers.get("user-agent", "")[:250],
        "revoked": False,
    })
    response.set_cookie("access_token", access, httponly=True, secure=True, samesite="lax", max_age=hours * 3600, path="/")
    if used_recovery if 'used_recovery' in locals() else False:
        await log_audit(user, "2fa_recovery_used", email, "Login via recovery code", ip)
    await log_audit(user, "login", email, f"Connexion réussie (session {hours}h)", ip)
    return {"access_token": access, "refresh_token": refresh, "user": public_user(user)}


async def _get_session_hours() -> int:
    """Timeout configuré via `settings.security.session_hours` (défaut 8h).

    Valeurs supportées : 0.25 (15min) / 0.5 (30min) / 1 / 4 / 8 / custom.
    Le champ est stocké en float (heures) pour supporter les valeurs < 1h ;
    le cookie / JWT sont ensuite calculés en secondes.
    """
    doc = await db.settings.find_one({"id": "security"}, {"_id": 0}) or {}
    return max(1, int(round(float(doc.get("session_hours", 8)))))


@auth_router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordInput, request: Request):
    email = data.email.lower()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    # Réponse générique (anti-énumération de comptes)
    if user:
        token = secrets.token_urlsafe(32)
        await db.password_reset_tokens.insert_one({
            "id": str(uuid.uuid4()), "token": token, "user_id": user["id"], "email": email,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "used": False, "created_at": datetime.now(timezone.utc).isoformat(),
        })
        reset_link = f"/reset-password?token={token}"
        # Pas d'infra mail garantie : on journalise le lien (récupérable côté ops)
        print(f"[MG-VMS] Password reset for {email}: {reset_link}  (token={token})")
        await log_audit(user, "password_reset_requested", email, "", _client_ip(request))
        # Best-effort: envoi par SMTP si configuré
        try:
            from notifications import _load_raw, _channel_cfg, send_smtp
            doc = await _load_raw()
            if doc.get("smtp", {}).get("enabled"):
                cfg = await _channel_cfg(doc, "smtp")
                await send_smtp(cfg, "[MG-VMS] Réinitialisation de mot de passe",
                                f"Lien de réinitialisation (valide 1h): {reset_link}\nToken: {token}")
        except Exception as e:
            print(f"[MG-VMS] reset email send skipped: {e}")
    return {"message": "Si ce compte existe, un lien de réinitialisation a été envoyé."}


@auth_router.post("/reset-password")
async def reset_password(data: ResetPasswordInput, request: Request):
    rec = await db.password_reset_tokens.find_one({"token": data.token}, {"_id": 0})
    if not rec or rec.get("used"):
        raise HTTPException(status_code=400, detail="Jeton invalide ou déjà utilisé")
    if datetime.fromisoformat(rec["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Jeton expiré")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au moins 8 caractères")
    await db.users.update_one({"id": rec["user_id"]}, {"$set": {"password_hash": hash_password(data.new_password)}})
    await db.password_reset_tokens.update_one({"token": data.token}, {"$set": {"used": True}})
    user = await db.users.find_one({"id": rec["user_id"]}, {"_id": 0})
    await log_audit(user, "password_reset_success", rec["email"], "", _client_ip(request))
    return {"message": "Mot de passe réinitialisé avec succès."}


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
async def refresh_token(request: Request, response: Response):
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
        # v0.5.4-C · Blacklist du refresh consommé (rotation).
        old_jti = payload.get("jti") or payload.get("sub")
        used = await db.refresh_blacklist.find_one({"jti": old_jti})
        if used:
            # Réutilisation détectée → possible token stealing : révoque tout.
            await db.sessions.update_many({"user_id": payload["sub"]},
                                            {"$set": {"revoked": True}})
            raise HTTPException(status_code=401, detail="Refresh token réutilisé - toutes les sessions révoquées")
        await db.refresh_blacklist.insert_one({"jti": old_jti,
                                                 "used_at": datetime.now(timezone.utc).isoformat()})
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        hours = await _get_session_hours()
        import uuid as _uuid
        new_jti = str(_uuid.uuid4())
        access = create_access_token(user["id"], user["email"], user["role"], hours=hours, jti=new_jti)
        new_refresh = create_refresh_token(user["id"])
        # Nouvelle session (le client peut avoir plusieurs onglets)
        await db.sessions.insert_one({
            "jti": new_jti, "user_id": user["id"], "email": user["email"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(),
            "ip": request.client.host if request.client else "?",
            "user_agent": request.headers.get("user-agent", "")[:250],
            "revoked": False, "via_refresh": True,
        })
        response.set_cookie("access_token", access, httponly=True, secure=True,
                             samesite="lax", max_age=hours * 3600, path="/")
        return {"access_token": access, "refresh_token": new_refresh}
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
    # v0.5.4-C · Génère 10 codes de récupération (une seule fois, à conserver).
    # Stockage haché bcrypt côté DB, retour clair côté client.
    import secrets as _secrets
    plain = [_secrets.token_hex(4).upper() for _ in range(10)]
    hashes = [bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode() for p in plain]
    await db.users.update_one({"id": user["id"]}, {
        "$set": {"twofa_enabled": True, "twofa_recovery_hashes": hashes},
    })
    await log_audit(user, "2fa_enabled", user["email"])
    return {"ok": True, "recovery_codes": plain}


@auth_router.post("/2fa/recovery-regenerate")
async def regenerate_recovery_codes(user: dict = Depends(get_current_user)):
    """Régénère 10 nouveaux codes de récupération (invalide les anciens)."""
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    if not fresh.get("twofa_enabled"):
        raise HTTPException(status_code=400, detail="2FA non activée")
    import secrets as _secrets
    plain = [_secrets.token_hex(4).upper() for _ in range(10)]
    hashes = [bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode() for p in plain]
    await db.users.update_one({"id": user["id"]},
                               {"$set": {"twofa_recovery_hashes": hashes}})
    await log_audit(user, "2fa_recovery_regen", user["email"])
    return {"recovery_codes": plain}


@auth_router.post("/2fa/disable")
async def disable_2fa(user: dict = Depends(get_current_user)):
    await db.users.update_one({"id": user["id"]}, {"$set": {"twofa_enabled": False, "twofa_secret": None}})
    await log_audit(user, "2fa_disabled", user["email"])
    return {"ok": True}
