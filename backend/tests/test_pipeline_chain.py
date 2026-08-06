"""Tests pipeline Detector → Tracker → Segmenter → PipelineConsumer."""
from __future__ import annotations
import asyncio
import sys
from datetime import datetime, timezone

import numpy as np
import pytest

sys.path.insert(0, "/app/backend")

from plugin_manager import bus, Frame
from plugin_manager.interfaces import Detection, FrameAnalyzer, AnalysisResult
from plugin_manager.loader import loader


class _SeedAnalyzer(FrameAnalyzer):
    """Analyzer factice qui retourne des detections fixes pour tester le pipeline."""
    name = "_pipeline_test_seed"
    version = "test"

    def __init__(self, dets):
        self._dets = dets

    async def analyze(self, frame, camera_config):
        return AnalysisResult(detections=list(self._dets), timing_ms=0)


def _make_frame():
    arr = np.zeros((480, 640, 3), dtype=np.uint8)
    return Frame(camera_id="test", timestamp=datetime.now(timezone.utc).isoformat(),
                 numpy_bgr=arr, width=640, height=480)


def test_pipeline_dispatches_detections_to_tracker_and_business():
    """Le pipeline enchaîne detector → tracker → business en une passe."""
    async def _run():
        # Load builtin plugins (idempotent) puis registre du seed analyzer
        await loader.discover_and_load_all()

        # Désactive TOUS les FrameAnalyzers pour ne garder que le seed
        fa_states = {}
        for e in bus.list_entries("FrameAnalyzer"):
            fa_states[e.name] = e.enabled
            bus.set_enabled(e.name, False)

        try:
            seed = _SeedAnalyzer([
                Detection(label="person", confidence=0.9, bbox=(100, 100, 200, 400)),
                Detection(label="car", confidence=0.85, bbox=(300, 200, 500, 400)),
            ])
            bus.register("_pipeline_test_seed", seed, order=1)
            frame = _make_frame()
            # v0.4.3 · Fermeture stricte : enabled_plugins explicite obligatoire
            pr = await bus.dispatch_pipeline(
                frame,
                camera_config={"enabled_plugins": [
                    "_pipeline_test_seed", "occupancy", "core-tracking-stage",
                ]},
                run_business=True, emit_events=False,
            )

            # Vérifie le chaînage
            assert len(pr.detections) == 2
            assert "_pipeline_test_seed" in pr.plugins_used.get("detectors", [])
            # Business plugins doivent avoir été appelés
            assert "occupancy" in pr.plugins_used.get("business", [])
            # Au moins l'événement occupancy est présent
            assert any(ev.get("type") == "occupancy.zone" for ev in pr.business_events)
        finally:
            bus.unregister("_pipeline_test_seed")
            for name, en in fa_states.items():
                bus.set_enabled(name, en)
    asyncio.run(_run())


def test_pipeline_fire_detection_emits_critical():
    async def _run():
        await loader.discover_and_load_all()
        fa_states = {}
        for e in bus.list_entries("FrameAnalyzer"):
            fa_states[e.name] = e.enabled
            bus.set_enabled(e.name, False)
        try:
            seed = _SeedAnalyzer([
                Detection(label="fire", confidence=0.88, bbox=(300, 100, 500, 300)),
            ])
            bus.register("_pipeline_test_seed", seed, order=1)
            pr = await bus.dispatch_pipeline(
                _make_frame(),
                camera_config={"enabled_plugins": [
                    "_pipeline_test_seed", "fire-detection",
                ]},
                run_business=True,
            )
            fire_events = [ev for ev in pr.business_events
                           if ev.get("source") == "fire-detection"]
            assert len(fire_events) == 1
            assert fire_events[0]["severity"] == "critical"
        finally:
            bus.unregister("_pipeline_test_seed")
            for name, en in fa_states.items():
                bus.set_enabled(name, en)
    asyncio.run(_run())


def test_pipeline_returns_timing_metrics():
    async def _run():
        await loader.discover_and_load_all()
        # v0.4.3 · timing metrics disponibles même quand aucun plugin ne
        # tourne (fermeture stricte, whitelist vide).
        pr = await bus.dispatch_pipeline(
            _make_frame(),
            camera_config={"enabled_plugins": ["occupancy"]},
            run_business=True,
        )
        assert "detection_ms" in pr.timing_ms
        assert "tracking_ms" in pr.timing_ms
        assert "business_ms" in pr.timing_ms
    asyncio.run(_run())
