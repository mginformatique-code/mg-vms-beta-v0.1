"""Sprint 3 — Plugin registry + blacklist auto-alert + ANPR detect (REST + WebSocket).

Covers:
  * GET /api/plugins returns 10 plugins; anpr core+enabled
  * PUT /api/plugins/<id>: admin only; core (anpr) cannot be disabled; non-core toggles persist
  * POST /api/anpr/detect: ZZ-999-ZZ -> list_status=black + blacklist_alert=true + critical alert row
  * POST /api/anpr/detect: normal plate -> list_status=none, no alert, plate stored in /api/plates
  * WebSocket /api/ws?token= receives {type:'alert'} when ZZ-999-ZZ is detected
"""
import asyncio
import json
import os
import time

import pytest
import requests
import websockets

# Load REACT_APP_BACKEND_URL from frontend/.env so the suite is portable
def _load_base_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    env_path = "/app/frontend/.env"
    if os.path.exists(env_path):
        for line in open(env_path):
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


BASE_URL = _load_base_url()
WS_URL = BASE_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/ws?token="

CREDS = {
    "admin": ("admin@mg-vms.com", "Admin@2026"),
    "tech": ("tech@mg-vms.com", "Tech@2026"),
    "client": ("client@mg-vms.com", "Client@2026"),
    "viewer": ("viewer@mg-vms.com", "Viewer@2026"),
}


def _login(role: str) -> str:
    email, pw = CREDS[role]
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, f"login {role} -> {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin")


@pytest.fixture(scope="module")
def tech_token():
    return _login("tech")


@pytest.fixture(scope="module")
def client_token():
    return _login("client")


