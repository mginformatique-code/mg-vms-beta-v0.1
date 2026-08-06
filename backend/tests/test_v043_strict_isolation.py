"""Tests v0.4.3 — Fermeture stricte fail-safe + isolation ANPR par caméra.

Ces tests garantissent que le bug historique "caméra sans plugin ANPR
produit malgré tout des plaques" NE PEUT PLUS jamais réapparaître, et que
`enabled_plugins ∈ {[], null, absent}` ne dispatche aucun plugin.

Preuves testées :
  1. `bus.dispatch_pipeline(camera_config sans enabled_plugins)` → 0 dispatch
  2. `bus.dispatch_pipeline(camera_config={"enabled_plugins": []})` → 0 dispatch
  3. `bus.dispatch_pipeline(camera_config={"enabled_plugins": None})` → 0 dispatch
  4. `bus.dispatch_plate(only=None|set())` → 0 moteur ANPR appelé
  5. `bus.dispatch_frame(camera_config sans whitelist)` → 0 FrameAnalyzer appelé
  6. `CameraWorker._stage_anpr` : caméra sans "fast-alpr" dans enabled_plugins
     → aucune plaque produite, même si des véhicules sont détectés
  7. Isolation caméra ↔ caméra : les plaques de A n'apparaissent jamais côté B
  8. Grand-angle vs téléobjectif (whitelists disjointes) : aucun crossover
"""
from __future__ import annotations

import asyncio
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")


def _img(w=640, h=480):
    rng = np.random.default_rng(11)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


# ────────────────────────────────────────────────────────────────────────
# P1 · Fermeture stricte fail-safe sur PluginBus
# ────────────────────────────────────────────────────────────────────────

class TestBusFailSafeClosure:
    def _make_bus_with_spies(self):
        from plugin_manager.bus import PluginBus
        from plugin_manager.interfaces import (FrameAnalyzer, PlateRecognizer,
                                                PipelineConsumer, AnalysisResult,
                                                PlateResult)

        calls = {"frame": 0, "plate": 0, "consumer": 0}

        class _FA(FrameAnalyzer):
            name = "spy-fa"
            async def analyze(self, frame, camera_config=None):
                calls["frame"] += 1
                return AnalysisResult(detections=[])

        class _PR(PlateRecognizer):
            name = "spy-pr"
            async def recognize(self, frame, vehicle_bbox=None):
                calls["plate"] += 1
                return [PlateResult(text="XX", confidence=0.9, engine="spy")]

        class _CS(PipelineConsumer):
            name = "spy-cs"
            async def consume(self, frame, pr):
                calls["consumer"] += 1
                return []

        bus = PluginBus(default_timeout_s=1.0)
        bus.register("spy-fa", _FA())
        bus.register("spy-pr", _PR())
        bus.register("spy-cs", _CS())
        return bus, calls

    def test_dispatch_pipeline_empty_list_dispatches_nothing(self):
        from plugin_manager.interfaces import Frame
        bus, calls = self._make_bus_with_spies()
        frame = Frame(camera_id="c", timestamp="t", numpy_bgr=_img(),
                      width=640, height=480)
        asyncio.new_event_loop().run_until_complete(
            bus.dispatch_pipeline(frame,
                                   camera_config={"enabled_plugins": []},
                                   run_business=True))
        assert calls == {"frame": 0, "plate": 0, "consumer": 0}

    def test_dispatch_pipeline_none_dispatches_nothing(self):
        from plugin_manager.interfaces import Frame
        bus, calls = self._make_bus_with_spies()
        frame = Frame(camera_id="c", timestamp="t", numpy_bgr=_img(),
                      width=640, height=480)
        asyncio.new_event_loop().run_until_complete(
            bus.dispatch_pipeline(frame,
                                   camera_config={"enabled_plugins": None},
                                   run_business=True))
        assert calls == {"frame": 0, "plate": 0, "consumer": 0}

    def test_dispatch_pipeline_absent_field_dispatches_nothing(self):
        from plugin_manager.interfaces import Frame
        bus, calls = self._make_bus_with_spies()
        frame = Frame(camera_id="c", timestamp="t", numpy_bgr=_img(),
                      width=640, height=480)
        asyncio.new_event_loop().run_until_complete(
            bus.dispatch_pipeline(frame,
                                   camera_config={},  # aucune whitelist
                                   run_business=True))
        assert calls == {"frame": 0, "plate": 0, "consumer": 0}

    def test_dispatch_pipeline_no_camera_config_at_all(self):
        from plugin_manager.interfaces import Frame
        bus, calls = self._make_bus_with_spies()
        frame = Frame(camera_id="c", timestamp="t", numpy_bgr=_img(),
                      width=640, height=480)
        asyncio.new_event_loop().run_until_complete(
            bus.dispatch_pipeline(frame, run_business=True))
        assert calls == {"frame": 0, "plate": 0, "consumer": 0}

    def test_dispatch_plate_requires_only(self):
        from plugin_manager.interfaces import Frame
        bus, calls = self._make_bus_with_spies()
        frame = Frame(camera_id="c", timestamp="t", numpy_bgr=_img(),
                      width=640, height=480)
        # only=None → 0
        res = asyncio.new_event_loop().run_until_complete(bus.dispatch_plate(frame))
        assert res == [] and calls["plate"] == 0
        # only=empty → 0
        res = asyncio.new_event_loop().run_until_complete(
            bus.dispatch_plate(frame, only=set()))
        assert res == [] and calls["plate"] == 0
        # only={"spy-pr"} → 1
        res = asyncio.new_event_loop().run_until_complete(
            bus.dispatch_plate(frame, only={"spy-pr"}))
        assert calls["plate"] == 1

    def test_dispatch_frame_empty_whitelist_no_call(self):
        from plugin_manager.interfaces import Frame
        bus, calls = self._make_bus_with_spies()
        frame = Frame(camera_id="c", timestamp="t", numpy_bgr=_img(),
                      width=640, height=480)
        # sans whitelist
        asyncio.new_event_loop().run_until_complete(bus.dispatch_frame(frame))
        assert calls["frame"] == 0
        # whitelist vide
        asyncio.new_event_loop().run_until_complete(
            bus.dispatch_frame(frame, camera_config={"enabled_plugins": []}))
        assert calls["frame"] == 0
        # whitelist explicite
        asyncio.new_event_loop().run_until_complete(
            bus.dispatch_frame(frame, camera_config={"enabled_plugins": ["spy-fa"]}))
        assert calls["frame"] == 1


