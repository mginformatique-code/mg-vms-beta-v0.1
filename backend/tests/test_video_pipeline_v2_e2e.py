"""
E2E tests for video pipeline v2 architecture.
Validates:
- /api/cameras/{id}/video-status contract for the 3 E2E cameras
- /api/stream/{id}/live.mjpeg and /api/video/{id}/mjpeg dispatch per pipeline
- /api/video/{id}/whep signaling for mediamtx
- /api/cameras/{id}/refresh-stream pipeline-aware
- Camera create/delete with mediamtx pipeline + MediaMTX path presence
- GET /api/cameras returns stream_pipeline; demos in 'mjpeg'
- Go2RTC isolation: no cam_{id} for real cameras
"""
import os
import time
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    BASE = "https://video-command-6.preview.emergentagent.com"

ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}

E2E_MEDIAMTX = "286eeced-ec07-4914-935a-85b232e24b19"
E2E_MJPEG = "b875a677-8f45-4abd-8783-4b6eb2c8a68a"
E2E_DIRECT = "0da7f4f3-4e50-40a8-a0b2-4bd73dc5cf3e"

SDP_OFFER_MIN = (
    "v=0\r\n"
    "o=- 4611731400430051336 2 IN IP4 127.0.0.1\r\n"
    "s=-\r\n"
    "t=0 0\r\n"
    "a=group:BUNDLE 0\r\n"
    "a=msid-semantic: WMS\r\n"
    "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
    "c=IN IP4 0.0.0.0\r\n"
    "a=rtcp:9 IN IP4 0.0.0.0\r\n"
    "a=ice-ufrag:F7gI\r\n"
    "a=ice-pwd:x9cml/YzichV2+XlhiMu8g\r\n"
    "a=fingerprint:sha-256 12:34:56:78:9A:BC:DE:F0:12:34:56:78:9A:BC:DE:F0:12:34:56:78:9A:BC:DE:F0:12:34:56:78:9A:BC:DE:F0\r\n"
    "a=setup:actpass\r\n"
    "a=mid:0\r\n"
    "a=recvonly\r\n"
    "a=rtcp-mux\r\n"
    "a=rtpmap:96 H264/90000\r\n"
    "a=fmtp:96 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f\r\n"
)


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- video-status ----------
@pytest.mark.parametrize("cam_id,expected_pipeline", [
    (E2E_MEDIAMTX, "mediamtx"),
    (E2E_MJPEG, "mjpeg"),
    (E2E_DIRECT, "direct_rtsp"),
])
def test_video_status_contract(auth_headers, cam_id, expected_pipeline):
    r = requests.get(f"{BASE}/api/cameras/{cam_id}/video-status", headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ["camera_id", "pipeline", "status", "source", "codec", "fps",
              "last_frame_at", "latency_ms", "error", "checked_at"]:
        assert k in d, f"missing key {k} in {d}"
    assert d["camera_id"] == cam_id
    assert d["pipeline"] == expected_pipeline

    if expected_pipeline == "mediamtx":
        assert d["status"] == "online", d
        assert (d.get("codec") or "").lower() == "h264"
    elif expected_pipeline == "mjpeg":
        assert d["status"] in ("online", "on-demand"), d
    elif expected_pipeline == "direct_rtsp":
        assert d["status"] == "online", d
        assert d.get("browser_playable") is False
        assert "rtsp_url_masked" in d


# ---------- live.mjpeg dispatch ----------
def _stream_head(url, token, expect_status, expect_pipeline=None, read_bytes=0):
    with requests.get(f"{url}?token={token}", stream=True, timeout=15) as r:
        assert r.status_code == expect_status, f"{r.status_code} {r.text[:200]}"
        if expect_pipeline:
            assert r.headers.get("X-Video-Pipeline") == expect_pipeline, dict(r.headers)
        if read_bytes and r.status_code == 200:
            chunk = next(r.iter_content(chunk_size=read_bytes), b"")
            assert len(chunk) > 0


def test_live_mjpeg_dispatch_mjpeg(token):
    _stream_head(f"{BASE}/api/stream/{E2E_MJPEG}/live.mjpeg", token, 200, "mjpeg", 2048)


def test_live_mjpeg_dispatch_mediamtx(token):
    _stream_head(f"{BASE}/api/stream/{E2E_MEDIAMTX}/live.mjpeg", token, 200, "mediamtx", 2048)


def test_live_mjpeg_dispatch_direct_rtsp(token):
    r = requests.get(f"{BASE}/api/stream/{E2E_DIRECT}/live.mjpeg?token={token}", timeout=10)
    assert r.status_code == 409, r.text


def test_video_mjpeg_endpoint_mjpeg(token):
    _stream_head(f"{BASE}/api/video/{E2E_MJPEG}/mjpeg", token, 200, "mjpeg", 2048)


def test_video_mjpeg_endpoint_mediamtx(token):
    _stream_head(f"{BASE}/api/video/{E2E_MEDIAMTX}/mjpeg", token, 200, "mediamtx", 2048)


def test_video_mjpeg_endpoint_direct_rtsp(token):
    r = requests.get(f"{BASE}/api/video/{E2E_DIRECT}/mjpeg?token={token}", timeout=10)
    assert r.status_code == 409


# ---------- WHEP ----------
def test_whep_mediamtx(auth_headers):
    r = requests.post(
        f"{BASE}/api/video/{E2E_MEDIAMTX}/whep",
        headers={**auth_headers, "Content-Type": "application/sdp"},
        data=SDP_OFFER_MIN,
        timeout=20,
    )
    assert r.status_code == 201, f"{r.status_code} {r.text[:300]}"
    assert r.text.startswith("v=0"), r.text[:120]
    assert r.headers.get("X-Whep-Session"), dict(r.headers)


def test_whep_mjpeg_rejected(auth_headers):
    r = requests.post(
        f"{BASE}/api/video/{E2E_MJPEG}/whep",
        headers={**auth_headers, "Content-Type": "application/sdp"},
        data=SDP_OFFER_MIN,
        timeout=15,
    )
    assert r.status_code == 409, r.text[:200]


def test_whep_direct_rtsp_rejected(auth_headers):
    r = requests.post(
        f"{BASE}/api/video/{E2E_DIRECT}/whep",
        headers={**auth_headers, "Content-Type": "application/sdp"},
        data=SDP_OFFER_MIN,
        timeout=15,
    )
    assert r.status_code == 409


# ---------- refresh-stream ----------
def test_refresh_stream_mediamtx(auth_headers):
    r = requests.post(f"{BASE}/api/cameras/{E2E_MEDIAMTX}/refresh-stream", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("success") is True
    assert d.get("pipeline") == "mediamtx"
    assert "ready" in d


def test_refresh_stream_mjpeg(auth_headers):
    r = requests.post(f"{BASE}/api/cameras/{E2E_MJPEG}/refresh-stream", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("success") is True
    assert d.get("pipeline") == "mjpeg"


def test_refresh_stream_direct_rtsp(auth_headers):
    r = requests.post(f"{BASE}/api/cameras/{E2E_DIRECT}/refresh-stream", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("success") is True
    assert d.get("pipeline") == "direct_rtsp"
    assert "rtsp_reachable" in d


# ---------- cameras list ----------
def test_cameras_list_has_stream_pipeline(auth_headers):
    r = requests.get(f"{BASE}/api/cameras", headers=auth_headers, timeout=15)
    assert r.status_code == 200
    cams = r.json()
    assert isinstance(cams, list) and len(cams) > 0
    for c in cams:
        assert "stream_pipeline" in c, c
    demos = {c["id"]: c for c in cams if c["id"] in ("demo-cam-001", "demo-cam-002")}
    assert len(demos) == 2
    for c in demos.values():
        assert c["stream_pipeline"] == "mjpeg", c


# ---------- camera lifecycle mediamtx ----------
def test_create_and_delete_mediamtx_camera(auth_headers):
    sites = requests.get(f"{BASE}/api/sites", headers=auth_headers, timeout=10)
    assert sites.status_code == 200
    site_list = sites.json()
    assert site_list, "no sites available"
    site_id = site_list[0]["id"]

    payload = {
        "name": "TEST_v2_mediamtx_lifecycle",
        "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
        "site_id": site_id,
        "stream_pipeline": "mediamtx",
    }
    r = requests.post(f"{BASE}/api/cameras", headers=auth_headers, json=payload, timeout=20)
    assert r.status_code in (200, 201), r.text
    cam = r.json()
    cid = cam.get("id") or cam.get("_id")
    assert cid

    try:
        # wait ~6s for MediaMTX path to be published
        online = False
        for _ in range(8):
            time.sleep(1)
            s = requests.get(f"{BASE}/api/cameras/{cid}/video-status", headers=auth_headers, timeout=10)
            if s.status_code == 200 and s.json().get("status") == "online":
                online = True
                break
        assert online, "created mediamtx camera never came online"
    finally:
        d = requests.delete(f"{BASE}/api/cameras/{cid}", headers=auth_headers, timeout=15)
        assert d.status_code in (200, 204), d.text

    # after delete video-status should be offline OR 404
    s = requests.get(f"{BASE}/api/cameras/{cid}/video-status", headers=auth_headers, timeout=10)
    assert s.status_code in (404, 410) or (s.status_code == 200 and s.json().get("status") in ("offline", "unknown", "error"))


# ---------- Go2RTC isolation ----------
def test_go2rtc_isolation():
    try:
        r = requests.get("http://localhost:1984/api/streams", timeout=5)
    except Exception as e:
        pytest.skip(f"go2rtc not reachable locally: {e}")
    if r.status_code != 200:
        pytest.skip(f"go2rtc returned {r.status_code}")
    streams = r.json() or {}
    allowed_prefixes = ("cam_demo-cam-001", "cam_demo-cam-002")
    real_cam_ids = (E2E_MEDIAMTX, E2E_MJPEG, E2E_DIRECT)
    bad = []
    for name in streams.keys():
        for rid in real_cam_ids:
            if rid in name:
                bad.append(name)
        # any cam_<uuid> that isn't demo
        if name.startswith("cam_") and not any(name.startswith(p) for p in allowed_prefixes):
            # allow suffix _hd/_sd of demos
            if not (name.startswith("cam_demo-cam-001") or name.startswith("cam_demo-cam-002")):
                bad.append(name)
    assert not bad, f"go2rtc contains non-demo streams: {bad}"
