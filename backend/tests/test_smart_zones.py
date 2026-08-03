"""Tests P3 · Smart Zones — engine, actuators, CRUD."""
import asyncio
import time

import httpx
import pytest


BASE = "http://localhost:8001"
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


def _token():
    r = httpx.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=10)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d.get("token")


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


# ── Engine · point-in-polygon ─────────────────────────────────────────
def test_bbox_in_polygon_relative_coords():
    from smart_zones.engine import SmartZonesEngine
    poly = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
    # bbox center 0.5, 0.5 → inside
    assert SmartZonesEngine._bbox_in_polygon((0.4, 0.4, 0.2, 0.2), poly) is True
    # bbox center 0.05, 0.05 → outside
    assert SmartZonesEngine._bbox_in_polygon((0.0, 0.0, 0.05, 0.05), poly) is False


def test_empty_polygon_matches_everything():
    from smart_zones.engine import SmartZonesEngine
    assert SmartZonesEngine._bbox_in_polygon((0.5, 0.5, 0.1, 0.1), []) is True


# ── Actuators · dispatch avec type inconnu ────────────────────────────
def test_dispatch_unknown_type_returns_error():
    from smart_zones.actuators import dispatch_action
    async def _run():
        r = await dispatch_action({"type": "nonexistent"}, {})
        assert r["ok"] is False
        assert "inconnu" in r["error"]
    asyncio.run(_run())


def test_dispatch_webhook_missing_url():
    from smart_zones.actuators import dispatch_action
    async def _run():
        r = await dispatch_action({"type": "webhook", "config": {}}, {"zone_name": "z"})
        assert r["ok"] is False
    asyncio.run(_run())


def test_interpolation_replaces_placeholders():
    from smart_zones.actuators import _interpolate
    ctx = {"zone_name": "Entrée", "camera_id": "cam1", "class": "person"}
    assert _interpolate("Alerte {zone_name} on {camera_id}", ctx) == "Alerte Entrée on cam1"
    assert _interpolate({"msg": "{class}"}, ctx) == {"msg": "person"}
    assert _interpolate(["a", "{zone_name}"], ctx) == ["a", "Entrée"]


# ── CRUD API ───────────────────────────────────────────────────────────
def test_create_zone_requires_valid_camera():
    r = httpx.post(f"{BASE}/api/smart-zones",
                    json={"name": "z", "camera_id": "unknown-cam"},
                    headers=_auth(), timeout=10)
    assert r.status_code == 400


def test_create_get_update_delete_zone_lifecycle():
    # Trouve une caméra existante
    r = httpx.get(f"{BASE}/api/cameras", headers=_auth(), timeout=10)
    cams = r.json()
    assert cams, "il faut au moins une caméra en DB"
    cam_id = cams[0]["id"]

    # CREATE
    payload = {
        "name": "TEST-ZONE-P3",
        "camera_id": cam_id,
        "enabled": True,
        "polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        "detect": {"classes": ["person"], "min_confidence": 0.5, "min_dwell_seconds": 0, "cooldown_seconds": 30},
        "trigger_on": ["enter", "exit"],
        "actions": [
            {"type": "webhook", "config": {"url": "http://localhost:1", "body": {"msg": "{zone_name}"}}},
        ],
    }
    r = httpx.post(f"{BASE}/api/smart-zones", json=payload, headers=_auth(), timeout=10)
    assert r.status_code == 200, r.text
    zone = r.json()
    zid = zone["id"]

    # GET single
    r = httpx.get(f"{BASE}/api/smart-zones/{zid}", headers=_auth(), timeout=10)
    assert r.status_code == 200
    assert r.json()["name"] == "TEST-ZONE-P3"

    # LIST filtered by camera
    r = httpx.get(f"{BASE}/api/smart-zones", params={"camera_id": cam_id}, headers=_auth(), timeout=10)
    assert r.status_code == 200
    assert any(z["id"] == zid for z in r.json()["zones"])

    # UPDATE
    payload["name"] = "TEST-ZONE-P3-updated"
    r = httpx.put(f"{BASE}/api/smart-zones/{zid}", json=payload, headers=_auth(), timeout=10)
    assert r.status_code == 200
    assert r.json()["name"] == "TEST-ZONE-P3-updated"

    # DELETE
    r = httpx.delete(f"{BASE}/api/smart-zones/{zid}", headers=_auth(), timeout=10)
    assert r.status_code == 200


def test_actuators_list_endpoint():
    r = httpx.get(f"{BASE}/api/smart-zones/actuators/available", headers=_auth(), timeout=10)
    assert r.status_code == 200
    types = {a["type"] for a in r.json()["actuators"]}
    assert {"webhook", "mqtt", "home_assistant", "tuya", "plugin", "tts"} <= types


def test_get_unknown_zone_returns_404():
    r = httpx.get(f"{BASE}/api/smart-zones/nonexistent-uuid",
                  headers=_auth(), timeout=10)
    assert r.status_code == 404
