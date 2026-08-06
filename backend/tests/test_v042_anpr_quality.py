"""Tests v0.4.2 · ANPR Quality Controller + Auto-suspension + Caméras spécialisées.

Valide :
1. Évaluation qualité (brightness / sharpness / contrast / night detection)
2. Machine à états ACTIVE ↔ SUSPENDED avec hystérésis N/M
3. Détection caméras spécialisées (Dahua ITC, Hikvision DeepInView)
4. Reconfiguration à chaud
5. Endpoints HTTP diagnostics
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import numpy as np
import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from pipeline_v2.anpr_quality import (AnprQualityController, QualityScore,
                                       SPECIALIZED_ANPR_MODELS, anpr_quality)


def _make_good_frame():
    """Image bien contrastée : gradient + bruit → sharpness élevée."""
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    # gradient horizontal → contraste haut
    for x in range(320):
        img[:, x, :] = int(x * 255 / 320)
    # + damier fin pour la variance Laplacienne
    img[::2, ::2, :] = 255
    img[1::2, 1::2, :] = 0
    return img


def _make_dark_frame():
    """Image très sombre + plate → simulate nuit sans IR."""
    return np.full((240, 320, 3), 8, dtype=np.uint8)


def _make_blurry_frame():
    """Image uniforme grise → très faible sharpness + contraste."""
    return np.full((240, 320, 3), 128, dtype=np.uint8)


# ── 1. Évaluation qualité ─────────────────────────────────────────

def test_evaluate_good_frame_gives_high_score():
    ctrl = AnprQualityController()
    q = ctrl.evaluate(_make_good_frame(), now=datetime(2026, 2, 6, 14, 0))
    assert q.score >= 0.5
    assert q.sharpness > 100
    assert q.contrast > 25
    assert q.is_night is False


def test_evaluate_dark_frame_gives_low_score():
    ctrl = AnprQualityController()
    q = ctrl.evaluate(_make_dark_frame(), now=datetime(2026, 2, 6, 2, 0))
    assert q.score < 0.4
    assert q.brightness < 30
    assert any("brightness" in r for r in q.reasons_fail)
    assert q.is_night is True


def test_evaluate_blurry_frame_flagged():
    ctrl = AnprQualityController()
    q = ctrl.evaluate(_make_blurry_frame(), now=datetime(2026, 2, 6, 14, 0))
    assert q.sharpness < 100
    assert any("sharpness" in r for r in q.reasons_fail)


# ── 2. Machine à états ACTIVE ↔ SUSPENDED ─────────────────────────

def test_hysteresis_suspends_after_n_bad_cycles():
    """5 cycles consécutifs sous seuil → suspendu."""
    ctrl = AnprQualityController(min_score=0.5, suspend_after_bad=5)
    dark = _make_dark_frame()
    for i in range(4):
        should_run, state, _ = ctrl.should_run_anpr("cam-A", dark)
        assert should_run is True
        assert state.suspended is False
    # 5e cycle → suspension
    should_run, state, _ = ctrl.should_run_anpr("cam-A", dark)
    assert should_run is False
    assert state.suspended is True
    assert state.total_suspensions == 1
    assert "suspendu automatiquement" in state.last_reason


def test_hysteresis_resumes_after_m_good_cycles():
    """Suspendu → 3 cycles bons consécutifs → repris."""
    ctrl = AnprQualityController(min_score=0.4, suspend_after_bad=2,
                                  resume_after_good=3)
    dark = _make_dark_frame()
    good = _make_good_frame()

    # Suspend
    ctrl.should_run_anpr("cam-B", dark)
    should_run, state, _ = ctrl.should_run_anpr("cam-B", dark)
    assert state.suspended is True

    # 2 cycles bons → toujours suspendu
    ctrl.should_run_anpr("cam-B", good)
    should_run, state, _ = ctrl.should_run_anpr("cam-B", good)
    assert state.suspended is True

    # 3e cycle bon → repris
    should_run, state, _ = ctrl.should_run_anpr("cam-B", good)
    assert state.suspended is False
    assert "repris" in state.last_reason


def test_single_bad_cycle_does_not_suspend():
    """Anti-blip : 1 seul cycle sous seuil ne suspend pas."""
    ctrl = AnprQualityController(min_score=0.5, suspend_after_bad=5)
    should_run, state, _ = ctrl.should_run_anpr("cam-C", _make_dark_frame())
    assert should_run is True
    assert state.suspended is False
    assert state.consecutive_bad == 1


# ── 3. Caméras spécialisées ANPR 24/7 ─────────────────────────────

def test_specialized_camera_dahua_itc_bypasses_suspension():
    """Une Dahua ITC413 doit rester en OCR même en nuit noire."""
    ctrl = AnprQualityController(min_score=0.5, suspend_after_bad=1)
    cam = {"id": "cam-itc", "model": "Dahua ITC413-PW6M"}
    for _ in range(20):
        should_run, state, _ = ctrl.should_run_anpr("cam-itc", _make_dark_frame(),
                                                     camera=cam)
        assert should_run is True
        assert state.suspended is False
        assert state.is_specialized is True
        assert "Dahua ITC413" in state.specialized_model


def test_specialized_camera_hikvision_deepinview():
    ctrl = AnprQualityController()
    cam = {"id": "cam-hv", "model": "Hikvision iDS-2CD7A46G0"}
    should_run, state, _ = ctrl.should_run_anpr("cam-hv", _make_dark_frame(),
                                                 camera=cam)
    assert should_run is True
    assert state.is_specialized is True


def test_non_specialized_camera_can_be_suspended():
    """Une caméra générique (Hikvision DS classique) peut être suspendue."""
    ctrl = AnprQualityController(min_score=0.5, suspend_after_bad=2)
    cam = {"id": "cam-basic", "model": "Hikvision DS-2CD2043G0"}
    for _ in range(3):
        should_run, state, _ = ctrl.should_run_anpr("cam-basic", _make_dark_frame(),
                                                     camera=cam)
    assert state.suspended is True
    assert state.is_specialized is False


# ── 4. Configuration à chaud ───────────────────────────────────────

def test_configure_updates_thresholds():
    ctrl = AnprQualityController()
    ctrl.configure(min_score=0.75, sharpness_min=150, suspend_after_bad=10)
    cfg = ctrl.config_dict()
    assert cfg["min_score"] == 0.75
    assert cfg["sharpness_min"] == 150.0
    assert cfg["suspend_after_bad"] == 10


def test_reset_clears_state():
    ctrl = AnprQualityController()
    ctrl.should_run_anpr("cam-X", _make_dark_frame())
    assert "cam-X" in ctrl.states()
    ctrl.reset("cam-X")
    assert "cam-X" not in ctrl.states()


# ── 5. Endpoint HTTP ──────────────────────────────────────────────

def test_http_anpr_quality_endpoints():
    import requests
    api_url = ""
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    api_url = line.split("=", 1)[1].strip()
                    break
    except FileNotFoundError:
        pytest.skip("No frontend/.env")
    if not api_url:
        pytest.skip("No backend URL")

    r = requests.post(f"{api_url}/api/auth/login",
                       json={"email": "admin@mg-vms.com", "password": "Admin@2026"},
                       timeout=10)
    if r.status_code != 200:
        pytest.skip("Auth unavailable")
    token = r.json()["access_token"]
    hdr = {"Authorization": f"Bearer {token}"}

    # GET
    r = requests.get(f"{api_url}/api/diagnostics/anpr-quality", headers=hdr, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert "config" in body
    assert "cameras" in body

    # PUT config
    r = requests.put(f"{api_url}/api/diagnostics/anpr-quality/config",
                      headers={**hdr, "Content-Type": "application/json"},
                      json={"min_score": 0.42},
                      timeout=10)
    assert r.status_code == 200
    assert r.json()["config"]["min_score"] == 0.42

    # POST reset all
    r = requests.post(f"{api_url}/api/diagnostics/anpr-quality/reset",
                       headers=hdr, timeout=10)
    assert r.status_code == 200
    assert r.json()["reset"] == "all"

    # Restore defaults (pour ne pas polluer le runtime)
    requests.put(f"{api_url}/api/diagnostics/anpr-quality/config",
                 headers={**hdr, "Content-Type": "application/json"},
                 json={"min_score": 0.4, "suspend_after_bad": 5},
                 timeout=10)


# ── 6. Registre modèles spécialisés ───────────────────────────────

def test_specialized_registry_has_key_brands():
    assert "itc413" in SPECIALIZED_ANPR_MODELS
    assert "ids-2cd7a" in SPECIALIZED_ANPR_MODELS
    assert len(SPECIALIZED_ANPR_MODELS) >= 5


def test_singleton_anpr_quality_available():
    """Le singleton runtime est bien exposé."""
    assert isinstance(anpr_quality, AnprQualityController)
