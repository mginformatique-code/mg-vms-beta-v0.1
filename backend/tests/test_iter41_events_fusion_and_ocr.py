"""Iteration 41 tests — P0-1/P0-2/P0-3.

Covers:
- /api/plugins/bus lazy state refresh (fast-alpr/easyocr/tesseract/opencv-ocr ready ; paddle-ocr error)
- /api/system/anpr-benchmark multi-engine + fusion
- /api/events multi-type filter
- /api/smart-search returns full event fiches + camera_hint extraction
- /api/events/{id}/reanalyze regression
- /api/plugins/easyocr/install-deps + status polling
"""
import os
import time
import pytest
import requests

def _load_base():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


BASE = _load_base()
ADMIN_EMAIL = "admin@mg-vms.com"
ADMIN_PW = "Admin@2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PW},
                      timeout=30)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}"}


# -------- P0-3: plugins bus lazy refresh --------
def test_plugins_bus_lazy_states(h):
    r = requests.get(f"{BASE}/api/plugins/bus", headers=h, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    plugins = data.get("entries") or data.get("plugins") or data.get("items") or data
    # normalize to list of dicts with id/state
    if isinstance(plugins, dict):
        plugins = list(plugins.values())
    by_id = {}
    for p in plugins:
        pid = p.get("id") or p.get("name") or p.get("plugin_id")
        st = p.get("state") or p.get("status")
        by_id[pid] = (st, p)
    print("Plugin states:", {k: v[0] for k, v in by_id.items()})
    # Expected ANPR/OCR plugins
    expected_ready = ["fast-alpr", "easyocr", "tesseract", "opencv-ocr"]
    for pid in expected_ready:
        assert pid in by_id, f"missing plugin {pid} in bus response; keys={list(by_id)}"
        assert by_id[pid][0] == "ready", f"{pid} expected ready, got {by_id[pid][0]}"
    assert "paddle-ocr" in by_id, "paddle-ocr missing"
    st, meta = by_id["paddle-ocr"]
    assert st in ("error", "failed"), f"paddle-ocr expected error, got {st}"


# -------- P0-2: multi-engine ANPR benchmark --------
def test_anpr_benchmark_multi_engine(h):
    url = f"{BASE}/api/system/anpr-benchmark"
    params = {"iterations": 1,
              "engines": "fast-alpr,easyocr,tesseract,opencv-ocr",
              "fusion": "true"}
    # workers can warm up ~20s after restart → retry a few times on 502
    last = None
    for attempt in range(4):
        r = requests.post(url, headers=h, params=params, timeout=180)
        last = r
        if r.status_code == 200:
            break
        if r.status_code == 502:
            time.sleep(15)
            continue
        break
    assert last.status_code == 200, f"HTTP {last.status_code}: {last.text[:300]}"
    body = last.json()
    engines = body.get("ocr_engines") or body.get("engines")
    assert engines, f"no ocr_engines in body keys={list(body)}"
    if isinstance(engines, dict):
        engines_list = list(engines.values())
    else:
        engines_list = engines
    names = {(e.get("engine") or e.get("name") or e.get("id")) for e in engines_list}
    print("Benchmark engines:", names)
    for name in ("fast-alpr", "easyocr", "tesseract", "opencv-ocr"):
        assert name in names, f"engine {name} missing from benchmark; got {names}"
    for e in engines_list:
        # every entry should have the perf keys (or an available=false marker)
        avail = e.get("available", True)
        if avail:
            for k in ("avg_ms",):
                assert k in e, f"missing {k} in engine result {e}"


# -------- P0-1: events multi-type filter --------
def test_events_multi_type_filter(h):
    r = requests.get(f"{BASE}/api/events",
                     headers=h,
                     params={"types": "Voiture,Camion,Bus,Moto", "limit": 10},
                     timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    events = body.get("events") if isinstance(body, dict) else body
    assert isinstance(events, list)
    allowed = {"Voiture", "Camion", "Bus", "Moto"}
    for ev in events:
        t = ev.get("type") or ev.get("event_type") or ev.get("category")
        assert t in allowed, f"event type {t} not in {allowed}: {ev}"


# -------- Smart Search full fiches --------
def test_smart_search_full_fiches(h):
    r = requests.post(f"{BASE}/api/smart-search",
                      headers=h,
                      json={"query": "personne détectée aujourd'hui"},
                      timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    print("smart-search keys:", list(body))
    ev_count = body.get("events_count", body.get("count"))
    events = body.get("events") or []
    # Not strictly asserting >0 (depends on live traffic) — but structure
    assert isinstance(events, list)
    if events:
        e0 = events[0]
        for k in ("type", "camera_name", "timestamp"):
            assert k in e0, f"missing {k} in fiche {e0}"


def test_smart_search_camera_hint(h):
    r = requests.post(f"{BASE}/api/smart-search",
                      headers=h,
                      json={"query": "voiture passée devant la caméra Démo cet après-midi"},
                      timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    filt = body.get("filters") or {}
    target = body.get("target") or body.get("intent")
    print("target:", target, "filters:", filt)
    # Best-effort: camera_hint should be extracted
    cam_hint = filt.get("camera_hint") or filt.get("camera")
    assert cam_hint, f"camera_hint missing from filters {filt}"


# -------- Reanalyze regression --------
def test_event_reanalyze(h):
    r = requests.get(f"{BASE}/api/events", headers=h, params={"limit": 1}, timeout=30)
    assert r.status_code == 200
    body = r.json()
    events = body.get("events") if isinstance(body, dict) else body
    if not events:
        pytest.skip("no events available")
    eid = events[0].get("id") or events[0].get("_id") or events[0].get("event_id")
    assert eid
    r2 = requests.post(f"{BASE}/api/events/{eid}/reanalyze", headers=h, timeout=60)
    assert r2.status_code in (200, 202), f"HTTP {r2.status_code}: {r2.text[:300]}"


# -------- Plugin install-deps + status --------
def test_easyocr_install_deps(h):
    r = requests.post(f"{BASE}/api/plugins/easyocr/install-deps", headers=h, timeout=30)
    assert r.status_code in (200, 202), r.text
    # poll status
    deadline = time.time() + 120
    verified = None
    status = None
    while time.time() < deadline:
        rs = requests.get(f"{BASE}/api/plugins/easyocr/install-status",
                          headers=h, timeout=15)
        if rs.status_code == 200:
            body = rs.json()
            status = body.get("status")
            verified = body.get("verified_state")
            if status in ("success", "error", "failed"):
                break
        time.sleep(2)
    print("easyocr install-status:", status, "verified_state:", verified)
    assert status == "success", f"install status {status}"
    assert verified == "ready", f"verified_state {verified}"