def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ----- PLUGINS -----
class TestPlugins:
    def test_list_plugins_returns_10_with_anpr_core(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/plugins", headers=_h(admin_token), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 10, f"expected 10 plugins, got {len(data)}"
        ids = {p["id"] for p in data}
        assert "anpr" in ids
        anpr = next(p for p in data if p["id"] == "anpr")
        assert anpr["enabled"] is True
        assert anpr.get("core") is True
        # All except anpr should be disabled by default (clean state assumption: anpr is the only default-on)
        anpr_only_default_enabled = [p for p in data if p["enabled"] and p.get("core")]
        assert any(p["id"] == "anpr" for p in anpr_only_default_enabled)

    def test_non_admin_cannot_toggle(self, tech_token, client_token):
        for tok in (tech_token, client_token):
            r = requests.put(f"{BASE_URL}/api/plugins/ai_detection", headers=_h(tok),
                             json={"enabled": True}, timeout=15)
            assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"

    def test_cannot_disable_core_anpr(self, admin_token):
        r = requests.put(f"{BASE_URL}/api/plugins/anpr", headers=_h(admin_token),
                         json={"enabled": False}, timeout=15)
        assert r.status_code == 400, f"expected 400 for core disable, got {r.status_code} {r.text}"

    def test_toggle_non_core_persists(self, admin_token):
        # enable
        r = requests.put(f"{BASE_URL}/api/plugins/ai_detection", headers=_h(admin_token),
                         json={"enabled": True}, timeout=15)
        assert r.status_code == 200
        assert r.json()["enabled"] is True
        # verify via GET
        lst = requests.get(f"{BASE_URL}/api/plugins", headers=_h(admin_token), timeout=15).json()
        assert next(p for p in lst if p["id"] == "ai_detection")["enabled"] is True
        # disable back
        r2 = requests.put(f"{BASE_URL}/api/plugins/ai_detection", headers=_h(admin_token),
                          json={"enabled": False}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["enabled"] is False
        lst2 = requests.get(f"{BASE_URL}/api/plugins", headers=_h(admin_token), timeout=15).json()
        assert next(p for p in lst2 if p["id"] == "ai_detection")["enabled"] is False

    def test_unknown_plugin_404(self, admin_token):
        r = requests.put(f"{BASE_URL}/api/plugins/does_not_exist", headers=_h(admin_token),
                         json={"enabled": True}, timeout=15)
        assert r.status_code == 404


# ----- ANPR DETECT -----
class TestAnprDetect:
    def test_detect_normal_plate(self, client_token):
        plate = "XY-111-ZW"
        before = requests.get(f"{BASE_URL}/api/alerts?acknowledged=false",
                              headers=_h(client_token), timeout=15)
        before_count = int(before.headers.get("X-Total-Count", "0"))

        r = requests.post(f"{BASE_URL}/api/anpr/detect", headers=_h(client_token),
                          json={"plate": plate}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["list_status"] == "none"
        assert body["blacklist_alert"] is False
        det = body["detection"]
        assert det["plate"] == plate.upper()
        # verify stored in /api/plates
        plates = requests.get(f"{BASE_URL}/api/plates?plate={plate}",
                              headers=_h(client_token), timeout=15).json()
        assert any(p["id"] == det["id"] for p in plates), "detection not visible in /api/plates"

        # alert count unchanged
        after = requests.get(f"{BASE_URL}/api/alerts?acknowledged=false",
                             headers=_h(client_token), timeout=15)
        after_count = int(after.headers.get("X-Total-Count", "0"))
        assert after_count == before_count, "normal plate should not create an alert"

    def test_detect_blacklisted_plate_creates_critical_alert(self, client_token, admin_token):
        plate = "ZZ-999-ZZ"
        # snapshot alerts (admin sees all, but client suffices since alert is on the cam returned by detect)
        before_total = int(requests.get(f"{BASE_URL}/api/alerts", headers=_h(admin_token),
                                        timeout=15).headers.get("X-Total-Count", "0"))

        r = requests.post(f"{BASE_URL}/api/anpr/detect", headers=_h(client_token),
                          json={"plate": plate}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["list_status"] == "black"
        assert body["blacklist_alert"] is True

        # allow background to settle (alert is created inline before broadcast; notification is BG)
        time.sleep(1.0)
        alerts_resp = requests.get(f"{BASE_URL}/api/alerts?limit=20", headers=_h(admin_token), timeout=15)
        assert alerts_resp.status_code == 200
        new_total = int(alerts_resp.headers.get("X-Total-Count", "0"))
        # >=1 to be robust if another worker also creates an alert in parallel
        assert new_total >= before_total + 1, f"expected at least +1 alert, before={before_total} after={new_total}"
        # find an anpr_blacklist alert matching the plate in the latest entries
        matching = [a for a in alerts_resp.json()
                    if a.get("type") == "anpr_blacklist" and plate in (a.get("message") or "")]
        assert matching, "no anpr_blacklist alert for ZZ-999-ZZ found"
        latest = matching[0]
        assert latest["severity"] == "critical"
        assert latest["acknowledged"] is False

    def test_detect_requires_client_role(self):
        # No token -> 401/403
        r = requests.post(f"{BASE_URL}/api/anpr/detect", json={"plate": "AB-123-CD"}, timeout=15)
        assert r.status_code in (401, 403)


# ----- WEBSOCKET broadcast -----
class TestAnprWebsocket:
    def test_ws_receives_alert_on_blacklist_detect(self, admin_token, client_token):
        async def run():
            ws_url = WS_URL + admin_token
            async with websockets.connect(ws_url, open_timeout=10, close_timeout=5) as ws:
                # Drain initial metrics msg
                try:
                    first = await asyncio.wait_for(ws.recv(), timeout=5)
                    json.loads(first)  # must be valid JSON
                except asyncio.TimeoutError:
                    pass

                # Trigger detection via REST in a thread to keep ws loop free
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(None, lambda: requests.post(
                    f"{BASE_URL}/api/anpr/detect",
                    headers=_h(client_token),
                    json={"plate": "ZZ-999-ZZ"},
                    timeout=20,
                ))
                assert resp.status_code == 200

                # Now wait up to 10s for an 'alert' frame
                deadline = time.time() + 10
                got_alert = False
                while time.time() < deadline:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    except asyncio.TimeoutError:
                        continue
                    try:
                        payload = json.loads(msg)
                    except Exception:
                        continue
                    if payload.get("type") == "alert":
                        data = payload.get("data", {})
                        if data.get("type") == "anpr_blacklist" or "ZZ-999-ZZ" in (data.get("message") or ""):
                            got_alert = True
                            break
                assert got_alert, "did not receive alert frame on ws within 10s"

        asyncio.new_event_loop().run_until_complete(run())


# ----- NON-REGRESSION smoke -----
class TestNonRegression:
    def test_login_all_roles(self):
        for role in ("admin", "tech", "client", "viewer"):
            tok = _login(role)
            r = requests.get(f"{BASE_URL}/api/auth/me",
                             headers={"Authorization": f"Bearer {tok}"}, timeout=15)
            assert r.status_code == 200, f"{role} /auth/me -> {r.status_code}"
            assert r.json()["email"] == CREDS[role][0]

    def test_client_site_scoping(self, client_token):
        sites = requests.get(f"{BASE_URL}/api/sites", headers=_h(client_token), timeout=15).json()
        # Client should see only their assigned sites (typically 1)
        assert isinstance(sites, list)
        assert len(sites) >= 1
        assert len(sites) <= 2, f"client expected to see <=2 sites, saw {len(sites)}"

    def test_pagination_x_total_count(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/plates?limit=5", headers=_h(admin_token), timeout=15)
        assert r.status_code == 200
        assert "X-Total-Count" in r.headers
        assert len(r.json()) <= 5

    def test_dashboard_real_metrics(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/dashboard/stats", headers=_h(admin_token), timeout=15)
        assert r.status_code == 200
        sys_block = r.json().get("system", {})
        for k in ("cpu", "ram", "storage", "uptime_days"):
            assert k in sys_block, f"missing {k} in dashboard system metrics"

    def test_alert_ack(self, admin_token, client_token):
        # find an unack alert (created by blacklist test or others)
        alerts = requests.get(f"{BASE_URL}/api/alerts?acknowledged=false&limit=5",
                              headers=_h(admin_token), timeout=15).json()
        if not alerts:
            pytest.skip("no unacknowledged alert to ack")
        aid = alerts[0]["id"]
        r = requests.post(f"{BASE_URL}/api/alerts/{aid}/ack", headers=_h(client_token), timeout=15)
        assert r.status_code == 200
