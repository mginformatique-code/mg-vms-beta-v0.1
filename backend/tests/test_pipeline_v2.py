"""Tests · Pipeline Engine v2 (Feb 2026).

Vérifie :
1. Interfaces : Protocols runtime-checkable + dataclasses standardisées
2. FusionEngine : 6 stratégies
3. Stages : Detection / Tracking / ROI / Recognition / Business
4. PipelineEngine : orchestration séquentielle + timings
5. Scheduler : multi-caméra + priorités + backpressure
6. Adapter : compat rétro plugins v1
"""
import asyncio
import os
import time

import numpy as np
import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "mgvms_test_pipeline_v2")


# ══════════════════════════════════════════════════════════════════
# Interfaces
# ══════════════════════════════════════════════════════════════════

def test_bbox_area_and_center():
    from pipeline_v2.interfaces import BBox
    b = BBox(10, 20, 110, 220)
    assert b.area == 100 * 200
    assert b.center == (60, 120)


def test_plate_result_standard_format():
    from pipeline_v2.interfaces import PlateResult
    p = PlateResult(plate="AB123CD", confidence=0.9, provider="fast-alpr",
                    processing_time_ms=42.5, country="FR")
    assert p.plate == "AB123CD"
    assert p.provider == "fast-alpr"
    assert p.processing_time_ms == 42.5


def test_provider_protocols_runtime_checkable():
    from pipeline_v2.interfaces import (DetectionProvider, TrackingProvider,
                                         PlateRecognitionProvider, PipelineConsumer)

    class MockDetector:
        name = "mock"
        def detect(self, frame): return None

    assert isinstance(MockDetector(), DetectionProvider)

    class NotADetector:
        name = "x"
    assert not isinstance(NotADetector(), DetectionProvider)


# ══════════════════════════════════════════════════════════════════
# Fusion Engine — 6 stratégies
# ══════════════════════════════════════════════════════════════════

def _mk_plate(text, conf, provider, latency=100):
    from pipeline_v2.interfaces import PlateResult
    return PlateResult(plate=text, confidence=conf, provider=provider,
                       processing_time_ms=latency)


class TestFusionStrategies:
    def test_highest_confidence(self):
        from pipeline_v2.fusion import FusionEngine
        f = FusionEngine("highest_confidence", min_confidence=0.5)
        r = f.fuse([_mk_plate("AB123CD", 0.7, "a"), _mk_plate("AB123CD", 0.9, "b")])
        assert r.plate == "AB123CD" and r.confidence == 0.9 and r.provider == "b"

    def test_first_success(self):
        from pipeline_v2.fusion import FusionEngine
        f = FusionEngine("first_success", min_confidence=0.5)
        r = f.fuse([_mk_plate("XY", 0.6, "a"), _mk_plate("ZZ", 0.9, "b")])
        assert r.provider == "a"

    def test_best_latency(self):
        from pipeline_v2.fusion import FusionEngine
        f = FusionEngine("best_latency", min_confidence=0.5)
        r = f.fuse([_mk_plate("XY", 0.6, "a", latency=500),
                    _mk_plate("XY", 0.7, "b", latency=100)])
        assert r.provider == "b"

    def test_majority_vote(self):
        from pipeline_v2.fusion import FusionEngine
        f = FusionEngine("majority_vote", min_confidence=0.5)
        readings = [_mk_plate("AB123CD", 0.7, "a"),
                    _mk_plate("AB123CD", 0.8, "b"),
                    _mk_plate("XX999XX", 0.9, "c")]
        r = f.fuse(readings)
        assert r.plate == "AB123CD"  # 2 votes vs 1
        assert "fusion:majority" in r.provider

    def test_weighted_vote(self):
        from pipeline_v2.fusion import FusionEngine
        # Google Vision est fortement pondéré
        f = FusionEngine("weighted_vote", min_confidence=0.5,
                         weights={"fast-alpr": 1.0, "google-vision": 3.0})
        readings = [_mk_plate("AB123CD", 0.9, "fast-alpr"),
                    _mk_plate("XY999ZZ", 0.9, "google-vision")]
        r = f.fuse(readings)
        # google-vision * 3.0 * 0.9 = 2.7 > fast-alpr * 1.0 * 0.9 = 0.9
        assert r.plate == "XY999ZZ"

    def test_cascade(self):
        from pipeline_v2.fusion import FusionEngine
        f = FusionEngine("cascade", min_confidence=0.7,
                         order=["fast-alpr", "google-vision", "openalpr"])
        # fast-alpr n'atteint pas 0.7 → cascade essaie google-vision qui passe
        readings = [_mk_plate("AB123CD", 0.5, "fast-alpr"),
                    _mk_plate("AB123CD", 0.8, "google-vision")]
        r = f.fuse(readings)
        assert r.provider == "google-vision" and r.confidence == 0.8

    def test_min_confidence_filter(self):
        from pipeline_v2.fusion import FusionEngine
        f = FusionEngine("highest_confidence", min_confidence=0.95)
        r = f.fuse([_mk_plate("AB", 0.7, "a"), _mk_plate("AB", 0.9, "b")])
        assert r is None  # aucun ne passe le seuil

    def test_invalid_strategy_raises(self):
        from pipeline_v2.fusion import FusionEngine
        with pytest.raises(ValueError):
            FusionEngine("bogus")


