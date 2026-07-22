"""Iteration 23 — ANPR watchlist & camera local-lists CSV import/export."""
import os
import io
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    # fallback to frontend .env
    with open('/app/frontend/.env') as f:
        for line in f:
            if line.startswith('REACT_APP_BACKEND_URL='):
                BASE_URL = line.split('=', 1)[1].strip().rstrip('/')

ADMIN_EMAIL = "admin@mg-vms.com"
ADMIN_PASSWORD = "Admin@2026"
TECH_EMAIL = "tech@mg-vms.com"
TECH_PASSWORD = "Tech@2026"

TEST_PLATES = ["TEST-AB123CD", "TEST-XY456ZZ", "TEST-PQ789RS", "TEST-BOM01AA"]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"login admin failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def tech_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": TECH_EMAIL, "password": TECH_PASSWORD})
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def demo_camera_id(h):
    r = requests.get(f"{BASE_URL}/api/cameras", headers=h)
    assert r.status_code == 200
    cams = r.json()
    for c in cams:
        if c["id"] == "demo-cam-001":
            return c["id"]
    return cams[0]["id"] if cams else "demo-cam-001"


@pytest.fixture(scope="module", autouse=True)
def cleanup(h):
    yield
    # cleanup test plates from watchlist
    r = requests.get(f"{BASE_URL}/api/watchlist", headers=h)
    if r.status_code == 200:
        for item in r.json():
            if item.get("plate", "").startswith("TEST-"):
                requests.delete(f"{BASE_URL}/api/watchlist/{item['id']}", headers=h)


