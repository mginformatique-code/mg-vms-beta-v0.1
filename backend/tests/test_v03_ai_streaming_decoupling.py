"""Tests v0.3 — séparation IA/streaming + accumulateur ANPR par track."""
import os
import time

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "mgvms_test_v03")


class TestAnprTracker:
    def test_single_reading_below_min_confidence_ignored(self):
        from anpr_tracker import AnprTracker, PlateReading
        t = AnprTracker(min_readings=1, min_confidence=0.7)
        r = PlateReading(plate="AB123CD", confidence=0.5, ts=time.time())
        assert t.record_reading("cam1", track_id=1, reading=r) is False
        assert not t.pop_ready_events()

    def test_first_valid_reading_emits_entry_event(self):
        from anpr_tracker import AnprTracker, PlateReading
        t = AnprTracker(min_readings=1, min_confidence=0.5)
        r = PlateReading(plate="AB123CD", confidence=0.85, ts=time.time())
        assert t.record_reading("cam1", track_id=42, reading=r) is True
        evts = t.pop_ready_events()
        assert len(evts) == 1
        assert evts[0]["state"] == "ENTRY"
        assert evts[0]["best"].plate == "AB123CD"

    def test_stationary_vehicle_emits_only_once(self):
        """Véhicule stationné = plusieurs lectures, mais 1 seul événement."""
        from anpr_tracker import AnprTracker, PlateReading
        t = AnprTracker(min_readings=1, min_confidence=0.5)
        for _ in range(20):
            r = PlateReading(plate="AB123CD", confidence=0.9, ts=time.time())
            t.record_reading("cam1", track_id=1, reading=r)
        evts = t.pop_ready_events()
        assert len(evts) == 1  # UN SEUL événement ENTRY

    def test_moving_vehicle_multiple_readings_best_wins(self):
        """Véhicule en mouvement : 3 lectures avec plaques légèrement différentes.
        Le consensus doit remonter la plaque majoritaire avec la meilleure confiance."""
        from anpr_tracker import AnprTracker, PlateReading
        t = AnprTracker(min_readings=3, min_confidence=0.5)
        # 3 lectures pour le même track — dont 2 identiques et 1 blur
        t.record_reading("cam1", track_id=7, reading=PlateReading("XY555ZZ", 0.6, time.time()))
        t.record_reading("cam1", track_id=7, reading=PlateReading("AB123CD", 0.8, time.time()))
        t.record_reading("cam1", track_id=7, reading=PlateReading("AB123CD", 0.9, time.time()))
        evts = t.pop_ready_events()
        assert len(evts) == 1
        assert evts[0]["best"].plate == "AB123CD"
        assert evts[0]["best"].confidence == 0.9
        assert evts[0]["readings_count"] == 3

    def test_track_exit_emits_exit_event(self):
        """Véhicule qui quitte la scène → EXIT event après lost_cycles cycles."""
        from anpr_tracker import AnprTracker, PlateReading
        t = AnprTracker(min_readings=1, min_confidence=0.5, lost_cycles=3)
        t.record_reading("cam1", track_id=1, reading=PlateReading("XX999YY", 0.9, time.time()))
        # ENTRY event
        entry_evts = t.pop_ready_events()
        assert len(entry_evts) == 1
        # Simule 3 cycles sans revoir le track
        for _ in range(3):
            t.tick_missing("cam1", seen_track_ids=set())
        exit_evts = t.pop_ready_events()
        assert len(exit_evts) == 1
        assert exit_evts[0]["state"] == "EXIT"

    def test_returning_vehicle_new_track_id_new_event(self):
        """Nouveau track_id (véhicule revient) = nouvel événement."""
        from anpr_tracker import AnprTracker, PlateReading
        t = AnprTracker(min_readings=1, min_confidence=0.5, lost_cycles=1)
        t.record_reading("cam1", track_id=1, reading=PlateReading("AA111BB", 0.9, time.time()))
        t.pop_ready_events()  # entry
        t.tick_missing("cam1", seen_track_ids=set())  # → EXIT
        t.pop_ready_events()  # exit
        # Retour avec un nouveau track_id
        t.record_reading("cam1", track_id=99, reading=PlateReading("AA111BB", 0.9, time.time()))
        evts = t.pop_ready_events()
        assert len(evts) == 1
        assert evts[0]["state"] == "ENTRY"


class TestPipelineDecoupling:
    def test_frame_source_uses_native_rtsp_when_available(self):
        """v0.3 — Vérifie que _sync_frame_source_workers utilise camera.rtsp_url
        directement plutôt que go2rtc quand une URL est présente."""
        import inspect
        from ai_engine import _sync_frame_source_workers
        src = inspect.getsource(_sync_frame_source_workers)
        # La fonction doit lire les champs directs de la caméra
        assert "ai_rtsp_url" in src
        assert "rtsp_url" in src
        # Et respecter l'env var d'override
        assert "MGVMS_AI_DIRECT_RTSP" in src

    def test_camera_model_has_ai_rtsp_url_field(self):
        from routers import CameraInput
        c = CameraInput(name="test", ip="1.2.3.4", site_id="s1")
        assert hasattr(c, "ai_rtsp_url")
        assert c.ai_rtsp_url == ""


class TestStreamingMetricsSeparate:
    def test_streaming_metrics_endpoint_exists(self):
        from routes.health_dashboard import health_dashboard_router
        paths = [r.path for r in health_dashboard_router.routes]
        assert "/api/diagnostics/streaming-metrics" in paths
        assert "/api/diagnostics/anpr-tracker" in paths
        assert "/api/diagnostics/pipeline-metrics" in paths
