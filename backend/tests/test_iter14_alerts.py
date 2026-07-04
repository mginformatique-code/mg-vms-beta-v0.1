"""Iteration 14: AI alert scenarios + vehicle color filter (case-insensitive)."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://video-command-6.preview.emergentagent.com").rstrip("/")
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}

EXPECTED_SCENARIOS = {"intrusion_nocturne", "vol_vehicule", "rodeur", "attroupement",
                     "vive_allure", "collision", "enfant_route"}


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}"}


# ----- Vehicle color filter (case-insensitive) -----
def test_plates_color_lowercase(h):
    r = requests.get(f"{BASE_URL}/api/plates", params={"color": "gris"}, headers=h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)
    for p in data:
        vc = (p.get("vehicle_color") or "").lower()
        assert vc == "gris", f"unexpected color {p.get('vehicle_color')}"


def test_plates_color_uppercase(h):
    r = requests.get(f"{BASE_URL}/api/plates", params={"color": "GRIS"}, headers=h, timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_plates_color_unknown_returns_empty_ok(h):
    r = requests.get(f"{BASE_URL}/api/plates", params={"color": "zzzunknown"}, headers=h, timeout=15)
    assert r.status_code == 200
    assert r.json() == []


# ----- AI Alert Rules -----
def test_get_ai_alert_rules_has_7_scenarios(h):
    r = requests.get(f"{BASE_URL}/api/ai/alert-rules", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    rules = r.json()
    assert isinstance(rules, dict)
    keys = set(rules.keys())
    assert EXPECTED_SCENARIOS.issubset(keys), f"missing: {EXPECTED_SCENARIOS - keys}"
    for k in EXPECTED_SCENARIOS:
        rule = rules[k]
        assert "enabled" in rule
        assert "severity" in rule
        assert "label" in rule


def test_put_ai_alert_rules_toggle_rodeur(h):
    # Read current
    r = requests.get(f"{BASE_URL}/api/ai/alert-rules", headers=h, timeout=15)
    original = r.json()["rodeur"].get("enabled", True)

    # Toggle off
    payload = {"rodeur": {"enabled": False}}
    r2 = requests.put(f"{BASE_URL}/api/ai/alert-rules", json=payload, headers=h, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["rodeur"]["enabled"] is False

    # Verify GET
    r3 = requests.get(f"{BASE_URL}/api/ai/alert-rules", headers=h, timeout=15)
    assert r3.json()["rodeur"]["enabled"] is False

    # Restore
    requests.put(f"{BASE_URL}/api/ai/alert-rules",
                 json={"rodeur": {"enabled": original}}, headers=h, timeout=15)


def test_put_ai_alert_rules_ignores_unknown_keys(h):
    r = requests.put(f"{BASE_URL}/api/ai/alert-rules",
                     json={"nonexistent_scenario": {"enabled": True}}, headers=h, timeout=15)
    assert r.status_code == 200
    assert "nonexistent_scenario" not in r.json()


# ----- Alerts with scenario -----
def test_enfant_route_alert_exists_with_thumbnail(h):
    r = requests.get(f"{BASE_URL}/api/alerts", headers=h, timeout=15, params={"limit": 200})
    assert r.status_code == 200
    alerts = r.json()
    assert isinstance(alerts, list)
    matches = [a for a in alerts if a.get("scenario") == "enfant_route"]
    assert len(matches) >= 1, "no enfant_route alert found"
    a = matches[0]
    assert a.get("severity") == "critical"
    assert a.get("camera_name") or a.get("camera_id")
    assert a.get("timestamp")
    # thumbnail may be data URI or url
    assert a.get("thumbnail") or a.get("snapshot") or a.get("image"), f"missing thumbnail keys: {list(a.keys())}"


def test_no_mongo_id_leak(h):
    r = requests.get(f"{BASE_URL}/api/alerts", headers=h, timeout=15, params={"limit": 20})
    assert r.status_code == 200
    for a in r.json():
        assert "_id" not in a


# ----- Trigger a scenario alert (intrusion_nocturne with wide window) -----
def test_trigger_intrusion_nocturne(h):
    # Snapshot original
    orig = requests.get(f"{BASE_URL}/api/ai/alert-rules", headers=h, timeout=15).json()["intrusion_nocturne"]

    # Enable and widen window
    requests.put(f"{BASE_URL}/api/ai/alert-rules", headers=h, timeout=15,
                 json={"intrusion_nocturne": {"enabled": True, "night_start": 0, "night_end": 23}})

    before = requests.get(f"{BASE_URL}/api/alerts", headers=h, timeout=15, params={"limit": 200}).json()
    before_ids = {a.get("id") for a in before if a.get("scenario") == "intrusion_nocturne"}

    triggered = False
    for _ in range(9):  # up to ~90s
        time.sleep(10)
        after = requests.get(f"{BASE_URL}/api/alerts", headers=h, timeout=15, params={"limit": 200}).json()
        new_ids = {a.get("id") for a in after if a.get("scenario") == "intrusion_nocturne"} - before_ids
        if new_ids:
            triggered = True
            break

    # Restore
    requests.put(f"{BASE_URL}/api/ai/alert-rules", headers=h, timeout=15,
                 json={"intrusion_nocturne": {
                     "enabled": orig.get("enabled", True),
                     "night_start": orig.get("night_start", 22),
                     "night_end": orig.get("night_end", 6),
                 }})

    assert triggered, "no new intrusion_nocturne alert produced within 90s (cooldown 180s may be active from earlier trigger)"
