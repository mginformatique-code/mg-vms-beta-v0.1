"""v0.8-rc6 · FEATURE FREEZE · Stabilisation Sprint 3

Priorité #4 · Camera State Fusion — un état caméra fusionne 4 signaux
Priorité #7 · Pipeline Inspector End-to-End — suit UNE détection

Preuves mesurables exigées par mandat.
"""
from __future__ import annotations

import asyncio
import os
import time
import pytest


os.environ["TESTING"] = "1"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ═══════════════════════════════════════════════════════════════════
# Suite A · Camera State Fusion
# ═══════════════════════════════════════════════════════════════════
class TestCameraStateFusionRules:
    def test_online_if_frame_source_positive(self):
        from pipeline_v2.camera_state import _apply_rules, Signal
        signals = [
            Signal("frame_source", True, "frame 0.5s"),
            Signal("pipeline_activity", False, "pas de record"),
            Signal("go2rtc_stream", False, "idle"),
            Signal("tcp_reachable", False, "timeout"),
        ]
        fused = _apply_rules("cam-x", signals)
        assert fused.status == "online"
        # confidence = 1/4 = 25%
        assert fused.confidence == 25
        assert any("frame_source ok" in r for r in fused.reasons)

    def test_online_if_pipeline_activity_positive_even_without_frame(self):
        """Une caméra qui traite des events est en ligne, peu importe le reste."""
        from pipeline_v2.camera_state import _apply_rules, Signal
        signals = [
            Signal("frame_source", False, "worker mort"),
            Signal("pipeline_activity", True, "stage 5s"),
            Signal("go2rtc_stream", False, "0 octet"),
            Signal("tcp_reachable", False, "unknown"),
        ]
        fused = _apply_rules("cam-x", signals)
        assert fused.status == "online"

    def test_degraded_if_only_tcp_reachable(self):
        """Caméra visible réseau mais pas de flux → dégradé, PAS offline."""
        from pipeline_v2.camera_state import _apply_rules, Signal
        signals = [
            Signal("frame_source", False, "pas de worker"),
            Signal("pipeline_activity", False, "vide"),
            Signal("go2rtc_stream", False, "idle"),
            Signal("tcp_reachable", True, "port 554 ouvert"),
        ]
        fused = _apply_rules("cam-x", signals)
        assert fused.status == "degraded"
        assert any("TCP joignable" in r for r in fused.reasons)

    def test_offline_only_if_all_signals_negative(self):
        from pipeline_v2.camera_state import _apply_rules, Signal
        signals = [
            Signal("frame_source", False, "pas de worker"),
            Signal("pipeline_activity", False, "vide"),
            Signal("go2rtc_stream", False, "unreachable"),
            Signal("tcp_reachable", False, "no route"),
        ]
        fused = _apply_rules("cam-x", signals)
        assert fused.status == "offline"
        assert fused.confidence == 0

    def test_never_offline_when_producing_frames(self):
        """PROMESSE CLIENT : une caméra qui produit des frames RTSP n'est
        JAMAIS offline, même si go2rtc et TCP échouent."""
        from pipeline_v2.camera_state import _apply_rules, Signal
        signals = [
            Signal("frame_source", True, "12 fps"),
            Signal("pipeline_activity", False, "vide"),
            Signal("go2rtc_stream", False, "unreachable"),
            Signal("tcp_reachable", False, "no route"),
        ]
        fused = _apply_rules("cam-x", signals)
        assert fused.status == "online", "Une caméra produisant des frames ne doit JAMAIS être offline"


class TestCameraStateSignalCheckers:
    def test_check_frame_source_returns_negative_when_no_worker(self):
        from pipeline_v2.camera_state import check_frame_source
        sig = check_frame_source("ghost-camera-that-does-not-exist-999")
        assert sig.name == "frame_source"
        assert sig.positive is False
        assert "aucun worker actif" in sig.detail

    def test_check_pipeline_activity_returns_negative_for_unknown(self):
        from pipeline_v2.camera_state import check_pipeline_activity
        sig = check_pipeline_activity("ghost-cam-999")
        assert sig.name == "pipeline_activity"
        assert sig.positive is False


class TestCameraStateEndpoint:
    def test_endpoints_registered(self):
        from server import app
        paths = {r.path for r in app.routes}
        assert "/api/diagnostics/camera-state/{camera_id}" in paths
        assert "/api/diagnostics/camera-state" in paths


