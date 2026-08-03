"""Tests P2 · Fernet secrets dans plugin_config_store (Feb 2026)."""
import json
import os

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


def test_sensitive_fields_encrypted_on_disk(tmp_path, monkeypatch):
    """Le store chiffre les champs sensibles à l'écriture."""
    from plugin_manager.config_store import PluginConfigStore, _is_sensitive
    from crypto_utils import is_encrypted, decrypt_secret

    p = tmp_path / "cfg.json"
    store = PluginConfigStore(path=p)

    store.set("test-plugin", {
        "api_token": "SECRET_ABC",
        "password": "hunter2",
        "webhook_url": "https://hooks.slack.com/xyz",
        "regions": ["fr"],
        "gpu": True,
    })

    # Fichier disque : les 3 sensibles sont chiffrés
    raw = json.loads(p.read_text())["test-plugin"]
    assert is_encrypted(raw["api_token"])
    assert is_encrypted(raw["password"])
    assert is_encrypted(raw["webhook_url"])
    # Non sensibles restent en clair
    assert raw["regions"] == ["fr"]
    assert raw["gpu"] is True

    # Décryptage transparent au .get()
    cfg = store.get("test-plugin")
    assert cfg["api_token"] == "SECRET_ABC"
    assert cfg["password"] == "hunter2"
    assert cfg["webhook_url"] == "https://hooks.slack.com/xyz"


def test_is_sensitive_matches_expected_keys():
    from plugin_manager.config_store import _is_sensitive
    for k in ("password", "api_token", "SECRET_KEY", "webhookUrl",
              "bot_token", "smtp_password", "Api_Key"):
        assert _is_sensitive(k), f"{k} devrait être sensible"
    for k in ("regions", "gpu", "lang", "confidence"):
        assert not _is_sensitive(k), f"{k} ne devrait pas être sensible"


def test_reencrypt_idempotent():
    """Une valeur déjà chiffrée n'est pas re-chiffrée deux fois."""
    from plugin_manager.config_store import _encrypt_config
    from crypto_utils import is_encrypted, decrypt_secret

    once = _encrypt_config({"api_token": "abc"})
    twice = _encrypt_config(once)
    assert once["api_token"] == twice["api_token"]  # même token
    assert decrypt_secret(twice["api_token"]) == "abc"


def test_api_returns_masked_secret():
    """GET /api/plugins/{name}/config masque les secrets en `***`."""
    # Set a secret
    r = httpx.put(f"{BASE}/api/plugins/plate-recognizer/config",
                   json={"api_token": "SECRET_TEST_123", "regions": ["us"]},
                   headers=_auth(), timeout=10)
    assert r.status_code == 200

    r = httpx.get(f"{BASE}/api/plugins/plate-recognizer/config",
                   headers=_auth(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["config"]["api_token"] == "***"
    assert d["config"]["regions"] == ["us"]


def test_api_preserves_secret_on_partial_update():
    """PUT avec `api_token: '***'` doit préserver la valeur existante."""
    # Init
    r = httpx.put(f"{BASE}/api/plugins/plate-recognizer/config",
                   json={"api_token": "ORIG_TOKEN", "regions": ["fr"]},
                   headers=_auth(), timeout=10)
    assert r.status_code == 200

    # Update partiel avec sentinel `***`
    r = httpx.put(f"{BASE}/api/plugins/plate-recognizer/config",
                   json={"api_token": "***", "regions": ["fr", "de"]},
                   headers=_auth(), timeout=10)
    assert r.status_code == 200

    # Le token n'a pas été écrasé
    disk = json.loads(open("/app/backend/data/plugin_configs.json").read())
    from crypto_utils import decrypt_secret
    on_disk_token = disk["plate-recognizer"]["api_token"]
    assert decrypt_secret(on_disk_token) == "ORIG_TOKEN"
