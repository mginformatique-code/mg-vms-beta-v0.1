"""Tests for granular per-user permissions (iteration 11)."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://video-command-6.preview.emergentagent.com").rstrip("/")

ADMIN = ("admin@mg-vms.com", "Admin@2026")
TECH = ("tech@mg-vms.com", "Tech@2026")
VIEWER = ("viewer@mg-vms.com", "Viewer@2026")
PERM = ("perm@mg-vms.com", "Perm@2026")

PERMISSIONS = ["view_live", "view_recordings", "read_plates", "stream_hd", "ptz_control", "export_files"]


def _login(email, pwd):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pwd}, timeout=15)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def tech_token():
    return _login(*TECH)


@pytest.fixture(scope="module")
def viewer_token():
    return _login(*VIEWER)


@pytest.fixture(scope="module")
def perm_token():
    return _login(*PERM)


# ---------- /auth/me retourne permissions ----------
class TestAuthMePermissions:
    def test_admin_me_all_true(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(admin_token))
        assert r.status_code == 200
        perms = r.json().get("permissions")
        assert perms is not None
        assert set(perms.keys()) == set(PERMISSIONS)
        for p in PERMISSIONS:
            assert perms[p] is True, f"admin should have {p}=True"

    def test_tech_me_all_true(self, tech_token):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(tech_token))
        assert r.status_code == 200
        perms = r.json()["permissions"]
        for p in PERMISSIONS:
            assert perms[p] is True

    def test_perm_user_only_view_live(self, perm_token):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(perm_token))
        assert r.status_code == 200
        perms = r.json()["permissions"]
        assert perms["view_live"] is True
        for p in ["view_recordings", "read_plates", "stream_hd", "ptz_control", "export_files"]:
            assert perms[p] is False, f"perm@ should have {p}=False but got {perms[p]}"


# ---------- RBAC sur /users (admin uniquement) ----------
class TestUsersRBAC:
    def test_tech_cannot_create(self, tech_token):
        r = requests.post(f"{BASE_URL}/api/users",
                          headers=_h(tech_token),
                          json={"email": f"TEST_x_{uuid.uuid4().hex[:6]}@t.com", "password": "Pwd@1234", "name": "X"})
        assert r.status_code == 403

    def test_viewer_cannot_create(self, viewer_token):
        r = requests.post(f"{BASE_URL}/api/users",
                          headers=_h(viewer_token),
                          json={"email": f"TEST_y_{uuid.uuid4().hex[:6]}@t.com", "password": "Pwd@1234", "name": "Y"})
        assert r.status_code == 403

    def test_perm_cannot_list(self, perm_token):
        r = requests.get(f"{BASE_URL}/api/users", headers=_h(perm_token))
        assert r.status_code == 403


# ---------- Création + modification permissions ----------
class TestUserPermissionsCRUD:
    created_id = None
    created_email = None

    def test_create_user_with_permissions(self, admin_token):
        email = f"test_p_{uuid.uuid4().hex[:6]}@mg-vms.com"
        TestUserPermissionsCRUD.created_email = email
        payload = {
            "email": email, "password": "Pwd@2026", "name": "Test Perm",
            "role": "readonly",
            "permissions": {"view_live": True, "stream_hd": False, "view_recordings": True,
                            "read_plates": False, "ptz_control": False, "export_files": False,
                            "bogus_key": True},  # clé invalide ignorée
        }
        r = requests.post(f"{BASE_URL}/api/users", headers=_h(admin_token), json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        TestUserPermissionsCRUD.created_id = data["id"]
        perms = data["permissions"]
        assert "bogus_key" not in perms
        assert perms["view_live"] is True
        assert perms["stream_hd"] is False
        assert perms["view_recordings"] is True
        assert perms["read_plates"] is False

    def test_login_new_user_reflects_perms(self, admin_token):
        tok = _login(TestUserPermissionsCRUD.created_email, "Pwd@2026")
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(tok))
        assert r.status_code == 200
        perms = r.json()["permissions"]
        assert perms["view_live"] is True
        assert perms["stream_hd"] is False
        assert perms["view_recordings"] is True
        assert perms["read_plates"] is False

    def test_update_user_permissions(self, admin_token):
        uid = TestUserPermissionsCRUD.created_id
        assert uid
        r = requests.put(f"{BASE_URL}/api/users/{uid}", headers=_h(admin_token),
                         json={"permissions": {"view_live": False, "ptz_control": True, "fake": True}})
        assert r.status_code == 200, r.text
        perms = r.json()["permissions"]
        assert perms["view_live"] is False
        assert perms["ptz_control"] is True
        assert "fake" not in perms
        # /me du user reflète
        tok = _login(TestUserPermissionsCRUD.created_email, "Pwd@2026")
        m = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(tok)).json()
        assert m["permissions"]["view_live"] is False
        assert m["permissions"]["ptz_control"] is True

    def test_delete_test_user(self, admin_token):
        uid = TestUserPermissionsCRUD.created_id
        if not uid:
            pytest.skip("no user")
        r = requests.delete(f"{BASE_URL}/api/users/{uid}", headers=_h(admin_token))
        assert r.status_code == 200


# ---------- Enforcement sur perm@ ----------
class TestEnforcement:
    @pytest.fixture(scope="class")
    def cam_id(self, admin_token):
        # On prend la 1re caméra disponible
        r = requests.get(f"{BASE_URL}/api/cameras", headers=_h(admin_token))
        assert r.status_code == 200
        cams = r.json()
        if not cams:
            pytest.skip("no cameras seeded")
        return cams[0]["id"]

    def test_plates_forbidden(self, perm_token):
        r = requests.get(f"{BASE_URL}/api/plates", headers=_h(perm_token))
        assert r.status_code == 403

    def test_timeline_forbidden(self, perm_token, cam_id):
        r = requests.get(f"{BASE_URL}/api/recordings/timeline?camera_id={cam_id}", headers=_h(perm_token))
        assert r.status_code == 403

    def test_ptz_forbidden(self, perm_token, cam_id):
        r = requests.post(f"{BASE_URL}/api/cameras/{cam_id}/ptz?command=left", headers=_h(perm_token))
        assert r.status_code == 403

    def test_export_recording_forbidden(self, perm_token, cam_id):
        r = requests.post(f"{BASE_URL}/api/recordings/export", headers=_h(perm_token),
                          json={"camera_id": cam_id, "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:05:00Z"})
        assert r.status_code == 403

    def test_plates_export_forbidden(self, perm_token):
        r = requests.get(f"{BASE_URL}/api/plates/export", headers=_h(perm_token))
        assert r.status_code == 403

    def test_anpr_detect_forbidden(self, perm_token, cam_id):
        r = requests.post(f"{BASE_URL}/api/anpr/detect", headers=_h(perm_token),
                          json={"camera_id": cam_id})
        assert r.status_code == 403


# ---------- stream HD/SD ----------
class TestStreamQuality:
    @pytest.fixture(scope="class")
    def cam_for_perm(self, perm_token, admin_token):
        # caméra du site assigné à perm@
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(perm_token)).json()
        site_ids = me.get("site_ids", [])
        cams = requests.get(f"{BASE_URL}/api/cameras", headers=_h(admin_token)).json()
        for c in cams:
            if not site_ids or c.get("site_id") in site_ids:
                return c["id"]
        pytest.skip("no cam available for perm user")

    def test_perm_user_gets_sd(self, perm_token, cam_for_perm):
        r = requests.get(f"{BASE_URL}/api/cameras/{cam_for_perm}/stream", headers=_h(perm_token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["quality"] == "SD"
        assert data["resolution"] == "640x480"

    def test_admin_gets_hd(self, admin_token, cam_for_perm):
        r = requests.get(f"{BASE_URL}/api/cameras/{cam_for_perm}/stream", headers=_h(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert data["quality"] == "HD"
        assert data["resolution"] == "1920x1080"


# ---------- Admin/tech bypass ----------
class TestAdminBypass:
    @pytest.fixture(scope="class")
    def cam_id(self, admin_token):
        cams = requests.get(f"{BASE_URL}/api/cameras", headers=_h(admin_token)).json()
        if not cams:
            pytest.skip("no cams")
        return cams[0]["id"]

    def test_admin_plates(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/plates", headers=_h(admin_token))
        assert r.status_code == 200

    def test_tech_plates(self, tech_token):
        r = requests.get(f"{BASE_URL}/api/plates", headers=_h(tech_token))
        assert r.status_code == 200

    def test_admin_timeline(self, admin_token, cam_id):
        r = requests.get(f"{BASE_URL}/api/recordings/timeline?camera_id={cam_id}", headers=_h(admin_token))
        assert r.status_code == 200

    def test_tech_timeline(self, tech_token, cam_id):
        r = requests.get(f"{BASE_URL}/api/recordings/timeline?camera_id={cam_id}", headers=_h(tech_token))
        assert r.status_code == 200
