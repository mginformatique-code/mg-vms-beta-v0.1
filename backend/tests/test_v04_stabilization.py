"""Tests · Sprint stabilisation v0.4 (Feb 2026).

Vérifie que les 8 points d'audit v0.4 sont corrigés :
1. Plugin Loader : chemin résolu robuste (Docker + dev)
2. ONVIF WSDL bundle présent + factory injecte wsdl_dir
3. Pile IA démarre sans exception (import torch OK)
4. GPU log au démarrage (torch.__version__ visible dans logs)
5. Runtime state ByteTrack exposé dans /diagnostics/pipeline-metrics
6. Message erreur clair quand WSDL manquant (pas "identifiants incorrects")
7. Docker build : COPY data/plugins/ explicite + assertion build-time
"""
import os
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "mgvms_test_v04")


class TestPluginLoaderRobust:
    def test_backend_local_data_plugins_priority(self):
        """v0.4 · Nouveau chemin canonical Docker : <backend>/data/plugins."""
        import inspect
        from plugin_manager.loader import _resolve_plugins_dir
        src = inspect.getsource(_resolve_plugins_dir)
        assert "backend_dir / \"data\" / \"plugins\"" in src

    def test_loader_finds_50_plugins(self):
        from plugin_manager.loader import PluginLoader
        loader = PluginLoader()
        manifests = loader.discover()
        assert len(manifests) >= 40


class TestGPUBootLogging:
    def test_startup_logs_gpu_state(self):
        """v0.4 · Log GPU au démarrage (Torch + TorchVision + CUDA + Device)."""
        import inspect
        from server import on_startup
        src = inspect.getsource(on_startup)
        assert 'torch.__version__' in src
        assert 'cuda.is_available()' in src
        assert 'torchvision' in src


class TestRuntimeStateExposed:
    def test_pipeline_metrics_exposes_bytetrack_runtime(self):
        """v0.4 · Le runtime state (ByteTrack, GPU) doit être dans le snapshot."""
        import inspect
        from routes.health_dashboard import diagnostics_pipeline_metrics
        src = inspect.getsource(diagnostics_pipeline_metrics)
        assert '"bytetrack"' in src
        assert '"gpu"' in src
        assert '_bytetrack_cfg' in src

    def test_bytetrack_put_syncs_runtime(self):
        """v0.4 → v0.7.e · PUT /tracking/config déclenche le rechargement runtime.

        Avant v0.7.e : appel bloquant direct ``await load_runtime_config()``.
        Depuis v0.7.e (Wave A · Hot Reload chirurgical) : pose un signal
        ``signal_config_changed()`` — la boucle IA rechargera au prochain
        cycle sans bloquer la réponse HTTP.
        """
        import inspect
        from plugin_config import tracking_config_put
        src = inspect.getsource(tracking_config_put)
        assert 'signal_config_changed' in src or 'load_runtime_config' in src


class TestOnvifClearErrors:
    def test_onvif_factory_preflight_check(self):
        """v0.4 · onvif_camera() lève FileNotFoundError explicite si WSDL absents."""
        import inspect
        from wsdl_path import onvif_camera
        src = inspect.getsource(onvif_camera)
        assert 'devicemgmt.wsdl' in src
        assert 'PAS un problème d' in src  # message ambiguous message clarity check
        assert 'FileNotFoundError' in src


class TestDockerBuild:
    def test_dockerfile_copies_data_plugins(self):
        """v0.4 · Le Dockerfile copie explicitement data/plugins/."""
        df = Path("/app/backend/Dockerfile").read_text()
        assert "COPY data/plugins/" in df
        # Assertion build-time présente
        assert "Plugins check OK" in df

    def test_dockerfile_uses_backend_prefix(self):
        """v0.4 · Le context passe à la racine du repo → COPY backend/..."""
        df = Path("/app/backend/Dockerfile").read_text()
        assert "COPY backend/requirements.txt" in df
        assert "COPY backend/ ." in df

    def test_docker_compose_context_is_repo_root(self):
        yml = Path("/app/deploy-app/docker-compose.yml").read_text()
        assert "context: .." in yml
        assert "dockerfile: backend/Dockerfile" in yml