# ══════════════════════════════════════════════════════════════════
# Pipeline Engine · orchestration
# ══════════════════════════════════════════════════════════════════

def _mk_frame(cam="cam1"):
    from pipeline_v2.interfaces import Frame
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    return Frame(camera_id=cam, image=img, timestamp=time.time())


class FakeDetector:
    name = "yolo-fake"
    def detect(self, frame):
        from pipeline_v2.interfaces import BBox, Detection, DetectionResult
        return DetectionResult(detections=[
            Detection(label="car", confidence=0.9,
                       bbox=BBox(100, 100, 300, 300)),
        ], provider=self.name)


class FakeTracker:
    name = "bytetrack-fake"
    def update(self, frame, detections):
        from pipeline_v2.interfaces import Track, TrackingResult
        return TrackingResult(tracks=[
            Track(track_id=42, label=d.label, bbox=d.bbox,
                  confidence=d.confidence)
            for d in detections
        ], provider=self.name)


class FakeAlpr:
    name = "fast-alpr-fake"
    def recognize(self, roi):
        from pipeline_v2.interfaces import PlateResult
        return [PlateResult(plate="AB123CD", confidence=0.88,
                            processing_time_ms=15, provider=self.name)]


class TestPipelineEngine:
    def test_build_default_creates_ordered_stages(self):
        from pipeline_v2.engine import PipelineEngine
        eng = PipelineEngine.build_default(
            detectors=[FakeDetector()], tracker=FakeTracker(),
            recognizers=[FakeAlpr()])
        desc = eng.describe()
        names = [s["name"] for s in desc["stages"]]
        assert names == ["detection", "tracking", "roi_extraction", "recognition"]

    def test_full_pipeline_populates_context(self):
        from pipeline_v2.engine import PipelineEngine
        eng = PipelineEngine.build_default(
            detectors=[FakeDetector()], tracker=FakeTracker(),
            recognizers=[FakeAlpr()])
        ctx = asyncio.run(eng.process(_mk_frame()))
        assert len(ctx.detections) == 1
        assert ctx.detections[0].track_id == 42
        assert len(ctx.tracks) == 1
        assert len(ctx.plates) == 1
        assert ctx.plates[0].plate == "AB123CD"
        assert ctx.plates[0].track_id == 42
        # Timings mesurés
        assert "detection" in ctx.timings_ms
        assert "tracking" in ctx.timings_ms
        assert "recognition" in ctx.timings_ms
        assert "total_ms" in ctx.timings_ms

    def test_engine_stats_aggregates_per_camera(self):
        from pipeline_v2.engine import PipelineEngine
        eng = PipelineEngine.build_default(detectors=[FakeDetector()])
        asyncio.run(eng.process(_mk_frame("camA")))
        asyncio.run(eng.process(_mk_frame("camA")))
        asyncio.run(eng.process(_mk_frame("camB")))
        s = eng.stats()
        assert s["camA"]["processed"] == 2
        assert s["camB"]["processed"] == 1


# ══════════════════════════════════════════════════════════════════
# Adapter · compat rétro plugin v1
# ══════════════════════════════════════════════════════════════════

def test_adapter_converts_v1_plate_dict():
    from pipeline_v2.adapter import _to_v2_plates
    raw = [{"plate": "ab123cd", "confidence": 0.9, "country": "FR"}]
    plates = _to_v2_plates(raw, provider="test", elapsed_ms=50)
    assert len(plates) == 1
    assert plates[0].plate == "AB123CD"
    assert plates[0].confidence == 0.9
    assert plates[0].provider == "test"


def test_adapter_converts_v1_detections():
    from pipeline_v2.adapter import _to_v2_detections
    raw = [{"label": "car", "confidence": 0.9, "bbox": (10, 20, 100, 200)}]
    dets = _to_v2_detections(raw)
    assert len(dets) == 1
    assert dets[0].label == "car"
    assert dets[0].bbox.x1 == 10 and dets[0].bbox.x2 == 100


# ══════════════════════════════════════════════════════════════════
# Scheduler · multi-caméra
# ══════════════════════════════════════════════════════════════════

def test_scheduler_registers_cameras():
    from pipeline_v2.scheduler import CameraSchedule, FrameScheduler
    from pipeline_v2.engine import PipelineEngine
    eng = PipelineEngine.build_default(detectors=[FakeDetector()])
    sched = FrameScheduler(eng, frame_source=lambda cid: None)
    sched.register(CameraSchedule("cam1", fps_target=10, priority=5))
    sched.register(CameraSchedule("cam2", fps_target=25, priority=9))
    assert set(sched.schedules.keys()) == {"cam1", "cam2"}
    assert sched.schedules["cam2"].fps_target == 25
    assert sched.schedules["cam2"].priority == 9
