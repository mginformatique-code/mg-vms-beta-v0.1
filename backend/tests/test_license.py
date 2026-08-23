"""Tests — vérification de licence Ed25519 (v3.3, août 2026)."""
import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import routes.license as license_mod

BASE = "http://localhost:8001"
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


def _token():
    r = httpx.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=10)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d.get("token")


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _pub_b64(priv: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode()


def _sign_test_license(priv: Ed25519PrivateKey, **overrides) -> str:
    payload = {
        "license_id": "test-license-id",
        "client": "Test Client",
        "type": "gold",
        "issued_at": "2026-01-01T00:00:00+00:00",
        "expires_at": None,
        **overrides,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    signature = priv.sign(payload_bytes)
    return f"{_b64u(payload_bytes)}.{_b64u(signature)}"


# ── verify_license_key (unit, hors serveur) ─────────────────────────────
def test_verify_license_key_accepts_valid_signature(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    monkeypatch.setattr(license_mod, "LICENSE_PUBLIC_KEY_B64", _pub_b64(priv))

    key = _sign_test_license(priv)
    payload = license_mod.verify_license_key(key)
    assert payload["client"] == "Test Client"
    assert payload["type"] == "gold"


def test_verify_license_key_rejects_wrong_signer(monkeypatch):
    # La clé publique configurée ne correspond PAS à la clé qui a signé -> invalide
    other_priv = Ed25519PrivateKey.generate()
    monkeypatch.setattr(license_mod, "LICENSE_PUBLIC_KEY_B64", _pub_b64(other_priv))

    signing_priv = Ed25519PrivateKey.generate()
    key = _sign_test_license(signing_priv)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        license_mod.verify_license_key(key)
    assert exc.value.status_code == 400


def test_verify_license_key_rejects_malformed_key():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        license_mod.verify_license_key("not-a-valid-license-key")
    assert exc.value.status_code == 400


def test_verify_license_key_rejects_unknown_type(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    monkeypatch.setattr(license_mod, "LICENSE_PUBLIC_KEY_B64", _pub_b64(priv))

    key = _sign_test_license(priv, type="not-a-real-type")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        license_mod.verify_license_key(key)
    assert exc.value.status_code == 400


# ── Endpoints (intégration, via serveur en cours d'exécution) ──────────
def test_license_status_requires_admin():
    r = httpx.get(f"{BASE}/api/license/status", timeout=10)
    assert r.status_code in (401, 403)


def test_license_activate_requires_admin():
    r = httpx.post(f"{BASE}/api/license/activate", json={"license_key": "x.y"}, timeout=10)
    assert r.status_code in (401, 403)


def test_license_activate_rejects_garbage_key():
    r = httpx.post(f"{BASE}/api/license/activate", json={"license_key": "garbage"}, headers=_auth(), timeout=10)
    assert r.status_code == 400


def test_license_status_shape():
    r = httpx.get(f"{BASE}/api/license/status", headers=_auth(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    for k in ("active", "expired", "license"):
        assert k in d