# ────────────────────────────────────────────────────────────────────────
# P9 · Isolation ANPR par caméra (au niveau CameraWorker)
# ────────────────────────────────────────────────────────────────────────

class TestCameraWorkerAnprIsolation:
    def _seed_vehicle(self, worker, ctx):
        """Injecte une détection véhicule et un ROI dans le contexte pour
        tester _stage_anpr sans dépendre d'un YOLO réel."""
        from pipeline_v2.frame_context import VehicleROI
        ctx.image = _img(1280, 720)
        bbox = (100, 100, 700, 500)
        det = {"class": "car", "label": "Voiture", "confidence": 0.9,
               "thumbnail": None, "_crop": ctx.image[100:500, 100:700],
               "vehicle_color": "Rouge", "_bbox": bbox}
        ctx.detections.append(det)
        ctx.vehicle_rois.append(VehicleROI(
            owner=det, bbox=bbox, crop=ctx.image[100:500, 100:700],
        ))

    def test_no_plate_when_fast_alpr_not_whitelisted(self):
        """Caméra sans "fast-alpr" dans enabled_plugins → 0 plaque."""
        from pipeline_v2.camera_worker import CameraWorker
        from pipeline_v2.frame_context import FrameContext
        w = CameraWorker("wide-cam")
        ctx = FrameContext(camera_id="wide-cam")
        self._seed_vehicle(w, ctx)
        # enabled_plugins ne contient PAS fast-alpr
        w._stage_anpr(ctx, enabled_plugins=["yolo", "bytetrack"], camera=None)
        assert ctx.plates == [], "aucune plaque ne doit être produite"

    def test_no_plate_when_enabled_plugins_empty(self):
        from pipeline_v2.camera_worker import CameraWorker
        from pipeline_v2.frame_context import FrameContext
        w = CameraWorker("cam-empty")
        ctx = FrameContext(camera_id="cam-empty")
        self._seed_vehicle(w, ctx)
        w._stage_anpr(ctx, enabled_plugins=[], camera=None)
        assert ctx.plates == []

    def test_no_plate_when_enabled_plugins_none(self):
        from pipeline_v2.camera_worker import CameraWorker
        from pipeline_v2.frame_context import FrameContext
        w = CameraWorker("cam-null")
        ctx = FrameContext(camera_id="cam-null")
        self._seed_vehicle(w, ctx)
        w._stage_anpr(ctx, enabled_plugins=None, camera=None)
        assert ctx.plates == []

    def test_two_cameras_no_plate_crossover(self):
        """Cam A produit peut-être des plaques (fast-alpr whitelisté). Cam B
        (grand-angle, sans fast-alpr) ne doit jamais voir les plaques de A."""
        from pipeline_v2.camera_worker import CameraWorker
        from pipeline_v2.frame_context import FrameContext
        wA = CameraWorker("teleobjectif-A")
        wB = CameraWorker("grand-angle-B")
        ctxA = FrameContext(camera_id="teleobjectif-A")
        ctxB = FrameContext(camera_id="grand-angle-B")
        self._seed_vehicle(wA, ctxA)
        self._seed_vehicle(wB, ctxB)
        # A : fast-alpr autorisé (peut ou non produire selon disponibilité alpr)
        wA._stage_anpr(ctxA, enabled_plugins=["fast-alpr"], camera=None)
        # B : téléobjectif interdit, aucun plugin ANPR autorisé
        wB._stage_anpr(ctxB, enabled_plugins=["yolo"], camera=None)
        # B ne doit JAMAIS avoir de plaque, quelle que soit A
        assert ctxB.plates == []
        # Aucune fuite d'état : le cache plaques de A n'est pas lu par B
        assert wA._plate_cache is not wB._plate_cache

    def test_worker_pool_never_shares_between_cameras(self):
        from pipeline_v2.camera_worker import PipelineRuntime
        rt = PipelineRuntime()
        wA = rt.worker("camA")
        wB = rt.worker("camB")
        assert wA is not wB
        assert wA._plate_cache is not wB._plate_cache
        wA._plate_cache["AB123CD"] = None  # sentinel
        assert "AB123CD" not in wB._plate_cache


# ────────────────────────────────────────────────────────────────────────
# Downstream · isolation multi-ANPR cloud (whitelist stricte)
# ────────────────────────────────────────────────────────────────────────

class TestDownstreamMultiAnprIsolation:
    def test_source_reads_strict_whitelist(self):
        """Le code de downstream doit refléter la fermeture stricte."""
        import inspect
        from pipeline_v2.downstream import run_downstream
        src = inspect.getsource(run_downstream)
        # v0.4.3 · doit contenir la fermeture explicite
        assert "if not _cam_whitelist" in src, (
            "downstream multi-ANPR doit fermer strictement quand whitelist vide")
        # Il ne doit plus exister de branche où _anpr_entries est peuplé
        # sans passer par le filtre `if e.name in _cam_whitelist`.
        assert "e.name in _cam_whitelist" in src
