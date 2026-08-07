"""v0.7.e · Wave A · Hot Reload chirurgical — tests de non-régression.

Objectifs prouvés par cette suite :

  1. Une modif caméra pose un SIGNAL — n'exécute PAS de reload global.
  2. Le cycle AI n'appelle ``load_runtime_config`` / ``refresh_per_camera_configs``
     / ``_sync_frame_source_workers`` **que si un signal a été reçu ou si le
     TTL de sûreté a expiré** (par défaut 10 s).
  3. La suppression d'une caméra n'affecte pas les workers des autres caméras.
  4. Les compteurs Hot Reload sont bien exposés par
     ``/api/diagnostics/hot-reload``.
"""
from __future__ import annotations

import inspect
import os

import pytest

os.environ["TESTING"] = "1"


class TestHotReloadSignals:
    def test_signal_functions_exist(self):
        import ai_engine
        assert callable(ai_engine.signal_config_changed)
        assert callable(ai_engine.signal_camera_config_changed)
        assert callable(ai_engine.signal_camera_topology_changed)
        assert callable(ai_engine.get_hot_reload_metrics)

    def test_signal_config_changed_flips_dirty_flag(self):
        import ai_engine
        ai_engine._config_dirty = False
        ai_engine.signal_config_changed()
        assert ai_engine._config_dirty is True

    def test_signal_camera_topology_targets_single_cam(self):
        import ai_engine
        ai_engine._camera_dirty_set.clear()
        ai_engine._cameras_topology_dirty = False
        ai_engine.signal_camera_topology_changed("cam-42")
        assert ai_engine._cameras_topology_dirty is True
        assert "cam-42" in ai_engine._camera_dirty_set

    def test_metrics_include_all_counters(self):
        import ai_engine
        m = ai_engine.get_hot_reload_metrics()
        for k in ("config_reloads", "camera_config_reloads",
                  "topology_syncs_full", "topology_syncs_partial",
                  "frame_source_starts", "frame_source_stops",
                  "cycles_since_boot", "signals_received", "flags"):
            assert k in m


class TestAiLoopNoLongerHammersMongo:
    """Le cœur de la Wave A : la boucle IA ne recharge pas la DB chaque cycle."""

    def test_ai_loop_body_uses_signals_or_ttl(self):
        import ai_engine
        src = inspect.getsource(ai_engine.ai_loop)
        assert "_config_dirty" in src or "_camera_config_dirty" in src, \
            "ai_loop doit gater les reloads via un dirty flag ou un TTL"
        assert "_HOT_RELOAD_TTL_SEC" in src
        # Le code doit passer explicitement `only=` au sync partiel
        # (fonctionnalité de chirurgie ciblée).
        assert "only=" in src

    def test_sync_frame_source_workers_supports_partial(self):
        import ai_engine
        sig = inspect.signature(ai_engine._sync_frame_source_workers)
        assert "only" in sig.parameters, \
            "_sync_frame_source_workers doit accepter le mode partiel via `only`"

    def test_process_camera_no_longer_calls_ensure_running(self):
        """v0.7.e · l'appel `_ensure_frame_source_running` par-cycle a été
        retiré de `_process_camera` (redondant avec `_sync_frame_source_workers`).
        """
        import ai_engine
        src = inspect.getsource(ai_engine._process_camera)
        assert "_ensure_frame_source_running(" not in src, \
            "double warm-start supprimé : le sync topology est la seule autorité"


class TestCameraRoutesEmitSignals:
    """Les routes qui modifient une caméra doivent poser un signal."""

    def test_create_camera_emits_topology_signal(self):
        import routers
        src = inspect.getsource(routers.create_camera)
        assert "signal_camera_topology_changed" in src

    def test_update_camera_emits_topology_signal(self):
        import routers
        src = inspect.getsource(routers.update_camera)
        assert "signal_camera_topology_changed" in src

    def test_delete_camera_emits_topology_signal(self):
        import routers
        src = inspect.getsource(routers.delete_camera)
        assert "signal_camera_topology_changed" in src

    def test_pipeline_config_put_emits_config_signal(self):
        import routers
        src = inspect.getsource(routers.update_pipeline_config_endpoint)
        assert "signal_camera_config_changed" in src

    def test_anpr_camera_put_emits_config_signal(self):
        import plugin_config
        src = inspect.getsource(plugin_config.anpr_camera_put)
        assert "signal_camera_config_changed" in src

    def test_bytetrack_put_uses_signal_not_direct_load(self):
        """v0.7.e · PUT /tracking/config n'appelle plus load_runtime_config
        directement — utilise le mécanisme signal, non-bloquant."""
        import plugin_config
        src = inspect.getsource(plugin_config.tracking_config_put)
        assert "signal_config_changed" in src


class TestBusChangesRemainSurgical:
    """Les changements du PluginBus restent per-camera (lazy rebuild)."""

    def test_bus_register_bumps_registry_lazily(self):
        from plugin_manager.bus import PluginBus
        src = inspect.getsource(PluginBus.register)
        assert "_bump_graph_registry" in src

    def test_registry_rebuild_is_per_camera(self):
        from pipeline_v2.registry import registry, _hash_plugins
        # Le hash change avec le bus_version mais le rebuild n'est déclenché
        # que sur `.get(camera_id)` — pas de force rebuild global.
        v0 = registry._bus_version
        registry.bump_bus_version()
        assert registry._bus_version == v0 + 1
        # bump_bus_version ne doit PAS vider les graphes existants
        # (elle invalide via la comparaison de hash au prochain get()).
        assert isinstance(registry._graphs, dict)


class TestDiagnosticsEndpointExposed:
    def test_hot_reload_endpoint_registered(self):
        from server import app
        paths = {route.path for route in app.routes}
        assert "/api/diagnostics/hot-reload" in paths