# ═══ Watchlist import ═══
def test_import_watchlist_with_headers(h):
    csv_content = "plate,list_type,reason\nTEST-AB123CD,white,Employé\nTEST-XY456ZZ,black,Suspicion\n"
    files = {"csv_file": ("plates.csv", csv_content.encode(), "text/csv")}
    r = requests.post(f"{BASE_URL}/api/plugins/anpr/watchlist/import",
                      headers=h, files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["inserted"] + data["updated"] == 2
    assert data["errors"] == []

    # verify persisted
    r = requests.get(f"{BASE_URL}/api/watchlist", headers=h)
    plates = {i["plate"]: i for i in r.json()}
    assert "TEST-AB123CD" in plates
    assert plates["TEST-AB123CD"]["list_type"] == "white"
    assert plates["TEST-XY456ZZ"]["list_type"] == "black"


def test_import_plate_only_with_default(h):
    csv_content = "TEST-PQ789RS\n"
    files = {"csv_file": ("simple.csv", csv_content.encode(), "text/csv")}
    r = requests.post(f"{BASE_URL}/api/plugins/anpr/watchlist/import?default_list_type=white",
                      headers=h, files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] >= 1
    r = requests.get(f"{BASE_URL}/api/watchlist", headers=h)
    plates = {i["plate"]: i for i in r.json()}
    assert plates.get("TEST-PQ789RS", {}).get("list_type") == "white"


def test_import_with_utf8_bom(h):
    # Excel exports with BOM
    csv_content = "\ufeffplate,list_type,reason\nTEST-BOM01AA,white,BOM test\n".encode("utf-8")
    files = {"csv_file": ("bom.csv", csv_content, "text/csv")}
    r = requests.post(f"{BASE_URL}/api/plugins/anpr/watchlist/import",
                      headers=h, files=files)
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 1
    r = requests.get(f"{BASE_URL}/api/watchlist", headers=h)
    plates = {i["plate"] for i in r.json()}
    assert "TEST-BOM01AA" in plates


def test_import_with_invalid_list_type(h):
    csv_content = "plate,list_type,reason\nTEST-VALIDONE,white,ok\nTEST-INVALID,gris,bad\n"
    files = {"csv_file": ("mixed.csv", csv_content.encode(), "text/csv")}
    r = requests.post(f"{BASE_URL}/api/plugins/anpr/watchlist/import",
                      headers=h, files=files)
    assert r.status_code == 200
    data = r.json()
    assert len(data["errors"]) >= 1
    assert data["total"] >= 1  # only the valid one
    # cleanup
    r2 = requests.get(f"{BASE_URL}/api/watchlist", headers=h)
    for item in r2.json():
        if item.get("plate") in ("TEST-VALIDONE",):
            requests.delete(f"{BASE_URL}/api/watchlist/{item['id']}", headers=h)


def test_import_empty_csv_returns_400(h):
    files = {"csv_file": ("empty.csv", b"\n\n", "text/csv")}
    r = requests.post(f"{BASE_URL}/api/plugins/anpr/watchlist/import",
                      headers=h, files=files)
    assert r.status_code == 400


def test_import_all_invalid_returns_400(h):
    csv_content = "plate,list_type,reason\nAA,gris,x\nBB,foo,y\n"
    files = {"csv_file": ("bad.csv", csv_content.encode(), "text/csv")}
    r = requests.post(f"{BASE_URL}/api/plugins/anpr/watchlist/import",
                      headers=h, files=files)
    assert r.status_code == 400


def test_import_non_csv_extension_returns_400(h):
    files = {"csv_file": ("file.xlsx", b"binary content", "application/vnd.ms-excel")}
    r = requests.post(f"{BASE_URL}/api/plugins/anpr/watchlist/import",
                      headers=h, files=files)
    assert r.status_code == 400
    assert "CSV" in r.json().get("detail", "")


def test_import_too_large_returns_400(h):
    # ~2.5 MB of CSV
    big = ("TEST-LARGE" + "X" * 20 + ",white,pad\n") * 80000
    content = ("plate,list_type,reason\n" + big).encode()
    assert len(content) > 2 * 1024 * 1024
    files = {"csv_file": ("big.csv", content, "text/csv")}
    r = requests.post(f"{BASE_URL}/api/plugins/anpr/watchlist/import",
                      headers=h, files=files)
    assert r.status_code == 400


def test_upsert_reimport_increments_updated(h):
    # Re-import same plates
    csv_content = "plate,list_type,reason\nTEST-AB123CD,white,Updated reason\n"
    files = {"csv_file": ("re.csv", csv_content.encode(), "text/csv")}
    r = requests.post(f"{BASE_URL}/api/plugins/anpr/watchlist/import",
                      headers=h, files=files)
    assert r.status_code == 200
    data = r.json()
    assert data["updated"] >= 1
    assert data["inserted"] == 0

    # verify no duplicate & reason updated
    r = requests.get(f"{BASE_URL}/api/watchlist", headers=h)
    matches = [i for i in r.json() if i["plate"] == "TEST-AB123CD"]
    assert len(matches) == 1
    assert matches[0]["reason"] == "Updated reason"


# ═══ Watchlist export ═══
def test_export_watchlist_via_bearer(h):
    r = requests.get(f"{BASE_URL}/api/plugins/anpr/watchlist/export", headers=h)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("Content-Type", "")
    assert "attachment" in r.headers.get("Content-Disposition", "")
    assert r.text.startswith("plate,list_type,reason")


def test_export_watchlist_via_query_token(admin_token):
    """get_current_user must accept token as query param (for <a href> download)."""
    r = requests.get(f"{BASE_URL}/api/plugins/anpr/watchlist/export?token={admin_token}")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("Content-Type", "")
    assert r.text.startswith("plate,list_type,reason")


def test_get_without_auth_but_with_token_query(admin_token):
    """Sanity: any authenticated endpoint accepts token via query."""
    r = requests.get(f"{BASE_URL}/api/auth/me?token={admin_token}")
    assert r.status_code == 200
    assert r.json().get("email") == ADMIN_EMAIL


# ═══ Camera local list import / export ═══
def test_camera_whitelist_import_merge(h, demo_camera_id):
    # first import
    csv1 = "TEST-CAM-AA111\nTEST-CAM-BB222\n"
    files = {"csv_file": ("wl.csv", csv1.encode(), "text/csv")}
    r = requests.post(
        f"{BASE_URL}/api/plugins/anpr/cameras/{demo_camera_id}/lists/import?target=whitelist",
        headers=h, files=files)
    assert r.status_code == 200, r.text
    d1 = r.json()
    assert d1["target"] == "whitelist"
    total_after_first = d1["total"]

    # second import with 1 dup + 1 new → union, no duplicates
    csv2 = "TEST-CAM-BB222\nTEST-CAM-CC333\n"
    files = {"csv_file": ("wl2.csv", csv2.encode(), "text/csv")}
    r = requests.post(
        f"{BASE_URL}/api/plugins/anpr/cameras/{demo_camera_id}/lists/import?target=whitelist",
        headers=h, files=files)
    assert r.status_code == 200
    d2 = r.json()
    assert d2["total"] == total_after_first + 1  # only 1 new added

    # verify via GET /anpr/cameras/{id}
    r = requests.get(f"{BASE_URL}/api/plugins/anpr/cameras/{demo_camera_id}", headers=h)
    assert r.status_code == 200
    wl = r.json().get("whitelist_local", [])
    assert "TEST-CAM-AA111" in wl
    assert "TEST-CAM-BB222" in wl
    assert "TEST-CAM-CC333" in wl


def test_camera_blacklist_import(h, demo_camera_id):
    csv_c = "TEST-CAM-BL999\n"
    files = {"csv_file": ("bl.csv", csv_c.encode(), "text/csv")}
    r = requests.post(
        f"{BASE_URL}/api/plugins/anpr/cameras/{demo_camera_id}/lists/import?target=blacklist",
        headers=h, files=files)
    assert r.status_code == 200
    r = requests.get(f"{BASE_URL}/api/plugins/anpr/cameras/{demo_camera_id}", headers=h)
    assert "TEST-CAM-BL999" in r.json().get("blacklist_local", [])


def test_camera_list_export_whitelist(admin_token, demo_camera_id):
    r = requests.get(
        f"{BASE_URL}/api/plugins/anpr/cameras/{demo_camera_id}/lists/export?target=whitelist&token={admin_token}")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("Content-Type", "")
    assert r.text.startswith("plate")
    assert "TEST-CAM-AA111" in r.text or "TEST-CAM" in r.text


def test_camera_list_export_invalid_target(h, demo_camera_id):
    r = requests.get(
        f"{BASE_URL}/api/plugins/anpr/cameras/{demo_camera_id}/lists/export?target=bogus",
        headers=h)
    assert r.status_code == 400


def test_camera_list_import_invalid_target(h, demo_camera_id):
    files = {"csv_file": ("x.csv", b"AA\n", "text/csv")}
    r = requests.post(
        f"{BASE_URL}/api/plugins/anpr/cameras/{demo_camera_id}/lists/import?target=bogus",
        headers=h, files=files)
    assert r.status_code == 400


# ═══ Cleanup camera lists ═══
def test_cleanup_camera_local_lists(h, demo_camera_id):
    """Remove the TEST- plates from demo camera to keep env clean."""
    r = requests.get(f"{BASE_URL}/api/plugins/anpr/cameras/{demo_camera_id}", headers=h)
    cfg = r.json()
    wl = [p for p in cfg.get("whitelist_local", []) if not p.startswith("TEST-")]
    bl = [p for p in cfg.get("blacklist_local", []) if not p.startswith("TEST-")]
    cfg["whitelist_local"] = wl
    cfg["blacklist_local"] = bl
    r = requests.put(f"{BASE_URL}/api/plugins/anpr/cameras/{demo_camera_id}",
                     headers=h, json=cfg)
    assert r.status_code == 200


# ═══ Regression ═══
def test_regression_anpr_config_get(h):
    r = requests.get(f"{BASE_URL}/api/plugins/anpr/config", headers=h)
    assert r.status_code == 200
    assert "country" in r.json()


def test_regression_anpr_cameras_list(h):
    r = requests.get(f"{BASE_URL}/api/plugins/anpr/cameras", headers=h)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
