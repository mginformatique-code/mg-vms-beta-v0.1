"""Tests Map Center / Site Manager (v0.5.2 · Phase 1)."""
from pathlib import Path

import pytest
import requests

_env = Path("/app/frontend/.env").read_text()
BASE_URL = None
for line in _env.splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
assert BASE_URL

IMG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAeImBZsAAAAASUVORK5CYII="
)


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "admin@mg-vms.com", "password": "Admin@2026"},
                       timeout=8)
    assert r.status_code == 200
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def site_id(token):
    r = requests.get(f"{BASE_URL}/api/sites",
                      headers={"Authorization": f"Bearer {token}"}, timeout=8)
    assert r.status_code == 200 and r.json()
    return r.json()[0]["id"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_building_crud(token, site_id):
    # CREATE
    r = requests.post(f"{BASE_URL}/api/site-manager/buildings", headers=_auth(token),
                       json={"site_id": site_id, "name": "Bat Test v052", "order": 0},
                       timeout=8)
    assert r.status_code == 200
    bid = r.json()["id"]
    # LIST
    r2 = requests.get(f"{BASE_URL}/api/site-manager/buildings?site_id={site_id}",
                       headers=_auth(token), timeout=8)
    assert bid in [b["id"] for b in r2.json()]
    # PATCH
    r3 = requests.put(f"{BASE_URL}/api/site-manager/buildings/{bid}",
                       headers=_auth(token),
                       json={"name": "Bat Test v052 (renamed)"}, timeout=8)
    assert r3.status_code == 200
    assert r3.json()["name"] == "Bat Test v052 (renamed)"
    # DELETE
    r4 = requests.delete(f"{BASE_URL}/api/site-manager/buildings/{bid}",
                          headers=_auth(token), timeout=8)
    assert r4.status_code == 200


def test_plan_lifecycle_and_projection(token, site_id):
    r = requests.post(f"{BASE_URL}/api/site-manager/plans", headers=_auth(token),
                       json={"site_id": site_id, "name": "Plan Test",
                              "type": "rdc", "image_data_uri": IMG,
                              "width": 512, "height": 384},
                       timeout=8)
    assert r.status_code == 200
    pid = r.json()["id"]
    # List sans image_data_uri par défaut
    lst = requests.get(f"{BASE_URL}/api/site-manager/plans?site_id={site_id}",
                        headers=_auth(token), timeout=8).json()
    match = [p for p in lst if p["id"] == pid][0]
    assert "image_data_uri" not in match
    # Get complet avec image
    full = requests.get(f"{BASE_URL}/api/site-manager/plans/{pid}",
                         headers=_auth(token), timeout=8).json()
    assert full["image_data_uri"].startswith("data:image/")
    # Cleanup
    requests.delete(f"{BASE_URL}/api/site-manager/plans/{pid}",
                     headers=_auth(token), timeout=8)


def test_plan_rejects_invalid_image(token, site_id):
    r = requests.post(f"{BASE_URL}/api/site-manager/plans", headers=_auth(token),
                       json={"site_id": site_id, "name": "Bad",
                              "type": "rdc", "image_data_uri": "not-a-data-uri"},
                       timeout=8)
    assert r.status_code == 400


def test_camera_position_merge(token, site_id):
    # Crée un plan
    p = requests.post(f"{BASE_URL}/api/site-manager/plans", headers=_auth(token),
                       json={"site_id": site_id, "name": "P", "type": "rdc",
                              "image_data_uri": IMG},
                       timeout=8).json()
    pid = p["id"]
    # Trouve une caméra du site
    cams = requests.get(f"{BASE_URL}/api/cameras", headers=_auth(token), timeout=8).json()
    cam = next((c for c in cams if c.get("site_id") == site_id), None)
    if not cam:
        pytest.skip("Pas de caméra sur ce site")
    cid = cam["id"]
    # PUT position initiale
    r1 = requests.put(f"{BASE_URL}/api/site-manager/cameras/{cid}/position",
                       headers=_auth(token),
                       json={"plan_id": pid, "x": 100, "y": 200, "rotation": 30,
                              "height_m": 3, "angle_h": 90, "range_m": 20},
                       timeout=8)
    assert r1.status_code == 200
    assert r1.json()["map_position"]["x"] == 100
    # PUT patch partiel (x seul) → merge, height_m conservé
    r2 = requests.put(f"{BASE_URL}/api/site-manager/cameras/{cid}/position",
                       headers=_auth(token),
                       json={"x": 150}, timeout=8)
    mp = r2.json()["map_position"]
    assert mp["x"] == 150
    assert mp["height_m"] == 3
    # Verif liste par plan
    on_plan = requests.get(f"{BASE_URL}/api/site-manager/cameras?plan_id={pid}",
                            headers=_auth(token), timeout=8).json()
    assert any(c["id"] == cid for c in on_plan)
    # Clear
    requests.delete(f"{BASE_URL}/api/site-manager/cameras/{cid}/position",
                     headers=_auth(token), timeout=8)
    # Cleanup plan
    requests.delete(f"{BASE_URL}/api/site-manager/plans/{pid}",
                     headers=_auth(token), timeout=8)


def test_deleting_plan_unlinks_cameras(token, site_id):
    p = requests.post(f"{BASE_URL}/api/site-manager/plans", headers=_auth(token),
                       json={"site_id": site_id, "name": "P2", "type": "rdc",
                              "image_data_uri": IMG}, timeout=8).json()
    pid = p["id"]
    cams = requests.get(f"{BASE_URL}/api/cameras", headers=_auth(token), timeout=8).json()
    cam = next((c for c in cams if c.get("site_id") == site_id), None)
    if not cam:
        pytest.skip("Pas de caméra")
    cid = cam["id"]
    requests.put(f"{BASE_URL}/api/site-manager/cameras/{cid}/position",
                  headers=_auth(token), json={"plan_id": pid, "x": 10, "y": 10},
                  timeout=8)
    # Delete plan
    r = requests.delete(f"{BASE_URL}/api/site-manager/plans/{pid}",
                         headers=_auth(token), timeout=8)
    assert r.status_code == 200
    # La caméra ne doit plus être positionnée
    updated = next((c for c in requests.get(f"{BASE_URL}/api/cameras",
                                              headers=_auth(token), timeout=8).json()
                     if c["id"] == cid), None)
    assert (updated.get("map_position") or {}).get("plan_id") != pid


def test_site_accepts_enriched_fields(token):
    """Sites acceptent client_name, phone, contact_name, notes."""
    r = requests.post(f"{BASE_URL}/api/sites", headers=_auth(token),
                       json={"name": "Site v052 Test", "type": "commercial",
                              "address": "1 rue Test", "client_name": "Client SA",
                              "phone": "+33 1 23 45 67 89", "contact_name": "M. Dupont",
                              "notes": "Site d'audit"},
                       timeout=8)
    assert r.status_code == 200
    sid = r.json()["id"]
    got = requests.get(f"{BASE_URL}/api/sites", headers=_auth(token), timeout=8).json()
    match = [s for s in got if s["id"] == sid][0]
    assert match["client_name"] == "Client SA"
    assert match["phone"].startswith("+33")
    # cleanup
    requests.delete(f"{BASE_URL}/api/sites/{sid}", headers=_auth(token), timeout=8)


def test_map_endpoints_require_auth():
    r = requests.get(f"{BASE_URL}/api/site-manager/buildings", timeout=6)
    assert r.status_code in (401, 403)
    r2 = requests.get(f"{BASE_URL}/api/site-manager/plans", timeout=6)
    assert r2.status_code in (401, 403)
