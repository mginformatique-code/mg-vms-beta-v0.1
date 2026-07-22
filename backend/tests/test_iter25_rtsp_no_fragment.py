"""Iteration 25 — BUG FIX: _build_rtsp_url ne doit PLUS ajouter '#transport=…'.

Le fragment cassait go2rtc (frame.jpeg vide, MJPEG KO). Fix : suppression totale
de l'ajout automatique. Le transport reste géré via ffprobe CLI (-rtsp_transport)
et go2rtc négocie automatiquement.
"""
import os
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

for _k in ("MONGO_URL", "DB_NAME"):
    if not os.environ.get(_k):
        v = _read_env("/app/backend/.env", _k)
        if v:
            os.environ[_k] = v

import sys
sys.path.insert(0, "/app/backend")

# ffprobe lives in /app/bin (backend supervisor PATH); tests need it too
if "/app/bin" not in os.environ.get("PATH", ""):
    os.environ["PATH"] = "/app/bin:" + os.environ.get("PATH", "")

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
# 1) UNIT TESTS on _build_rtsp_url — NO MORE #transport=…
# ═══════════════════════════════════════════════════════════════════════════
class TestBuildRtspUrlNoFragment:
    def test_no_fragment_appended_udp(self):
        from streaming import _build_rtsp_url
        out = _build_rtsp_url({"rtsp_url": "rtsp://cam.local:554/foo",
                                "rtsp_transport": "udp"})
        assert "#transport=" not in out, f"Fragment leaked: {out}"
        assert out == "rtsp://cam.local:554/foo"

    def test_no_fragment_appended_tcp(self):
        from streaming import _build_rtsp_url
        out = _build_rtsp_url({"rtsp_url": "rtsp://cam.local:554/foo",
                                "rtsp_transport": "tcp"})
        assert "#transport=" not in out
        assert out == "rtsp://cam.local:554/foo"

    def test_historic_fragment_stripped(self):
        from streaming import _build_rtsp_url
        out = _build_rtsp_url({"rtsp_url": "rtsp://x:554/foo#transport=tcp"})
        assert out == "rtsp://x:554/foo"
        assert "#" not in out

    def test_historic_fragment_udp_stripped(self):
        from streaming import _build_rtsp_url
        out = _build_rtsp_url({"rtsp_url": "rtsp://x:554/foo#transport=udp",
                                "rtsp_transport": "udp"})
        assert out == "rtsp://x:554/foo"

    def test_credentials_still_injected_no_fragment(self):
        from streaming import _build_rtsp_url
        out = _build_rtsp_url({"rtsp_url": "rtsp://cam:554/live",
                                "username": "admin",
                                "password": "P@ss#1",
                                "rtsp_transport": "tcp"})
        assert "#transport=" not in out
        assert "admin:" in out
        # '#' from password must be encoded (%23)
        assert "%23" in out

    def test_empty_url_returns_empty(self):
        from streaming import _build_rtsp_url
        assert _build_rtsp_url({"rtsp_url": ""}) == ""


