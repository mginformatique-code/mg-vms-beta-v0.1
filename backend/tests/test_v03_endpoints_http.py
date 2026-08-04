"""v0.3 · Tests HTTP end-to-end sur le backend externe.

Vérifie via l'URL publique REACT_APP_BACKEND_URL :
 - login admin
 - endpoints diagnostics : anpr-tracker, streaming-metrics, pipeline-metrics
 - auth requise (401 sans Bearer)
 - non-régression : plugins/bus (50), plugins/tracking/config
 - modèle CameraInput.ai_rtsp_url (POST /api/cameras)
"""
import os
import uuid
from pathlib import Path

import pytest
import requests

# Lecture directe du .env frontend (pas de default → fail-fast)
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
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    assert "access_token" in data, f"no access_token: {data}"
    return data["access_token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


class TestLogin:
    def test_admin_login_ok(self, token):
        assert isinstance(token, str) and len(token) > 20


class TestDiagnosticsAuthRequired:
    """401 sans Bearer sur les 3 endpoints diagnostics v0.3."""

    @pytest.mark.parametrize("path", [
        "/api/diagnostics/anpr-tracker",
        "/api/diagnostics/streaming-metrics",
        "/api/diagnostics/pipeline-metrics",
    ])
    def test_requires_auth(self, path):
        r = requests.get(f"{BASE_URL}{path}", timeout=10)
        assert r.status_code in (401, 403), f"{path} attendu 401/403, got {r.status_code}"


class TestAnprTrackerEndpoint:
    def test_snapshot_shape(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/diagnostics/anpr-tracker",
                         headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "config" in data
        assert "cameras" in data
        cfg = data["config"]
        for k in ("min_readings", "lost_cycles", "min_confidence"):
            assert k in cfg, f"config manque {k}"
        assert isinstance(data["cameras"], dict)


class TestStreamingMetricsEndpoint:
    def test_shape(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/diagnostics/streaming-metrics",
                         headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "go2rtc_reachable" in data
        assert isinstance(data["go2rtc_reachable"], bool)
        assert "streams" in data
        assert isinstance(data["streams"], dict)


class TestPipelineMetricsEndpoint:
    def test_shape_no_regression(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/diagnostics/pipeline-metrics",
                         headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "cameras" in data
        # Snapshot cameras est dict; les entrées peuvent contenir stages détaillés
        assert isinstance(data["cameras"], dict)


class TestPluginsBusRegression:
    def test_plugins_bus_still_50(self, auth_headers):
        # Route confirmée /api/plugins/bus
        r = requests.get(f"{BASE_URL}/api/plugins/bus",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        # Format actuel: {"entries":[...], "counts": {"total": 50, ...}}
        if isinstance(data, dict):
            entries = data.get("entries") or data.get("plugins") or []
            total = (data.get("counts") or {}).get("total", len(entries))
        else:
            entries = data
            total = len(entries)
        assert total >= 50, f"attendu >=50 plugins, got total={total} entries={len(entries)}"

    def test_plugins_tracking_config(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/plugins/tracking/config",
                         headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data.get("enabled") is True


class TestCameraAiRtspUrl:
    def test_create_camera_with_ai_rtsp_url(self, auth_headers):
        # Récupère un site valide (site_id doit exister en DB)
        rs = requests.get(f"{BASE_URL}/api/sites", headers=auth_headers, timeout=10)
        assert rs.status_code == 200, rs.text[:200]
        sites = rs.json()
        assert sites, "Aucun site en DB — impossible de tester create camera"
        site_id = sites[0]["id"]

        cam_name = f"TEST_v03_{uuid.uuid4().hex[:8]}"
        payload = {
            "name": cam_name,
            "ip": "10.0.0.99",
            "site_id": site_id,
            "rtsp_url": "rtsp://10.0.0.99:554/live",
            "ai_rtsp_url": "rtsp://10.0.0.99:554/ai-substream",
            "allow_rtsp_override": True,
        }
        r = requests.post(f"{BASE_URL}/api/cameras",
                          headers=auth_headers, json=payload, timeout=60)
        assert r.status_code in (200, 201), f"POST /api/cameras failed: {r.status_code} {r.text[:300]}"
        created = r.json()
        cam_id = created.get("id")
        assert cam_id, f"pas d'id dans response: {created}"

        # Vérifie persistance via GET
        rg = requests.get(f"{BASE_URL}/api/cameras/{cam_id}",
                          headers=auth_headers, timeout=10)
        assert rg.status_code == 200
        fetched = rg.json()
        assert fetched.get("ai_rtsp_url") == "rtsp://10.0.0.99:554/ai-substream", \
            f"ai_rtsp_url non persisté: {fetched}"

        # Cleanup
        requests.delete(f"{BASE_URL}/api/cameras/{cam_id}",
                        headers=auth_headers, timeout=10)
