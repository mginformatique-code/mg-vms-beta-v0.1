"""Iteration 18 — Finalisation chaîne vidéo, IA, événements et exploitation.
Tests P0 :
- REGRESSION live.mjpeg (boundary + bytes > 0)
- REGRESSION frame.jpeg (JPEG magic)
- Nouveaux champs rtsp_transport / preferred_codec (persistance)
- Nouvel endpoint /cameras/{id}/diagnostic (structure)
- URL RTSP contient #transport=tcp|udp
- Régression /api/plugins, /api/storage/overview, /api/plugins/anpr/config
"""
import os
import re
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}
DEMOS = ["demo-cam-001", "demo-cam-002"]


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_h(token):
    return {"Authorization": f"Bearer {token}"}


# ============ P0.a live.mjpeg ============
@pytest.mark.parametrize("cam_id", DEMOS)
def test_live_mjpeg_boundary_and_bytes(cam_id, token):
    url = f"{BASE_URL}/api/stream/{cam_id}/live.mjpeg?token={token}"
    with requests.get(url, stream=True, timeout=15) as r:
        assert r.status_code == 200, f"HTTP {r.status_code} pour {cam_id}"
        ct = r.headers.get("content-type", "")
        assert "multipart/x-mixed-replace" in ct.lower(), f"content-type manquant multipart: {ct}"
        assert "boundary=" in ct.lower(), f"boundary manquant dans content-type: {ct}"
        # Récupère les premières données (attente 3s max)
        received = 0
        deadline = time.time() + 3.5
        for chunk in r.iter_content(chunk_size=4096):
            if chunk:
                received += len(chunk)
            if received > 5000 or time.time() > deadline:
                break
        assert received > 1000, f"Reçu seulement {received} bytes en 3s (attendu >1kB)"


# ============ P0.b frame.jpeg ============
@pytest.mark.parametrize("cam_id", DEMOS)
def test_frame_jpeg_returns_jpeg(cam_id, token):
    url = f"{BASE_URL}/api/stream/{cam_id}/frame.jpeg?token={token}"
    r = requests.get(url, timeout=15)
    assert r.status_code == 200, f"HTTP {r.status_code} pour {cam_id}"
    assert r.content[:3] == b"\xff\xd8\xff", f"pas un JPEG (magic={r.content[:3]!r})"


# ============ P0.c rtsp_transport / preferred_codec dans CameraInput ============
def test_create_camera_with_new_fields(auth_h):
    # Récupère un site_id valide
    sites = requests.get(f"{BASE_URL}/api/sites", headers=auth_h, timeout=10).json()
    assert sites, "no sites"
    site_id = sites[0]["id"]
    payload = {
        "name": "TEST_iter18_cam",
        "site_id": site_id,
        "mode": "rtsp",
        "rtsp_url": "rtsp://192.0.2.10:554/live",
        "username": "user",
        "password": "pw",
        "rtsp_transport": "udp",
        "preferred_codec": "h265",
    }
    r = requests.post(f"{BASE_URL}/api/cameras", json=payload, headers=auth_h, timeout=15)
    assert r.status_code in (200, 201), r.text
    body = r.json()
    cam_id = body.get("id") or body.get("camera", {}).get("id")
    assert cam_id, f"pas d'id: {body}"

    # GET pour vérifier persistance
    g = requests.get(f"{BASE_URL}/api/cameras/{cam_id}", headers=auth_h, timeout=15)
    assert g.status_code == 200
    cam = g.json()
    assert cam.get("rtsp_transport") == "udp", cam
    assert cam.get("preferred_codec") == "h265", cam

    # PUT change
    r2 = requests.put(f"{BASE_URL}/api/cameras/{cam_id}",
                      json={**payload, "rtsp_transport": "tcp", "preferred_codec": "h264"},
                      headers=auth_h, timeout=15)
    assert r2.status_code == 200, r2.text
    g2 = requests.get(f"{BASE_URL}/api/cameras/{cam_id}", headers=auth_h, timeout=15).json()
    assert g2["rtsp_transport"] == "tcp"
    assert g2["preferred_codec"] == "h264"

    # Cleanup
    requests.delete(f"{BASE_URL}/api/cameras/{cam_id}", headers=auth_h, timeout=15)


# ============ P0.d diagnostic endpoint ============
@pytest.mark.parametrize("cam_id", DEMOS)
def test_camera_diagnostic_structure(cam_id, auth_h):
    r = requests.get(f"{BASE_URL}/api/cameras/{cam_id}/diagnostic", headers=auth_h, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for key in ("camera", "flux", "ai", "stats_24h", "last_event", "last_plate"):
        assert key in d, f"missing key {key} in diagnostic"
    # camera fields
    for k in ("rtsp_transport", "preferred_codec", "record_mode"):
        assert k in d["camera"], f"camera.{k} manquant"
    # flux fields
    assert isinstance(d["flux"]["go2rtc_registered"], bool)
    assert isinstance(d["flux"]["camera_online"], bool)
    # ai fields
    assert "detect_enabled" in d["ai"]
    assert "last_yolo_ms" in d["ai"]
    # stats
    assert "events" in d["stats_24h"]
    assert "plates" in d["stats_24h"]


# ============ P0.e URL RTSP inclut #transport ============
def test_rtsp_url_has_transport_fragment():
    """Test unitaire direct sur _build_rtsp_url via subprocess pour éviter le côté Motor."""
    import subprocess
    code = (
        "import sys, os; sys.path.insert(0,'/app/backend'); "
        "from dotenv import load_dotenv; load_dotenv('/app/backend/.env'); "
        "from streaming import _build_rtsp_url; "
        "u1=_build_rtsp_url({'rtsp_url':'rtsp://1.2.3.4/live','username':'a','password':'b','rtsp_transport':'udp'}); "
        "u2=_build_rtsp_url({'rtsp_url':'rtsp://1.2.3.4/live','username':'a','password':'b','rtsp_transport':'tcp'}); "
        "u3=_build_rtsp_url({'rtsp_url':'rtsp://1.2.3.4/live'}); "
        "print(u1);print(u2);print(u3)"
    )
    p = subprocess.run(["python3", "-c", code], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    lines = p.stdout.strip().splitlines()
    assert lines[0].endswith("#transport=udp"), lines
    assert lines[1].endswith("#transport=tcp"), lines
    assert lines[2].endswith("#transport=tcp"), lines


# ============ Régressions ============
def test_regression_plugins(auth_h):
    r = requests.get(f"{BASE_URL}/api/plugins", headers=auth_h, timeout=15)
    assert r.status_code == 200
    data = r.json()
    plugins = data if isinstance(data, list) else data.get("plugins", [])
    assert len(plugins) >= 8, f"attendu ≥8 plugins, reçu {len(plugins)}"


def test_regression_storage_overview(auth_h):
    r = requests.get(f"{BASE_URL}/api/storage/overview", headers=auth_h, timeout=15)
    assert r.status_code == 200, r.text


def test_regression_anpr_config(auth_h):
    r = requests.get(f"{BASE_URL}/api/plugins/anpr/config", headers=auth_h, timeout=15)
    assert r.status_code == 200, r.text
