"""Tests v0.4.3 — Pipeline Engine v2 (architecture first).

Vérifie les garanties structurelles de la refonte :
  1. FrameContext : JPEG memoizé (un seul encodage)
  2. VehicleROI : crop/JPEG partagés
  3. TrackerPool : un tracker par caméra, isolation stricte
  4. dispatch_pipeline(precomputed_tracks) : plugins Tracker JAMAIS appelés
  5. dispatch_plate(only=...) : moteurs hors whitelist JAMAIS appelés
  6. Frame.jpeg() plugin_manager : encodage partagé multi-moteurs
  7. CameraWorker.analyze : forme legacy + _ctx présent
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
    rng = np.random.default_rng(7)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


class TestFrameContextSharedCaches:
    def test_frame_jpeg_data_uri_memoized(self):
        from pipeline_v2.frame_context import FrameContext
        ctx = FrameContext(camera_id="c1", image=_img())
        u1 = ctx.jpeg_data_uri(640, 60)
        u2 = ctx.jpeg_data_uri(640, 60)
        assert u1 is u2  # même objet → un seul encodage
        assert u1.startswith("data:image/jpeg;base64,")

    def test_vehicle_roi_jpeg_memoized(self):
        from pipeline_v2.frame_context import VehicleROI
        roi = VehicleROI(owner={}, bbox=(0, 0, 100, 100), crop=_img(100, 100))
        b1 = roi.jpeg(85)
        b2 = roi.jpeg(85)
        assert b1 is b2 and isinstance(b1, bytes)
        d1 = roi.jpeg_data_uri()
        assert d1 is roi.jpeg_data_uri()

    def test_plugin_frame_jpeg_shared(self, monkeypatch):
        """Frame.jpeg() (plugin_manager) : un SEUL cv2.imencode pour N moteurs."""
        import cv2
        from plugin_manager.interfaces import Frame
        calls = {"n": 0}
        orig = cv2.imencode

        def counting(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)

        monkeypatch.setattr(cv2, "imencode", counting)
        f = Frame(camera_id="c1", timestamp="t", numpy_bgr=_img(), width=640, height=480)
        b1 = f.jpeg(85)
        b2 = f.jpeg(85)
        b3 = f.jpeg(85)
        assert b1 is b2 is b3
        assert calls["n"] == 1


class TestTrackerPoolSingleTracking:
    def test_one_tracker_per_camera_isolated(self):
        from pipeline_v2.tracking import TrackerPool
        from pipeline_v2.frame_context import FrameContext
        pool = TrackerPool()
        for cam in ("camA", "camB"):
            ctx = FrameContext(camera_id=cam, image=_img())
            ctx.detections = [{"class": "car", "confidence": 0.9,
                               "_bbox": (10, 10, 200, 200)}]
            meta = pool.update(cam, ctx, {}, enabled_plugins=[])
            assert meta["algo_effective"] == "bytetrack"
        assert set(pool.describe().keys()) == {"camA", "camB"}
        assert pool._instances["camA"]["tracker"] is not pool._instances["camB"]["tracker"]

    def test_resolve_algo_from_whitelist(self):
        from pipeline_v2.tracking import resolve_algo
        assert resolve_algo([]) == ("bytetrack", "bytetrack")
        assert resolve_algo(["fast-alpr", "botsort"]) == ("botsort", "botsort")
        # algo non implémenté → fallback bytetrack, demande tracée
        assert resolve_algo(["deepsort"]) == ("deepsort", "bytetrack")

    def test_track_ids_attached(self):
        from pipeline_v2.tracking import TrackerPool
        from pipeline_v2.frame_context import FrameContext
        pool = TrackerPool()
        tid = None
        for _ in range(3):  # ByteTrack confirme après quelques frames
            ctx = FrameContext(camera_id="camT", image=_img())
            ctx.detections = [{"class": "car", "confidence": 0.95,
                               "_bbox": (50, 50, 300, 300)}]
            pool.update("camT", ctx, {}, enabled_plugins=[])
            tid = ctx.detections[0].get("track_id")
        assert tid is not None
        assert ctx.tracks and ctx.tracks[0]["track_id"] == tid


class TestBusSingleTrackingDispatch:
    def test_tracker_plugins_never_called_with_precomputed_tracks(self):
        from plugin_manager.bus import PluginBus
        from plugin_manager.interfaces import Tracker, TrackingResult, Track, Frame

        calls = {"n": 0}

        class _SpyTracker(Tracker):
            name = "spy-tracker"

            async def track(self, frame, detections):
                calls["n"] += 1
                return TrackingResult(tracks=[], timing_ms=0)

        bus = PluginBus()
        bus.register("spy-tracker", _SpyTracker())
        frame = Frame(camera_id="c1", timestamp="t", numpy_bgr=_img(),
                      width=640, height=480)
        pre_tracks = [Track(track_id="42", label="car", confidence=0.9,
                            bbox=(0, 0, 10, 10), age=1)]

        async def _run():
            return await bus.dispatch_pipeline(
                frame, camera_config={"camera_id": "c1"},
                precomputed_detections=[], precomputed_tracks=pre_tracks,
                run_business=False, emit_events=False)

        pr = asyncio.new_event_loop().run_until_complete(_run())
        assert calls["n"] == 0, "le plugin Tracker ne doit JAMAIS être appelé"
        assert pr.plugins_used["trackers"] == ["core-tracking-stage"]
        assert len(pr.tracks) == 1 and pr.tracks[0].track_id == "42"

    def test_dispatch_plate_only_whitelist(self):
        from plugin_manager.bus import PluginBus
        from plugin_manager.interfaces import PlateRecognizer, Frame

        called = []

        def _mk(name):
            class _R(PlateRecognizer):
                async def recognize(self, frame, vehicle_bbox=None):
                    called.append(self.name)
                    return []
            _R.name = name
            return _R()

        bus = PluginBus()
        bus.register("engine-a", _mk("engine-a"))
        bus.register("engine-b", _mk("engine-b"))
        frame = Frame(camera_id="c1", timestamp="t", numpy_bgr=_img(),
                      width=640, height=480)

        async def _run():
            return await bus.dispatch_plate(frame, only={"engine-a"})

        res = asyncio.new_event_loop().run_until_complete(_run())
        assert called == ["engine-a"]
        assert [n for n, _ in res] == ["engine-a"]


class TestCameraWorker:
    def test_analyze_legacy_shape_and_ctx(self):
        import cv2
        from pipeline_v2.camera_worker import CameraWorker
        ok, buf = cv2.imencode(".jpg", _img())
        w = CameraWorker("cam-w1")
        res = w.analyze(buf.tobytes(), enabled_plugins=[], camera={"id": "cam-w1"})
        for key in ("detections", "plates", "motion_pct", "timings",
                    "overlay_boxes", "counts", "_img_bgr", "_ctx"):
            assert key in res, f"clé legacy manquante : {key}"
        ctx = res["_ctx"]
        assert ctx.camera_id == "cam-w1"
        assert res["_img_bgr"] is ctx.image  # même référence, zéro copie
        for t in ("decode_ms", "motion_ms", "yolo_ms", "tracking_ms", "alpr_ms", "total_ms"):
            assert t in res["timings"]

    def test_runtime_one_worker_per_camera(self):
        from pipeline_v2.camera_worker import PipelineRuntime
        rt = PipelineRuntime()
        w1 = rt.worker("camX")
        w2 = rt.worker("camX")
        w3 = rt.worker("camY")
        assert w1 is w2
        assert w1 is not w3

    def test_worker_state_isolation(self):
        """Le cache plaques / motion d'une caméra ne fuit pas vers une autre."""
        from pipeline_v2.camera_worker import CameraWorker
        wa, wb = CameraWorker("A"), CameraWorker("B")
        from datetime import datetime, timezone, timedelta
        wa._plate_cache["AB123CD"] = datetime.now(timezone.utc) + timedelta(seconds=10)
        assert "AB123CD" not in wb._plate_cache


class TestInspector:
    def test_records_and_snapshot(self):
        from pipeline_v2.inspector import PipelineInspector
        ins = PipelineInspector()
        ins.record("cam1", "yolo", 12.5)
        ins.record("cam1", "yolo", 20.0, error=True)
        ins.record("cam1", "decode", 3.0)
        snap = ins.snapshot()
        st = snap["cameras"]["cam1"]["stages"]["yolo"]
        assert st["calls"] == 2 and st["errors"] == 1
        assert st["max_ms"] == 20.0
        assert "system" in snap

    def test_ai_engine_wrapper_delegates_to_worker(self):
        """ai_engine._analyze_frame doit déléguer au CameraWorker (pipeline v2)."""
        import cv2
        import ai_engine
        from pipeline_v2.camera_worker import runtime
        ok, buf = cv2.imencode(".jpg", _img())
        res = ai_engine._analyze_frame("cam-wrap", buf.tobytes(), [], {"id": "cam-wrap"})
        assert res.get("_ctx") is not None
        assert "cam-wrap" in runtime.describe()["workers"]
