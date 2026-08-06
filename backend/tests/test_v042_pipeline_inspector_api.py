"""API-driven tests for MG-VMS v0.4.2 pipeline inspector + regressions.

Uses single login (rate-limit 30 /60s) and validates:
- /api/diagnostics/pipeline-inspector (structure, stages, runtime)
- reset endpoint
- Regressions: pipeline-v2, pipeline-v2/stats, anpr-quality, ai-health, pipeline-metrics
- Downstream: /api/events, /api/plates
- /api/ai/debug snapshot
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://video-command-6.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@mg-vms.com"
ADMIN_PASS = "Admin@2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=15,
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"No access_token in response: {data}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


CAMERA_ID = "demo-cam-002"


class TestPipelineInspector:
    def test_get_inspector_structure(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/diagnostics/pipeline-inspector", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "cameras" in data
        assert "system" in data
        assert "stage_order" in data
        assert "runtime" in data
        sys = data["system"]
        for k in ("cpu_percent", "ram", "uptime_s"):
            assert k in sys, f"missing system.{k}: {list(sys.keys())}"
        # gpu key may be None on CPU-only but must exist
        assert "gpu" in sys

    def test_camera_stages_present(self, auth_headers):
        # give worker some time to run
        time.sleep(6)
        r = requests.get(f"{BASE_URL}/api/diagnostics/pipeline-inspector", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        cams = data.get("cameras", {})
        assert CAMERA_ID in cams, f"{CAMERA_ID} not in cameras: {list(cams.keys())}"
        cam = cams[CAMERA_ID]
        assert "stages" in cam
        assert "meta" in cam
        # tracker meta - set only when detections happen; demo-cam-002 (testsrc2) rarely detects
        meta = cam.get("meta", {})
        tracker_val = meta.get("tracker")
        assert tracker_val in (None, "bytetrack"), f"unexpected tracker meta: {meta}"
        stages = cam["stages"]
        expected = ["fetch", "decode", "motion", "yolo", "tracking", "roi"]
        for stg in expected:
            assert stg in stages, f"stage {stg} missing: {list(stages.keys())}"
            s = stages[stg]
            assert s.get("calls", 0) > 0, f"stage {stg} has 0 calls: {s}"
            assert "avg_ms" in s
        # yolo timing sanity (broad)
        yolo_avg = stages["yolo"].get("avg_ms", 0)
        assert 5 <= yolo_avg <= 2000, f"yolo avg_ms out of range: {yolo_avg}"

    def test_runtime_workers_and_trackers(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/diagnostics/pipeline-inspector", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        rt = r.json().get("runtime", {})
        workers = rt.get("workers", [])
        trackers = rt.get("trackers", {})
        # workers may be list of ids or list of dicts
        worker_ids = []
        for w in workers:
            worker_ids.append(w if isinstance(w, str) else (w.get("camera_id") or w.get("id")))
        assert CAMERA_ID in worker_ids, f"worker for {CAMERA_ID} not present: {workers}"
        # trackers: expect one per camera when detections have occurred; may be empty for testsrc2
        if isinstance(trackers, dict) and trackers:
            if CAMERA_ID in trackers:
                t = trackers[CAMERA_ID]
                name = t if isinstance(t, str) else (t.get("name") or t.get("kind") or t.get("type") or t.get("algo"))
                assert name and "bytetrack" in str(name).lower(), f"tracker not bytetrack: {t}"

    def test_z_reset_endpoint(self, auth_headers):
        r = requests.post(
            f"{BASE_URL}/api/diagnostics/pipeline-inspector/reset",
            params={"camera_id": CAMERA_ID},
            headers=auth_headers,
            timeout=15,
        )
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body.get("ok") is True, body
        # After reset, calls should drop; then may grow again but should be low right after
        time.sleep(3)
        r2 = requests.get(f"{BASE_URL}/api/diagnostics/pipeline-inspector", headers=auth_headers, timeout=15)
        assert r2.status_code == 200
        cam = r2.json().get("cameras", {}).get(CAMERA_ID, {})
        stages = cam.get("stages", {})
        # After reset+3s, worker has ticked at least once (interval=2s) - counts are lower than pre-reset
        assert "fetch" in stages, f"stages empty after reset+3s: {stages}"
        assert stages["fetch"].get("calls", 0) < 20, f"reset didn't zero counters: {stages['fetch']}"


class TestRegressionEndpoints:
    def test_pipeline_v2(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/diagnostics/pipeline-v2", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:200]

    def test_pipeline_v2_stats(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/diagnostics/pipeline-v2/stats", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:200]

    def test_anpr_quality(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/diagnostics/anpr-quality", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:200]

    def test_ai_health(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/diagnostics/ai-health", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert data.get("yolo_loaded") is True, data
        assert data.get("alpr_loaded") is True, data
        assert data.get("loop_alive") is True, data

    def test_pipeline_metrics(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/diagnostics/pipeline-metrics", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:200]


class TestDownstream:
    def test_events(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/events", params={"limit": 5}, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:200]

    def test_plates(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/plates", params={"limit": 5}, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:200]


class TestAiDebug:
    def test_ai_debug_snapshot(self, auth_headers):
        # Try camera-specific first
        r = requests.get(f"{BASE_URL}/api/ai/debug/{CAMERA_ID}", headers=auth_headers, timeout=15)
        if r.status_code == 404:
            r = requests.get(f"{BASE_URL}/api/ai/debug", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        # snapshot should contain something meaningful; be tolerant to shape
        assert isinstance(data, dict) and len(data) > 0
