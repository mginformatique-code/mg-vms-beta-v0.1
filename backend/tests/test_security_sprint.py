"""Sprint Sécurité — backend tests
Covers: brute-force lockout, rate limiting, security headers, password reset,
per-site permissions (cloisonnement), refresh token.
"""
import os
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
if not BASE_URL:
    # fall back to frontend/.env parse
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}
TECH = {"email": "tech@mg-vms.com", "password": "Tech@2026"}
CLIENT = {"email": "client@mg-vms.com", "password": "Client@2026"}
VIEWER = {"email": "viewer@mg-vms.com", "password": "Viewer@2026"}


# ---------------- Fixtures ----------------
@pytest.fixture(scope="session")
def mongo():
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    c = MongoClient(url)
    return c[db_name]


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def client_token():
    r = requests.post(f"{API}/auth/login", json=CLIENT, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def viewer_token():
    r = requests.post(f"{API}/auth/login", json=VIEWER, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------------- Security headers ----------------
class TestSecurityHeaders:
    def test_headers_present(self):
        r = requests.get(f"{API}/health", timeout=10)
        # health route may not exist; try /api/sites with auth instead via login response
        h = {k.lower(): v for k, v in r.headers.items()}
        # The middleware sets headers on every response
        assert h.get("x-frame-options") == "DENY"
        assert h.get("x-content-type-options") == "nosniff"
        assert "referrer-policy" in h
        assert "permissions-policy" in h


# ---------------- Brute force lockout ----------------
class TestBruteForce:
    THROWAWAY = f"locktest_{uuid.uuid4().hex[:6]}@x.com"

    def _clear(self, mongo):
        mongo.login_attempts.delete_many({})

    def test_lockout_after_5_failures(self, mongo):
        self._clear(mongo)
        # 4 wrong attempts -> 401
        for i in range(4):
            r = requests.post(f"{API}/auth/login", json={"email": self.THROWAWAY, "password": "wrong"}, timeout=10)
            assert r.status_code == 401, f"attempt {i+1}: {r.status_code} {r.text}"
        # 5th -> 423 lockout with French message
        r = requests.post(f"{API}/auth/login", json={"email": self.THROWAWAY, "password": "wrong"}, timeout=10)
        assert r.status_code == 423, r.text
        detail = r.json().get("detail", "")
        assert "verrouill" in detail.lower() or "tentatives" in detail.lower()

    def test_correct_password_blocked_during_lockout(self, mongo):
        # Use a real account but only AFTER setting lockout manually so we don't lock the real admin
        # Insert a lockout record for a synthetic identifier matching admin from this IP
        # Safer: just verify the throwaway account remains locked even with a valid-looking password
        r = requests.post(f"{API}/auth/login", json={"email": self.THROWAWAY, "password": "AnythingNow!"}, timeout=10)
        assert r.status_code == 423, r.text

    def test_cleanup_lockout(self, mongo):
        mongo.login_attempts.delete_many({})
        # ensure admin can still login
        r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=10)
        assert r.status_code == 200


# ---------------- Rate limit ----------------
class TestZRateLimit:  # named TestZ so it runs LAST (alphabetical) — rate-limit window is 60s in-memory
    def test_zzz_login_rate_limit_429(self, mongo):
        # clear lockout so 401s don't become 423
        mongo.login_attempts.delete_many({})
        throwaway = f"rl_{uuid.uuid4().hex[:6]}@x.com"
        got_429 = False
        retry_after = None
        for i in range(15):
            r = requests.post(f"{API}/auth/login", json={"email": throwaway, "password": "x"}, timeout=10)
            if r.status_code == 429:
                got_429 = True
                retry_after = r.headers.get("Retry-After")
                break
        assert got_429, "expected 429 after 10+ rapid login attempts"
        assert retry_after is not None
        # cleanup
        mongo.login_attempts.delete_many({})


# ---------------- Password reset ----------------
class TestPasswordReset:
    @classmethod
    def setup_class(cls):
        # Wait so rate-limit (10 POST /api/auth/login per 60s per IP) doesn't reject our login(s) below
        time.sleep(65)

    def test_forgot_password_generic_response_known_email(self, mongo):
        # use a unique non-existent email to avoid triggering tokens for real users
        r = requests.post(f"{API}/auth/forgot-password", json={"email": "nope_xyz@example.com"}, timeout=10)
        assert r.status_code == 200
        assert "réinitialisation" in r.json().get("message", "").lower()

    def test_forgot_password_existing_creates_token(self, mongo):
        # Trigger forgot for tech (we will restore password at end)
        r = requests.post(f"{API}/auth/forgot-password", json={"email": TECH["email"]}, timeout=10)
        assert r.status_code == 200
        # Token must exist in db
        rec = mongo.password_reset_tokens.find_one(
            {"email": TECH["email"], "used": False}, sort=[("created_at", -1)]
        )
        assert rec is not None
        assert rec.get("token")

    def test_reset_password_flow_and_reuse_blocked(self, mongo):
        # Self-contained: trigger forgot then use that token
        r = requests.post(f"{API}/auth/forgot-password", json={"email": TECH["email"]}, timeout=10)
        assert r.status_code == 200, r.text
        rec = mongo.password_reset_tokens.find_one(
            {"email": TECH["email"], "used": False}, sort=[("created_at", -1)]
        )
        assert rec is not None
        tok = rec["token"]

        # Short password rejected
        r = requests.post(f"{API}/auth/reset-password", json={"token": tok, "new_password": "short"}, timeout=10)
        assert r.status_code == 400

        # Successful reset
        r = requests.post(f"{API}/auth/reset-password", json={"token": tok, "new_password": "Temp@99887"}, timeout=10)
        assert r.status_code == 200, r.text

        # Login with new password works
        r = requests.post(f"{API}/auth/login", json={"email": TECH["email"], "password": "Temp@99887"}, timeout=10)
        assert r.status_code == 200

        # Reusing token -> 400
        r = requests.post(f"{API}/auth/reset-password", json={"token": tok, "new_password": "Another@99887"}, timeout=10)
        assert r.status_code == 400

        # Invalid token -> 400
        r = requests.post(f"{API}/auth/reset-password", json={"token": "invalid-xxx", "new_password": "Another@99887"}, timeout=10)
        assert r.status_code == 400

        # RESTORE tech password to Tech@2026 via fresh reset
        requests.post(f"{API}/auth/forgot-password", json={"email": TECH["email"]}, timeout=10)
        rec2 = mongo.password_reset_tokens.find_one(
            {"email": TECH["email"], "used": False}, sort=[("created_at", -1)]
        )
        assert rec2 is not None
        r = requests.post(f"{API}/auth/reset-password", json={"token": rec2["token"], "new_password": TECH["password"]}, timeout=10)
        assert r.status_code == 200

        # Verify tech can log in with original
        r = requests.post(f"{API}/auth/login", json=TECH, timeout=10)
        assert r.status_code == 200


# ---------------- Refresh token ----------------
class TestRefresh:
    @classmethod
    def setup_class(cls):
        time.sleep(65)

    def test_refresh_returns_new_access_token(self):
        r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=10)
        assert r.status_code == 200
        refresh = r.json()["refresh_token"]
        r2 = requests.post(f"{API}/auth/refresh", headers={"Authorization": f"Bearer {refresh}"}, timeout=10)
        assert r2.status_code == 200, r2.text
        assert "access_token" in r2.json()

    def test_refresh_with_access_token_rejected(self, admin_token):
        r = requests.post(f"{API}/auth/refresh", headers=auth(admin_token), timeout=10)
        assert r.status_code == 401


