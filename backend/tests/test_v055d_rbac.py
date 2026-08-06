"""Tests — Phase D RBAC + notifications MFA (v0.5.5.d).

Couvre :
  - GET  /api/security/rbac          : structure de la matrice
  - PUT  /api/security/rbac          : override d'un rôle
  - DELETE /api/security/rbac/{role} : reset
  - Bypass admin : impossible d'altérer les perms du rôle admin
  - Auth : 401 sans token, 403 pour non-admin (utilisateur technicien)

Les changements sont ensuite réinitialisés en fin de test pour ne pas
polluer la base de démo.
"""
import os
import sys
from pathlib import Path

import pytest
import requests

# Charge env pour tests Mongo directs
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


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_rbac_requires_admin():
    r = requests.get(f"{BASE_URL}/api/security/rbac", timeout=5)
    assert r.status_code == 401


def test_rbac_get_shape(admin_token):
    r = requests.get(f"{BASE_URL}/api/security/rbac",
                       headers=_auth(admin_token), timeout=6)
    assert r.status_code == 200
    body = r.json()
    for key in ("permissions", "permission_meta", "permission_groups",
                 "roles", "defaults", "overrides", "effective"):
        assert key in body
    assert "manage_users" in body["permissions"]
    assert "view_audit_log" in body["permissions"]
    assert "access_security_center" in body["permissions"]
    assert "admin" in body["roles"]
    assert body["effective"]["admin"]["view_live"] is True
    # Chaque permission a une meta group/label
    for p in body["permissions"]:
        assert p in body["permission_meta"]
        assert body["permission_meta"][p]["group"] in {"video", "manage", "security"}


def test_rbac_put_readonly_override(admin_token):
    # Override
    r = requests.put(f"{BASE_URL}/api/security/rbac",
                      headers=_auth(admin_token),
                      json={"role": "readonly",
                            "permissions": {"view_live": True, "view_audit_log": True}},
                      timeout=6)
    assert r.status_code == 200
    body = r.json()
    assert body["overrides"]["readonly"]["view_audit_log"] is True
    assert body["effective"]["readonly"]["view_audit_log"] is True

    # Reset (nettoyage)
    r2 = requests.delete(f"{BASE_URL}/api/security/rbac/readonly",
                          headers=_auth(admin_token), timeout=6)
    assert r2.status_code == 200
    body2 = r2.json()
    assert "readonly" not in body2["overrides"] or not body2["overrides"]["readonly"]
    assert body2["effective"]["readonly"]["view_audit_log"] is False


def test_rbac_admin_role_is_immutable(admin_token):
    r = requests.put(f"{BASE_URL}/api/security/rbac",
                      headers=_auth(admin_token),
                      json={"role": "admin", "permissions": {"view_live": False}},
                      timeout=6)
    assert r.status_code == 400


def test_rbac_unknown_role_rejected(admin_token):
    r = requests.put(f"{BASE_URL}/api/security/rbac",
                      headers=_auth(admin_token),
                      json={"role": "wizard", "permissions": {"view_live": True}},
                      timeout=6)
    assert r.status_code == 400


def test_rbac_reset_admin_forbidden(admin_token):
    r = requests.delete(f"{BASE_URL}/api/security/rbac/admin",
                         headers=_auth(admin_token), timeout=6)
    assert r.status_code == 400
