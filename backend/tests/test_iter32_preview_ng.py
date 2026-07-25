"""Iteration 32 — Preview NG v2.30 : chantiers A (Plugin Manager PoC) + B (Fernet secrets) + D (URL versioning).

Vérifie que :
1. GET /api/plugins retourne la liste des 6 plugins bundle avec état runtime.
2. Chiffrement Fernet des credentials caméra : encrypt/decrypt cycle + compat legacy + idempotence.
3. URL versioning `/api/v1/...` fonctionne en parallèle de `/api/...` avec header d'alias.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://video-command-6.preview.emergentagent.com",
).rstrip("/")
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class TestChantierA_PluginManagerPoC:
    def test_plugins_endpoint_lists_bundle(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/plugins",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "plugins" in data
        assert "core_version" in data
        assert data["core_version"].startswith("2.30")
        assert data["plugin_manager_version"] == "0.1.0"
        # 6 plugins bundle attendus
        names = {p["name"] for p in data["plugins"]}
        expected = {
            "yolo-detection", "fast-alpr", "smtp-notifier",
            "discord-notifier", "telegram-notifier", "zone-analytics",
        }
        assert expected == names, f"plugins bundle attendus manquants : {expected - names}"

    def test_plugin_detail(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/plugins/yolo-detection",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert r.status_code == 200
        p = r.json()
        assert p["name"] == "yolo-detection"
        assert p["interface"] == "FrameAnalyzer"
        assert "camera.frame.read" in p["capabilities"]
        # état runtime synchronisé depuis _ai_health
        assert p["state"] in ("running", "crashed", "loaded")

    def test_plugin_not_found(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/plugins/inexistant-xyz",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert r.status_code == 404


class TestChantierB_FernetSecrets:
    def setup_method(self):
        import sys
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        from dotenv import load_dotenv
        load_dotenv(os.path.join(backend_dir, ".env"))

    def test_encrypt_decrypt_cycle(self):
        from crypto_utils import encrypt_secret, decrypt_secret
        original = "SuperSecret!2026"
        encrypted = encrypt_secret(original)
        assert encrypted.startswith("gAAAAA"), "Token Fernet doit commencer par gAAAAA"
        assert encrypted != original
        assert decrypt_secret(encrypted) == original

    def test_legacy_compat(self):
        """Un mot de passe en clair (legacy pré-migration) est renvoyé tel quel."""
        from crypto_utils import decrypt_secret
        assert decrypt_secret("cleartext_legacy") == "cleartext_legacy"
        assert decrypt_secret("") == ""

    def test_idempotent_encryption(self):
        """encrypt_secret est idempotent : ne re-chiffre pas si déjà chiffré."""
        from crypto_utils import encrypt_secret
        original = "test"
        enc1 = encrypt_secret(original)
        enc2 = encrypt_secret(enc1)
        assert enc1 == enc2, "Double chiffrement doit être évité"

    def test_is_encrypted_detection(self):
        from crypto_utils import encrypt_secret, is_encrypted
        assert is_encrypted(encrypt_secret("x"))
        assert not is_encrypted("plaintext")
        assert not is_encrypted("")


class TestChantierD_URLVersioning:
    def test_v1_alias_works(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/v1/plugins",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        # Header d'alias présent
        assert r.headers.get("X-API-Version-Alias") == "v1"
        # Même contenu que /api/plugins
        data = r.json()
        assert "plugins" in data
        assert len(data["plugins"]) == 6

    def test_v1_alias_ai_health(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/v1/diagnostics/ai-health",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert r.status_code == 200
        assert r.headers.get("X-API-Version-Alias") == "v1"
        assert "yolo_loaded" in r.json()

    def test_legacy_path_still_works(self, admin_token):
        """Compat descendante : `/api/*` sans version fonctionne toujours."""
        r = requests.get(
            f"{BASE_URL}/api/plugins",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert r.status_code == 200
        # Pas de header alias (path legacy, pas passé par le middleware)
        assert "X-API-Version-Alias" not in r.headers
