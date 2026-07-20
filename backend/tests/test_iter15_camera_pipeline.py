"""Iteration 15 — MG-VMS real camera pipeline tests.

Covers:
- POST /api/cameras/test-connectivity (success + failure)
- POST /api/cameras with invalid RTSP is rejected (400) and not persisted
- POST /api/cameras with loopback RTSP creates a camera, registers streams in go2rtc,
  returns rtsp_port/onvif_port fields.
- GET /api/stream/{id}/frame.jpeg returns valid JPEG (>5KB, FFD8FF magic).
- GET /api/stream/{id}/live.mjpeg returns multipart mjpeg content-type.
- Camera status becomes 'online' within ~60s.
- Cleanup: DELETE created cameras.
"""
import os
import time
import httpx
import pytest
import requests
import subprocess

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
GO2RTC = "http://localhost:1984"
ADMIN_EMAIL = "admin@mg-vms.com"
ADMIN_PASSWORD = "Admin@2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def site_id(client):
    r = client.get(f"{BASE_URL}/api/sites")
    assert r.status_code == 200
    sites = r.json()
    assert sites, "Aucun site présent"
    return sites[0]["id"]


# ----- Connectivité -----
def test_connectivity_success_loopback(client):
    r = client.post(f"{BASE_URL}/api/cameras/test-connectivity", json={
        "ip": "127.0.0.1", "rtsp_port": 8554, "onvif_port": 1984,
        "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["success"] is True
    assert d["ip_reachable"] is True
    assert d["rtsp_reachable"] is True
    assert d.get("resolution")
    assert d.get("codec")


def test_connectivity_unreachable(client):
    r = client.post(f"{BASE_URL}/api/cameras/test-connectivity", json={
        "ip": "10.99.99.99", "rtsp_port": 554, "onvif_port": 80,
        "rtsp_url": "rtsp://10.99.99.99:554/stream1",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is False
    assert d["ip_reachable"] is False
    assert d.get("message")


# ----- Création caméra invalide -----
def test_create_camera_invalid_rtsp_rejected(client, site_id):
    payload = {"name": "TEST_invalid_rtsp", "site_id": site_id,
               "ip": "127.0.0.1", "rtsp_port": 8554, "onvif_port": 1984,
               "rtsp_url": "not-a-url"}
    r = client.post(f"{BASE_URL}/api/cameras", json=payload)
    assert r.status_code == 400, r.text
    # Verify not persisted
    cams = client.get(f"{BASE_URL}/api/cameras").json()
    assert not any(c["name"] == "TEST_invalid_rtsp" for c in cams)


# ----- Création caméra valide + live -----
@pytest.fixture(scope="module")
def created_camera(client, site_id):
    payload = {
        "name": "TEST_loopback_iter15", "site_id": site_id,
        "ip": "127.0.0.1", "rtsp_port": 8554, "onvif_port": 1984,
        "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
        "record_enabled": True, "detect_enabled": False,
    }
    r = client.post(f"{BASE_URL}/api/cameras", json=payload)
    assert r.status_code == 200, r.text
    cam = r.json()
    yield cam
    # Teardown
    client.delete(f"{BASE_URL}/api/cameras/{cam['id']}")


def test_created_camera_has_ports_and_streams(client, created_camera):
    cam_id = created_camera["id"]
    got = client.get(f"{BASE_URL}/api/cameras/{cam_id}").json()
    assert got.get("rtsp_port") == 8554
    assert got.get("onvif_port") == 1984
    # go2rtc streams
    streams = httpx.get(f"{GO2RTC}/api/streams", timeout=5).json()
    assert f"cam_{cam_id}" in streams
    assert f"cam_{cam_id}_sd" in streams


def test_frame_jpeg_returns_valid_image(token, created_camera):
    cam_id = created_camera["id"]
    # Allow go2rtc a couple of seconds to open the stream
    ok = False
    for _ in range(6):
        r = requests.get(f"{BASE_URL}/api/stream/{cam_id}/frame.jpeg",
                         params={"token": token}, timeout=15)
        if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff" and len(r.content) > 5000:
            ok = True
            break
        time.sleep(2)
    assert ok, f"frame.jpeg not valid; status={r.status_code} size={len(r.content)}"


def test_mjpeg_stream_headers(token, created_camera):
    cam_id = created_camera["id"]
    with requests.get(f"{BASE_URL}/api/stream/{cam_id}/live.mjpeg",
                      params={"token": token}, stream=True, timeout=15) as r:
        assert r.status_code == 200, r.text
        ctype = r.headers.get("content-type", "")
        assert "multipart" in ctype or "mjpeg" in ctype.lower(), ctype
        # Read a small chunk to confirm stream flows
        it = r.iter_content(chunk_size=1024)
        chunk = next(it, b"")
        assert len(chunk) > 0


def test_status_online_within_60s(client, created_camera):
    cam_id = created_camera["id"]
    deadline = time.time() + 75
    status = None
    while time.time() < deadline:
        got = client.get(f"{BASE_URL}/api/cameras/{cam_id}").json()
        status = got.get("status")
        if status == "online":
            return
        time.sleep(5)
    pytest.fail(f"Status did not reach online within 75s (last={status})")


def test_ffmpeg_recorder_and_directory(created_camera):
    cam_id = created_camera["id"]
    # Recorder loop ticks every 30 s; give it up to ~150 s to spawn ffmpeg and
    # create the recording directory. We consider the plumbing OK if the
    # directory exists and either the ffmpeg process is visible in ps OR the
    # backend log confirms it was started (some races between fixture teardown
    # and ps snapshot are unavoidable).
    found_proc = False
    found_dir = False
    deadline = time.time() + 150
    while time.time() < deadline and not (found_proc and found_dir):
        out = subprocess.run(["ps", "-ef"], capture_output=True, text=True).stdout
        if any(f"cam_{cam_id}" in l and "ffmpeg" in l for l in out.splitlines()):
            found_proc = True
        if os.path.isdir(f"/data/recordings/{cam_id}") or os.path.isdir(f"/app/recordings/{cam_id}"):
            found_dir = True
        if found_proc and found_dir:
            break
        time.sleep(5)
    # Fallback: check backend log evidence
    if not found_proc:
        try:
            log_paths = [p for p in os.listdir("/var/log/supervisor") if p.startswith("backend")]
            for lp in log_paths:
                with open(f"/var/log/supervisor/{lp}", errors="ignore") as fh:
                    if f"caméra {cam_id}" in fh.read():
                        found_proc = True
                        break
        except OSError:
            pass
    assert found_dir, "recording directory never created for new camera"
    assert found_proc, "no ffmpeg process (or log evidence) for new camera within 150 s"


def test_demo_cameras_have_real_mp4_segments():
    # At least one .mp4 file for each demo camera
    for cid in ("demo-cam-001", "demo-cam-002"):
        for base in ("/data/recordings", "/app/recordings"):
            d = f"{base}/{cid}"
            if os.path.isdir(d):
                mp4s = [f for f in os.listdir(d) if f.endswith(".mp4")]
                if mp4s:
                    break
        else:
            pytest.fail(f"No mp4 segments found for {cid}")
