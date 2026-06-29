"""Backend tests — Hardware module (CPU/GPU resource management) — Phase 1."""
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


# --------- /api/hardware/info ---------
def test_hardware_info_admin(admin_h):
    r = requests.get(f"{BASE}/hardware/info", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ["cpu", "ram", "gpus", "accelerators", "simulated_gpu"]:
        assert k in d, k
    assert isinstance(d["cpu"], dict)
    assert d["cpu"].get("threads", 0) >= 1
    assert d["cpu"].get("cores", 0) >= 1
    assert isinstance(d["ram"], dict)
    assert d["ram"].get("total_mb", 0) > 0
    assert isinstance(d["gpus"], list)
    # 4 simulated GPUs in sandbox
    assert d["simulated_gpu"] is True
    assert len(d["gpus"]) == 4
    names = " ".join(g["name"] for g in d["gpus"])
    assert "RTX 4070" in names
    assert "RTX A2000" in names
    assert "Intel UHD Graphics 770" in names
    assert "Coral" in names
    # accelerators aggregated
    accel = d["accelerators"]
    assert "CUDA" in accel and "NVENC" in accel and "QuickSync" in accel and "EdgeTPU" in accel


def test_hardware_info_tech_can_view(tech_h):
    r = requests.get(f"{BASE}/hardware/info", headers=tech_h, timeout=15)
    assert r.status_code == 200
    assert "gpus" in r.json()


def test_hardware_info_unauth():
    r = requests.get(f"{BASE}/hardware/info", timeout=15)
    assert r.status_code in (401, 403)


# --------- /api/hardware/config GET ---------
def test_hardware_config_shape(admin_h):
    r = requests.get(f"{BASE}/hardware/config", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ["profile", "assignments", "priorities", "auto_optimize", "options", "labels",
              "priority_levels", "priority_engines", "profiles"]:
        assert k in d, k
    assert d["profile"] in ("economy", "balanced", "performance", "ultra", "custom")
    # 10 functions
    assert len(d["assignments"]) == 10
    assert set(d["assignments"].keys()) == set(d["options"].keys())
    assert len(d["options"]) == 10
    assert "realtime" in d["priority_levels"]
    assert "normal" in d["priority_levels"]
    assert "low" in d["priority_levels"]


# --------- profiles ---------
def test_apply_performance_profile_admin(admin_h):
    r = requests.post(f"{BASE}/hardware/profile/performance", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["profile"] == "performance"
    # performance assignments per spec: ai=gpu0, encode=nvenc
    assert cfg["assignments"]["ai"] == "gpu0"
    assert cfg["assignments"]["encode"] == "nvenc"
    # GET verify persistence
    g = requests.get(f"{BASE}/hardware/config", headers=admin_h, timeout=15).json()
    assert g["profile"] == "performance"
    assert g["assignments"]["ai"] == "gpu0"
    assert g["priorities"]["ai"] == "realtime"


def test_apply_unknown_profile_400(admin_h):
    r = requests.post(f"{BASE}/hardware/profile/foobar", headers=admin_h, timeout=15)
    assert r.status_code == 400


def test_apply_profile_tech_denied(tech_h):
    r = requests.post(f"{BASE}/hardware/profile/economy", headers=tech_h, timeout=15)
    assert r.status_code == 403


def test_apply_profile_viewer_denied(viewer_h):
    r = requests.post(f"{BASE}/hardware/profile/economy", headers=viewer_h, timeout=15)
    assert r.status_code in (401, 403)


# --------- PUT /config ---------
def test_put_config_admin_marks_custom(admin_h):
    # apply balanced first so we know baseline
    requests.post(f"{BASE}/hardware/profile/balanced", headers=admin_h, timeout=15)
    payload = {
        "assignments": {"decode": "nvdec", "ai": "gpu1"},
        "priorities": {"ai": "low"},
        "auto_optimize": False,
    }
    r = requests.put(f"{BASE}/hardware/config", headers=admin_h, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["profile"] == "custom"
    assert d["assignments"]["decode"] == "nvdec"
    assert d["assignments"]["ai"] == "gpu1"
    assert d["priorities"]["ai"] == "low"
    assert d["auto_optimize"] is False
    # verify GET reflects
    g = requests.get(f"{BASE}/hardware/config", headers=admin_h, timeout=15).json()
    assert g["profile"] == "custom"
    assert g["assignments"]["decode"] == "nvdec"


def test_put_config_invalid_values_ignored(admin_h):
    payload = {"assignments": {"decode": "totally_invalid"}, "priorities": {"unknown_engine": "low"}}
    r = requests.put(f"{BASE}/hardware/config", headers=admin_h, json=payload, timeout=15)
    assert r.status_code == 200
    d = r.json()
    # decode must remain valid; not changed to invalid value
    assert d["assignments"]["decode"] in ["cpu", "nvdec", "quicksync", "amf", "auto"]
    assert "unknown_engine" not in d["priorities"]


def test_put_config_tech_denied(tech_h):
    r = requests.put(f"{BASE}/hardware/config", headers=tech_h,
                     json={"auto_optimize": True}, timeout=15)
    assert r.status_code == 403


def test_put_config_viewer_denied(viewer_h):
    r = requests.put(f"{BASE}/hardware/config", headers=viewer_h,
                     json={"auto_optimize": True}, timeout=15)
    assert r.status_code in (401, 403)


# --------- /api/hardware/monitor ---------
def test_hardware_monitor(admin_h):
    r = requests.get(f"{BASE}/hardware/monitor", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ["cpu_pct", "ram_pct", "ai_load_pct", "ffmpeg_load_pct", "streams",
              "fps", "power_total_w", "gpus", "timestamp"]:
        assert k in d, k
    assert isinstance(d["gpus"], list) and len(d["gpus"]) == 4
    for g in d["gpus"]:
        for k in ["id", "name", "vendor", "util_pct", "vram_mb", "vram_used_mb", "temp_c", "power_w"]:
            assert k in g, k
        assert 0 <= g["util_pct"] <= 100
        assert 0 <= g["temp_c"] <= 120


def test_hardware_monitor_tech(tech_h):
    r = requests.get(f"{BASE}/hardware/monitor", headers=tech_h, timeout=15)
    assert r.status_code == 200


# --------- regression ---------
def test_regression_reports_types(admin_h):
    r = requests.get(f"{BASE}/reports/types", headers=admin_h, timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_regression_network_stats(admin_h):
    r = requests.get(f"{BASE}/network/stats", headers=admin_h, timeout=15)
    assert r.status_code == 200


# --------- teardown: restore balanced ---------
def test_zz_restore_balanced(admin_h):
    r = requests.post(f"{BASE}/hardware/profile/balanced", headers=admin_h, timeout=15)
    assert r.status_code == 200
    assert r.json()["profile"] == "balanced"