# ═══════════════════════════════════════════════════════════════════════════
# 2) API — test-connectivity avec transport udp NE DOIT PLUS échouer
# ═══════════════════════════════════════════════════════════════════════════
class TestConnectivity:
    def test_connectivity_demo_cam_tcp(self, h):
        r = requests.post(
            f"{BASE}/api/cameras/test-connectivity",
            headers=h, timeout=60,
            json={
                "mode": "rtsp",
                "ip": "127.0.0.1",
                "rtsp_port": 8554,
                "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
                "rtsp_transport": "tcp",
                "preferred_codec": "auto",
            },
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("rtsp_url_validated") is True, d
        # Ensure the final URL stored/returned has no fragment
        used = d.get("rtsp_url_used") or d.get("rtsp_url") or ""
        assert "#transport=" not in used, f"fragment leaked: {used}"

    def test_connectivity_demo_cam_udp(self, h):
        r = requests.post(
            f"{BASE}/api/cameras/test-connectivity",
            headers=h, timeout=60,
            json={
                "mode": "rtsp",
                "ip": "127.0.0.1",
                "rtsp_port": 8554,
                "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
                "rtsp_transport": "udp",
                "preferred_codec": "auto",
            },
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("rtsp_url_validated") is True, d
        used = d.get("rtsp_url_used") or d.get("rtsp_url") or ""
        assert "#transport=" not in used, f"fragment leaked: {used}"


# ═══════════════════════════════════════════════════════════════════════════
# 3) Streaming endpoints — go2rtc frame.jpeg + live.mjpeg
# ═══════════════════════════════════════════════════════════════════════════
def _stream_token(h, token):
    """Le token d'accès JWT est réutilisé comme query token pour les endpoints stream."""
    return token


class TestGo2rtcFrame:
    def test_frame_jpeg_size(self, h, token):
        tok = _stream_token(h, token)
        r = requests.get(
            f"{BASE}/api/stream/demo-cam-001/frame.jpeg",
            params={"token": tok}, timeout=15,
        )
        assert r.status_code == 200, f"status={r.status_code} body={r.content[:200]!r}"
        assert r.content[:3] == b"\xff\xd8\xff", "not a JPEG"
        assert len(r.content) > 30_000, f"JPEG too small: {len(r.content)}"

    def test_live_mjpeg_stream(self, h, token):
        tok = _stream_token(h, token)
        url = f"{BASE}/api/stream/demo-cam-001/live.mjpeg?token={tok}"
        total = 0
        boundary_seen = False
        with requests.get(url, stream=True, timeout=10) as r:
            assert r.status_code == 200, r.text
            ct = r.headers.get("Content-Type", "")
            assert "boundary=frame" in ct, ct
            deadline = time.time() + 3.0
            for chunk in r.iter_content(4096):
                if chunk:
                    total += len(chunk)
                    if not boundary_seen and b"--frame" in chunk:
                        boundary_seen = True
                if time.time() >= deadline:
                    break
        assert total > 10_000, f"MJPEG too small in 3s: {total}"
        assert boundary_seen


# ═══════════════════════════════════════════════════════════════════════════
# 4) ffprobe uses -rtsp_transport via CLI (regression backend log check)
# ═══════════════════════════════════════════════════════════════════════════
class TestFfprobeCli:
    def test_ffprobe_command_uses_cli_transport(self):
        """Vérifie via appel direct : _ffprobe honore le transport passé en arg."""
        from streaming import _ffprobe
        # Réel : demo-cam-001 en TCP doit répondre.
        res = _ffprobe("rtsp://127.0.0.1:8554/cam_demo-cam-001", transport="tcp")
        assert res is not None
        assert res.get("transport") == "tcp"
        assert res.get("codec") == "H264"


# ═══════════════════════════════════════════════════════════════════════════
# 5) POST /api/cameras — mode=rtsp validation (invalid → 400, valid → 200)
# ═══════════════════════════════════════════════════════════════════════════
class TestCameraCreate:
    @pytest.fixture(scope="class")
    def site_id(self, h):
        r = requests.get(f"{BASE}/api/sites", headers=h, timeout=10)
        if r.status_code != 200:
            pytest.skip(f"/api/sites unavailable: {r.status_code}")
        sites = r.json() if isinstance(r.json(), list) else r.json().get("items") or []
        if not sites:
            pytest.skip("no site available")
        return sites[0].get("id")

    def test_create_rtsp_invalid_returns_400(self, h, site_id):
        payload = {
            "name": "TEST_iter25_invalid",
            "site_id": site_id,
            "mode": "rtsp",
            "rtsp_url": "rtsp://127.0.0.1:9/does_not_exist",
            "rtsp_transport": "tcp",
        }
        r = requests.post(f"{BASE}/api/cameras", headers=h, json=payload, timeout=30)
        # ffprobe validation obligatoire → doit refuser
        assert r.status_code in (400, 422), f"expected 400/422 got {r.status_code} {r.text}"

    def test_create_rtsp_valid_returns_200_no_fragment(self, h, site_id):
        payload = {
            "name": "TEST_iter25_valid",
            "site_id": site_id,
            "mode": "rtsp",
            "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
            "rtsp_transport": "udp",
        }
        r = requests.post(f"{BASE}/api/cameras", headers=h, json=payload, timeout=45)
        assert r.status_code == 200, r.text
        d = r.json()
        cam_id = d.get("id") or (d.get("camera") or {}).get("id")
        stored = d.get("rtsp_url") or (d.get("camera") or {}).get("rtsp_url") or ""
        assert "#transport=" not in stored, f"stored URL has fragment: {stored}"
        # Cleanup
        if cam_id:
            requests.delete(f"{BASE}/api/cameras/{cam_id}", headers=h, timeout=10)


# ═══════════════════════════════════════════════════════════════════════════
# 6) Regression sanity — ANPR / face_recognition / watchlist endpoints
# ═══════════════════════════════════════════════════════════════════════════
class TestRegressionEndpoints:
    def test_anpr_config(self, h):
        r = requests.get(f"{BASE}/api/plugins/anpr/config", headers=h, timeout=10)
        assert r.status_code == 200, r.text

    def test_anpr_cameras(self, h):
        r = requests.get(f"{BASE}/api/plugins/anpr/cameras", headers=h, timeout=10)
        assert r.status_code == 200, r.text

    def test_anpr_watchlist_export(self, h):
        r = requests.get(f"{BASE}/api/plugins/anpr/watchlist/export",
                          headers=h, timeout=10)
        assert r.status_code == 200, r.text

    def test_face_recognition_config(self, h):
        r = requests.get(f"{BASE}/api/plugins/face_recognition/config",
                          headers=h, timeout=10)
        assert r.status_code == 200, r.text

    def test_face_recognition_faces(self, h):
        r = requests.get(f"{BASE}/api/plugins/face_recognition/faces",
                          headers=h, timeout=10)
        assert r.status_code == 200, r.text
