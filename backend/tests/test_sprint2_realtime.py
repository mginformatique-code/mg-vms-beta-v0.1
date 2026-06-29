"""Sprint 2 — Temps réel : real metrics (psutil), pagination + X-Total-Count, WebSocket (auth/scoping/broadcast)."""
import os
import asyncio
import json
import time
import uuid

import pytest
import requests
import websockets

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

API = f"{BASE_URL}/api"
WS_BASE = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
WS_URL = f"{WS_BASE}/api/ws"

CREDS = {
    "admin": ("admin@mg-vms.com", "Admin@2026"),
    "tech": ("tech@mg-vms.com", "Tech@2026"),
    "client": ("client@mg-vms.com", "Client@2026"),
}


def _login(role):
    email, pwd = CREDS[role]
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=15)
    assert r.status_code == 200, f"login failed for {role}: {r.text}"
    return r.json()["access_token"], r.json()["user"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="session")
def tokens():
    return {role: _login(role)[0] for role in CREDS}


# ============ REAL METRICS via psutil ============
class TestRealMetrics:
    def test_dashboard_stats_system_keys(self, tokens):
        r = requests.get(f"{API}/dashboard/stats", headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        sys = r.json()["system"]
        for k in ("cpu", "ram", "storage", "temperature", "bandwidth_mbps", "uptime_days"):
            assert k in sys, f"missing system key: {k}"
        # plausible real values
        assert 0 <= sys["cpu"] <= 100
        assert 0 <= sys["ram"] <= 100
        assert 0 <= sys["storage"] <= 100
        assert isinstance(sys["uptime_days"], int) and sys["uptime_days"] >= 0

    def test_metrics_change_over_time_not_random_range(self, tokens):
        # old code returned random 28..62 — real psutil should give different distribution
        vals = []
        for _ in range(4):
            r = requests.get(f"{API}/dashboard/stats", headers=H(tokens["admin"]), timeout=10)
            vals.append(r.json()["system"]["cpu"])
            time.sleep(1.2)
        # at least one value should be < 28 or > 62 OR all values identical (real low-CPU container)
        out_of_old_range = any(v < 28 or v > 62 for v in vals)
        # Or values stable (random would jitter widely)
        stable = max(vals) - min(vals) <= 5
        assert out_of_old_range or stable, f"CPU values look like old random 28-62 range: {vals}"


# ============ PAGINATION + X-Total-Count ============
class TestPagination:
    @pytest.mark.parametrize("path", ["plates", "events", "alerts", "audit"])
    def test_list_endpoints_pagination(self, tokens, path):
        # audit requires tech+, others admin works
        t = tokens["admin"]
        r1 = requests.get(f"{API}/{path}?limit=10&offset=0", headers=H(t), timeout=15)
        assert r1.status_code == 200, f"{path}: {r1.status_code} {r1.text}"
        # body must remain a JSON list (non-breaking)
        body1 = r1.json()
        assert isinstance(body1, list), f"{path} body must be a list, got {type(body1)}"
        assert len(body1) <= 10
        # X-Total-Count header present (case-insensitive)
        total_hdr = r1.headers.get("X-Total-Count") or r1.headers.get("x-total-count")
        assert total_hdr is not None, f"{path}: missing X-Total-Count header. Headers: {dict(r1.headers)}"
        total = int(total_hdr)
        assert total >= 0
        # If enough data, offset=10 should return different items
        if total > 10 and len(body1) == 10:
            r2 = requests.get(f"{API}/{path}?limit=10&offset=10", headers=H(t), timeout=15)
            assert r2.status_code == 200
            body2 = r2.json()
            assert isinstance(body2, list)
            ids1 = {x.get("id") for x in body1 if x.get("id")}
            ids2 = {x.get("id") for x in body2 if x.get("id")}
            if ids1 and ids2:
                assert ids1.isdisjoint(ids2), f"{path}: page1 and page2 overlap"

    def test_plates_total_count_reasonable(self, tokens):
        r = requests.get(f"{API}/plates?limit=1&offset=0", headers=H(tokens["admin"]), timeout=15)
        total = int(r.headers.get("X-Total-Count", "0"))
        # seeded demo data should give a healthy number of plates
        assert total >= 50, f"expected >=50 seeded plates, got {total}"


# ============ WEBSOCKET ============
def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestWebSocket:
    def test_ws_invalid_token_closed(self):
        async def _go():
            try:
                async with websockets.connect(f"{WS_URL}?token=BADTOKEN", open_timeout=10) as ws:
                    await asyncio.wait_for(ws.recv(), timeout=5)
                return False  # no error means socket stayed open
            except Exception:
                return True
        assert _run(_go()) is True

    def test_ws_missing_token_closed(self):
        async def _go():
            try:
                async with websockets.connect(WS_URL, open_timeout=10) as ws:
                    await asyncio.wait_for(ws.recv(), timeout=5)
                return False
            except Exception:
                return True
        assert _run(_go()) is True

    def test_ws_admin_first_message_metrics(self, tokens):
        async def _go():
            async with websockets.connect(f"{WS_URL}?token={tokens['admin']}", open_timeout=10) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                return json.loads(msg)
        data = _run(_go())
        assert data["type"] == "metrics"
        assert "cpu" in data["data"]
        assert "ram" in data["data"]

    def test_ws_admin_receives_alert_broadcast(self, tokens):
        async def _go():
            async with websockets.connect(f"{WS_URL}?token={tokens['admin']}", open_timeout=10) as ws:
                # consume first metrics msg
                await asyncio.wait_for(ws.recv(), timeout=10)
                # find a site to attach alert to
                sites = requests.get(f"{API}/sites", headers=H(tokens["admin"]), timeout=10).json()
                site_id = sites[0]["id"]
                unique = f"TEST_WS_ALERT_{uuid.uuid4().hex[:8]}"
                r = requests.post(
                    f"{API}/alerts",
                    headers=H(tokens["admin"]),
                    json={"message": unique, "severity": "critical", "site_id": site_id, "alert_type": "test"},
                    timeout=10,
                )
                assert r.status_code == 200, r.text
                received = None
                deadline = time.time() + 10
                while time.time() < deadline:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=8)
                    except asyncio.TimeoutError:
                        break
                    try:
                        payload = json.loads(msg)
                    except Exception:
                        continue
                    if payload.get("type") == "alert" and payload.get("data", {}).get("message") == unique:
                        received = payload
                        break
                return received
        received = _run(_go())
        assert received is not None, "admin ws did not receive alert broadcast"

    def test_ws_site_scoping_client(self, tokens):
        """Client (Mairie Centrale only) must NOT receive alert for a different site."""
        async def _go():
            sites = requests.get(f"{API}/sites", headers=H(tokens["admin"]), timeout=10).json()
            other = next((s for s in sites if s["name"] != "Mairie Centrale"), None)
            assert other is not None, "need a non-Mairie site for scoping test"
            # find a camera in the non-Mairie site (create_alert derives site_id from camera, not body)
            cams = requests.get(f"{API}/cameras?site_id={other['id']}", headers=H(tokens["admin"]), timeout=10).json()
            assert cams, f"no cameras in site {other['name']} to test scoping"
            cam_id = cams[0]["id"]
            async with websockets.connect(f"{WS_URL}?token={tokens['client']}", open_timeout=10) as ws_client:
                await asyncio.wait_for(ws_client.recv(), timeout=10)
                unique = f"TEST_SCOPE_{uuid.uuid4().hex[:8]}"
                r = requests.post(
                    f"{API}/alerts",
                    headers=H(tokens["admin"]),
                    json={"message": unique, "severity": "critical", "camera_id": cam_id, "alert_type": "test"},
                    timeout=10,
                )
                assert r.status_code == 200
                # confirm the actually-stored alert is on the non-Mairie site
                created = r.json()
                assert created.get("site_name") != "Mairie Centrale", f"alert ended up in Mairie: {created}"
                got_alert = False
                deadline = time.time() + 4
                while time.time() < deadline:
                    try:
                        msg = await asyncio.wait_for(ws_client.recv(), timeout=2)
                    except asyncio.TimeoutError:
                        continue
                    try:
                        payload = json.loads(msg)
                    except Exception:
                        continue
                    if payload.get("type") == "alert" and payload.get("data", {}).get("message") == unique:
                        got_alert = True
                        break
                return got_alert
        assert _run(_go()) is False, "client received alert for a site it shouldn't see"
