"""Backend tests — Network Supervision module (P1)."""
import os
import time
import pytest
import requests
from pathlib import Path

BACKEND = os.environ.get("REACT_APP_BACKEND_URL")
if not BACKEND:
    env_path = Path("/app/frontend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                BACKEND = line.split("=", 1)[1].strip()
                break
BASE = BACKEND.rstrip("/") + "/api"

ADMIN = ("admin@mg-vms.com", "Admin@2026")
TECH = ("tech@mg-vms.com", "Tech@2026")
VIEWER = ("viewer@mg-vms.com", "Viewer@2026")


def _login(email, password, attempts=4):
    last = None
    for i in range(attempts):
        r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=15)
        if r.status_code == 200:
            return r.json()["access_token"]
        last = r
        time.sleep(2 + i * 2)
    pytest.skip(f"login failed {email}: {last.status_code} {last.text[:160]}")


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(*ADMIN)}"}


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login(*TECH)}"}


@pytest.fixture(scope="module")
def viewer_h():
    return {"Authorization": f"Bearer {_login(*VIEWER)}"}


# -------- network/stats & topology
def test_network_stats(admin_h):
    r = requests.get(f"{BASE}/network/stats", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ["total", "online", "warning", "offline", "ups_on_battery"]:
        assert k in d, k
        assert isinstance(d[k], int)
    assert d["total"] >= 1, "seed_equipment should produce >=1 equipment"


def test_network_topology(admin_h):
    r = requests.get(f"{BASE}/network/topology", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "nodes" in d and "edges" in d
    assert isinstance(d["nodes"], list) and isinstance(d["edges"], list)
    assert len(d["nodes"]) >= 1
    n = d["nodes"][0]
    for k in ["id", "name", "type", "status", "site_id"]:
        assert k in n
    ids = {x["id"] for x in d["nodes"]}
    for e in d["edges"]:
        assert e["source"] in ids and e["target"] in ids
        assert e["status"] in ("up", "down")


# -------- equipment list
def test_list_equipment(admin_h):
    r = requests.get(f"{BASE}/network/equipment", headers=admin_h, timeout=15)
    assert r.status_code == 200
    eqs = r.json()
    assert isinstance(eqs, list) and len(eqs) > 0
    for e in eqs[:5]:
        assert "_id" not in e
        assert e["status"] in ("online", "warning", "offline")


def test_list_equipment_filter_type(admin_h):
    r = requests.get(f"{BASE}/network/equipment", headers=admin_h, params={"type": "UPS"}, timeout=15)
    assert r.status_code == 200
    for e in r.json():
        assert e["type"] == "UPS"


# -------- CRUD
@pytest.fixture(scope="module")
def site_id(admin_h):
    r = requests.get(f"{BASE}/sites", headers=admin_h, timeout=15)
    assert r.status_code == 200
    sites = r.json()
    assert sites
    return sites[0]["id"]


def test_create_get_update_delete_equipment(tech_h, site_id):
    payload = {"name": "TEST_NET_SW01", "type": "Switch", "site_id": site_id, "ip": "10.99.0.1", "vendor": "Cisco"}
    r = requests.post(f"{BASE}/network/equipment", headers=tech_h, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["name"] == "TEST_NET_SW01" and created["type"] == "Switch"
    assert created["site_id"] == site_id
    assert "id" in created
    eq_id = created["id"]

    # GET verify
    g = requests.get(f"{BASE}/network/equipment/{eq_id}", headers=tech_h, timeout=15)
    assert g.status_code == 200
    assert g.json()["name"] == "TEST_NET_SW01"

    # invalid type
    bad = requests.post(f"{BASE}/network/equipment", headers=tech_h,
                       json={**payload, "name": "TEST_NET_BAD", "type": "WHATEVER"}, timeout=15)
    assert bad.status_code == 400

    # UPDATE
    u = requests.put(f"{BASE}/network/equipment/{eq_id}", headers=tech_h,
                     json={**payload, "name": "TEST_NET_SW01b", "vendor": "Aruba"}, timeout=15)
    assert u.status_code == 200
    assert u.json()["name"] == "TEST_NET_SW01b"

    # DELETE
    d = requests.delete(f"{BASE}/network/equipment/{eq_id}", headers=tech_h, timeout=15)
    assert d.status_code == 200
    assert d.json().get("ok") is True

    # confirm 404
    g2 = requests.get(f"{BASE}/network/equipment/{eq_id}", headers=tech_h, timeout=15)
    assert g2.status_code == 404


def test_viewer_cannot_create(viewer_h, site_id):
    r = requests.post(f"{BASE}/network/equipment", headers=viewer_h,
                      json={"name": "TEST_NET_DENY", "type": "Switch", "site_id": site_id}, timeout=15)
    assert r.status_code in (401, 403)


# -------- ping & poll
def test_ping_equipment(admin_h):
    eqs = requests.get(f"{BASE}/network/equipment", headers=admin_h, timeout=15).json()
    assert eqs
    eq_id = eqs[0]["id"]
    r = requests.post(f"{BASE}/network/equipment/{eq_id}/ping", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "equipment" in d and "result" in d
    assert d["equipment"]["id"] == eq_id
    assert d["equipment"]["status"] in ("online", "warning", "offline")


def test_ping_404(admin_h):
    r = requests.post(f"{BASE}/network/equipment/does-not-exist/ping", headers=admin_h, timeout=15)
    assert r.status_code == 404


def test_poll_all_tech(tech_h):
    r = requests.post(f"{BASE}/network/poll", headers=tech_h, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "polled" in d and "alerts_raised" in d
    assert isinstance(d["polled"], int) and d["polled"] >= 1


def test_poll_viewer_denied(viewer_h):
    r = requests.post(f"{BASE}/network/poll", headers=viewer_h, timeout=15)
    assert r.status_code in (401, 403)


# -------- site cloisonnement
def test_viewer_site_scope(viewer_h, admin_h):
    """Viewer should see only equipment from sites they are assigned to (subset of admin's view)."""
    admin_eqs = requests.get(f"{BASE}/network/equipment", headers=admin_h, timeout=15).json()
    viewer_eqs = requests.get(f"{BASE}/network/equipment", headers=viewer_h, timeout=15).json()
    admin_sites = {e["site_id"] for e in admin_eqs}
    viewer_sites = {e["site_id"] for e in viewer_eqs}
    assert viewer_sites.issubset(admin_sites)
    # if viewer has site restriction, expect strict subset
    me = requests.get(f"{BASE}/auth/me", headers=viewer_h, timeout=15).json()
    if me.get("sites"):
        assert viewer_sites.issubset(set(me["sites"]))


# -------- regression : recordings
def test_recordings_timeline(admin_h):
    # need a camera_id
    cams = requests.get(f"{BASE}/cameras", headers=admin_h, timeout=15).json()
    if not cams:
        pytest.skip("no cameras seeded")
    cam_id = cams[0]["id"]
    r = requests.get(f"{BASE}/recordings/timeline", headers=admin_h,
                     params={"camera_id": cam_id}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert isinstance(d, (list, dict))
