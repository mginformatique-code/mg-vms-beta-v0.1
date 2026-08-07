"""Bootstrap : enregistre les plugins bundle sur le bus au démarrage.

Appelé depuis `server.py` startup. Effectue :

  1. **Loader dynamique** : découvre `/app/data/plugins/*/manifest.yaml` et
     charge chaque plugin conforme (importlib + register sur le bus).
  2. **Fallback bundle** : si un plugin officiel n'est pas trouvé sur disque
     (installation minimale), fallback sur les wrappers `builtin/`.

Idempotent — peut être appelé plusieurs fois (reload à chaud dev).
"""
from __future__ import annotations

import logging

from .bus import bus
from .context import PluginContext
from .loader import loader
from .builtin import YoloDetectionPlugin, FastAlprPlugin

logger = logging.getLogger("plugin_bootstrap")

_bootstrapped = False

# Noms des plugins officiels obligatoires pour la démo v2.30
REQUIRED_BUNDLE = ("yolo-detection", "fast-alpr")


async def bootstrap_bundle():
    """Bootstrap dynamique + fallback bundle."""
    global _bootstrapped
    if _bootstrapped:
        return

    # 1. Loader dynamique — parse tous les manifests présents
    try:
        await loader.discover_and_load_all()
    except Exception as e:  # pragma: no cover
        logger.warning("bootstrap.loader_error err=%s", e)

    # 2. Fallback pour les plugins officiels absents du filesystem
    for name in REQUIRED_BUNDLE:
        if any(e.name == name for e in bus.list_entries()):
            continue  # déjà chargé par le loader
        logger.info("bootstrap.fallback_builtin name=%s (manifest absent, wrapper interne)", name)
        if name == "yolo-detection":
            inst = YoloDetectionPlugin()
            order = 10
        elif name == "fast-alpr":
            inst = FastAlprPlugin()
            order = 20
        else:  # pragma: no cover
            continue
        ctx = PluginContext(
            plugin_name=name,
            version=inst.version,
            capabilities=["camera.frame.read", "event.write"],
        )
        try:
            await inst.on_load(ctx)
        except Exception as e:  # pragma: no cover
            logger.warning("bootstrap.on_load_error name=%s err=%s", name, e)
        bus.register(name, inst, order=order)

    _bootstrapped = True
    logger.info("plugin_bootstrap.done registered=%s dynamic=%s",
                [e.name for e in bus.list_entries()],
                [p["name"] for p in loader.loaded() if p["loaded"]])

    # v1.0-rc4 · P0-3 : warm-up différé des états paresseux (fast-alpr charge
    # son modèle après le bootstrap — sans ça le 1er GET /plugins/bus d'un
    # consommateur API externe verrait encore un état périmé).
    import asyncio

    async def _delayed_state_refresh():
        for delay in (20, 60):
            await asyncio.sleep(delay)
            try:
                bus.refresh_lazy_states()
            except Exception:  # pragma: no cover
                pass

    asyncio.create_task(_delayed_state_refresh())
