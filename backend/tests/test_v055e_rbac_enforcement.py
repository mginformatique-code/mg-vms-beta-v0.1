"""Tests — Enforcement RBAC (v0.5.5.e).

Vérifie que `require_permission()` bloque effectivement les endpoints :

  - `/api/audit` — nécessite `view_audit_log`
  - `/api/users` — nécessite `manage_users`

Un utilisateur guest (par défaut aucune perm) doit être 403.
Un admin passe toujours (bypass strict).
"""
import os
import sys
import uuid
from pathlib import Path

import pytest
import requests

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

ADMIN_EMAIL = "admin@mg-vms.com"
ADMIN_PASSWORD = "Admin@2026"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                       timeout=8)
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def guest_creds(admin_token):
    """Crée un utilisateur guest de test (pas de permissions par défaut)."""
    import time
    email = f"rbac-guest-{uuid.uuid4().hex[:8]}@example.com"
    password = "GuestPass@2026"
    r = requests.post(f"{BASE_URL}/api/users",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"email": email, "password": password,
                             "name": "RBAC Guest", "role": "guest"},
                       timeout=6)
    assert r.status_code == 200, r.text
    user_id = r.json()["id"]
    # Login guest — retry si la propagation Mongo tarde.
    guest_token = None
    for _ in range(5):
        time.sleep(0.2)
        r2 = requests.post(f"{BASE_URL}/api/auth/login",
                            json={"email": email, "password": password},
                            timeout=6)
        if r2.status_code == 200:
            guest_token = r2.json().get("access_token")
            if guest_token:
                break
    assert guest_token, f"Impossible d'obtenir un token guest: r2={r2.status_code} {r2.text[:200]}"
    yield email, guest_token, user_id
    # Cleanup
    requests.delete(f"{BASE_URL}/api/users/{user_id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    timeout=6)


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_guest_cannot_list_audit(guest_creds):
    _, guest_token, _ = guest_creds
    r = requests.get(f"{BASE_URL}/api/audit", headers=_auth(guest_token), timeout=6)
    assert r.status_code == 403


def test_guest_cannot_list_users(guest_creds):
    _, guest_token, _ = guest_creds
    r = requests.get(f"{BASE_URL}/api/users", headers=_auth(guest_token), timeout=6)
    assert r.status_code == 403


def test_admin_can_list_audit(admin_token):
    r = requests.get(f"{BASE_URL}/api/audit", headers=_auth(admin_token), timeout=6)
    assert r.status_code == 200


def test_audit_filter_rbac_action_prefix(admin_token):
    """La modification RBAC crée une entrée d'audit filtrable."""
    # Trigger un update RBAC pour garantir au moins 1 entrée.
    requests.put(f"{BASE_URL}/api/security/rbac",
                  headers=_auth(admin_token),
                  json={"role": "readonly",
                        "permissions": {"view_live": True}},
                  timeout=6)
    r = requests.get(f"{BASE_URL}/api/audit",
                       headers=_auth(admin_token),
                       params={"action_prefix": "rbac_", "limit": 50},
                       timeout=6)
    assert r.status_code == 200
    entries = r.json()
    assert any(e.get("action", "").startswith("rbac_") for e in entries)
    # Nettoyage
    requests.delete(f"{BASE_URL}/api/security/rbac/readonly",
                    headers=_auth(admin_token), timeout=6)


def test_grant_manage_users_to_guest_role_unlocks(admin_token, guest_creds):
    """Après override RBAC (guest → manage_users), un guest peut lister users."""
    _, guest_token, _ = guest_creds
    # Grant perm
    r = requests.put(f"{BASE_URL}/api/security/rbac",
                      headers=_auth(admin_token),
                      json={"role": "guest",
                            "permissions": {"manage_users": True,
                                            "view_audit_log": False}},
                      timeout=6)
    assert r.status_code == 200
    try:
        # Guest doit maintenant pouvoir lister users
        r2 = requests.get(f"{BASE_URL}/api/users", headers=_auth(guest_token), timeout=6)
        assert r2.status_code == 200, r2.text
        # Mais toujours pas /audit
        r3 = requests.get(f"{BASE_URL}/api/audit", headers=_auth(guest_token), timeout=6)
        assert r3.status_code == 403
    finally:
        # Cleanup
        requests.delete(f"{BASE_URL}/api/security/rbac/guest",
                        headers=_auth(admin_token), timeout=6)
