"""Tests v0.5.4 Phase A · Session Manager + timeout configurable."""
from pathlib import Path

import pytest
import requests

_env = Path("/app/frontend/.env").read_text()
BASE_URL = None
for line in _env.splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
assert BASE_URL


def _login():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "admin@mg-vms.com", "password": "Admin@2026"},
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
    t = _login()
    r = requests.get(f"{BASE_URL}/api/security/timeout", headers=_auth(t), timeout=8)
    assert r.status_code == 200
    assert r.json()["session_hours"] > 0
    assert 4 in r.json()["options"]

    r2 = requests.put(f"{BASE_URL}/api/security/timeout", headers=_auth(t),
                       json={"session_hours": 4.0}, timeout=8)
    assert r2.status_code == 200
    assert r2.json()["session_hours"] == 4.0
    # cleanup
    requests.put(f"{BASE_URL}/api/security/timeout", headers=_auth(t),
                  json={"session_hours": 8.0}, timeout=8)


def test_timeout_rejects_invalid_range():
    t = _login()
    for bad in (0.1, 25):
        r = requests.put(f"{BASE_URL}/api/security/timeout", headers=_auth(t),
                          json={"session_hours": bad}, timeout=8)
        assert r.status_code in (400, 422), f"{bad} should be rejected"


def test_revoke_others_kills_other_sessions():
    t1 = _login()
    t2 = _login()  # nouvelle session
    # T2 révoque toutes les autres
    r = requests.post(f"{BASE_URL}/api/security/sessions/revoke-others",
                       headers=_auth(t2), timeout=8)
    assert r.status_code == 200 and r.json()["revoked_count"] >= 1
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
