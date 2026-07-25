"""MG-VMS Crypto utilities — Fernet symmetric encryption pour secrets au repos.

Applique R05 « Aucun secret en clair sur disque » et ADR-06 (chapitre 4).

Utilisation :
    from crypto_utils import encrypt_secret, decrypt_secret

    # À l'écriture
    doc["password"] = encrypt_secret(user_input)

    # À la lecture
    password = decrypt_secret(doc.get("password", ""))

Compat descendante : si `decrypt_secret` reçoit une chaîne non-chiffrée
(migration douce), elle retourne la valeur telle quelle (tolérance).

En v3.0 : clé dédiée `MGVMS_ENCRYPTION_KEY` (rotable). En v2.30 (Preview NG) :
réutilise `JWT_SECRET` pour ne pas casser les déploiements existants.
"""
from __future__ import annotations

import base64
import hashlib
import os
import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Marqueur permettant de détecter à la lecture si une valeur est chiffrée
# (les tokens Fernet commencent tous par "gAAAAA").
_FERNET_PREFIX = "gAAAAA"


def _fernet() -> Fernet:
    """Instancie Fernet depuis MGVMS_ENCRYPTION_KEY, ou fallback JWT_SECRET."""
    key_src = os.environ.get("MGVMS_ENCRYPTION_KEY") or os.environ.get("JWT_SECRET")
    if not key_src:
        raise RuntimeError("Ni MGVMS_ENCRYPTION_KEY ni JWT_SECRET défini — chiffrement impossible")
    key = base64.urlsafe_b64encode(hashlib.sha256(key_src.encode()).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Chiffre une valeur. Retourne "" si input vide."""
    if not plaintext:
        return ""
    # Idempotent : si déjà chiffré, ne pas re-chiffrer
    if plaintext.startswith(_FERNET_PREFIX):
        return plaintext
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(value: str) -> str:
    """Déchiffre une valeur. Compat descendante : renvoie tel quel si non-chiffré.

    Cette tolérance permet une migration progressive : les anciens mots de passe
    en clair continuent à fonctionner, les nouveaux sont chiffrés.
    """
    if not value:
        return ""
    if not value.startswith(_FERNET_PREFIX):
        # Legacy : mot de passe en clair — tolérance migration
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        logger.warning("decrypt_secret: token Fernet invalide (clé changée ?), retour valeur brute")
        return value


def is_encrypted(value: str) -> bool:
    """Retourne True si la valeur semble chiffrée Fernet."""
    return bool(value) and value.startswith(_FERNET_PREFIX)
