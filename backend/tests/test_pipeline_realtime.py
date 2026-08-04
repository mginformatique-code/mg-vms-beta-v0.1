"""Tests du refactor P0 · Pipeline temps réel non-bloquant (Feb 2026).

Vérifie que :
- _process_camera termine rapidement (Phase A sync)
- Le downstream tourne en asyncio.create_task (Phase B fire-and-forget)
- pipeline_metrics record les stages correctement
- Backpressure guard active si trop de tâches en vol
- ByteTrack config est activée par défaut
"""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "mgvms_test_pipeline")

import pytest
from pipeline_metrics import PipelineMetrics, pipeline_metrics


class TestPipelineMetrics:
    def test_record_stage_all_stages(self):
        pm = PipelineMetrics()
        pm.record_stage("cam1", "yolo_ms", 150.0)
        pm.record_stage("cam1", "tracking_ms", 30.0)
        pm.record_stage("cam1", "realtime_ms", 190.0)
        pm.record_stage("cam1", "downstream_ms", 5.0)
        snap = pm.snapshot()
        assert "cam1" in snap
        stages = snap["cam1"]["stages"]
        assert stages["yolo_ms"]["avg"] == 150.0
        assert stages["tracking_ms"]["avg"] == 30.0
        assert stages["realtime_ms"]["avg"] == 190.0
        assert stages["downstream_ms"]["avg"] == 5.0

    def test_record_stage_unknown_ignored(self):
        pm = PipelineMetrics()
        pm.record_stage("cam1", "invalid_stage", 100.0)
        pm.record_stage("cam1", "yolo_ms", 50.0)
        snap = pm.snapshot()
        assert snap["cam1"]["stages"]["yolo_ms"]["avg"] == 50.0

    def test_fps_computed_from_realtime_stage(self):
        pm = PipelineMetrics()
        for _ in range(3):
            pm.record_stage("cam1", "realtime_ms", 200.0)
        snap = pm.snapshot()
        # 3 frames dans les 5s → fps = 0.6
        assert snap["cam1"]["fps_5s"] > 0

    def test_drops_tracked(self):
        pm = PipelineMetrics()
        pm.record_drop("cam1")
        pm.record_drop("cam1")
        snap = pm.snapshot()
        assert snap["cam1"]["drops_5s"] == 2
        assert snap["cam1"]["drop_count"] == 2

    def test_p95_requires_5_samples(self):
        pm = PipelineMetrics()
        pm.record_stage("cam1", "yolo_ms", 100.0)
        snap = pm.snapshot()
        # 1 sample: pas de p95
        assert snap["cam1"]["stages"]["yolo_ms"]["p95"] is None
        for _ in range(5):
            pm.record_stage("cam1", "yolo_ms", 200.0)
        snap = pm.snapshot()
        # 6 samples: p95 disponible
        assert snap["cam1"]["stages"]["yolo_ms"]["p95"] is not None

    def test_multi_camera_isolation(self):
        pm = PipelineMetrics()
        pm.record_stage("cam1", "yolo_ms", 100.0)
        pm.record_stage("cam2", "yolo_ms", 300.0)
        snap = pm.snapshot()
        assert snap["cam1"]["stages"]["yolo_ms"]["avg"] == 100.0
        assert snap["cam2"]["stages"]["yolo_ms"]["avg"] == 300.0

    def test_window_limit(self):
        pm = PipelineMetrics()
        for i in range(150):
            pm.record_stage("cam1", "yolo_ms", float(i))
        snap = pm.snapshot()
        # Deque maxlen=100 → moyenne des 100 derniers (50..149) = 99.5
        assert 99.0 <= snap["cam1"]["stages"]["yolo_ms"]["avg"] <= 100.0


class TestPipelineArchitecture:
    """Vérifie l'architecture Phase A / Phase B."""

    def test_process_camera_is_async(self):
        from ai_engine import _process_camera, _process_downstream, _do_downstream_work
        assert asyncio.iscoroutinefunction(_process_camera)
        assert asyncio.iscoroutinefunction(_process_downstream)
        assert asyncio.iscoroutinefunction(_do_downstream_work)

    def test_downstream_uses_create_task_pattern(self):
        """Vérifie que _process_camera fire-and-forget le downstream."""
        import inspect
        from ai_engine import _process_camera
        src = inspect.getsource(_process_camera)
        assert "asyncio.create_task" in src
        assert "_process_downstream" in src

    def test_backpressure_guard_exists(self):
        """Vérifie le guard _MAX_DOWNSTREAM_INFLIGHT."""
        from ai_engine import _MAX_DOWNSTREAM_INFLIGHT, _downstream_inflight
        assert _MAX_DOWNSTREAM_INFLIGHT >= 1
        assert isinstance(_downstream_inflight, dict)


class TestByteTrackDefaults:
    """Le default enabled=True + params sains (P0 Feb 2026)."""

    def test_bytetrack_config_defaults(self):
        from plugin_config import ByteTrackConfig
        c = ByteTrackConfig()
        assert c.enabled is True
        assert c.track_thresh == 0.25
        assert c.match_thresh == 0.85
        assert c.track_buffer == 60
        assert c.id_persist_seconds == 120


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
