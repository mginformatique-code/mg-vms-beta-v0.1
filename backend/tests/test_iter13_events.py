"""Test iter 13 review: events, timeline correlation, plates enrichment."""
import os
import datetime as dt
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://video-command-6.preview.emergentagent.com").rstrip("/")
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, r.text
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}"}


def test_events_list_structure(hdr):
    r = requests.get(f"{BASE_URL}/api/events", headers=hdr, params={"limit": 100}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list) and len(data) > 0, "No events found"
    print(f"Events count: {len(data)}")
    # Validate keys on a sample
    ev = data[0]
    for k in ("id", "timestamp", "type", "camera_name"):
        assert k in ev, f"missing key {k}"
    # thumbnail data URI
    with_thumb = [e for e in data if e.get("thumbnail", "").startswith("data:image/jpeg;base64,")]
    assert len(with_thumb) > 0, "No event has data-URI thumbnail"
    print(f"Events with thumbnail: {len(with_thumb)}")


def test_events_voiture_has_vehicle_color(hdr):
    r = requests.get(f"{BASE_URL}/api/events", headers=hdr, params={"type": "Voiture", "limit": 100}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    print(f"Voiture events: {len(data)}")
    with_color = [e for e in data if e.get("vehicle_color")]
    print(f"Voiture with color: {len(with_color)}")
    assert len(with_color) > 0, "No Voiture event has vehicle_color"
    ev = with_color[0]
    assert ev.get("confidence") is not None
    print(f"Sample voiture color: {ev.get('vehicle_color')} conf={ev.get('confidence')}")


def test_events_mouvement_has_motion_pct(hdr):
    r = requests.get(f"{BASE_URL}/api/events", headers=hdr, params={"type": "Mouvement", "limit": 50}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    print(f"Mouvement events: {len(data)}")
    if len(data) == 0:
        pytest.skip("No Mouvement events yet")
    with_pct = [e for e in data if isinstance(e.get("motion_pct"), (int, float))]
    assert len(with_pct) > 0, "No Mouvement event has numeric motion_pct"
    print(f"Sample motion_pct: {with_pct[0].get('motion_pct')}")


def test_timeline_correlation(hdr):
    today = dt.datetime.utcnow().strftime("%Y-%m-%d")
    r = requests.get(f"{BASE_URL}/api/recordings/timeline",
                     headers=hdr,
                     params={"camera_id": "demo-cam-002", "date": today},
                     timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    segs = data.get("segments") if isinstance(data, dict) else data
    assert isinstance(segs, list), f"segments not list: {type(segs)}"
    print(f"Segments count: {len(segs)}")
    assert len(segs) > 0, "No segments today"
    modes = {s.get("mode") for s in segs}
    print(f"Modes seen: {modes}")
    with_event = [s for s in segs if s.get("has_event")]
    print(f"Segments with has_event: {len(with_event)}")
    ai_or_motion = [s for s in segs if s.get("mode") in ("ai", "motion")]
    print(f"AI/motion segs: {len(ai_or_motion)}")
    assert len(ai_or_motion) > 0, "No segment has mode ai/motion"
    ev_seg = [s for s in segs if s.get("has_event") and s.get("event_type") and (s.get("event_count") or 0) >= 1]
    assert len(ev_seg) > 0, f"No segment with has_event+event_type+event_count>=1. Sample: {segs[0] if segs else None}"
    print(f"Sample event seg: mode={ev_seg[0].get('mode')} type={ev_seg[0].get('event_type')} count={ev_seg[0].get('event_count')}")


def test_plates_structure(hdr):
    r = requests.get(f"{BASE_URL}/api/plates", headers=hdr, params={"limit": 50}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    print(f"Plates: {len(data)}")
    if len(data) == 0:
        pytest.skip("No plates yet")
    p = data[0]
    for k in ("timestamp", "confidence"):
        assert k in p, f"missing key {k}"
    # vehicle_type / vehicle_color may be null but should exist as fields
    assert "vehicle_type" in p or "vehicle_color" in p, "Neither vehicle_type nor vehicle_color present in plate document"
    print(f"Sample plate keys: {list(p.keys())}")


def test_live_cameras_regression(hdr):
    r = requests.get(f"{BASE_URL}/api/cameras", headers=hdr, timeout=30)
    assert r.status_code == 200
    cams = r.json()
    assert len(cams) >= 2
    print(f"Total cameras: {len(cams)}")


def test_dashboard_regression(hdr):
    r = requests.get(f"{BASE_URL}/api/dashboard/stats", headers=hdr, timeout=30)
    assert r.status_code == 200
    print(f"Dashboard stats keys: {list(r.json().keys())}")
