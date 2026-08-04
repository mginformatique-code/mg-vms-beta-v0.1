"""Tests correctif audit v0.3 — validation post-audit.

Vérifie que les 4 corrections de l'audit sont réellement appliquées :
1. Garde-fou go2rtc-only dans frame_source.start SUPPRIMÉ
2. Workers frame_source démarrent aussi pour les caméras démo
3. Endpoint /diagnostics/frame-source disponible
4. alpr_ms enregistré dans pipeline_metrics
5. ANPR utilise crops véhicule (pas image entière)
"""
import os
import sys

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "mgvms_test_audit_fix")


class TestAuditFixes:
    def test_frame_source_start_no_longer_refuses_native_rtsp(self):
        """Garde-fou go2rtc-only supprimé : accepte n'importe quelle URL RTSP."""
        import inspect
        from frame_source import start
        src = inspect.getsource(start)
        # Le ValueError d'origine ne doit plus être là
        assert "refuse une URL RTSP hors go2rtc" not in src
        # Et l'ancien check "allowed_prefixes" doit être supprimé du corps
        assert "allowed_prefixes" not in src

    def test_sync_frame_source_workers_starts_workers_for_demos(self):
        """Les démos ne sont plus skippées - un worker est démarré."""
        import inspect
        from ai_engine import _sync_frame_source_workers
        src = inspect.getsource(_sync_frame_source_workers)
        # Ne doit PAS contenir le skip démo
        assert "if cam_id.startswith(\"demo-\") or cam_id.startswith(\"demo_\"):\n            continue" not in src
        # Doit contenir la nouvelle branche "demo-go2rtc-relay"
        assert "demo-go2rtc-relay" in src

    def test_alpr_ms_relayed_to_pipeline_metrics(self):
        """alpr_ms doit être appelé sur pipeline_metrics.record_stage."""
        import inspect
        from ai_engine import _process_camera
        src = inspect.getsource(_process_camera)
        assert 'record_stage(cam["id"], "alpr_ms"' in src

    def test_anpr_uses_vehicle_crops_not_full_image(self):
        """ANPR doit itérer sur les véhicules et faire predict sur le crop."""
        import inspect
        from ai_engine import _analyze_frame
        src = inspect.getsource(_analyze_frame)
        # Nouvelle boucle explicite par véhicule
        assert "for owner in vehicles:" in src
        # Crop véhicule injecté dans _alpr.predict
        assert "_alpr.predict(vehicle_crop)" in src
        # L'ancien "for r in _alpr.predict(img):" ne doit plus être là
        assert "_alpr.predict(img)" not in src

    def test_frame_source_diagnostics_endpoint_registered(self):
        """L'endpoint /diagnostics/frame-source est bien monté."""
        from routes.health_dashboard import health_dashboard_router
        paths = [r.path for r in health_dashboard_router.routes]
        assert "/api/diagnostics/frame-source" in paths

    def test_pipeline_metrics_alpr_ms_stage_supported(self):
        """PipelineMetrics accepte bien 'alpr_ms' dans STAGES."""
        from pipeline_metrics import PipelineMetrics
        assert "alpr_ms" in PipelineMetrics._STAGES
        pm = PipelineMetrics()
        pm.record_stage("cam1", "alpr_ms", 42.5)
        snap = pm.snapshot()
        assert snap["cam1"]["stages"]["alpr_ms"]["avg"] == 42.5
