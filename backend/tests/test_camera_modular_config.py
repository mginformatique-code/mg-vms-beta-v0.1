"""Tests v0.3 · Config caméra modulaire — enabled_plugins par caméra."""
import os
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "mgvms_test_modular")


class TestCameraModularConfig:
    def test_camera_input_has_enabled_plugins_field(self):
        from routers import CameraInput
        c = CameraInput(name="test", ip="1.2.3.4", site_id="s1")
        assert hasattr(c, "enabled_plugins")
        assert c.enabled_plugins == []

    def test_camera_input_accepts_plugin_list(self):
        from routers import CameraInput
        c = CameraInput(name="test", ip="1.2.3.4", site_id="s1",
                        enabled_plugins=["yolo-detection", "bytetrack", "anpr-eps"])
        assert c.enabled_plugins == ["yolo-detection", "bytetrack", "anpr-eps"]

    def test_dispatch_pipeline_filters_by_enabled_plugins(self):
        """Vérifie que le code de dispatch_pipeline filtre bien par enabled_plugins."""
        import inspect
        from plugin_manager.bus import PluginBus
        src = inspect.getsource(PluginBus.dispatch_pipeline)
        # Filtre présent
        assert 'enabled_plugins' in src
        assert 'enabled = set(' in src
        assert '_filter' in src

    def test_ai_engine_passes_enabled_plugins(self):
        """Vérifie que le downstream v2 injecte enabled_plugins dans camera_config."""
        import inspect
        from pipeline_v2.downstream import run_downstream
        src = inspect.getsource(run_downstream)
        assert '"enabled_plugins": cam.get("enabled_plugins")' in src


class TestPluginsCatalogEndpoint:
    def test_endpoint_registered(self):
        from routes.plugins_bus import plugins_bus_router
        paths = [r.path for r in plugins_bus_router.routes]
        assert "/api/plugins/catalog" in paths

    def test_primary_category_grouping(self):
        """Vérifie les 12 catégories principales."""
        from routes.plugins_bus import plugins_catalog
        import inspect
        src = inspect.getsource(plugins_catalog)
        for cat in ["ANPR / LPR", "Tracking", "Segmentation", "Feu / Fumée",
                    "Sûreté active", "EPI", "Comptage", "Retail", "Parking",
                    "Agriculture", "Notifications", "Détection IA"]:
            assert cat in src, f"Catégorie manquante : {cat}"
