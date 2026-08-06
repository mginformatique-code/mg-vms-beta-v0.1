"""Tests v0.5.4 Phase A · Session Manager + timeout configurable.

Ce fichier manipule les sessions et refresh tokens du user `admin@mg-vms.com`.
En exécution parallèle (`pytest-xdist`), plusieurs workers peuvent partager
le même user et se marcher dessus lors des révocations. On force donc tous
les tests de ce fichier sur le **même worker** via `xdist_group`.
"""
import pytest

pytestmark = pytest.mark.xdist_group(name="sessions")


# v0.5.4-C · Utilisateur dédié à ces tests pour éviter de tuer les
# sessions du user `admin@mg-vms.com` utilisé par d'autres fichiers
# de test en parallèle (`test_v052_site_manager.py`, etc.).
TEST_EMAIL = "sessions-test@mg-vms.com"
TEST_PASSWORD = "SessionsTest@2026"

from pathlib import Path

import requests

_env = Path("/app/frontend/.env").read_text()
BASE_URL = None
for line in _env.splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
assert BASE_URL


def _ensure_test_user():
    """Crée le user test s'il n'existe pas (via admin)."""
    admin = requests.post(f"{BASE_URL}/api/auth/login",
                           json={"email": "admin@mg-vms.com", "password": "Admin@2026"},
                           timeout=8).json()
    at = admin.get("access_token")
    # Vérifie
    users = requests.get(f"{BASE_URL}/api/users",
                          headers={"Authorization": f"Bearer {at}"}, timeout=8).json()
    if any(u.get("email") == TEST_EMAIL for u in users):
        return
    requests.post(f"{BASE_URL}/api/users",
                   headers={"Authorization": f"Bearer {at}"},
                   json={"email": TEST_EMAIL, "password": TEST_PASSWORD,
                          "role": "technician", "name": "Sessions Test"},
                   timeout=8)


def _login():
    _ensure_test_user()
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
                       timeout=8)
    assert r.status_code == 200
    return r.json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_sessions_endpoint_lists_current():
    t = _login()
    r = requests.get(f"{BASE_URL}/api/security/sessions", headers=_auth(t), timeout=8)
    assert r.status_code == 200
    data = r.json()
    assert data["current_jti"]
    assert any(s.get("current") for s in data["items"])


def test_timeout_get_and_update():
    """PUT /timeout requiert admin — utilise le compte admin principal."""
    admin_token = requests.post(f"{BASE_URL}/api/auth/login",
                                  json={"email": "admin@mg-vms.com", "password": "Admin@2026"},
                                  timeout=8).json()["access_token"]
    r = requests.get(f"{BASE_URL}/api/security/timeout", headers=_auth(admin_token), timeout=8)
    assert r.status_code == 200
    assert r.json()["session_hours"] > 0
    assert 4 in r.json()["options"]

    r2 = requests.put(f"{BASE_URL}/api/security/timeout", headers=_auth(admin_token),
                       json={"session_hours": 4.0}, timeout=8)
    assert r2.status_code == 200
    assert r2.json()["session_hours"] == 4.0
    # cleanup
    requests.put(f"{BASE_URL}/api/security/timeout", headers=_auth(admin_token),
                  json={"session_hours": 8.0}, timeout=8)


def test_timeout_rejects_invalid_range():
    admin_token = requests.post(f"{BASE_URL}/api/auth/login",
                                  json={"email": "admin@mg-vms.com", "password": "Admin@2026"},
                                  timeout=8).json()["access_token"]
    for bad in (0.1, 25):
        r = requests.put(f"{BASE_URL}/api/security/timeout", headers=_auth(admin_token),
                          json={"session_hours": bad}, timeout=8)
        assert r.status_code in (400, 422), f"{bad} should be rejected"


def test_revoke_others_kills_other_sessions():
    """Note : appelle `revoke-others` isolé pour ne pas casser les autres
    fichiers de test qui utilisent aussi admin@mg-vms.com."""
    t1 = _login()
    t2 = _login()  # nouvelle session
    # T2 révoque toutes les autres → tue T1
    r = requests.post(f"{BASE_URL}/api/security/sessions/revoke-others",
                       headers=_auth(t2), timeout=8)
    assert r.status_code == 200
    # T1 doit maintenant recevoir 401
    r1 = requests.get(f"{BASE_URL}/api/security/sessions", headers=_auth(t1), timeout=8)
    assert r1.status_code == 401
    # T2 reste valide
    r2 = requests.get(f"{BASE_URL}/api/security/sessions", headers=_auth(t2), timeout=8)
    assert r2.status_code == 200


def test_revoke_specific_session():
    _login()  # session A
    t = _login()  # session B (avec laquelle on va révoquer)
    sess = requests.get(f"{BASE_URL}/api/security/sessions", headers=_auth(t), timeout=8).json()
    cur = sess["current_jti"]
    other = next((s for s in sess["items"] if s["jti"] != cur), None)
    if not other:
        pytest.skip("Pas d'autre session active")
    r = requests.delete(f"{BASE_URL}/api/security/sessions/{other['jti']}",
                         headers=_auth(t), timeout=8)
    assert r.status_code == 200
    # T actuel reste valide
    r2 = requests.get(f"{BASE_URL}/api/security/sessions", headers=_auth(t), timeout=8)
    assert r2.status_code == 200


def test_security_endpoints_require_auth():
    for path in ("/api/security/sessions", "/api/security/timeout"):
        r = requests.get(f"{BASE_URL}{path}", timeout=6)
        assert r.status_code in (401, 403)


def test_security_score_endpoint():
    """Phase B — /api/security/score renvoie un score 0-100 + 10 critères."""
    t = _login()
    r = requests.get(f"{BASE_URL}/api/security/score", headers=_auth(t), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert 0 <= d["score"] <= 100
    assert d["grade"] in ("A", "B", "C", "D", "E")
    expected = {"https", "jwt_env", "strong_passwords", "mfa", "backups",
                 "plugin_sandbox", "camera_firmware", "mongo_auth", "disk", "certs"}
    assert expected.issubset(set(d["checks"].keys()))
    for k, v in d["checks"].items():
        assert "ok" in v and "label" in v and "weight" in v and "detail" in v


def test_security_score_requires_auth():
    r = requests.get(f"{BASE_URL}/api/security/score", timeout=6)
    assert r.status_code in (401, 403)


def test_refresh_token_rotation_detects_reuse():
    """Phase C — le refresh token consommé ne peut plus être réutilisé.
    Une réutilisation révoque toutes les sessions du user."""
    r0 = requests.post(f"{BASE_URL}/api/auth/login",
                        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
                        timeout=8).json()
    _ensure_test_user()
    refresh1 = r0["refresh_token"]
    r1 = requests.post(f"{BASE_URL}/api/auth/refresh",
                        headers={"Authorization": f"Bearer {refresh1}"}, timeout=8)
    assert r1.status_code == 200
    assert r1.json()["refresh_token"] != refresh1
    # Réutilisation → 401
    r2 = requests.post(f"{BASE_URL}/api/auth/refresh",
                        headers={"Authorization": f"Bearer {refresh1}"}, timeout=8)
    assert r2.status_code == 401
    assert "réutilisé" in r2.json().get("detail", "").lower() or \
           "reused" in r2.json().get("detail", "").lower() or \
           "invalid" in r2.json().get("detail", "").lower()
