"""Iteration 31 — Phase 2 (v2.22.0) : Réconciliation DB ↔ go2rtc.

Vérifie que :
1. GET /api/diagnostics/streams-sync retourne le contrat attendu.
2. Simulation drift : suppression d'une variante _hd → drift détecté.
3. POST /repair réaligne tout et laisse in_sync avec 0 problème.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://video-command-6.preview.emergentagent.com",
).rstrip("/")
GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://localhost:1984")
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_streams_sync_contract(admin_token):
    r = requests.get(
        f"{BASE_URL}/api/diagnostics/streams-sync",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    expected = {"in_sync", "missing_in_go2rtc", "orphan_in_go2rtc",
                "variant_drift", "demo_names", "go2rtc_reachable",
                "go2rtc_error", "db_cameras_count", "go2rtc_streams_count"}
    missing = expected - set(data.keys())
    assert not missing, f"Champs manquants : {missing}"
    assert isinstance(data["in_sync"], list)
    assert isinstance(data["missing_in_go2rtc"], list)
    assert isinstance(data["variant_drift"], list)
    assert data["go2rtc_reachable"] is True, f"go2rtc doit être joignable en sandbox : {data['go2rtc_error']}"
    assert data["db_cameras_count"] >= 2, "au moins 2 caméras démo attendues"


def test_streams_sync_all_aligned_by_default(admin_token):
    """Après boot normal, aucun problème de sync attendu."""
    r = requests.get(
        f"{BASE_URL}/api/diagnostics/streams-sync",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    data = r.json()
    total_issues = len(data["missing_in_go2rtc"]) + len(data["variant_drift"]) + len(data["orphan_in_go2rtc"])
    assert total_issues == 0, f"Problèmes détectés : missing={data['missing_in_go2rtc']}, drift={data['variant_drift']}, orphans={data['orphan_in_go2rtc']}"


def test_streams_sync_drift_detection_and_repair(admin_token):
    """Simulation d'un drift : delete une variante _hd via go2rtc direct → repair → aligned."""
    # 1. Supprimer la variante _hd de demo-cam-001 directement via go2rtc
    try:
        del_r = requests.delete(f"{GO2RTC_URL}/api/streams?src=cam_demo-cam-001_hd", timeout=5)
    except requests.RequestException:
        pytest.skip("go2rtc pas joignable depuis les tests (env de test différent)")
    if del_r.status_code >= 500:
        pytest.skip(f"go2rtc DELETE échoué : {del_r.status_code}")

    time.sleep(1.5)
    # 2. Vérifier le drift
    r = requests.get(
        f"{BASE_URL}/api/diagnostics/streams-sync",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    d = r.json()
    drift = d["variant_drift"]
    assert any(x["stream_name"] == "cam_demo-cam-001" and x["hd_present"] is False for x in drift), \
        f"Drift attendu sur cam_demo-cam-001, obtenu : {drift}"

    # 3. Repair
    rep = requests.post(
        f"{BASE_URL}/api/diagnostics/streams-sync/repair",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert rep.status_code == 200, rep.text
    data_after = rep.json()
    total_issues = len(data_after["missing_in_go2rtc"]) + len(data_after["variant_drift"]) + len(data_after["orphan_in_go2rtc"])
    assert total_issues == 0, f"Après repair, il reste des problèmes : {data_after}"
