"""Tests P1 stabilisation — PTZ ONVIF réel + Recorder Health."""
import httpx


BASE = "http://localhost:8001"
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


def _token():
    r = httpx.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=10)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d.get("token")


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


# ── PTZ ────────────────────────────────────────────────────────────────
def test_ptz_rejects_camera_without_ptz_flag():
    """Demo cam n'a pas ptz_enabled → 400."""
    r = httpx.post(f"{BASE}/api/cameras/demo-cam-001/ptz",
                   params={"command": "pan_left"}, headers=_auth(), timeout=10)
    assert r.status_code == 400
    assert "PTZ" in r.text


def test_ptz_404_on_unknown_camera():
    r = httpx.post(f"{BASE}/api/cameras/nonexistent-camera/ptz",
                   params={"command": "pan_left"}, headers=_auth(), timeout=10)
    assert r.status_code == 404


def test_ptz_presets_rejects_non_onvif():
    r = httpx.get(f"{BASE}/api/cameras/demo-cam-001/ptz/presets",
                  headers=_auth(), timeout=10)
    # Rejette avec 400 (pas ptz_enabled) ou 404
    assert r.status_code in (400, 404)


def test_ptz_preset_goto_rejects_non_onvif():
    r = httpx.post(f"{BASE}/api/cameras/demo-cam-001/ptz/preset/tok1",
                   headers=_auth(), timeout=10)
    assert r.status_code in (400, 404)


# ── Recorder Health ────────────────────────────────────────────────────
def test_recorder_health_endpoint_shape():
    r = httpx.get(f"{BASE}/api/diagnostics/recorder-health",
                  headers=_auth(), timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "cameras" in d
    assert "segment_seconds" in d
    assert "generated_at" in d
    if d["cameras"]:
        cam = d["cameras"][0]
        for k in ("camera_id", "ffmpeg_alive", "pid_alive_os",
                  "last_segment_start", "last_segment_end",
                  "last_segment_age_sec", "expected_segment_sec",
                  "gap_detected", "continuity_24h"):
            assert k in cam, f"Champ '{k}' manquant"
        c24 = cam["continuity_24h"]
        for k in ("segments", "recorded_seconds", "gaps", "gap_count"):
            assert k in c24


def test_recorder_health_filter_by_camera_id():
    """Le paramètre camera_id doit filtrer."""
    r = httpx.get(f"{BASE}/api/diagnostics/recorder-health",
                  params={"camera_id": "demo-cam-001"},
                  headers=_auth(), timeout=15)
    assert r.status_code == 200
    d = r.json()
    ids = [c["camera_id"] for c in d["cameras"]]
    assert all(i == "demo-cam-001" for i in ids)


def test_recorder_health_included_in_dashboard():
    """Le health-dashboard agrégé doit contenir 'recorder' avec la nouvelle forme."""
    r = httpx.get(f"{BASE}/api/diagnostics/health-dashboard",
                  headers=_auth(), timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "recorder" in d
    rec = d["recorder"]
    # Forme nouvelle : dict avec cameras[] (pas juste une list)
    assert isinstance(rec, dict)
    assert "cameras" in rec or "error" in rec
