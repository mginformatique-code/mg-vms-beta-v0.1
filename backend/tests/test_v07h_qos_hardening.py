"""v0.7.h · Wave I · QoS & Production Hardening — tests."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TESTING"] = "1"


class TestQualityScore100:
    def test_score_100_scales_correctly(self):
        from pipeline_v2.plate_quality import CropQuality
        q = CropQuality(200, 80, 60, 45, 0, 0.75, False, False, "ok")
        assert q.score_100 == 75
        d = q.to_dict()
        assert d["score_100"] == 75


class TestEngineReliability:
    def test_neutral_before_10_readings(self):
        from pipeline_v2 import engine_reliability as er
        er.reset()
        for _ in range(5):
            er.record_engine_reading("cam1", "fast-alpr", success=True, time_ms=20)
        assert er.reliability_mult("cam1", "fast-alpr") == 1.0

    def test_full_success_boosts_weight(self):
        from pipeline_v2 import engine_reliability as er
        er.reset()
        for _ in range(50):
            er.record_engine_reading("cam1", "fast-alpr", success=True, time_ms=15)
        m = er.reliability_mult("cam1", "fast-alpr")
        assert 1.4 <= m <= 1.5    # accuracy 1.0 → mult ≈ 1.5

    def test_full_failure_reduces_weight(self):
        from pipeline_v2 import engine_reliability as er
        er.reset()
        for _ in range(50):
            er.record_engine_reading("cam2", "tesseract", success=False, time_ms=30)
        m = er.reliability_mult("cam2", "tesseract")
        assert 0.5 <= m <= 0.6    # accuracy 0 → mult ≈ 0.5

    def test_snapshot_exposes_per_cam_per_engine(self):
        from pipeline_v2 import engine_reliability as er
        er.reset()
        er.record_engine_reading("cam1", "fast-alpr", success=True, time_ms=20)
        er.record_engine_reading("cam2", "tesseract", success=False, time_ms=30)
        snap = er.snapshot()
        assert "cam1" in snap and "fast-alpr" in snap["cam1"]
        assert "cam2" in snap and "tesseract" in snap["cam2"]
        assert snap["cam1"]["fast-alpr"]["reads_total"] == 1


class TestQosAlertsThresholds:
    def test_defaults_reasonable(self):
        from pipeline_v2.qos_alerts import DEFAULT_THRESHOLDS
        assert DEFAULT_THRESHOLDS["pipeline_total_ms"] == 200
        assert DEFAULT_THRESHOLDS["yolo_ms"] == 50
        assert DEFAULT_THRESHOLDS["anpr_ms"] == 120
        assert DEFAULT_THRESHOLDS["fps_min"] == 5

    def test_check_camera_stages_flags_slow_pipeline(self):
        from pipeline_v2.qos_alerts import _check_camera_stages, DEFAULT_THRESHOLDS
        stages = {
            "yolo":     {"avg_ms_60s": 150.0, "p95_60s": 200.0, "samples_60s": 30},
            "tracking": {"avg_ms_60s":   3.0, "p95_60s":   4.0, "samples_60s": 30},
            "anpr":     {"avg_ms_60s": 100.0, "p95_60s": 140.0, "samples_60s": 30},
        }
        v = _check_camera_stages("cam-x", stages, DEFAULT_THRESHOLDS)
        kinds = {x["kind"] for x in v}
        assert "pipeline_slow" in kinds        # 150+3+100=253 > 200
        assert "yolo_slow" in kinds            # p95 200 > 50
        assert "anpr_slow" in kinds            # p95 140 > 120

    def test_check_camera_stages_ok_below_thresholds(self):
        from pipeline_v2.qos_alerts import _check_camera_stages, DEFAULT_THRESHOLDS
        stages = {
            "yolo":     {"avg_ms_60s": 30.0, "p95_60s": 45.0, "samples_60s": 30},
            "tracking": {"avg_ms_60s":  2.0, "p95_60s":  4.0, "samples_60s": 30},
            "anpr":     {"avg_ms_60s": 80.0, "p95_60s": 100.0, "samples_60s": 30},
        }
        v = _check_camera_stages("cam-y", stages, DEFAULT_THRESHOLDS)
        assert v == []


class TestQosEndpointsRegistered:
    def test_endpoints_exist(self):
        from server import app
        paths = {r.path for r in app.routes}
        assert "/api/diagnostics/engine-reliability" in paths
        assert "/api/diagnostics/qos-thresholds" in paths


class TestMongoAuditScript:
    def test_script_exists(self):
        p = Path(__file__).resolve().parents[1] / "stress" / "mongo_audit.py"
        assert p.exists()
        content = p.read_text()
        assert "EXPECTED_INDEXES" in content
        assert "EXPECTED_TTL" in content
        assert "collStats" in content
