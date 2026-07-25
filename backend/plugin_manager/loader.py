"""Loader dynamique de plugins (chapitre 11 §11.4.1 - Découverte / Chargement).

Découvre les plugins dans un répertoire (`/app/data/plugins/` par défaut) en
parsant le `manifest.yaml` de chacun. Chaque plugin conforme est importé
dynamiquement via `importlib.util`, instancié, et enregistré sur le
`PluginBus`.

**Validation** : le manifest doit déclarer `apiVersion: mgvms.io/v1`,
`kind: Plugin`, et fournir `metadata.name`, `spec.runtime`,
`spec.entrypoint`, `spec.interface`. Une erreur de validation ⇒ plugin
ignoré + log warning, mais le core démarre normalement (isolation).

**Sécurité PoC v2.30** : pas de sandbox, pas de vérification signature. Le
manifest est exécuté sans restriction. En v3.0 : sandbox sub-process + GPG.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .bus import bus, BusEntry
from .context import PluginContext

logger = logging.getLogger("plugin_loader")

DEFAULT_PLUGINS_DIR = Path("/app/data/plugins")

VALID_INTERFACES = {"FrameAnalyzer", "PlateRecognizer", "EventConsumer"}


@dataclass
class LoadedPlugin:
    name: str
    version: str
    interface: str
    manifest_path: str
    entry: Optional[BusEntry] = None
    error: Optional[str] = None
    config_schema: Optional[dict] = None


class PluginLoader:
    """Découverte + chargement dynamique des plugins depuis /data/plugins."""

    def __init__(self, plugins_dir: Path = DEFAULT_PLUGINS_DIR):
        self.plugins_dir = Path(plugins_dir)
        self._loaded: dict[str, LoadedPlugin] = {}

    def loaded(self) -> list[dict]:
        """Snapshot sérialisable des plugins chargés dynamiquement."""
        return [
            {
                "name": p.name,
                "version": p.version,
                "interface": p.interface,
                "manifest_path": p.manifest_path,
                "loaded": p.entry is not None,
                "error": p.error,
                "has_config_schema": p.config_schema is not None,
            }
            for p in self._loaded.values()
        ]

    def get_config_schema(self, name: str) -> Optional[dict]:
        p = self._loaded.get(name)
        return p.config_schema if p else None

    # ── Découverte ──────────────────────────────────────────────────────

    def discover(self) -> list[Path]:
        """Retourne la liste des dossiers plugin qui contiennent un manifest.yaml."""
        if not self.plugins_dir.exists():
            return []
        manifests = []
        for entry in sorted(self.plugins_dir.iterdir()):
            if not entry.is_dir():
                continue
            m = entry / "manifest.yaml"
            if m.exists():
                manifests.append(m)
        return manifests

    # ── Chargement d'un plugin ──────────────────────────────────────────

    def _validate_manifest(self, data: dict, path: Path) -> tuple[str, str, str, str, int]:
        """Retourne (name, version, entrypoint, interface, bus_order).
        Lève ValueError si invalide.
        """
        if data.get("apiVersion") != "mgvms.io/v1":
            raise ValueError(f"apiVersion invalide (attendu 'mgvms.io/v1'): {data.get('apiVersion')!r}")
        if data.get("kind") != "Plugin":
            raise ValueError(f"kind invalide (attendu 'Plugin'): {data.get('kind')!r}")
        meta = data.get("metadata") or {}
        spec = data.get("spec") or {}
        name = str(meta.get("name") or "").strip()
        if not name:
            raise ValueError("metadata.name manquant")
        version = str(meta.get("version") or "0.0.0")
        entrypoint = str(spec.get("entrypoint") or "").strip()
        if not entrypoint:
            raise ValueError("spec.entrypoint manquant")
        interface = str(spec.get("interface") or "").strip()
        if interface not in VALID_INTERFACES:
            raise ValueError(f"spec.interface invalide (valide: {sorted(VALID_INTERFACES)})")
        runtime = str(spec.get("runtime") or "python")
        if runtime != "python":
            raise ValueError(f"runtime non supporté en v2.30 (PoC python only): {runtime!r}")
        bus_cfg = spec.get("bus") or {}
        order = int(bus_cfg.get("order", 100))
        return name, version, entrypoint, interface, order

    def _load_config_schema(self, manifest_dir: Path, spec: dict) -> Optional[dict]:
        rel = spec.get("config_schema")
        if not rel:
            return None
        schema_path = manifest_dir / rel
        if not schema_path.exists():
            return None
        try:
            return json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("plugin_loader.config_schema_error path=%s err=%s", schema_path, e)
            return None

    def _import_plugin_module(self, name: str, entrypoint_path: Path):
        """Importe dynamiquement le module Python du plugin."""
        # Isolation : chaque plugin a un nom de module unique préfixé
        module_name = f"mgvms_plugin_{name.replace('-', '_')}"
        spec_mod = importlib.util.spec_from_file_location(
            module_name, entrypoint_path, submodule_search_locations=[str(entrypoint_path.parent)],
        )
        if spec_mod is None or spec_mod.loader is None:
            raise ImportError(f"impossible de créer un spec_module pour {entrypoint_path}")
        module = importlib.util.module_from_spec(spec_mod)
        sys.modules[module_name] = module
        spec_mod.loader.exec_module(module)
        return module

    async def load_one(self, manifest_path: Path) -> LoadedPlugin:
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            err = f"YAML error: {e}"
            lp = LoadedPlugin(name=manifest_path.parent.name, version="?",
                              interface="?", manifest_path=str(manifest_path), error=err)
            self._loaded[lp.name] = lp
            logger.warning("plugin_loader.yaml_error path=%s err=%s", manifest_path, e)
            return lp

        try:
            name, version, entrypoint, interface, order = self._validate_manifest(data, manifest_path)
        except ValueError as e:
            err = f"manifest invalid: {e}"
            lp = LoadedPlugin(name=manifest_path.parent.name, version="?",
                              interface="?", manifest_path=str(manifest_path), error=err)
            self._loaded[lp.name] = lp
            logger.warning("plugin_loader.manifest_invalid path=%s err=%s", manifest_path, e)
            return lp

        spec = data.get("spec") or {}
        manifest_dir = manifest_path.parent
        entry_file = manifest_dir / entrypoint

        lp = LoadedPlugin(
            name=name, version=version, interface=interface,
            manifest_path=str(manifest_path),
            config_schema=self._load_config_schema(manifest_dir, spec),
        )

        if not entry_file.exists():
            lp.error = f"entrypoint introuvable: {entry_file}"
            self._loaded[name] = lp
            logger.warning("plugin_loader.entrypoint_missing name=%s path=%s", name, entry_file)
            return lp

        # Import + instanciation
        try:
            module = self._import_plugin_module(name, entry_file)
            class_name = spec.get("className")
            plugin_cls = None
            if class_name and hasattr(module, class_name):
                plugin_cls = getattr(module, class_name)
            else:
                # Fallback : première classe qui hérite d'une interface valide
                from .interfaces import Plugin as _PluginBase
                for attr in dir(module):
                    obj = getattr(module, attr)
                    if isinstance(obj, type) and issubclass(obj, _PluginBase) and obj is not _PluginBase:
                        plugin_cls = obj
                        break
            if plugin_cls is None:
                raise ImportError(f"aucune classe Plugin trouvée dans {entrypoint}")

            instance = plugin_cls()
            caps = (spec.get("capabilities") or [])
            ctx = PluginContext(plugin_name=name, version=version, capabilities=list(caps))
            try:
                await instance.on_load(ctx)
            except Exception as e:  # pragma: no cover
                logger.warning("plugin_loader.on_load_error name=%s err=%s", name, e)

            # Retirer une éventuelle instance builtin déjà enregistrée pour ce nom
            bus.unregister(name)
            entry = bus.register(name, instance, order=order)
            lp.entry = entry
            logger.info("plugin_loader.loaded name=%s v=%s interface=%s order=%s",
                        name, version, interface, order)
        except Exception as e:
            lp.error = f"load error: {type(e).__name__}: {e}"
            logger.warning("plugin_loader.load_error name=%s err=%s", name, e)

        self._loaded[name] = lp
        return lp

    async def discover_and_load_all(self) -> list[LoadedPlugin]:
        results = []
        for m in self.discover():
            results.append(await self.load_one(m))
        logger.info("plugin_loader.done total=%s ok=%s errors=%s",
                    len(results),
                    sum(1 for r in results if r.entry is not None),
                    sum(1 for r in results if r.error))
        return results


# Singleton
loader = PluginLoader()
