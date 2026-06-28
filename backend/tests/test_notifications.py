"""Tests for the Notifications/Integrations feature.

Covers:
- GET /api/notifications/settings (technician+, secrets MASKED)
- PUT /api/notifications/settings (admin only, secrets encrypted, empty secret preserves previous)
- RBAC: client/readonly blocked, tech can GET+test but not PUT
- POST /api/notifications/test (real send path; 500 on dummy config, 400 when unconfigured)
- POST /api/alerts critical -> dispatched=true; warning -> dispatched=false
"""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "admin": ("admin@mg-vms.com", "Admin@2026"),
    "tech": ("tech@mg-vms.com", "Tech@2026"),
    "client": ("client@mg-vms.com", "Client@2026"),
    "viewer": ("viewer@mg-vms.com", "Viewer@2026"),
}


def _login(role):
    email, pwd = CREDS[role]
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=15)
    assert r.status_code == 200, f"login failed for {role}: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def tokens():
    return {role: _login(role) for role in CREDS}


def H(t):
    return {"Authorization": f"Bearer {t}"}


# ---------- GET /settings: masking + RBAC ----------
class TestSettingsGet:
    def test_admin_get_settings_masked(self, tokens):
        r = requests.get(f"{API}/notifications/settings", headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        for ch in ("smtp", "discord", "telegram"):
            assert ch in d
        # secret values are NEVER returned
        assert d["smtp"].get("password", "") == ""
        assert d["discord"].get("webhook_url", "") == ""
        assert d["telegram"].get("bot_token", "") == ""
        # boolean flags exist
        assert "has_password" in d["smtp"]
        assert "has_webhook_url" in d["discord"]
        assert "has_bot_token" in d["telegram"]

    def test_tech_get_allowed(self, tokens):
        r = requests.get(f"{API}/notifications/settings", headers=H(tokens["tech"]), timeout=10)
        assert r.status_code == 200

    def test_client_get_forbidden(self, tokens):
        r = requests.get(f"{API}/notifications/settings", headers=H(tokens["client"]), timeout=10)
        assert r.status_code == 403

    def test_viewer_get_forbidden(self, tokens):
        r = requests.get(f"{API}/notifications/settings", headers=H(tokens["viewer"]), timeout=10)
        assert r.status_code == 403


# ---------- PUT /settings: admin only + secret persistence ----------
class TestSettingsPut:
    def test_tech_put_forbidden(self, tokens):
        payload = {
            "smtp": {"enabled": False, "host": "", "port": 587, "username": "", "password": "", "from_email": "", "to_email": "", "tls": True},
            "discord": {"enabled": False, "webhook_url": ""},
            "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        }
        r = requests.put(f"{API}/notifications/settings", headers=H(tokens["tech"]), json=payload, timeout=10)
        assert r.status_code == 403

    def test_client_put_forbidden(self, tokens):
        payload = {
            "smtp": {"enabled": False, "host": "", "port": 587, "username": "", "password": "", "from_email": "", "to_email": "", "tls": True},
            "discord": {"enabled": False, "webhook_url": ""},
            "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        }
        r = requests.put(f"{API}/notifications/settings", headers=H(tokens["client"]), json=payload, timeout=10)
        assert r.status_code == 403

    def test_viewer_put_forbidden(self, tokens):
        payload = {
            "smtp": {"enabled": False, "host": "", "port": 587, "username": "", "password": "", "from_email": "", "to_email": "", "tls": True},
            "discord": {"enabled": False, "webhook_url": ""},
            "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        }
        r = requests.put(f"{API}/notifications/settings", headers=H(tokens["viewer"]), json=payload, timeout=10)
        assert r.status_code == 403

    def test_admin_put_with_secrets_then_empty_preserves(self, tokens):
        # Step 1: PUT with real-looking secrets
        payload1 = {
            "smtp": {
                "enabled": True, "host": "smtp.fake-host.invalid", "port": 587,
                "username": "TEST_user@example.com", "password": "TEST_secret_pwd_123",
                "from_email": "TEST_from@example.com", "to_email": "TEST_to@example.com", "tls": True,
            },
            "discord": {"enabled": True, "webhook_url": "https://discord.com/api/webhooks/TEST/abc"},
            "telegram": {"enabled": True, "bot_token": "111111:TEST-BOT-TOKEN", "chat_id": "-100123"},
        }
        r = requests.put(f"{API}/notifications/settings", headers=H(tokens["admin"]), json=payload1, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        # Response is masked: secret fields empty
        assert d["smtp"]["password"] == ""
        assert d["discord"]["webhook_url"] == ""
        assert d["telegram"]["bot_token"] == ""
        # has_* flags true
        assert d["smtp"]["has_password"] is True
        assert d["discord"]["has_webhook_url"] is True
        assert d["telegram"]["has_bot_token"] is True
        # Non-secret persisted
        assert d["smtp"]["host"] == "smtp.fake-host.invalid"
        assert d["smtp"]["username"] == "TEST_user@example.com"
        assert d["telegram"]["chat_id"] == "-100123"

        # Step 2: GET to confirm masking persisted
        r = requests.get(f"{API}/notifications/settings", headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        g = r.json()
        assert g["smtp"]["has_password"] is True
        assert g["discord"]["has_webhook_url"] is True
        assert g["telegram"]["has_bot_token"] is True

        # Step 3: PUT with EMPTY secrets but changed non-secret => previous secrets MUST be preserved
        payload2 = {
            "smtp": {
                "enabled": True, "host": "smtp.fake-host.invalid", "port": 2525,  # port changed
                "username": "TEST_user@example.com", "password": "",  # empty
                "from_email": "TEST_from@example.com", "to_email": "TEST_to2@example.com", "tls": False,
            },
            "discord": {"enabled": True, "webhook_url": ""},
            "telegram": {"enabled": True, "bot_token": "", "chat_id": "-100999"},
        }
        r = requests.put(f"{API}/notifications/settings", headers=H(tokens["admin"]), json=payload2, timeout=15)
        assert r.status_code == 200, r.text
        d2 = r.json()
        assert d2["smtp"]["port"] == 2525
        assert d2["smtp"]["tls"] is False
        assert d2["telegram"]["chat_id"] == "-100999"
        # CRITICAL: previously stored secrets still present
        assert d2["smtp"]["has_password"] is True, "empty password should preserve previous"
        assert d2["discord"]["has_webhook_url"] is True, "empty webhook should preserve previous"
        assert d2["telegram"]["has_bot_token"] is True, "empty bot_token should preserve previous"


# ---------- POST /test: real send path ----------
class TestSendTest:
    def test_test_invalid_channel(self, tokens):
        r = requests.post(f"{API}/notifications/test?channel=invalid", headers=H(tokens["admin"]), timeout=15)
        assert r.status_code == 400
        assert "invalide" in r.json().get("detail", "").lower()

    def test_test_smtp_executes_real_send_path(self, tokens):
        # Settings were just configured with fake but plausible values by previous test class.
        # SMTP must fail (cannot connect) with 500 + French error.
        r = requests.post(f"{API}/notifications/test?channel=smtp", headers=H(tokens["admin"]), timeout=30)
        # 400 only if unconfigured; we configured it -> must be 500 (real send attempted)
        assert r.status_code == 500, f"expected 500 from real send failure, got {r.status_code}: {r.text}"
        detail = r.json().get("detail", "")
        assert "Échec" in detail or "échec" in detail.lower(), f"expected French failure: {detail}"

    def test_test_discord_executes_real_send_path(self, tokens):
        r = requests.post(f"{API}/notifications/test?channel=discord", headers=H(tokens["admin"]), timeout=30)
        assert r.status_code == 500
        assert "Échec" in r.json().get("detail", "")

    def test_test_telegram_executes_real_send_path(self, tokens):
        r = requests.post(f"{API}/notifications/test?channel=telegram", headers=H(tokens["admin"]), timeout=30)
        assert r.status_code == 500
        assert "Échec" in r.json().get("detail", "")

    def test_test_tech_allowed(self, tokens):
        # technician can call test endpoint
        r = requests.post(f"{API}/notifications/test?channel=smtp", headers=H(tokens["tech"]), timeout=30)
        assert r.status_code in (500, 400), r.text  # not 403

    def test_test_client_forbidden(self, tokens):
        r = requests.post(f"{API}/notifications/test?channel=smtp", headers=H(tokens["client"]), timeout=10)
        assert r.status_code == 403

    def test_test_viewer_forbidden(self, tokens):
        r = requests.post(f"{API}/notifications/test?channel=smtp", headers=H(tokens["viewer"]), timeout=10)
        assert r.status_code == 403


# ---------- POST /alerts: dispatched flag ----------
class TestAlertDispatch:
    def test_critical_alert_dispatched_true(self, tokens):
        r = requests.post(f"{API}/alerts", headers=H(tokens["tech"]),
                          json={"message": "TEST_critical_alert", "severity": "critical"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["dispatched"] is True
        assert d["severity"] == "critical"
        assert d["acknowledged"] is False

    def test_warning_alert_dispatched_false(self, tokens):
        r = requests.post(f"{API}/alerts", headers=H(tokens["tech"]),
                          json={"message": "TEST_warning_alert", "severity": "warning"}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["dispatched"] is False

    def test_alert_create_client_forbidden(self, tokens):
        r = requests.post(f"{API}/alerts", headers=H(tokens["client"]),
                          json={"message": "x", "severity": "warning"}, timeout=10)
        assert r.status_code == 403

    def test_alert_create_viewer_forbidden(self, tokens):
        r = requests.post(f"{API}/alerts", headers=H(tokens["viewer"]),
                          json={"message": "x", "severity": "critical"}, timeout=10)
        assert r.status_code == 403


# ---------- Cleanup: reset notifications to disabled empty state so future tests don't dispatch real attempts ----------
class TestCleanup:
    def test_zzz_reset_notifications_config(self, tokens):
        payload = {
            "smtp": {"enabled": False, "host": "", "port": 587, "username": "", "password": "", "from_email": "", "to_email": "", "tls": True},
            "discord": {"enabled": False, "webhook_url": ""},
            "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        }
        r = requests.put(f"{API}/notifications/settings", headers=H(tokens["admin"]), json=payload, timeout=15)
        assert r.status_code == 200
