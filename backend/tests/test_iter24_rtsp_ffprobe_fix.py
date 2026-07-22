"""Iteration 24 — BUG FIX RTSP ffprobe fragment stripping + regression suite.

Bug: _build_rtsp_url appends #transport=tcp (go2rtc fragment) to URL; ffprobe
interprets '#' as part of path → 404 Stream Not Found. Fix: _strip_go2rtc_fragments
removes '#...' before calling ffprobe.
"""
import os
import io
import re
import time
import pytest
import requests

def _read_env(path, key):
    try:
        with open(path) as f:
            for ln in f:
                if ln.startswith(key + "="):
                    return ln.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return None

BASE = (os.environ.get("REACT_APP_BACKEND_URL")
        or _read_env("/app/frontend/.env", "REACT_APP_BACKEND_URL")).rstrip("/")

# Load backend .env so `from streaming import ...` works (needs MONGO_URL, DB_NAME).
for _k in ("MONGO_URL", "DB_NAME"):
    if not os.environ.get(_k):
        v = _read_env("/app/backend/.env", _k)
        if v:
            os.environ[_k] = v
import sys
sys.path.insert(0, "/app/backend")
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


# ── Auth fixture ──────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════════════
# 1) UNIT-LEVEL tests on internal helpers (import backend directly)
# ═══════════════════════════════════════════════════════════════════════════
class TestHelpers:
    def test_strip_fragments_removes_transport(self):
        from streaming import _strip_go2rtc_fragments
        assert _strip_go2rtc_fragments("rtsp://x/y#transport=tcp") == "rtsp://x/y"

    def test_strip_fragments_no_hash(self):
        from streaming import _strip_go2rtc_fragments
        assert _strip_go2rtc_fragments("rtsp://x/y") == "rtsp://x/y"

    def test_strip_fragments_empty(self):
        from streaming import _strip_go2rtc_fragments
        assert _strip_go2rtc_fragments("") == ""

    def test_strip_fragments_multiple(self):
        from streaming import _strip_go2rtc_fragments
        # everything after first # removed
        assert _strip_go2rtc_fragments("rtsp://x/y#transport=tcp#video=h264") == "rtsp://x/y"

    def test_build_rtsp_url_still_adds_fragment(self):
        """REGRESSION : _build_rtsp_url MUST still append #transport=tcp (go2rtc needs it)."""
        from streaming import _build_rtsp_url
        out = _build_rtsp_url({
            "rtsp_url": "rtsp://ip:554/foo",
            "username": "u", "password": "p",
            "rtsp_transport": "tcp"
        })
        assert out == "rtsp://u:p@ip:554/foo#transport=tcp", f"got {out}"

    def test_build_rtsp_url_udp_fragment(self):
        from streaming import _build_rtsp_url
        out = _build_rtsp_url({
            "rtsp_url": "rtsp://ip:554/foo",
            "username": "u", "password": "p",
            "rtsp_transport": "udp"
        })
        assert out.endswith("#transport=udp")


# ═══════════════════════════════════════════════════════════════════════════
# 2) BUG FIX CRITIQUE : /api/cameras/test-connectivity — RTSP demo cam
# ═══════════════════════════════════════════════════════════════════════════
class TestConnectivityBugFix:
    def test_rtsp_demo_cam_validated(self, h):
        """The main fix : test-connectivity on demo-cam-001 must now succeed
        with codec=H264, resolution=1280x720. Before fix: rtsp_url_validated=false."""
        payload = {
            "mode": "rtsp",
            "ip": "127.0.0.1",
            "rtsp_port": 8554,
            "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
            "username": "",
            "password": "",
            "rtsp_transport": "tcp",
            "preferred_codec": "auto"
        }
        r = requests.post(f"{BASE}/api/cameras/test-connectivity",
                          json=payload, headers=h, timeout=60)
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:500]}"
        data = r.json()

        assert data.get("rtsp_url_validated") is True, \
            f"BUG NOT FIXED — rtsp_url_validated=False. debug_attempts={data.get('debug_attempts')}"
        assert data.get("codec") == "H264", f"codec={data.get('codec')}"
        assert data.get("resolution") == "1280x720", f"resolution={data.get('resolution')}"

    def test_password_never_leaked_in_debug(self, h):
        """REGRESSION : passwords in debug_attempts must be masked (******)."""
        payload = {
            "mode": "rtsp",
            "ip": "127.0.0.1",
            "rtsp_port": 8554,
            "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
            "username": "admin",
            "password": "SuperSecret42!",
            "rtsp_transport": "tcp",
            "preferred_codec": "auto"
        }
        r = requests.post(f"{BASE}/api/cameras/test-connectivity",
                          json=payload, headers=h, timeout=60)
        assert r.status_code == 200
        body_txt = r.text
        assert "SuperSecret42!" not in body_txt, "PASSWORD LEAKED in response body!"
        # debug_attempts should have masked url
        attempts = r.json().get("debug_attempts") or []
        for a in attempts:
            s = str(a)
            assert "SuperSecret42!" not in s
            if "admin:" in s:
                assert "******" in s, f"password not masked in attempt: {a}"


