"""Tests Welcome Center (v0.5.1.a) — HTTP live via REACT_APP_BACKEND_URL.

Suit le pattern des autres tests HTTP du projet (test_v03_endpoints_http.py)
pour éviter les conflits Motor / event-loop de starlette TestClient.
"""
import os
from pathlib import Path

import pytest
import requests


_env = Path("/app/frontend/.env").read_text()
BASE_URL = None
for line in _env.splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL manquant dans /app/frontend/.env"

ADMIN_EMAIL = "admin@mg-vms.com"
ADMIN_PASSWORD = "Admin@2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                        timeout=8)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("access_token") or j.get("token")


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_welcome_summary_shape(token):
    r = requests.get(f"{BASE_URL}/api/welcome/summary", headers=_auth(token), timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("version", "health", "stats", "alerts", "tips", "news", "prefs", "changelog"):
        assert key in body, f"Missing block: {key}"
    h = body["health"]
    assert 0 <= h["score"] <= 100
    for comp in ("gpu", "mongo", "pipeline", "go2rtc", "disk", "cpu", "ram", "cameras", "plugins"):
        assert comp in h["components"]
        assert "score" in h["components"][comp]
        assert h["components"][comp]["status"] in ("ok", "warn", "crit")


def test_welcome_changelog_parses_versions(token):
    r = requests.get(f"{BASE_URL}/api/welcome/changelog?limit=5", headers=_auth(token), timeout=8)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 0
    for e in body["entries"]:
        assert e["version"].startswith("v")


def test_welcome_changelog_since_version_filter(token):
    r1 = requests.get(f"{BASE_URL}/api/welcome/changelog", headers=_auth(token), timeout=8)
    entries = r1.json()["entries"]
    assert len(entries) >= 2
    cut_at = entries[1]["version"]
    r2 = requests.get(f"{BASE_URL}/api/welcome/changelog?since_version={cut_at}",
                       headers=_auth(token), timeout=8)
    filtered = r2.json()["entries"]
    assert all(e["version"] != cut_at for e in filtered)
    assert len(filtered) == 1


def test_welcome_preferences_persist(token):
    r = requests.put(f"{BASE_URL}/api/welcome/preferences",
                      headers=_auth(token),
                      json={"last_seen_version": "v0.4.2", "important_only": True},
                      timeout=8)
    assert r.status_code == 200
    r2 = requests.get(f"{BASE_URL}/api/welcome/preferences", headers=_auth(token), timeout=8)
    assert r2.json()["last_seen_version"] == "v0.4.2"
    # cleanup
    requests.put(f"{BASE_URL}/api/welcome/preferences",
                  headers=_auth(token),
                  json={"last_seen_version": None, "important_only": False},
                  timeout=8)


def test_welcome_news_admin_crud(token):
    payload = {"title": "Test annonce (pytest)", "body": "corps de test",
                "severity": "info", "pinned": True}
    r = requests.post(f"{BASE_URL}/api/welcome/news",
                       headers=_auth(token), json=payload, timeout=8)
    assert r.status_code == 200, r.text
    news_id = r.json()["id"]

    r2 = requests.get(f"{BASE_URL}/api/welcome/news", headers=_auth(token), timeout=8)
    ids = [n["id"] for n in r2.json()["items"]]
    assert news_id in ids

    r3 = requests.delete(f"{BASE_URL}/api/welcome/news/{news_id}",
                          headers=_auth(token), timeout=8)
    assert r3.status_code == 200


def test_welcome_summary_reflects_new_since_last_seen(token):
    r_ch = requests.get(f"{BASE_URL}/api/welcome/changelog", headers=_auth(token), timeout=8)
    entries = r_ch.json()["entries"]
    older = entries[-1]["version"]
    requests.put(f"{BASE_URL}/api/welcome/preferences",
                  headers=_auth(token),
                  json={"last_seen_version": older},
                  timeout=8)
    r = requests.get(f"{BASE_URL}/api/welcome/summary", headers=_auth(token), timeout=10)
    ch = r.json()["changelog"]
    assert ch["has_new_version"] is True
    assert len(ch["new_since_last_seen"]) >= 1
    requests.put(f"{BASE_URL}/api/welcome/preferences",
                  headers=_auth(token),
                  json={"last_seen_version": None},
                  timeout=8)


def test_welcome_requires_auth():
    r = requests.get(f"{BASE_URL}/api/welcome/summary", timeout=8)
    assert r.status_code in (401, 403)


def test_welcome_news_denies_non_admin(token):
    # Sans être admin on ne peut pas créer/supprimer, on ne teste que sans token
    r = requests.post(f"{BASE_URL}/api/welcome/news",
                       json={"title": "x", "body": "y", "severity": "info"},
                       timeout=8)
    assert r.status_code in (401, 403)
