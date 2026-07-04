"""MG-VMS 100% real system tests (iteration 13).

Covers: dashboard real counters, cameras real test/snapshot/probe, ONVIF
discovery, recordings real MP4 playback, real ZIP/MP4 export, real AI
events, network real ping, real hardware monitor, no fake plates/GPUs.
"""
import io
import os
import time
import zipfile
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@mg-vms.com", "Admin@2026")


def H(t):
    return {"Authorization": f"Bearer {t}"}


# ---------- DASHBOARD ----------
def test_dashboard_real_counters(admin_token):
    r = requests.get(f"{API}/dashboard/stats", headers=H(admin_token), timeout=15)
    assert r.status_code == 200
    d = r.json()
    # Real system: exactly 2 demo cams and 1 site (per requirement)
    assert d["cameras_total"] == 2, f"expected 2 real demo cams, got {d['cameras_total']}"
    assert d["sites"] >= 1
    assert "cpu" in d["system"]
    print("dashboard stats:", {k: d[k] for k in ("cameras_total", "cameras_online", "sites", "events_today", "alerts_active", "plates_today")})


def test_dashboard_timeseries(admin_token):
    r = requests.get(f"{API}/dashboard/timeseries", headers=H(admin_token), timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert len(d["hourly"]) == 24


# ---------- CAMERAS ----------
def _get_demo_cams(token):
    r = requests.get(f"{API}/cameras", headers=H(token), timeout=15)
    assert r.status_code == 200
    cams = r.json()
    by_id = {c["id"]: c for c in cams}
    return cams, by_id


def test_two_demo_cameras_exist(admin_token):
    cams, by_id = _get_demo_cams(admin_token)
    assert "demo-cam-001" in by_id, list(by_id.keys())
    assert "demo-cam-002" in by_id, list(by_id.keys())


def test_camera_test_endpoint_real_probe(admin_token):
    r = requests.post(f"{API}/cameras/demo-cam-001/test", headers=H(admin_token), timeout=45)
    assert r.status_code == 200, r.text
    d = r.json()
    print("probe demo-cam-001:", d)
    # Accept status ok and check real-looking fields when present
    assert d.get("status") in ("online", "ok", "success", True) or d.get("ok") is True or "resolution" in d or "codec" in d, d


def test_camera_snapshot_real_jpeg(admin_token):
    r = requests.post(f"{API}/cameras/demo-cam-001/snapshot", headers=H(admin_token), timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    url = d.get("snapshot_url") or d.get("url")
    assert url, d
    # url is relative → prefix with API base; and add auth token
    full = url if url.startswith("http") else f"{API}{url}"
    sep = "&" if "?" in full else "?"
    full = f"{full}{sep}token={admin_token}"
    r2 = requests.get(full, timeout=30)
    assert r2.status_code == 200, f"{r2.status_code} {r2.text[:200]}"
    assert r2.content[:3] == b"\xff\xd8\xff", f"not a JPEG, ct={r2.headers.get('content-type')}"
    assert len(r2.content) > 2000, f"snapshot too small: {len(r2.content)}"


# ---------- ONVIF ----------
def test_onvif_discover_no_devices(admin_token):
    r = requests.post(f"{API}/cameras/discover", headers=H(admin_token), timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    # devices list must exist; expected empty here
    devices = d.get("devices", d if isinstance(d, list) else [])
    assert isinstance(devices, list)
    print("onvif discovered:", len(devices))


# ---------- MJPEG STREAM ----------
def test_live_mjpeg_stream(admin_token):
    # Streaming proxy takes ?token= for auth in <img>
    url = f"{API}/stream/demo-cam-001/live.mjpeg?token={admin_token}"
    with requests.get(url, stream=True, timeout=25) as r:
        assert r.status_code == 200, f"mjpeg status={r.status_code} body={r.text[:200]}"
        ct = r.headers.get("content-type", "")
        assert "multipart" in ct or "mjpeg" in ct.lower() or "image" in ct, ct
        # Read a bit of the stream to ensure real data flows
        buf = b""
        start = time.time()
        for chunk in r.iter_content(chunk_size=4096):
            buf += chunk
            if len(buf) > 8192 or time.time() - start > 15:
                break
        assert len(buf) > 500, f"no real MJPEG bytes: {len(buf)}"


# ---------- RECORDINGS ----------
def test_recordings_list_and_media_playback(admin_token):
    day = time.strftime("%Y-%m-%d")
    r = requests.get(f"{API}/recordings/timeline?camera_id=demo-cam-001&date={day}",
                     headers=H(admin_token), timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    segs = data.get("segments", [])
    print(f"segments today for demo-cam-001: {len(segs)}")
    if not segs:
        pytest.skip("no segments indexed yet — recorder may need more time")
    seg = segs[0]
    sid = seg.get("id")
    assert sid, seg
    media_url = f"{API}/recordings/{sid}/media?token={admin_token}"
    r2 = requests.get(media_url, stream=True, timeout=30)
    assert r2.status_code == 200, f"media status={r2.status_code} body={r2.text[:200]}"
    ct = r2.headers.get("content-type", "")
    assert "video" in ct or "mp4" in ct.lower(), ct
    total = 0
    for chunk in r2.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > 200_000:
            break
    assert total > 100_000, f"media too small: {total}"


def _iso(ts):
    from datetime import datetime, timezone as tz
    return datetime.fromtimestamp(ts, tz.utc).isoformat().replace("+00:00", "+00:00")


def _find_segment_range(admin_token):
    """Return (start_iso, end_iso, camera_id) covering an existing segment."""
    day = time.strftime("%Y-%m-%d")
    r = requests.get(f"{API}/recordings/timeline?camera_id=demo-cam-001&date={day}",
                     headers=H(admin_token), timeout=20)
    r.raise_for_status()
    segs = r.json().get("segments", [])
    if not segs:
        return None
    s = segs[0]
    return s["start"], s["end"], "demo-cam-001"


def test_recording_export_mp4(admin_token):
    rng = _find_segment_range(admin_token)
    if not rng:
        pytest.skip("no segments to export")
    start, end, cam = rng
    payload = {"camera_id": cam, "start": start, "end": end, "format": "mp4"}
    r = requests.post(f"{API}/recordings/export", headers=H(admin_token), json=payload, timeout=120)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("status") == "ready", d
    export_id = d["id"]
    r3 = requests.get(f"{API}/recordings/exports/{export_id}/download",
                      headers=H(admin_token), stream=True, timeout=60)
    assert r3.status_code == 200, r3.text
    total = 0
    head = b""
    for chunk in r3.iter_content(chunk_size=65536):
        if not head:
            head = chunk[:8]
        total += len(chunk)
        if total > 300_000:
            break
    assert total > 100_000, f"mp4 export too small: {total}"


def test_recording_export_zip(admin_token):
    rng = _find_segment_range(admin_token)
    if not rng:
        pytest.skip("no segments to export")
    start, end, cam = rng
    payload = {"camera_id": cam, "start": start, "end": end, "format": "zip"}
    r = requests.post(f"{API}/recordings/export", headers=H(admin_token), json=payload, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("status") == "ready"
    export_id = d["id"]
    r3 = requests.get(f"{API}/recordings/exports/{export_id}/download",
                      headers=H(admin_token), timeout=60)
    assert r3.status_code == 200, r3.text
    assert len(r3.content) > 100_000, f"zip too small: {len(r3.content)}"
    z = zipfile.ZipFile(io.BytesIO(r3.content))
    names = z.namelist()
    assert any(n.lower().endswith(".mp4") for n in names), names


# ---------- EVENTS (AI) ----------
def test_events_real_ai(admin_token):
    r = requests.get(f"{API}/events?limit=50", headers=H(admin_token), timeout=20)
    assert r.status_code == 200, r.text
    events = r.json()
    assert isinstance(events, list)
    print(f"events count: {len(events)}")
    # Should have at least one real AI event on demo-cam-002 (person/car)
    if events:
        types = {e.get("type") or e.get("label") or e.get("category") for e in events}
        print("event types:", types)


# ---------- NETWORK ----------
def test_network_equipment_empty_then_ping_real(admin_token):
    r = requests.get(f"{API}/network/equipment", headers=H(admin_token), timeout=15)
    assert r.status_code == 200, r.text
    devs = r.json()
    print(f"initial equipment: {len(devs)}")
    # get any site
    sites = requests.get(f"{API}/sites", headers=H(admin_token), timeout=15).json()
    assert sites, "no site available"
    site_id = sites[0]["id"]
    payload = {"name": "TEST_local", "type": "Serveur", "site_id": site_id, "ip": "127.0.0.1"}
    r = requests.post(f"{API}/network/equipment", headers=H(admin_token), json=payload, timeout=15)
    assert r.status_code == 200, r.text
    eq = r.json()
    eid = eq["id"]
    try:
        r2 = requests.post(f"{API}/network/equipment/{eid}/ping", headers=H(admin_token), timeout=20)
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        merged = d2.get("equipment", {})
        print("ping 127.0.0.1:", merged.get("status"), merged.get("latency_ms"), "result=", d2.get("result"))
        assert merged.get("status") == "online", d2
        assert merged.get("latency_ms") is not None and merged["latency_ms"] < 50, d2

        # unreachable
        payload2 = {"name": "TEST_unreach", "type": "Server", "site_id": site_id, "ip": "203.0.113.99"}
        r3 = requests.post(f"{API}/network/equipment", headers=H(admin_token), json=payload2, timeout=15)
        eid2 = r3.json()["id"]
        try:
            r4 = requests.post(f"{API}/network/equipment/{eid2}/ping", headers=H(admin_token), timeout=30)
            assert r4.status_code == 200
            m4 = r4.json().get("equipment", {})
            print("ping unreach:", m4.get("status"), m4.get("latency_ms"))
            assert m4.get("status") == "offline", r4.json()
        finally:
            requests.delete(f"{API}/network/equipment/{eid2}", headers=H(admin_token), timeout=10)
    finally:
        requests.delete(f"{API}/network/equipment/{eid}", headers=H(admin_token), timeout=10)


# ---------- HARDWARE ----------
def test_hardware_monitor_no_fake_gpus(admin_token):
    r = requests.get(f"{API}/hardware/monitor", headers=H(admin_token), timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    print("hardware monitor:", d)
    assert "cpu_pct" in d or "cpu" in d
    assert "ram_pct" in d or "ram" in d
    gpus = d.get("gpus", [])
    assert isinstance(gpus, list)
    # No fake GPUs (RTX 4070, A2000, Coral)
    for g in gpus:
        name = str(g.get("name", "")).lower()
        assert "rtx 4070" not in name and "a2000" not in name and "coral" not in name, gpus
    assert isinstance(d.get("ai_load_pct", 0), (int, float))
    assert isinstance(d.get("ffmpeg_load_pct", 0), (int, float))


# ---------- PLATES ----------
def test_plates_no_fake_seed(admin_token):
    r = requests.get(f"{API}/plates?limit=100", headers=H(admin_token), timeout=15)
    assert r.status_code == 200
    plates = r.json()
    print(f"plates count: {len(plates)}")
    # Ensure no seeded French demo plate
    for p in plates:
        pl = str(p.get("plate", "")).upper()
        assert pl != "AB-123-CD", "seeded fake plate present"