# ═══════════════════════════════════════════════════════════════════════════
# 3) LOGGING : backend.err.log must show the traced steps
# ═══════════════════════════════════════════════════════════════════════════
class TestLogs:
    def test_logs_contain_trace_steps(self, h):
        # Trigger a test-connectivity call
        payload = {
            "mode": "rtsp", "ip": "127.0.0.1", "rtsp_port": 8554,
            "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
            "rtsp_transport": "tcp", "preferred_codec": "auto"
        }
        r = requests.post(f"{BASE}/api/cameras/test-connectivity",
                          json=payload, headers=h, timeout=60)
        assert r.status_code == 200
        time.sleep(1.5)

        # Read backend logs
        import subprocess
        log_paths = ["/var/log/supervisor/backend.err.log",
                     "/var/log/supervisor/backend.out.log"]
        combined = ""
        for p in log_paths:
            if os.path.exists(p):
                combined += subprocess.check_output(["tail", "-n", "500", p]).decode("utf-8", errors="replace")

        markers = ["TEST_CONNECTIVITY start", "TRY_VARIANTS", "VARIANT_TEST",
                   "FFPROBE URL", "FFPROBE CMD", "FFPROBE RC", "TEST_CONNECTIVITY end"]
        missing = [m for m in markers if m not in combined]
        assert not missing, f"Missing log markers: {missing}\n---tail---\n{combined[-2000:]}"


# ═══════════════════════════════════════════════════════════════════════════
# 4) REGRESSION MASSIVE — plugins / storage / diagnostic / anpr / face
# ═══════════════════════════════════════════════════════════════════════════
class TestRegressionEndpoints:
    def test_plugins_list(self, h):
        r = requests.get(f"{BASE}/api/plugins", headers=h, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list) and len(r.json()) > 0

    def test_storage_overview(self, h):
        r = requests.get(f"{BASE}/api/storage/overview", headers=h, timeout=15)
        assert r.status_code == 200

    def test_camera_diagnostic(self, h):
        r = requests.get(f"{BASE}/api/cameras/demo-cam-001/diagnostic",
                         headers=h, timeout=20)
        assert r.status_code == 200
        j = r.json()
        # sanity : diag returns some structure
        assert isinstance(j, dict)

    def test_anpr_config_get(self, h):
        r = requests.get(f"{BASE}/api/plugins/anpr/config", headers=h, timeout=15)
        assert r.status_code == 200

    def test_anpr_cameras(self, h):
        r = requests.get(f"{BASE}/api/plugins/anpr/cameras", headers=h, timeout=15)
        assert r.status_code == 200

    def test_anpr_watchlist_export(self, h):
        r = requests.get(f"{BASE}/api/plugins/anpr/watchlist/export",
                         headers=h, timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("text/csv")

    def test_face_recognition_config(self, h):
        r = requests.get(f"{BASE}/api/plugins/face_recognition/config",
                         headers=h, timeout=15)
        assert r.status_code == 200

    def test_face_recognition_faces_list(self, h):
        r = requests.get(f"{BASE}/api/plugins/face_recognition/faces",
                         headers=h, timeout=15)
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# 5) LIVE VIDEO — /api/stream/{id}/live.mjpeg
# ═══════════════════════════════════════════════════════════════════════════
class TestLiveVideo:
    def test_mjpeg_streams_bytes(self, h):
        url = f"{BASE}/api/stream/demo-cam-001/live.mjpeg"
        got = 0
        boundary_ok = False
        with requests.get(url, headers=h, stream=True, timeout=8) as r:
            assert r.status_code == 200, f"HTTP {r.status_code}"
            ctype = r.headers.get("content-type", "")
            boundary_ok = "boundary=frame" in ctype
            start = time.time()
            for chunk in r.iter_content(chunk_size=4096):
                if chunk:
                    got += len(chunk)
                if got >= 10 * 1024 or time.time() - start > 3:
                    break
        assert boundary_ok, f"boundary=frame missing in Content-Type"
        assert got >= 10 * 1024, f"got only {got} bytes in 3s"
