"""Route module — Users admin (CRUD).
Extrait de `routers.py` (P1 modularisation, Feb 2026).
"""
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from auth import (
    hash_password, log_audit, public_user,
    PERMISSIONS, ROLES, require_permission, require_role,
    _is_main_admin,
)
from database import db
from notifications import send_email_to

users_router = APIRouter(prefix="/api", tags=["users"])


class UserCreate(BaseModel):
    email: str
    password: str
    name: str
    role: str = "client"
    site_ids: Optional[List[str]] = None
    permissions: Optional[Dict[str, bool]] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    site_ids: Optional[List[str]] = None
    permissions: Optional[Dict[str, bool]] = None


def _clean_permissions(perms: Optional[Dict[str, bool]]) -> Dict[str, bool]:
    if not perms:
        return {}
    return {k: bool(v) for k, v in perms.items() if k in PERMISSIONS}


@users_router.get("/users")
async def list_users(user: dict = Depends(require_permission("manage_users"))):
    users = await db.users.find({}, {"_id": 0, "password_hash": 0, "twofa_secret": 0}).to_list(500)
    return [public_user(u) for u in users]


@users_router.post("/users")
async def create_user(data: UserCreate, user: dict = Depends(require_permission("manage_users"))):
    email = data.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email déjà utilisé")
    role = data.role if data.role in ROLES else "client"
    doc = {
        "id": str(uuid.uuid4()), "email": email, "password_hash": hash_password(data.password),
        "name": data.name, "role": role, "twofa_enabled": False, "twofa_secret": None,
        "active": True, "site_ids": data.site_ids or [],
        "permissions": _clean_permissions(data.permissions),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(dict(doc))
    await log_audit(user, "user_created", email, role)
    return public_user(doc)


@users_router.put("/users/{user_id}")
async def update_user(user_id: str, data: UserUpdate, user: dict = Depends(require_role("admin"))):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if "role" in update and update["role"] not in ROLES:
        raise HTTPException(400, "Rôle invalide")
    if "permissions" in update:
        update["permissions"] = _clean_permissions(update["permissions"])
    # Email : normaliser en minuscules + vérifier unicité (si changement effectif)
    if "email" in update:
        new_email = update["email"].strip().lower()
        if not new_email or "@" not in new_email:
            raise HTTPException(400, "Email invalide")
        if await db.users.find_one({"email": new_email, "id": {"$ne": user_id}}):
            raise HTTPException(400, "Email déjà utilisé par un autre utilisateur")
        update["email"] = new_email
    # Mot de passe : hasher avant stockage, remplacer 'password' par 'password_hash'
    if "password" in update:
        pwd = update.pop("password")
        if len(pwd) < 8:
            raise HTTPException(400, "Mot de passe : minimum 8 caractères")
        update["password_hash"] = hash_password(pwd)
    res = await db.users.update_one({"id": user_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Utilisateur introuvable")
    await log_audit(user, "user_updated", user_id, ",".join(update.keys()))
    u = await db.users.find_one({"id": user_id}, {"_id": 0})
    return public_user(u)


@users_router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_permission("manage_users"))):
    if user_id == user["id"]:
        raise HTTPException(400, "Impossible de supprimer votre propre compte")
    await db.users.delete_one({"id": user_id})
    await log_audit(user, "user_deleted", user_id)
    return {"ok": True}


@users_router.delete("/users/{user_id}/mfa")
async def admin_disable_mfa(user_id: str,
                             background: BackgroundTasks,
                             user: dict = Depends(require_permission("manage_users"))):
    """Désactive la MFA d'un utilisateur (usage : perte du téléphone).

    Efface ``twofa_enabled``, ``twofa_secret`` et les hashes des codes de
    récupération, permettant à l'utilisateur de se reconnecter avec son
    seul mot de passe et de refaire un enrollment complet.

    Envoie également un email de notification au user concerné pour
    tracer et détecter les abus.

    Réservé aux admins. Ne peut pas s'appliquer sur son propre compte
    depuis cet endpoint (on utilise `/auth/2fa/disable` pour se
    désactiver soi-même — flux avec confirmation dédiée).
    """
    if user_id == user["id"]:
        raise HTTPException(
            400,
            "Utilisez la page MFA (Centre de sécurité → MFA) pour "
            "désactiver la MFA de votre propre compte.",
        )
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(404, "Utilisateur introuvable")
    if not target.get("twofa_enabled"):
        raise HTTPException(400, "La MFA n'est pas activée pour cet utilisateur")
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "twofa_enabled": False,
            "twofa_secret": None,
            "twofa_recovery_hashes": [],
        }},
    )
    await log_audit(
        user, "user_mfa_disabled_by_admin", target.get("email", user_id),
        f"admin={user.get('email')}"
    )
    # v0.5.5.d · Notifie le user concerné par email (best-effort, background).
    subject = "Votre MFA a été désactivée par un administrateur"
    body = (
        f"Bonjour {target.get('name') or target.get('email')},\n\n"
        f"L'administrateur {user.get('email')} vient de désactiver la MFA\n"
        f"de votre compte MG-VMS ({target.get('email')}).\n\n"
        "Vous pouvez désormais vous reconnecter avec votre seul mot de\n"
        "passe. Il est fortement recommandé de :\n"
        "  1. Vous reconnecter immédiatement,\n"
        "  2. Refaire un enrollement MFA depuis Centre de sécurité → MFA,\n"
        "  3. Signaler à l'administrateur toute action que vous n'auriez pas\n"
        "     autorisée.\n\n"
        f"Horodatage : {datetime.now(timezone.utc).isoformat()}\n"
        "-- MG-VMS Security"
    )
    background.add_task(send_email_to, target.get("email"), subject, body)
    return {"ok": True, "user_id": user_id, "email": target.get("email")}


# ─── v1.0-rc4.6 · Déverrouillage compte (brute-force) ─────────────────
@users_router.post("/users/{user_id}/unlock")
async def unlock_user_account(
    user_id: str,
    user: dict = Depends(require_role("admin")),
):
    """Déverrouille un compte utilisateur verrouillé après 5 échecs.

    - Réservé aux admins (`require_role("admin")`).
    - Le compte ADMIN_EMAIL (admin principal) est PROTÉGÉ : le déverrouillage
      passe UNIQUEMENT par la CLI `mgvms-admin unlock-user <email>` (voir
      `scripts/mgvms_admin.py`). Retour 403 explicite ici.
    - Idempotent : appeler unlock sur un compte non verrouillé n'écrit
      rien de destructif — remet juste `failed_login_count` à 0.
    """
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(404, "Utilisateur introuvable")
    if _is_main_admin(target.get("email", "")):
        raise HTTPException(
            403,
            "Le compte admin principal ne peut être déverrouillé que via la "
            "CLI serveur : `mgvms-admin unlock-user " + target["email"] + "`",
        )
    await db.users.update_one(
        {"id": user_id},
        {
            "$set": {"locked": False, "failed_login_count": 0},
            "$unset": {"locked_at": ""},
        },
    )
    await log_audit(
        user, "account_unlocked", target.get("email", user_id),
        f"admin={user.get('email')}",
    )
    return {"ok": True, "user_id": user_id, "email": target.get("email"), "locked": False}