# ═══════════════════════════════════════════════════════════════════
# Suite B · Pipeline Trace End-to-End
# ═══════════════════════════════════════════════════════════════════
class TestTraceCollectorSampling:
    def test_sampling_gating(self):
        from pipeline_v2.trace import TraceCollector
        c = TraceCollector(sampling_n=10)
        # 10 appels → 1 seul sample (au 10e)
        results = [c.should_sample("cam-a") for _ in range(10)]
        assert sum(results) == 1
        assert results[-1] is True  # le 10e est sampled

    def test_sampling_isolated_per_camera(self):
        from pipeline_v2.trace import TraceCollector
        c = TraceCollector(sampling_n=5)
        r_a = [c.should_sample("A") for _ in range(5)]
        r_b = [c.should_sample("B") for _ in range(5)]
        # chaque caméra sample 1 fois indépendamment
        assert sum(r_a) == 1 and sum(r_b) == 1

    def test_set_sampling_updates(self):
        from pipeline_v2.trace import TraceCollector
        c = TraceCollector(sampling_n=100)
        assert c.get_sampling() == 100
        c.set_sampling(500)
        assert c.get_sampling() == 500


class TestTraceLifecycle:
    def test_start_add_finish(self):
        from pipeline_v2.trace import TraceCollector, stage
        c = TraceCollector(sampling_n=1)
        t = c.start_trace("cam-x")
        assert t.trace_id
        assert t.camera_id == "cam-x"
        # Enregistrer 3 stages
        with stage(t, "decode"):
            time.sleep(0.001)
        with stage(t, "yolo"):
            time.sleep(0.002)
        with stage(t, "anpr"):
            time.sleep(0.001)
        # Le collecteur global capte via record_stage — vérifions via l'objet
        # NB : `stage` utilise le collector du module (pas c). On teste direct :
        c.record_stage(t, "test_stage", 1.23)
        assert any(s.name == "test_stage" for s in t.stages)
        c.finish_trace(t, {"plates": ["AB123"]})
        assert t.finished
        assert t.outcome == {"plates": ["AB123"]}

    def test_ring_buffer_caps_at_max(self):
        from pipeline_v2.trace import TraceCollector, MAX_TRACES
        c = TraceCollector(sampling_n=1)
        for i in range(MAX_TRACES + 5):
            c.start_trace(f"cam-{i}")
        rec = c.list_recent(limit=100)
        # Ne dépasse jamais MAX_TRACES
        assert len(rec) <= MAX_TRACES

    def test_get_returns_specific_trace(self):
        from pipeline_v2.trace import TraceCollector
        c = TraceCollector(sampling_n=1)
        t = c.start_trace("cam-1")
        c.finish_trace(t)
        found = c.get(t.trace_id)
        assert found is not None
        assert found["camera_id"] == "cam-1"
        assert c.get("nonexistent-id-999") is None

    def test_clear_purges_all(self):
        from pipeline_v2.trace import TraceCollector
        c = TraceCollector(sampling_n=1)
        c.start_trace("a")
        c.start_trace("b")
        n = c.clear()
        assert n == 2
        assert c.list_recent() == []


class TestTraceEndpoints:
    def test_endpoints_registered(self):
        from server import app
        paths = {r.path for r in app.routes}
        for p in ("/api/diagnostics/traces",
                   "/api/diagnostics/traces/{trace_id}",
                   "/api/diagnostics/traces/sampling",
                   "/api/diagnostics/traces/clear"):
            assert p in paths, f"endpoint {p} manquant"


class TestCameraWorkerTracingWiring:
    def test_camera_worker_source_uses_trace(self):
        src = open("/app/backend/pipeline_v2/camera_worker.py", encoding="utf-8").read()
        # Preuves d'intégration
        assert "from .trace import collector as _trace_collector" in src
        assert "start_trace(self.camera_id)" in src
        # Les 6 stages critiques instrumentés
        for stage_name in ("decode", "motion", "yolo", "tracking", "roi", "anpr"):
            assert f'_trace_stage(_trc, "{stage_name}")' in src, \
                f"stage {stage_name} pas instrumenté"
        assert 'finish_trace' in src


# ═══════════════════════════════════════════════════════════════════
# Suite C · Non-régression
# ═══════════════════════════════════════════════════════════════════
class TestNoRegression:
    def test_all_critical_diagnostic_endpoints_still_exist(self):
        from server import app
        paths = {r.path for r in app.routes}
        for p in ("/api/diagnostics/pipeline-inspector",
                   "/api/diagnostics/hot-reload",
                   "/api/diagnostics/frame-source",
                   "/api/diagnostics/plate-quality",
                   "/api/diagnostics/qos-thresholds",
                   "/api/diagnostics/anpr-quality",
                   # Nouveaux Sprint 3
                   "/api/diagnostics/camera-state",
                   "/api/diagnostics/traces"):
            assert p in paths, f"endpoint {p} disparu"
