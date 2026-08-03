"""Tests smoke pour /api/diagnostics/health-dashboard."""
import os
import sys
import pytest
import httpx

sys.path.insert(0, "/app/backend")


def _get_token():
    r = httpx.post("http://localhost:8001/api/auth/login",
                   json={"email": "admin@mg-vms.com", "password": "Admin@2026"},
                   timeout=10)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d.get("token")


def test_health_dashboard_endpoint_returns_all_sections():
    token = _get_token()
    r = httpx.get("http://localhost:8001/api/diagnostics/health-dashboard",
                   headers={"Authorization": f"Bearer {token}"}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for section in ("system", "mongo", "ai", "plugins", "cameras", "recorder", "timestamp"):
        assert section in d, f"Section '{section}' manquante"
    # System doit avoir les métriques attendues
    assert "cpu_percent" in d["system"]
    assert "ram_percent" in d["system"]
    assert "disk_percent" in d["system"]
    assert "uptime_seconds" in d["system"]
    # Mongo doit ping OK
    assert d["mongo"]["status"] == "ok"
    assert "collections" in d["mongo"]
    # Plugins doit avoir les counts
    assert "total" in d["plugins"]
    assert "dispatchable" in d["plugins"]
    assert d["plugins"]["total"] >= 40  # on a 49 plugins


def test_camera_diagnostic_events_endpoint():
    token = _get_token()
    r = httpx.get("http://localhost:8001/api/diagnostics/camera/nonexistent/events",
                   headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["camera_id"] == "nonexistent"
    assert d["count"] == 0
    assert d["events"] == []
