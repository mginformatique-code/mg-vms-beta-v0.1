"""Iteration 21 — RE-TEST du fix RTSP ONVIF POST /api/cameras :
- Cas A : mode='rtsp' + rtsp_url invalide + allow_rtsp_override=false → HTTP 400 avec 'URL RTSP invalide'
- Cas B : mode='rtsp' + rtsp_url valide (rtsp://127.0.0.1:8554/cam_demo-cam-001) + creds vides → 200 + codec/resolution
- Cas C : mode='rtsp' + rtsp_url invalide + allow_rtsp_override=true → doit soit accepter, soit refuser (comportement à documenter)
- Non-régression endpoints connexes
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


@pytest.fixture(scope="module")
def hdr():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=10)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def site_id(hdr):
    sites = requests.get(f"{BASE_URL}/api/sites", headers=hdr, timeout=10).json()
    assert sites, "au moins un site doit exister"
    return sites[0]["id"]


@pytest.fixture(scope="module", autouse=True)
def cleanup(hdr):
    yield
    # Cleanup toutes les caméras TEST_iter21_*
    cams = requests.get(f"{BASE_URL}/api/cameras", headers=hdr, timeout=10).json()
    for c in cams:
        if c.get("name", "").startswith("TEST_iter21_"):
            requests.delete(f"{BASE_URL}/api/cameras/{c['id']}", headers=hdr, timeout=10)


class TestRtspCreationValidation:
    def test_A_invalid_rtsp_override_false_returns_400(self, hdr, site_id):
        """CRITIQUE : URL RTSP invalide + override=false → HTTP 400 + message 'URL RTSP invalide'"""
        r = requests.post(f"{BASE_URL}/api/cameras", headers=hdr, json={
            "name": f"TEST_iter21_invalid_{uuid.uuid4().hex[:6]}",
            "site_id": site_id,
            "mode": "rtsp",
            "rtsp_url": "rtsp://127.0.0.1:8554/does_not_exist",
            "username": "",
            "password": "",
            "rtsp_transport": "tcp",
            "allow_rtsp_override": False,
        }, timeout=30)
        assert r.status_code == 400, f"Attendu 400, reçu {r.status_code} : {r.text}"
        detail = (r.json().get("detail") or "").lower()
        assert "url rtsp invalide" in detail or "invalid" in detail, f"Message inattendu : {detail}"

    def test_B_valid_rtsp_empty_creds_returns_200_with_codec(self, hdr, site_id):
        """REGRESSION : URL RTSP valide + creds vides → 200 + codec/resolution/fps depuis ffprobe"""
        r = requests.post(f"{BASE_URL}/api/cameras", headers=hdr, json={
            "name": f"TEST_iter21_valid_{uuid.uuid4().hex[:6]}",
            "site_id": site_id,
            "mode": "rtsp",
            "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
            "username": "",
            "password": "",
            "rtsp_transport": "tcp",
            "allow_rtsp_override": False,
        }, timeout=60)
        assert r.status_code == 200, f"Attendu 200, reçu {r.status_code} : {r.text}"
        cam = r.json()
        # ffprobe doit avoir rempli codec/resolution
        assert cam.get("codec"), f"codec manquant : {cam}"
        assert cam.get("resolution"), f"resolution manquante : {cam}"
        assert "x" in (cam.get("resolution") or ""), f"resolution invalide : {cam.get('resolution')}"

    def test_C_invalid_rtsp_override_true_behavior(self, hdr, site_id):
        """URL RTSP invalide + override=true → doit soit accepter (status=offline) soit rejeter avec 400 go2rtc.
        On documente le comportement observé, sans le contraindre.
        """
        r = requests.post(f"{BASE_URL}/api/cameras", headers=hdr, json={
            "name": f"TEST_iter21_override_{uuid.uuid4().hex[:6]}",
            "site_id": site_id,
            "mode": "rtsp",
            "rtsp_url": "rtsp://127.0.0.1:8554/does_not_exist",
            "username": "",
            "password": "",
            "rtsp_transport": "tcp",
            "allow_rtsp_override": True,
        }, timeout=30)
        # Doit être soit 200 (créé offline) soit 400 (go2rtc refuse)
        assert r.status_code in (200, 400), f"Statut inattendu {r.status_code} : {r.text}"
        print(f"\n[Cas C] override=true + invalid URL → HTTP {r.status_code}")


class TestRegressionEndpoints:
    def test_test_connectivity_still_works(self, hdr):
        r = requests.post(f"{BASE_URL}/api/cameras/test-connectivity", headers=hdr, json={
            "mode": "rtsp",
            "ip": "127.0.0.1",
            "rtsp_port": 8554,
            "rtsp_url": "rtsp://127.0.0.1:8554/cam_demo-cam-001",
            "username": "",
            "password": "",
            "rtsp_transport": "tcp",
            "preferred_codec": "auto",
        }, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "rtsp_url_validated" in body
        assert "debug_attempts" in body

    def test_diagnostic_still_works(self, hdr):
        r = requests.get(f"{BASE_URL}/api/cameras/demo-cam-001/diagnostic", headers=hdr, timeout=10)
        assert r.status_code == 200, r.text
        assert "rtsp_url_masked" in r.json().get("camera", {})

    def test_live_mjpeg_still_works(self, hdr):
        token = hdr["Authorization"].split(" ")[1]
        r = requests.get(f"{BASE_URL}/api/stream/demo-cam-001/live.mjpeg",
                         params={"token": token}, stream=True, timeout=8)
        assert r.status_code == 200
        assert "multipart/x-mixed-replace" in r.headers.get("content-type", "")
        r.close()
