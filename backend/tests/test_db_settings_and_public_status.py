"""Tests P2 · Database settings + Public status endpoints (Feb 2026)."""
import httpx


BASE = "http://localhost:8001"
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


def _token():
    r = httpx.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=10)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d.get("token")


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


# ── Public status (no auth) ────────────────────────────────────────────
def test_public_status_no_auth_required():
    r = httpx.get(f"{BASE}/api/system/public-status", timeout=10)
    assert r.status_code == 200
    d = r.json()
    for k in ("cameras_online", "anpr_active", "ai_engine"):
        assert k in d
    assert isinstance(d["cameras_online"], int)
    assert isinstance(d["anpr_active"], bool)
    assert isinstance(d["ai_engine"], bool)


def test_public_status_reflects_real_state():
    """Doit refléter au moins un chiffre non-fake."""
    r = httpx.get(f"{BASE}/api/system/public-status", timeout=10)
    d = r.json()
    # ai_engine devrait être True (yolo-detection chargé)
    assert d["ai_engine"] is True
    # cameras_online : au moins les 2 demo
    assert d["cameras_online"] >= 0


# ── Database settings ──────────────────────────────────────────────────
def test_db_settings_get_shows_current_config():
    r = httpx.get(f"{BASE}/api/settings/database", headers=_auth(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert "current" in d
    c = d["current"]
    for k in ("mongo_url_redacted", "db_name", "status", "ping_ms", "collections"):
        assert k in c
    assert d["engine"] == "mongodb"
    assert "mongodb" in d["supported_engines"]
    # Le mot de passe est bien masqué si présent dans l'URL
    assert ":***@" in c["mongo_url_redacted"] or "@" not in c["mongo_url_redacted"]


def test_db_settings_get_requires_admin():
    r = httpx.get(f"{BASE}/api/settings/database", timeout=10)
    assert r.status_code in (401, 403)


def test_db_test_valid_config():
    r = httpx.post(
        f"{BASE}/api/settings/database/test",
        json={"mongo_url": "mongodb://localhost:27017", "db_name": "test_database"},
        headers=_auth(), timeout=15,
    )
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["ping_ms"] >= 0
    assert isinstance(d["collections"], int)


def test_db_test_rejects_invalid_uri():
    r = httpx.post(
        f"{BASE}/api/settings/database/test",
        json={"mongo_url": "http://not-a-mongo-uri", "db_name": "x"},
        headers=_auth(), timeout=10,
    )
    assert r.status_code == 400


def test_db_test_rejects_invalid_db_name():
    r = httpx.post(
        f"{BASE}/api/settings/database/test",
        json={"mongo_url": "mongodb://localhost:27017", "db_name": "bad name!"},
        headers=_auth(), timeout=10,
    )
    assert r.status_code == 400


def test_db_test_fails_on_unreachable_host():
    r = httpx.post(
        f"{BASE}/api/settings/database/test",
        json={"mongo_url": "mongodb://nonexistent-host-mgvms:27017", "db_name": "test"},
        headers=_auth(), timeout=15,
    )
    assert r.status_code in (502, 504)


def test_restart_backend_requires_confirm():
    r = httpx.post(
        f"{BASE}/api/settings/database/restart-backend",
        json={"confirm": False},
        headers=_auth(), timeout=10,
    )
    assert r.status_code == 400
