"""Tests — Endpoint admin de désactivation MFA (v0.5.5.c).

Vérifie que ``DELETE /api/users/{user_id}/mfa`` :

  - N'est accessible qu'à un admin authentifié (403 sinon).
  - Renvoie 400 si l'utilisateur tente de se désactiver lui-même
    (le vrai endpoint est /auth/2fa/disable).
  - Renvoie 404 si l'utilisateur est introuvable.
  - Renvoie 400 si la MFA n'est pas activée pour cet utilisateur.
  - Efface correctement ``twofa_enabled`` / ``twofa_secret`` /
    ``twofa_recovery_hashes`` quand tout est bon.
"""
import os
import sys
from pathlib import Path

import pytest
import requests

# Chargement env pour Mongo direct
_env_file = Path("/app/backend/.env")
for line in _env_file.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
sys.path.insert(0, "/app/backend")
os.environ.setdefault("TESTING", "1")

_env = Path("/app/frontend/.env").read_text()
BASE_URL = None
for line in _env.splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL manquant"

ADMIN_EMAIL = "admin@mg-vms.com"
ADMIN_PASSWORD = "Admin@2026"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                       timeout=8)
    assert r.status_code == 200, r.text
    return r.json().get("access_token") or r.json().get("token")


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _get_users(t):
    r = requests.get(f"{BASE_URL}/api/users", headers=_auth(t), timeout=6)
    assert r.status_code == 200, r.text
    return r.json()


def test_admin_disable_mfa_requires_auth():
    r = requests.delete(f"{BASE_URL}/api/users/whatever/mfa", timeout=5)
    assert r.status_code == 401


def test_admin_cannot_disable_own_mfa(admin_token):
    users = _get_users(admin_token)
    me = next(u for u in users if u["email"] == ADMIN_EMAIL)
    r = requests.delete(f"{BASE_URL}/api/users/{me['id']}/mfa",
                         headers=_auth(admin_token), timeout=6)
    assert r.status_code == 400
    assert "propre compte" in r.json()["detail"].lower()


def test_admin_disable_mfa_user_not_found(admin_token):
    r = requests.delete(f"{BASE_URL}/api/users/nonexistent-uuid-xxxx/mfa",
                         headers=_auth(admin_token), timeout=6)
    assert r.status_code == 404


def test_admin_disable_mfa_when_not_enabled(admin_token):
    users = _get_users(admin_token)
    target = next(u for u in users
                   if u["email"] != ADMIN_EMAIL and not u.get("twofa_enabled"))
    r = requests.delete(f"{BASE_URL}/api/users/{target['id']}/mfa",
                         headers=_auth(admin_token), timeout=6)
    assert r.status_code == 400
    assert "activée" in r.json()["detail"].lower() or "enabled" in r.json()["detail"].lower()


def test_admin_disable_mfa_happy_path(admin_token):
    """Active MFA en direct Mongo → appel admin → vérifie que c'est purgé."""
    from pymongo import MongoClient

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = MongoClient(mongo_url)
    coll = client[db_name].users

    users = _get_users(admin_token)
    target = next(u for u in users if u["email"] != ADMIN_EMAIL)

    coll.update_one(
        {"id": target["id"]},
        {"$set": {"twofa_enabled": True,
                  "twofa_secret": "TESTFAKESECRET",
                  "twofa_recovery_hashes": ["h1", "h2"]}},
    )

    # Vérifie que l'API voit bien MFA activée.
    users2 = _get_users(admin_token)
    assert next(u for u in users2 if u["id"] == target["id"])["twofa_enabled"] is True

    # Désactive via endpoint admin.
    r = requests.delete(f"{BASE_URL}/api/users/{target['id']}/mfa",
                         headers=_auth(admin_token), timeout=6)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["user_id"] == target["id"]

    # Vérifie côté API.
    users3 = _get_users(admin_token)
    assert next(u for u in users3 if u["id"] == target["id"])["twofa_enabled"] is False

    # Vérifie côté DB : secret et recovery hashes bien purgés.
    doc = coll.find_one({"id": target["id"]}, {"_id": 0})
    assert doc["twofa_enabled"] is False
    assert doc["twofa_secret"] is None
    assert doc["twofa_recovery_hashes"] == []
    client.close()
