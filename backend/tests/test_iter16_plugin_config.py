"""MG-VMS Iter 16 — Tests d'intégration pour la configuration production des plugins.

Couvre :
- ANPR global + par-caméra (ROI polygone, whitelist/blacklist locale)
- ByteTrack (bornes)
- Face Recognition (config + CRUD faces)
- Parking zones CRUD
- Access Control (CRUD + test TCP)
- Sensors thermal/radar/drone CRUD
- Storage overview / pools CRUD / assignment caméra
- /api/plugins statuts étendus
- Helper snapshot (auth + route existe)
"""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "admin": ("admin@mg-vms.com", "Admin@2026"),
    "tech": ("tech@mg-vms.com", "Tech@2026"),
    "viewer": ("viewer@mg-vms.com", "Viewer@2026"),
}


def _login(role):
    email, pwd = CREDS[role]
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=15)
    assert r.status_code == 200, f"login {role} failed: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def tokens():
    return {r: _login(r) for r in CREDS}


def H(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def demo_cam(tokens):
    r = requests.get(f"{API}/cameras", headers=H(tokens["admin"]), timeout=10)
    assert r.status_code == 200
    cams = r.json()
    assert cams, "no cameras in DB"
    # prefer demo-cam-001 if present
    for c in cams:
        if c["id"] in ("demo-cam-001", "demo-cam-002"):
            return c
    return cams[0]


# ══════════════════════════════════════════════════════════════
# ANPR — global + par caméra
# ══════════════════════════════════════════════════════════════
class TestAnprConfig:
    def test_global_get_defaults(self, tokens):
        r = requests.get(f"{API}/plugins/anpr/config", headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        d = r.json()
        # defaults per PRD
        assert d["country"] == "fr"
        assert d["min_plate_px"] == 24
        assert d["max_plate_px"] == 400
        assert "ocr_confidence" in d and "cache_seconds" in d

    def test_global_put_admin_only(self, tokens):
        # viewer forbidden
        r = requests.put(f"{API}/plugins/anpr/config",
                         headers=H(tokens["viewer"]),
                         json={"country": "de", "min_plate_px": 30, "max_plate_px": 350},
                         timeout=10)
        assert r.status_code == 403
        # tech forbidden (require_role admin)
        r = requests.put(f"{API}/plugins/anpr/config",
                         headers=H(tokens["tech"]),
                         json={"country": "de", "min_plate_px": 30, "max_plate_px": 350},
                         timeout=10)
        assert r.status_code == 403

    def test_global_put_and_persist(self, tokens):
        payload = {"country": "de", "min_plate_px": 30, "max_plate_px": 350,
                   "ocr_confidence": 0.6, "cache_seconds": 10,
                   "alert_on_blacklist": True, "alert_on_unknown": True}
        r = requests.put(f"{API}/plugins/anpr/config",
                         headers=H(tokens["admin"]), json=payload, timeout=10)
        assert r.status_code == 200, r.text
        # GET to verify persistence
        r = requests.get(f"{API}/plugins/anpr/config", headers=H(tokens["admin"]), timeout=10)
        d = r.json()
        assert d["country"] == "de"
        assert d["min_plate_px"] == 30
        assert d["alert_on_unknown"] is True
        # restore FR defaults
        requests.put(f"{API}/plugins/anpr/config", headers=H(tokens["admin"]),
                     json={"country": "fr", "min_plate_px": 24, "max_plate_px": 400,
                           "ocr_confidence": 0.55, "cache_seconds": 8,
                           "alert_on_blacklist": True, "alert_on_unknown": False}, timeout=10)

    def test_camera_config_get(self, tokens, demo_cam):
        r = requests.get(f"{API}/plugins/anpr/cameras/{demo_cam['id']}",
                         headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert "roi_polygon" in d and "whitelist_local" in d and "blacklist_local" in d

    def test_camera_config_rejects_polygon_lt_3(self, tokens, demo_cam):
        r = requests.put(f"{API}/plugins/anpr/cameras/{demo_cam['id']}",
                         headers=H(tokens["tech"]),
                         json={"enabled": True,
                               "roi_polygon": [[0.1, 0.1], [0.2, 0.2]],
                               "country_override": "", "whitelist_local": [],
                               "blacklist_local": [], "min_confidence": 0.5},
                         timeout=10)
        assert r.status_code == 400

    def test_camera_config_rejects_out_of_range(self, tokens, demo_cam):
        r = requests.put(f"{API}/plugins/anpr/cameras/{demo_cam['id']}",
                         headers=H(tokens["tech"]),
                         json={"enabled": True,
                               "roi_polygon": [[0.1, 0.1], [1.5, 0.2], [0.3, 0.3]],
                               "country_override": "", "whitelist_local": [],
                               "blacklist_local": [], "min_confidence": 0.5},
                         timeout=10)
        assert r.status_code == 400

    def test_camera_config_put_ok_and_normalize_plates(self, tokens, demo_cam):
        r = requests.put(f"{API}/plugins/anpr/cameras/{demo_cam['id']}",
                         headers=H(tokens["tech"]),
                         json={"enabled": True,
                               "roi_polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
                               "country_override": "de",
                               "whitelist_local": ["ab 123 cd", "  ", "xy456"],
                               "blacklist_local": ["ba-999-zz"],
                               "min_confidence": 0.4},
                         timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        # plates normalized: upper + no space; empty removed
        assert "AB123CD" in d["whitelist_local"]
        assert "XY456" in d["whitelist_local"]
        assert "" not in d["whitelist_local"]
        assert d["blacklist_local"] == ["BA-999-ZZ"]
        assert len(d["roi_polygon"]) == 4

    def test_camera_config_404(self, tokens):
        r = requests.get(f"{API}/plugins/anpr/cameras/does-not-exist",
                         headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 404

    def test_cameras_list(self, tokens):
        r = requests.get(f"{API}/plugins/anpr/cameras",
                         headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list) and len(arr) >= 1
        row = arr[0]
        for k in ("id", "name", "anpr_enabled", "roi_points", "wl_count", "bl_count"):
            assert k in row


# ══════════════════════════════════════════════════════════════
# ByteTrack
# ══════════════════════════════════════════════════════════════
class TestTracking:
    def test_get_defaults(self, tokens):
        r = requests.get(f"{API}/plugins/tracking/config",
                         headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        d = r.json()
        for k in ("enabled", "track_thresh", "match_thresh", "track_buffer", "id_persist_seconds"):
            assert k in d

    def test_put_clamps_bounds(self, tokens):
        r = requests.put(f"{API}/plugins/tracking/config",
                         headers=H(tokens["admin"]),
                         json={"enabled": True, "track_thresh": 5.0, "match_thresh": 0.01,
                               "track_buffer": 99999, "min_box_area": 100,
                               "id_persist_seconds": 99999},
                         timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["track_thresh"] == 0.9
        assert d["match_thresh"] == 0.5
        assert d["track_buffer"] == 300
        assert d["id_persist_seconds"] == 600
        # restore reasonable defaults
        requests.put(f"{API}/plugins/tracking/config", headers=H(tokens["admin"]),
                     json={"enabled": False, "track_thresh": 0.5, "match_thresh": 0.8,
                           "track_buffer": 30, "min_box_area": 100,
                           "id_persist_seconds": 60}, timeout=10)

    def test_put_admin_only(self, tokens):
        r = requests.put(f"{API}/plugins/tracking/config",
                         headers=H(tokens["tech"]),
                         json={"enabled": True, "track_thresh": 0.5, "match_thresh": 0.8,
                               "track_buffer": 30, "min_box_area": 100,
                               "id_persist_seconds": 60}, timeout=10)
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════
# Face recognition
# ══════════════════════════════════════════════════════════════
class TestFaceRecognition:
    def test_config_roundtrip(self, tokens):
        r = requests.put(f"{API}/plugins/face_recognition/config",
                         headers=H(tokens["admin"]),
                         json={"enabled": True, "distance_threshold": 0.55,
                               "model_name": "hog", "alert_on_unknown": False,
                               "alert_on_watchlist": True}, timeout=10)
        assert r.status_code == 200
        r = requests.get(f"{API}/plugins/face_recognition/config",
                         headers=H(tokens["admin"]), timeout=10)
        assert r.json()["distance_threshold"] == 0.55

    def test_faces_crud(self, tokens):
        r = requests.post(f"{API}/plugins/face_recognition/faces",
                         headers=H(tokens["tech"]),
                         json={"name": "TEST_face_iter16", "watchlist": True, "notes": "n"},
                         timeout=10)
        assert r.status_code == 200
        fid = r.json()["id"]
        assert r.json()["name"] == "TEST_face_iter16"
        # list
        r = requests.get(f"{API}/plugins/face_recognition/faces",
                        headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        assert any(f["id"] == fid for f in r.json())
        # empty name rejected
        r = requests.post(f"{API}/plugins/face_recognition/faces",
                         headers=H(tokens["tech"]), json={"name": "  "}, timeout=10)
        assert r.status_code == 400
        # viewer forbidden
        r = requests.post(f"{API}/plugins/face_recognition/faces",
                         headers=H(tokens["viewer"]), json={"name": "x"}, timeout=10)
        assert r.status_code == 403
        # delete
        r = requests.delete(f"{API}/plugins/face_recognition/faces/{fid}",
                           headers=H(tokens["tech"]), timeout=10)
        assert r.status_code == 200
        # delete 404
        r = requests.delete(f"{API}/plugins/face_recognition/faces/{fid}",
                           headers=H(tokens["tech"]), timeout=10)
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════
# Parking zones
# ══════════════════════════════════════════════════════════════
class TestParking:
    def test_crud(self, tokens, demo_cam):
        # create with <3 points -> 400
        r = requests.post(f"{API}/plugins/parking/zones", headers=H(tokens["tech"]),
                         json={"name": "TEST_zone", "camera_id": demo_cam["id"],
                               "polygon": [[0.1, 0.1], [0.2, 0.2]], "capacity": 5}, timeout=10)
        assert r.status_code == 400
        # invalid camera -> 400
        r = requests.post(f"{API}/plugins/parking/zones", headers=H(tokens["tech"]),
                         json={"name": "TEST_zone", "camera_id": "nope",
                               "polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]], "capacity": 5},
                         timeout=10)
        assert r.status_code == 400
        # create OK
        r = requests.post(f"{API}/plugins/parking/zones", headers=H(tokens["tech"]),
                         json={"name": "TEST_zone_iter16", "camera_id": demo_cam["id"],
                               "polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
                               "capacity": 10}, timeout=10)
        assert r.status_code == 200, r.text
        zid = r.json()["id"]
        assert r.json()["capacity"] == 10
        assert r.json()["camera_name"] == demo_cam["name"]
        # list contains
        r = requests.get(f"{API}/plugins/parking/zones",
                        headers=H(tokens["admin"]), timeout=10)
        assert any(z["id"] == zid for z in r.json())
        # update
        r = requests.put(f"{API}/plugins/parking/zones/{zid}", headers=H(tokens["tech"]),
                        json={"name": "TEST_zone_iter16_updated", "camera_id": demo_cam["id"],
                              "polygon": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
                              "capacity": 20}, timeout=10)
        assert r.status_code == 200
        assert r.json()["capacity"] == 20
        # delete
        r = requests.delete(f"{API}/plugins/parking/zones/{zid}",
                           headers=H(tokens["tech"]), timeout=10)
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════
# Access control controllers
# ══════════════════════════════════════════════════════════════
class TestAccessControl:
    def test_crud_and_tcp_test(self, tokens):
        r = requests.post(f"{API}/plugins/access_control/controllers",
                         headers=H(tokens["tech"]),
                         json={"name": "TEST_ctrl_iter16", "kind": "gate",
                               "ip": "127.0.0.1", "port": 22, "protocol": "http"}, timeout=10)
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        # update
        r = requests.put(f"{API}/plugins/access_control/controllers/{cid}",
                        headers=H(tokens["tech"]),
                        json={"name": "TEST_ctrl_iter16_up", "kind": "gate",
                              "ip": "127.0.0.1", "port": 22, "protocol": "http"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["name"] == "TEST_ctrl_iter16_up"
        # tcp test (SSH port 22 may be closed -> offline is acceptable)
        r = requests.post(f"{API}/plugins/access_control/controllers/{cid}/test",
                         headers=H(tokens["tech"]), timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] in ("online", "offline")
        # delete
        r = requests.delete(f"{API}/plugins/access_control/controllers/{cid}",
                           headers=H(tokens["tech"]), timeout=10)
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════
# Sensors thermal / radar / drone
# ══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("kind", ["thermal", "radar", "drone"])
class TestSensors:
    def test_crud(self, tokens, kind):
        r = requests.post(f"{API}/plugins/{kind}/sensors",
                         headers=H(tokens["tech"]),
                         json={"name": f"TEST_{kind}_iter16", "kind": kind,
                               "ip": "10.0.0.1", "port": 8080, "protocol": "http"},
                         timeout=10)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        assert r.json()["kind"] == kind
        # list
        r = requests.get(f"{API}/plugins/{kind}/sensors",
                        headers=H(tokens["admin"]), timeout=10)
        assert any(s["id"] == sid for s in r.json())
        # delete
        r = requests.delete(f"{API}/plugins/{kind}/sensors/{sid}",
                           headers=H(tokens["tech"]), timeout=10)
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════
# Snapshot helper (route exists + requires auth)
# ══════════════════════════════════════════════════════════════
class TestSnapshotHelper:
    def test_requires_auth(self, demo_cam):
        r = requests.get(f"{API}/plugins/_helpers/camera-snapshot/{demo_cam['id']}",
                         timeout=15)
        assert r.status_code == 401

    def test_returns_jpeg_or_404(self, tokens, demo_cam):
        r = requests.get(f"{API}/plugins/_helpers/camera-snapshot/{demo_cam['id']}",
                        headers=H(tokens["admin"]), timeout=15)
        assert r.status_code in (200, 404), r.status_code
        if r.status_code == 200:
            assert r.headers.get("content-type", "").startswith("image/jpeg")
            assert r.content[:3] == b"\xff\xd8\xff"


# ══════════════════════════════════════════════════════════════
# Storage overview / pools CRUD / camera assignment
# ══════════════════════════════════════════════════════════════
class TestStorage:
    def test_overview(self, tokens):
        r = requests.get(f"{API}/storage/overview",
                        headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert "partitions" in d and isinstance(d["partitions"], list)
        assert "pools" in d and isinstance(d["pools"], list)
        assert "primary_recordings_dir" in d

    def test_pool_admin_only(self, tokens):
        r = requests.post(f"{API}/storage/pools", headers=H(tokens["tech"]),
                         json={"name": "TEST_pool", "path": "/tmp/test_pool_x"}, timeout=10)
        assert r.status_code == 403

    def test_pool_crud_and_assignment(self, tokens, demo_cam):
        path = "/tmp/mgvms_test_pool_iter16"
        r = requests.post(f"{API}/storage/pools", headers=H(tokens["admin"]),
                         json={"name": "TEST_pool_iter16", "path": path,
                               "enabled": True, "max_size_gb": 5, "priority": 1},
                         timeout=15)
        assert r.status_code == 200, r.text
        pool_id = r.json()["id"]
        assert os.path.isdir(path)
        # forbidden path
        r = requests.post(f"{API}/storage/pools", headers=H(tokens["admin"]),
                         json={"name": "x", "path": "/etc/evil"}, timeout=10)
        assert r.status_code == 400
        # duplicate path
        r = requests.post(f"{API}/storage/pools", headers=H(tokens["admin"]),
                         json={"name": "dup", "path": path}, timeout=10)
        assert r.status_code == 400
        # update
        r = requests.put(f"{API}/storage/pools/{pool_id}", headers=H(tokens["admin"]),
                        json={"name": "TEST_pool_iter16_up", "path": path,
                              "enabled": False, "max_size_gb": 10, "priority": 2},
                        timeout=10)
        assert r.status_code == 200
        assert r.json()["name"] == "TEST_pool_iter16_up"

        # assignment
        r = requests.put(f"{API}/storage/cameras/{demo_cam['id']}/assignment",
                        headers=H(tokens["tech"]),
                        json={"storage_pool_id": pool_id, "max_size_gb": 5,
                              "record_mode": "motion", "profile_token": "MainStream"},
                        timeout=10)
        assert r.status_code == 200
        # GET assignment
        r = requests.get(f"{API}/storage/cameras/{demo_cam['id']}/assignment",
                        headers=H(tokens["admin"]), timeout=10)
        d = r.json()
        assert d["storage_pool_id"] == pool_id
        assert d["record_mode"] == "motion"
        assert d["profile_token"] == "MainStream"

        # invalid mode
        r = requests.put(f"{API}/storage/cameras/{demo_cam['id']}/assignment",
                        headers=H(tokens["tech"]),
                        json={"storage_pool_id": pool_id, "max_size_gb": 0,
                              "record_mode": "bogus", "profile_token": ""},
                        timeout=10)
        assert r.status_code == 400

        # invalid pool_id
        r = requests.put(f"{API}/storage/cameras/{demo_cam['id']}/assignment",
                        headers=H(tokens["tech"]),
                        json={"storage_pool_id": "does-not-exist", "max_size_gb": 0,
                              "record_mode": "continuous", "profile_token": ""},
                        timeout=10)
        assert r.status_code == 400

        # cannot delete pool while assigned
        r = requests.delete(f"{API}/storage/pools/{pool_id}",
                           headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 400

        # detach
        r = requests.put(f"{API}/storage/cameras/{demo_cam['id']}/assignment",
                        headers=H(tokens["tech"]),
                        json={"storage_pool_id": "", "max_size_gb": 0,
                              "record_mode": "continuous", "profile_token": ""},
                        timeout=10)
        assert r.status_code == 200

        # delete pool
        r = requests.delete(f"{API}/storage/pools/{pool_id}",
                           headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        # cleanup dir
        try:
            os.rmdir(path)
        except OSError:
            pass


# ══════════════════════════════════════════════════════════════
# /api/plugins — health checks étendus
# ══════════════════════════════════════════════════════════════
class TestPluginsHealth:
    def test_list_plugins(self, tokens):
        r = requests.get(f"{API}/plugins", headers=H(tokens["admin"]), timeout=15)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list) and len(arr) >= 5
        ids = {p.get("id") or p.get("key") or p.get("name") for p in arr}
        # expected plugins present
        expected = {"anpr", "tracking", "face_recognition", "parking",
                    "access_control", "thermal", "radar", "drone"}
        assert expected.issubset({str(x).lower() for x in ids}), f"got={ids}"
