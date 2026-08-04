"""Integration HTTP tests P0 · Pipeline realtime refactor (Feb 2026).

Tests against the external REACT_APP_BACKEND_URL:
- /api/auth/login (returns access_token)
- /api/diagnostics/pipeline-metrics (auth-protected, structure)
- /api/plugins/tracking/config GET/PUT (ByteTrack config with clamping)
- Verify router ordering (tracking/config not intercepted by generic /plugins/{name}/config)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://video-command-6.preview.emergentagent.com",
).rstrip("/")

ADMIN_EMAIL = "admin@mg-vms.com"
ADMIN_PASSWORD = "Admin@2026"

STAGES_EXPECTED = ("fetch_ms", "yolo_ms", "tracking_ms", "alpr_ms", "realtime_ms", "downstream_ms")


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data, f"missing access_token in {data}"
    assert isinstance(data["access_token"], str) and len(data["access_token"]) > 10
    return data["access_token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


class TestAuth:
    def test_login_success(self, token):
        assert token

    def test_login_wrong_password(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": "wrong-password-xyz"},
            timeout=15,
        )
        assert r.status_code in (400, 401, 403), f"expected auth failure, got {r.status_code}"


class TestPipelineMetricsEndpoint:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/diagnostics/pipeline-metrics", timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403 without token, got {r.status_code}"

    def test_returns_structure(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/diagnostics/pipeline-metrics",
            headers=auth_headers,
            timeout=15,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        data = r.json()
        # Response should be a dict (possibly wrapper), per-camera metrics
        assert isinstance(data, (dict, list)), f"unexpected type: {type(data)}"
        # Look for a per-camera dict — either directly or under a key like 'metrics' / 'cameras'
        payload = data
        if isinstance(data, dict) and not any(
            isinstance(v, dict) and "stages" in v for v in data.values()
        ):
            # maybe wrapped
            for k in ("metrics", "cameras", "data", "pipeline"):
                if k in data and isinstance(data[k], dict):
                    payload = data[k]
                    break
        # If no cameras are running, dict may be empty — that's OK, endpoint just needs to respond
        if isinstance(payload, dict) and payload:
            # pick first camera and verify structure
            first_cam = next(iter(payload.values()))
            if isinstance(first_cam, dict):
                assert "stages" in first_cam or any(
                    s in first_cam for s in STAGES_EXPECTED
                ), f"missing stages: keys={list(first_cam.keys())}"
                # fps_5s, drops_5s should be present
                for expected in ("fps_5s", "drops_5s"):
                    assert expected in first_cam, f"missing {expected} in {list(first_cam.keys())}"


class TestByteTrackConfig:
    def test_get_returns_defaults(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/plugins/tracking/config",
            headers=auth_headers,
            timeout=15,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        cfg = r.json()
        assert isinstance(cfg, dict), f"expected dict, got {type(cfg)}"
        # Router ordering: if it were intercepted by /plugins/{name}/config, we'd get
        # a very different response (empty {} or plugin-generic shape). Verify BT keys:
        expected_keys = {
            "enabled",
            "track_thresh",
            "match_thresh",
            "track_buffer",
            "min_box_area",
            "id_persist_seconds",
        }
        assert expected_keys.issubset(set(cfg.keys())), (
            f"router order likely wrong — expected ByteTrack keys, got {list(cfg.keys())}"
        )
        assert cfg["enabled"] is True

    def test_put_and_reread(self, auth_headers):
        # Set custom valid values
        payload = {
            "enabled": True,
            "track_thresh": 0.35,
            "match_thresh": 0.75,
            "track_buffer": 90,
            "min_box_area": 150,
            "id_persist_seconds": 180,
        }
        r = requests.put(
            f"{BASE_URL}/api/plugins/tracking/config",
            headers=auth_headers,
            json=payload,
            timeout=15,
        )
        assert r.status_code == 200, f"PUT failed: {r.status_code} {r.text[:300]}"
        saved = r.json()
        for k, v in payload.items():
            assert saved[k] == v, f"{k}: expected {v}, got {saved.get(k)}"

        # Read back
        r2 = requests.get(
            f"{BASE_URL}/api/plugins/tracking/config",
            headers=auth_headers,
            timeout=15,
        )
        assert r2.status_code == 200
        cfg = r2.json()
        for k, v in payload.items():
            assert cfg[k] == v, f"persistence: {k} expected {v}, got {cfg.get(k)}"

    def test_put_clamps_out_of_bounds(self, auth_headers):
        payload = {
            "enabled": True,
            "track_thresh": 2.0,     # → clamped to 0.9
            "match_thresh": 0.1,     # → clamped to 0.5
            "track_buffer": 9999,    # → clamped to 300
            "min_box_area": 100,
            "id_persist_seconds": 5000,  # → clamped to 600
        }
        r = requests.put(
            f"{BASE_URL}/api/plugins/tracking/config",
            headers=auth_headers,
            json=payload,
            timeout=15,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        saved = r.json()
        assert saved["track_thresh"] == 0.9
        assert saved["match_thresh"] == 0.5
        assert saved["track_buffer"] == 300
        assert saved["id_persist_seconds"] == 600

    def test_restore_defaults(self, auth_headers):
        """Cleanup — restore ByteTrack defaults."""
        defaults = {
            "enabled": True,
            "track_thresh": 0.25,
            "match_thresh": 0.85,
            "track_buffer": 60,
            "min_box_area": 100,
            "id_persist_seconds": 120,
        }
        r = requests.put(
            f"{BASE_URL}/api/plugins/tracking/config",
            headers=auth_headers,
            json=defaults,
            timeout=15,
        )
        assert r.status_code == 200


class TestPipelineArchitectureIntrospection:
    """Static introspection of ai_engine source (matches unit tests)."""

    def test_process_camera_uses_create_task(self):
        import inspect
        import sys
        sys.path.insert(0, "/app/backend")
        from ai_engine import _process_camera  # type: ignore

        src = inspect.getsource(_process_camera)
        assert "asyncio.create_task" in src, "downstream must be fire-and-forget"
        assert "_process_downstream" in src


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
