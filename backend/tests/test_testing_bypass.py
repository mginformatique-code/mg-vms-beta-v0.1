"""Vérifie que `TESTING=1` bypasse totalement rate-limit + brute-force.

Sans ce bypass, les tests parallèles se bloquaient mutuellement (429/423)
sur `/api/auth/login`. Le fix est encodé dans security.py + auth.py, et
conftest.py force `TESTING=1` pour la campagne pytest.
"""
import os

import asyncio

import pytest


def test_testing_flag_active():
    """conftest.py doit forcer TESTING=1 dès l'import."""
    assert os.environ.get("TESTING") == "1"


def test_security_module_bypass_flag():
    from security import _testing_mode
    assert _testing_mode() is True


def test_auth_module_bypass_flag():
    from auth import _testing_mode
    assert _testing_mode() is True


def test_security_middleware_skips_when_testing(monkeypatch):
    """Sans TESTING, une salve > limite doit 429 ; avec TESTING, jamais."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from security import SecurityMiddleware, SENSITIVE_LIMITS

    app = FastAPI()
    app.add_middleware(SecurityMiddleware)

    @app.post("/api/auth/login")
    def _login():
        return {"ok": True}

    max_req = SENSITIVE_LIMITS["/api/auth/login"][0]
    client = TestClient(app)

    # TESTING=1 : peut envoyer beaucoup plus que la limite
    for _ in range(max_req + 5):
        r = client.post("/api/auth/login", json={})
        assert r.status_code == 200, f"TESTING=1 bypass cassé : {r.status_code}"

    # Sans TESTING : au-delà de la limite → 429
    monkeypatch.delenv("TESTING", raising=False)
    saw_429 = False
    for _ in range(max_req + 5):
        r = client.post("/api/auth/login", json={})
        if r.status_code == 429:
            saw_429 = True
            break
    assert saw_429, "SecurityMiddleware ne rate-limite plus sans TESTING=1"


def test_auth_lockout_bypassed_when_testing():
    """`_check_lockout` et `_register_failure` doivent no-op en test."""
    from auth import _check_lockout, _register_failure

    async def _run():
        await _check_lockout("test-bypass:foo@example.com")
        n = await _register_failure("test-bypass:foo@example.com")
        assert n == 0

    asyncio.run(_run())
