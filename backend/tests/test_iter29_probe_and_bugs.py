"""Iteration 29 — Regression tests for 3 production bugs (ONVIF/preview/disconnects)
- Non-invasive status probe stability
- ONVIF discover hint
- test-connectivity ONVIF error detail
- Pipeline no cuda hardware
- MJPEG/JPEG streaming
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://video-command-6.preview.emergentagent.com").rstrip("/")
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ── Regression: demo cameras online + stable ──
def test_demo_cameras_online(admin_headers):
    r = requests.get(f"{BASE_URL}/api/cameras", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    cams = r.json()
    ids = {c["id"]: c for c in cams}
    assert "demo-cam-001" in ids and "demo-cam-002" in ids, list(ids.keys())
    for cid in ("demo-cam-001", "demo-cam-002"):
        assert ids[cid].get("status") == "online", f"{cid}: {ids[cid].get('status')} / {ids[cid].get('error_message')}"


def test_demo_cameras_stable_over_two_probes(admin_headers):
    """Wait > 60s → cameras must remain online (probe non-invasif)."""
    time.sleep(65)
    r = requests.get(f"{BASE_URL}/api/cameras", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    ids = {c["id"]: c for c in r.json()}
    for cid in ("demo-cam-001", "demo-cam-002"):
        assert ids[cid]["status"] == "online", f"{cid} flapped: {ids[cid]}"


# ── Pipeline: no cuda hardware filter ──
def test_pipeline_no_cuda(admin_headers):
    r = requests.get(f"{BASE_URL}/api/pipeline/status", headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    # data can be {cameras: [...]} or {pipeline: {cam_id: {...}}} — inspect both
    payload_str = str(data).lower()
    assert "hardware=cuda" not in payload_str, "found hardware=cuda in pipeline filters"


# ── ONVIF discover hint (sandbox has no ONVIF device) ──
def test_onvif_discover_hint(admin_headers):
    r = requests.post(f"{BASE_URL}/api/cameras/discover", headers=admin_headers,
                      json={"timeout": 5}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("count", 0) == 0, f"unexpected devices: {data}"
    assert isinstance(data.get("devices", []), list)
    hint = data.get("hint")
    assert hint and isinstance(hint, str) and len(hint) > 0, f"hint missing: {data}"
    # hint should mention Docker/multicast/bridge context
    low = hint.lower()
    assert any(k in low for k in ("docker", "multicast", "bridge", "réseau", "network")), hint


# ── test-connectivity in RTSP mode on go2rtc local relay ──
def test_connectivity_rtsp_go2rtc_relay(admin_headers):
    payload = {
        "mode": "rtsp",
        "ip": "127.0.0.1",
        "rtsp_port": 8554,
        "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
    }
    r = requests.post(f"{BASE_URL}/api/cameras/test-connectivity",
                      headers=admin_headers, json=payload, timeout=45)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("success") is True, d
    assert d.get("rtsp_url_validated") is True, d


# ── test-connectivity ONVIF failure with meaningful message ──
def test_connectivity_onvif_error_detail(admin_headers):
    # Try a port open but NOT ONVIF-compatible (backend HTTP :8001 not reachable externally,
    # so use frontend :3000 that isn't reachable either — use a definitively non-ONVIF service).
    # We attempt port 27017 (mongo) which is open locally but not ONVIF.
    payload = {
        "mode": "onvif",
        "ip": "127.0.0.1",
        "onvif_port": 27017,  # mongo port — open but not ONVIF
        "username": "admin",
        "password": "invalid",
    }
    r = requests.post(f"{BASE_URL}/api/cameras/test-connectivity",
                      headers=admin_headers, json=payload, timeout=45)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:400]}"
    d = r.json()
    steps = d.get("steps") or []
    # steps is a list of dicts with 'name'
    if isinstance(steps, dict):
        steps = [{"name": k, **(v if isinstance(v, dict) else {"message": v})} for k, v in steps.items()]
    onvif_step = next((s for s in steps if s.get("name") in ("onvif_auth", "onvif", "onvif_connect")), None)
    assert onvif_step is not None, f"no onvif step in {steps}"
    # Must be in error state
    assert onvif_step.get("status") in ("error", "ko", "failed"), f"expected error: {onvif_step}"
    msg = str(onvif_step.get("message", "") or onvif_step.get("error", ""))
    # message must contain more than just an exception class name — check for some detail
    # (a bare class name would be very short/single-word)
    assert len(msg) > 15, f"error message too short/uninformative: {msg!r}"


# ── MJPEG live stream returns multipart with JPEG bytes ──
def test_mjpeg_live_stream(admin_token):
    url = f"{BASE_URL}/api/stream/demo-cam-001/live.mjpeg?token={admin_token}"
    with requests.get(url, stream=True, timeout=15) as r:
        assert r.status_code == 200, r.text[:200]
        ct = r.headers.get("Content-Type", "")
        assert "multipart" in ct.lower(), ct
        # Read some bytes and check for JPEG magic
        buf = b""
        start = time.time()
        for chunk in r.iter_content(4096):
            buf += chunk
            if b"\xff\xd8\xff" in buf and len(buf) > 20000:
                break
            if time.time() - start > 10:
                break
        assert b"\xff\xd8\xff" in buf, "no JPEG magic bytes in MJPEG stream"


def test_frame_jpeg_hd(admin_token):
    url = f"{BASE_URL}/api/stream/demo-cam-001/frame.jpeg?token={admin_token}&hd=1"
    r = requests.get(url, timeout=15)
    assert r.status_code == 200, r.text[:200]
    assert r.content[:3] == b"\xff\xd8\xff", "not a JPEG"
    assert len(r.content) > 1000


# ── Full flow: create real camera in RTSP mode, verify probe → online, cleanup ──
def test_create_real_camera_probe_online(admin_headers):
    # Find a valid site
    sites = requests.get(f"{BASE_URL}/api/sites", headers=admin_headers, timeout=15).json()
    assert sites, "no sites available"
    site_id = sites[0]["id"]

    payload = {
        "name": "TEST_iter29_real",
        "site_id": site_id,
        "mode": "rtsp",
        "ip": "127.0.0.1",
        "rtsp_port": 8554,
        "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
    }
    r = requests.post(f"{BASE_URL}/api/cameras", headers=admin_headers, json=payload, timeout=60)
    assert r.status_code in (200, 201), r.text
    cam = r.json()
    cam_id = cam.get("id") or cam.get("_id") or cam.get("camera_id")
    assert cam_id, cam
    assert (cam.get("codec") or "").lower() in ("h264", "h.264"), cam
    res = cam.get("resolution") or ""
    assert "1280" in str(res) and "720" in str(res), cam

    try:
        # Wait for probe cycle (up to 90s)
        online = False
        for _ in range(9):
            time.sleep(10)
            g = requests.get(f"{BASE_URL}/api/cameras/{cam_id}", headers=admin_headers, timeout=15)
            if g.status_code == 200 and g.json().get("status") == "online":
                online = True
                break
        assert online, "camera never became online"

        # Check lifecycle diagnostics
        lc = requests.get(f"{BASE_URL}/api/diagnostics/stream-lifecycle/{cam_id}",
                          headers=admin_headers, timeout=15)
        assert lc.status_code == 200, lc.text
        events = lc.json()
        if isinstance(events, dict):
            events = events.get("events") or events.get("entries") or []
        # Must have status_probe_ok entries
        probe_ok = [e for e in events if (e.get("action") or e.get("event") or e.get("type") or "") == "status_probe_ok"]
        assert probe_ok, f"no status_probe_ok entries in lifecycle: {events[:5]}"
        # Any 'reason' should mention non-invasif for at least one entry
        assert any("non-invasif" in (e.get("reason") or "").lower() for e in probe_ok), \
            f"no 'probe non-invasif' reason found in: {[e.get('reason') for e in probe_ok][:5]}"

        # No 'registering' events after initial creation (no churn)
        registerings = [e for e in events if (e.get("action") or e.get("event") or e.get("type") or "") == "registering"]
        # Allow at most 1 (the initial registration)
        assert len(registerings) <= 1, f"too many 'registering' entries: {len(registerings)}"
    finally:
        # Cleanup
        requests.delete(f"{BASE_URL}/api/cameras/{cam_id}", headers=admin_headers, timeout=30)


# ── AI still generates events on demo-cam-002 ──
def test_ai_generates_events(admin_headers):
    # Query recent events
    r = requests.get(f"{BASE_URL}/api/events", headers=admin_headers,
                     params={"limit": 20, "camera_id": "demo-cam-002"}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    events = data if isinstance(data, list) else data.get("events") or data.get("items") or []
    # At least some events should exist (AI has been running)
    assert len(events) > 0, "no events on demo-cam-002 — AI may be broken"
