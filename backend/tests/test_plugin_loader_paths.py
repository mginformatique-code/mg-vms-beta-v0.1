"""Vérifie que le loader de plugins résout un chemin portable.

Bug fixé Feb 2026 : le loader hardcodait `/app/data/plugins` — cassait
tout déploiement (Railway/Vercel/prod) où seuls les 2 built-in
(yolo-detection + fast-alpr) étaient enregistrés.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "mgvms_test_loader")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestLoaderPathResolution:
    def test_default_dir_resolves_to_repo_data_plugins(self):
        from plugin_manager.loader import _resolve_plugins_dir
        p = _resolve_plugins_dir()
        # En dev container il devrait résoudre à /app/data/plugins,
        # et en prod à <repo>/data/plugins — dans les deux cas le dossier
        # doit exister ET contenir au moins un manifest.
        assert p.exists(), f"Plugins dir résolu à {p} mais n'existe pas"
        manifests = list(p.glob("*/manifest.yaml"))
        assert len(manifests) >= 40, f"Attendu ≥40 manifests, trouvé {len(manifests)}"

    def test_env_var_override_takes_priority(self, tmp_path, monkeypatch):
        # Sanity : si MGVMS_PLUGINS_DIR est set, le loader le respecte
        monkeypatch.setenv("MGVMS_PLUGINS_DIR", str(tmp_path))
        # Force reimport pour ré-évaluer _resolve_plugins_dir
        import importlib
        from plugin_manager import loader as loader_mod
        importlib.reload(loader_mod)
        assert loader_mod.DEFAULT_PLUGINS_DIR == tmp_path
        # Cleanup: reset
        monkeypatch.delenv("MGVMS_PLUGINS_DIR", raising=False)
        importlib.reload(loader_mod)

    def test_discover_finds_50_plugins(self):
        from plugin_manager.loader import PluginLoader
        loader = PluginLoader()
        manifests = loader.discover()
        assert len(manifests) >= 40, f"Attendu ≥40 plugins, trouvé {len(manifests)}"
        # Vérifie quelques noms clés
        names = {m.parent.name for m in manifests}
        assert "yolo-detection" in names
        assert "fast-alpr" in names
        assert "bytetrack" in names
        assert "anpr-eps" in names
