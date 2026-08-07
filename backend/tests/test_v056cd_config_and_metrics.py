"""Tests — Phase C + D · Pipeline Hardening v0.5.6.

Phase C : Config par caméra (pipeline_config).
Phase D : Métriques p95/p99 dans snapshot.
"""
import os
import sys
from pathlib import Path

import pytest
import requests

_env_file = Path("/app/backend/.env")
for line in _env_file.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
sys.path.insert(0, "/app/backend")
os.environ.setdefault("TESTING", "1")

_env = Path("/app/frontend/.env").read_text()
BASE_URL = None
for line in _env.splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().rstrip("/")


# ═══════════════════════════════════════════════════════════════════════
# Phase C — registries lisent cam_config
# ═══════════════════════════════════════════════════════════════════════
def test_detector_registry_reads_cam_config():
    from pipeline_v2.detector import registry
    # Config sans detector → défaut yolov11
    _det, name, w = registry.get_active({})
    assert name == "yolov11" and w is None
    # Config avec detector inconnu → fallback + warning explicite
    _det, name, w = registry.get_active({"pipeline_config": {"detector": "rt-detr"}})
    assert name == "yolov11"
    assert w is not None and "rt-detr" in w


def test_plate_registry_reads_cam_config():
    from pipeline_v2.plate_recognizer import plate_registry
    _r, name, w = plate_registry.get_active({"pipeline_config": {"anpr": ["fast-alpr"]}})
    assert name == "fast-alpr" and w is None
    _r, name, w = plate_registry.get_active({"pipeline_config": {"anpr": ["ocr-inconnu", "fast-alpr"]}})
    assert name == "fast-alpr"
    assert w is not None and "ocr-inconnu" in w


def test_resolve_algo_reads_cam_config():
    from pipeline_v2.tracking import resolve_algo
    req, eff, w = resolve_algo([], {"pipeline_config": {"tracker": "botsort"}})
    assert req == "botsort" and eff == "botsort" and w is None
    req, eff, w = resolve_algo([], {"pipeline_config": {"tracker": "deepsort"}})
    assert req == "deepsort" and eff == "bytetrack"
    assert w and "deepsort" in w


# ═══════════════════════════════════════════════════════════════════════
# Phase C — API endpoint /pipeline-config
# ═══════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "admin@mg-vms.com", "password": "Admin@2026"},
                       timeout=8)
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def a_camera_id(admin_token):
    r = requests.get(f"{BASE_URL}/api/cameras",
                       headers={"Authorization": f"Bearer {admin_token}"}, timeout=8)
    cams = r.json()
    assert isinstance(cams, list) and cams, "Au moins une caméra requise pour le test"
    return cams[0]["id"]


def test_get_pipeline_config_defaults(admin_token, a_camera_id):
    r = requests.get(f"{BASE_URL}/api/cameras/{a_camera_id}/pipeline-config",
                       headers={"Authorization": f"Bearer {admin_token}"}, timeout=6)
    assert r.status_code == 200
    body = r.json()
    eff = body["pipeline_config"]
    # Migration auto : chaque cam existante retourne les défauts
    assert eff["detector"] == "yolov11"
    assert eff["tracker"] == "bytetrack"
    assert eff["anpr"] == ["fast-alpr"]
    assert eff["fusion"] == "hierarchical"


def test_put_pipeline_config_valid(admin_token, a_camera_id):
    r = requests.put(f"{BASE_URL}/api/cameras/{a_camera_id}/pipeline-config",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"tracker": "botsort", "fusion": "highest"},
                       timeout=6)
    assert r.status_code == 200
    assert r.json()["pipeline_config"]["tracker"] == "botsort"
    assert r.json()["pipeline_config"]["fusion"] == "highest"

    # Cleanup
    requests.put(f"{BASE_URL}/api/cameras/{a_camera_id}/pipeline-config",
                 headers={"Authorization": f"Bearer {admin_token}"},
                 json={"tracker": "bytetrack", "fusion": "hierarchical"},
                 timeout=6)


def test_put_pipeline_config_invalid_tracker(admin_token, a_camera_id):
    r = requests.put(f"{BASE_URL}/api/cameras/{a_camera_id}/pipeline-config",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"tracker": "some-fake-tracker"}, timeout=6)
    assert r.status_code == 400


def test_put_pipeline_config_invalid_fusion(admin_token, a_camera_id):
    r = requests.put(f"{BASE_URL}/api/cameras/{a_camera_id}/pipeline-config",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"fusion": "not-a-mode"}, timeout=6)
    assert r.status_code == 400


def test_put_pipeline_config_empty_anpr(admin_token, a_camera_id):
    r = requests.put(f"{BASE_URL}/api/cameras/{a_camera_id}/pipeline-config",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"anpr": []}, timeout=6)
    assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════════
# Phase D — snapshot avec p99 et min
# ═══════════════════════════════════════════════════════════════════════
def test_pipeline_metrics_p99_and_min():
    from pipeline_metrics import PipelineMetrics
    m = PipelineMetrics()
    # Simule 30 cycles pour dépasser le seuil des 20 pour p95 et 5 pour stage p95
    for i in range(30):
        m.record_stage("cam-test", "yolo_ms", 10 + i)
        m.record("cam-test", pipeline_ms=50 + i, plugins_used={})
    snap = m.snapshot()
    assert "cam-test" in snap
    yolo = snap["cam-test"]["stages"]["yolo_ms"]
    assert "p95" in yolo and yolo["p95"] is not None
    assert "p99" in yolo and yolo["p99"] is not None
    assert "min" in yolo
    assert "count" in yolo and yolo["count"] == 30
    assert snap["cam-test"]["pipeline_ms_min"] > 0
    assert snap["cam-test"]["pipeline_ms_p95"] is not None
    # p99 nécessite 100 échantillons
    assert snap["cam-test"]["pipeline_ms_p99"] is None
