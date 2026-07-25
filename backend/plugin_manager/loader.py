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

import asyncio
import importlib.util
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
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
    # Nouvelles métadonnées catégorie & deps (session 3)
    display_name: str = ""
    description: str = ""
    categories: list = field(default_factory=list)
    provider_group: Optional[str] = None  # ex: "object-detection", "anpr"
    python_dependencies: list = field(default_factory=list)
    system_dependencies: list = field(default_factory=list)


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
                "display_name": p.display_name or p.name,
                "description": p.description,
                "version": p.version,
                "interface": p.interface,
                "manifest_path": p.manifest_path,
                "loaded": p.entry is not None,
                "error": p.error,
                "has_config_schema": p.config_schema is not None,
                "categories": p.categories,
                "provider_group": p.provider_group,
                "python_dependencies": p.python_dependencies,
                "system_dependencies": p.system_dependencies,
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
            display_name=str((data.get("metadata") or {}).get("displayName") or name),
            description=str((data.get("metadata") or {}).get("description") or ""),
            categories=list((data.get("metadata") or {}).get("categories") or []),
            provider_group=str((data.get("metadata") or {}).get("providerGroup") or "") or None,
            python_dependencies=list((spec.get("dependencies") or {}).get("python") or []),
            system_dependencies=list((spec.get("dependencies") or {}).get("system") or []),
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
            # Injecte la config persistée depuis /app/backend/data/plugin_configs.json
            from .config_store import store as config_store
            persisted_config = config_store.get(name)
            ctx = PluginContext(
                plugin_name=name,
                version=version,
                capabilities=list(caps),
                config=persisted_config,
            )
            try:
                await instance.on_load(ctx)
            except Exception as e:  # pragma: no cover
                logger.warning("plugin_loader.on_load_error name=%s err=%s", name, e)
                ctx.set_state("error", str(e))

            # Retirer une éventuelle instance builtin déjà enregistrée pour ce nom
            bus.unregister(name)
            entry = bus.register(name, instance, order=order)
            # Reflète l'état déclaré par le plugin dans on_load
            entry.state = ctx.state
            entry.state_message = ctx.state_message
            # Conserve le ctx pour reload à chaud
            instance._mgvms_ctx = ctx  # type: ignore[attr-defined]
            lp.entry = entry
            logger.info("plugin_loader.loaded name=%s v=%s interface=%s state=%s order=%s",
                        name, version, interface, ctx.state, order)
        except Exception as e:
            lp.error = f"load error: {type(e).__name__}: {e}"
            logger.warning("plugin_loader.load_error name=%s err=%s", name, e)

        self._loaded[name] = lp
        return lp

    async def reload_config(self, name: str, new_config: dict) -> Optional[str]:
        """Persiste la nouvelle config + appelle plugin.on_config_change + met à jour l'état.

        Retourne None si succès, un message d'erreur sinon.
        """
        from .config_store import store as config_store
        entry = bus._entries.get(name) if hasattr(bus, "_entries") else None
        if entry is None:
            return f"Plugin '{name}' non enregistré"
        config_store.set(name, new_config)
        ctx = getattr(entry.instance, "_mgvms_ctx", None)
        if ctx is not None:
            ctx.config = dict(new_config)
            # Reset state avant nouvelle évaluation
            ctx.set_state("ready", None)
        try:
            await entry.instance.on_config_change(dict(new_config))
        except Exception as e:  # pragma: no cover
            logger.warning("plugin_loader.on_config_change_error name=%s err=%s", name, e)
            if ctx is not None:
                ctx.set_state("error", str(e))
        if ctx is not None:
            entry.state = ctx.state
            entry.state_message = ctx.state_message
        return None

    # ── Installation des dépendances Python ──────────────────────────

    _install_jobs: dict = {}  # {plugin_name: {status, log, returncode, started_at, finished_at}}

    async def install_dependencies(self, name: str, allow_upgrade_deps: bool = False) -> dict:
        """Lance `pip install` en arrière-plan pour les deps Python du plugin.

        Par défaut passe `--no-deps` pour protéger l'environnement (évite
        d'upgrader numpy/opencv qui casseraient d'autres plugins).
        Passer `allow_upgrade_deps=True` pour désactiver cette protection.

        Retourne immédiatement un job status. Le job continue en tâche de fond.
        Poll via `get_install_status(name)`.
        """
        from datetime import datetime, timezone
        lp = self._loaded.get(name)
        if not lp:
            return {"status": "error", "error": f"Plugin '{name}' non chargé"}
        deps = lp.python_dependencies
        if not deps:
            return {"status": "error", "error": "Aucune python_dependency déclarée dans le manifest"}

        # Un seul job à la fois par plugin
        current = self._install_jobs.get(name)
        if current and current.get("status") == "running":
            return current

        pip_flags = ["--no-cache-dir"]
        if not allow_upgrade_deps:
            pip_flags.append("--no-deps")

        job = {
            "status": "running",
            "deps": list(deps),
            "flags": pip_flags,
            "log": "",
            "returncode": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
        self._install_jobs[name] = job

        async def _run():
            try:
                cmd = [sys.executable, "-m", "pip", "install", *pip_flags, *deps]
                logger.info("plugin_install.start name=%s cmd=%s", name, cmd)
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                )
                # Timeout 15 min max pour éviter les blocages
                try:
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=900)
                except asyncio.TimeoutError:
                    proc.kill()
                    job["status"] = "timeout"
                    job["log"] += "\n[TIMEOUT après 15 minutes]"
                    return
                job["log"] = (stdout or b"").decode(errors="replace")[-8000:]  # dernier 8kB
                job["returncode"] = proc.returncode
                job["status"] = "success" if proc.returncode == 0 else "failed"
                logger.info("plugin_install.done name=%s status=%s rc=%s",
                            name, job["status"], proc.returncode)
                # Si succès → recharge le plugin pour re-évaluer l'état
                if job["status"] == "success":
                    await self.load_one(Path(lp.manifest_path))
            except Exception as e:  # pragma: no cover
                job["status"] = "error"
                job["log"] += f"\n[EXC] {type(e).__name__}: {e}"
            finally:
                job["finished_at"] = datetime.now(timezone.utc).isoformat()

        asyncio.create_task(_run())
        return job

    def get_install_status(self, name: str) -> Optional[dict]:
        return self._install_jobs.get(name)

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