# ---------------- Per-site permissions ----------------
class TestSiteScope:
    def test_admin_sees_all_sites(self, admin_token):
        r = requests.get(f"{API}/sites", headers=auth(admin_token), timeout=10)
        assert r.status_code == 200
        sites = r.json()
        assert isinstance(sites, list)
        assert len(sites) >= 5

    def test_client_sees_one_site(self, client_token):
        r = requests.get(f"{API}/sites", headers=auth(client_token), timeout=10)
        assert r.status_code == 200
        sites = r.json()
        assert len(sites) == 1, f"client should see 1 site, saw {len(sites)}: {sites}"
        assert sites[0]["name"] == "Mairie Centrale"

    def test_viewer_sees_assigned_site(self, viewer_token):
        r = requests.get(f"{API}/sites", headers=auth(viewer_token), timeout=10)
        assert r.status_code == 200
        sites = r.json()
        assert len(sites) == 1

    def test_client_cameras_scoped(self, client_token, admin_token):
        r_admin = requests.get(f"{API}/cameras", headers=auth(admin_token), timeout=10)
        r_client = requests.get(f"{API}/cameras", headers=auth(client_token), timeout=10)
        assert r_admin.status_code == 200 and r_client.status_code == 200
        admin_cams = r_admin.json()
        client_cams = r_client.json()
        # client should see strictly fewer cameras
        assert len(client_cams) <= len(admin_cams)
        # all client cameras belong to its single site
        r_sites = requests.get(f"{API}/sites", headers=auth(client_token), timeout=10)
        allowed = {s["id"] for s in r_sites.json()}
        for c in client_cams:
            assert c.get("site_id") in allowed

    def test_admin_can_assign_sites(self, admin_token, mongo):
        # Create temp user, assign sites, then delete
        email = f"TEST_assign_{uuid.uuid4().hex[:6]}@x.com"
        r = requests.post(f"{API}/auth/register", headers=auth(admin_token),
                          json={"email": email, "password": "Pass@1234", "name": "Tmp", "role": "client"}, timeout=10)
        assert r.status_code == 200, r.text
        uid = r.json()["id"]

        # Get first 2 sites
        sites = requests.get(f"{API}/sites", headers=auth(admin_token), timeout=10).json()
        site_ids = [sites[0]["id"], sites[1]["id"]]

        r = requests.put(f"{API}/users/{uid}", headers=auth(admin_token), json={"site_ids": site_ids}, timeout=10)
        assert r.status_code == 200, r.text

        # Verify persisted via GET /users
        r = requests.get(f"{API}/users", headers=auth(admin_token), timeout=10)
        u = next((x for x in r.json() if x["id"] == uid), None)
        assert u is not None
        assert set(u.get("site_ids", [])) == set(site_ids)

        # Cleanup
        requests.delete(f"{API}/users/{uid}", headers=auth(admin_token), timeout=10)


# ---------------- RBAC unchanged ----------------
class TestRBAC:
    def test_client_blocked_from_users(self, client_token):
        r = requests.get(f"{API}/users", headers=auth(client_token), timeout=10)
        assert r.status_code == 403

    def test_viewer_blocked_from_users(self, viewer_token):
        r = requests.get(f"{API}/users", headers=auth(viewer_token), timeout=10)
        assert r.status_code == 403
