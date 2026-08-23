"""Route module — License activation (v3.3, août 2026).

Vérifie et active des clés de licence "Gold Support" émises hors-ligne par le
générateur de licences (service local séparé, non versionné, voir
deploy-app/README pour le contexte). Ce module NE génère AUCUNE licence — il
ne fait que vérifier une signature Ed25519 avec la clé PUBLIQUE embarquée
ci-dessous et stocker l'état d'activation en base.

Format d'une clé de licence : base64url(JSON payload) + "." + base64url(signature)
Payload JSON : {"license_id", "client", "type", "issued_at", "expires_at"}
  - type: "trial" | "gold" | "enterprise"
  - issued_at / expires_at: ISO 8601 UTC, ou null pour expires_at = illimité
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_role, log_audit
from database import db

license_router = APIRouter(prefix="/api", tags=["license"])

# Clé publique Ed25519 (32 octets, base64 standard) — la clé privée
# correspondante ne vit QUE sur le générateur de licences local, jamais dans
# ce dépôt. Régénérer les deux ensemble si cette valeur change.
LICENSE_PUBLIC_KEY_B64 = "aLSm/Yj6P800SXJF/HMUAuKVbw8AP9iCz7YV8ElpCC0="

VALID_TYPES = {"trial", "gold", "enterprise"}


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def verify_license_key(license_key: str) -> dict:
    """Vérifie la signature Ed25519 d'une clé et retourne le payload décodé.

    Lève HTTPException(400) si le format ou la signature est invalide.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        raise HTTPException(500, "Module cryptography indisponible côté serveur")

    parts = (license_key or "").strip().split(".")
    if len(parts) != 2:
        raise HTTPException(400, "Format de clé de licence invalide")
    payload_b64, sig_b64 = parts
    try:
        payload_bytes = _b64u_decode(payload_b64)
        signature = _b64u_decode(sig_b64)
        payload = json.loads(payload_bytes)
    except Exception:
        raise HTTPException(400, "Clé de licence illisible (encodage invalide)")

    try:
        pubkey = Ed25519PublicKey.from_public_bytes(base64.b64decode(LICENSE_PUBLIC_KEY_B64))
        pubkey.verify(signature, payload_bytes)
    except InvalidSignature:
        raise HTTPException(400, "Signature de licence invalide")
    except Exception:
        raise HTTPException(500, "Clé publique de licence non configurée côté serveur")

    if payload.get("type") not in VALID_TYPES:
        raise HTTPException(400, "Type de licence inconnu")
    if not payload.get("license_id") or not payload.get("client"):
        raise HTTPException(400, "Licence incomplète (license_id/client manquant)")

    return payload


def _license_state(doc: dict | None) -> dict:
    if not doc:
        return {"active": False, "expired": False, "license": None}
    expires_at = doc.get("expires_at")
    expired = False
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            expired = datetime.now(timezone.utc) > exp
        except Exception:
            expired = False
    return {
        "active": not expired,
        "expired": expired,
        "license": {
            "license_id": doc.get("license_id"),
            "client": doc.get("client"),
            "type": doc.get("type"),
            "issued_at": doc.get("issued_at"),
            "expires_at": expires_at,
            "activated_at": doc.get("activated_at"),
        },
    }


@license_router.get("/license/status")
async def get_license_status(user: dict = Depends(require_role("admin"))):
    doc = await db.license.find_one({"_id": "current"})
    return _license_state(doc)


class ActivateLicenseInput(BaseModel):
    license_key: str


@license_router.post("/license/activate")
async def activate_license(data: ActivateLicenseInput, user: dict = Depends(require_role("admin"))):
    payload = verify_license_key(data.license_key)
    record = {
        "_id": "current",
        "license_id": payload["license_id"],
        "client": payload["client"],
        "type": payload["type"],
        "issued_at": payload.get("issued_at"),
        "expires_at": payload.get("expires_at"),
        "license_key": data.license_key,
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.license.replace_one({"_id": "current"}, record, upsert=True)
    await log_audit(user, "license_activated", payload["license_id"], payload["type"])
    return _license_state(record)


@license_router.delete("/license/deactivate")
async def deactivate_license(user: dict = Depends(require_role("admin"))):
    await db.license.delete_one({"_id": "current"})
    await log_audit(user, "license_deactivated", "current")
    return {"status": "deactivated"}
