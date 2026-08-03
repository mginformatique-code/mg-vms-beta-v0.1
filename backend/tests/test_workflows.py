"""Tests P4 · Workflow Engine — triggers, conditions, execution."""
import asyncio

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


# ── Conditions unitaires ────────────────────────────────────────────
def test_condition_field_equals():
    from workflow_engine import _eval_condition
    assert _eval_condition({"type": "field_equals", "path": "data.plate", "value": "AB-1"},
                           {"data": {"plate": "AB-1"}}) is True
    assert _eval_condition({"type": "field_equals", "path": "data.plate", "value": "X"},
                           {"data": {"plate": "AB-1"}}) is False


def test_condition_camera_is():
    from workflow_engine import _eval_condition
    assert _eval_condition({"type": "camera_is", "cameras": ["cam1"]},
                           {"camera_id": "cam1"}) is True
    assert _eval_condition({"type": "camera_is", "cameras": ["cam1"]},
                           {"camera_id": "cam2"}) is False


def test_condition_plate_in_list():
    from workflow_engine import _eval_condition
    assert _eval_condition({"type": "plate_in_list", "lists": ["black"]},
                           {"list_status": "black"}) is True
    assert _eval_condition({"type": "plate_in_list", "lists": ["black"]},
                           {"list_status": "white"}) is False


def test_trigger_matches_event_type():
    from workflow_engine import _trigger_matches
    assert _trigger_matches({"type": "event.type", "event_type": "plate.blacklist"},
                            {"type": "plate.blacklist"}) is True
    assert _trigger_matches({"type": "event.type", "event_type": "plate.blacklist"},
                            {"type": "other"}) is False


def test_trigger_matches_zone_enter():
    from workflow_engine import _trigger_matches
    assert _trigger_matches({"type": "zone.enter"}, {"type": "zone.enter"}) is True
    # Avec zone_id spécifique
    assert _trigger_matches({"type": "zone.enter", "zone_id": "z1"},
                            {"type": "zone.enter", "data": {"zone_id": "z1"}}) is True
    assert _trigger_matches({"type": "zone.enter", "zone_id": "z1"},
                            {"type": "zone.enter", "data": {"zone_id": "z2"}}) is False


# ── CRUD API ────────────────────────────────────────────────────────
def test_workflow_lifecycle():
    payload = {
        "name": "TEST-WF",
        "enabled": True,
        "description": "Test workflow",
        "triggers": [{"type": "event.type", "event_type": "plate.blacklist"}],
        "conditions": [{"type": "plate_in_list", "lists": ["black"]}],
        "actions": [{"type": "delay", "config": {"seconds": 0}}],
    }
    # CREATE
    r = httpx.post(f"{BASE}/api/workflows", json=payload, headers=_auth(), timeout=10)
    assert r.status_code == 200, r.text
    wf = r.json()
    wid = wf["id"]

    # GET
    r = httpx.get(f"{BASE}/api/workflows/{wid}", headers=_auth(), timeout=10)
    assert r.status_code == 200
    assert "runtime" in r.json()

    # LIST
    r = httpx.get(f"{BASE}/api/workflows", headers=_auth(), timeout=10)
    assert r.status_code == 200
    assert any(w["id"] == wid for w in r.json()["workflows"])

    # RUN manuel
    r = httpx.post(f"{BASE}/api/workflows/{wid}/run", json={"foo": "bar"}, headers=_auth(), timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "running")

    # UPDATE
    payload["enabled"] = False
    r = httpx.put(f"{BASE}/api/workflows/{wid}", json=payload, headers=_auth(), timeout=10)
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    # DELETE
    r = httpx.delete(f"{BASE}/api/workflows/{wid}", headers=_auth(), timeout=10)
    assert r.status_code == 200


def test_run_unknown_workflow_returns_400():
    r = httpx.post(f"{BASE}/api/workflows/nonexistent/run", headers=_auth(), timeout=10)
    assert r.status_code == 400
