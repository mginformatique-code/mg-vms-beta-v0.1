"""Bootstrap : enregistre les plugins bundle sur le bus au démarrage.

Appelé depuis `server.py` startup. Instancie les wrappers `builtin/` et les
enregistre sur `plugin_manager.bus`. Idempotent — peut être appelé plusieurs
fois (recharge chaude en dev).
"""
from __future__ import annotations

import logging

from .bus import bus
from .context import PluginContext, GPUInfo
from .builtin import YoloDetectionPlugin, FastAlprPlugin

logger = logging.getLogger("plugin_bootstrap")

_bootstrapped = False


async def bootstrap_bundle():
    """Enregistre les plugins officiels bundle sur le bus."""
    global _bootstrapped
    if _bootstrapped:
        return

    # yolo-detection
    yolo = YoloDetectionPlugin()
    yolo_ctx = PluginContext(
        plugin_name="yolo-detection",
        version=yolo.version,
        capabilities=["camera.frame.read", "event.write"],
    )
    try:
        await yolo.on_load(yolo_ctx)
    except Exception as e:  # pragma: no cover
        logger.warning("bootstrap yolo on_load err=%s", e)
    bus.register("yolo-detection", yolo, order=10)

    # fast-alpr
    alpr = FastAlprPlugin()
    alpr_ctx = PluginContext(
        plugin_name="fast-alpr",
        version=alpr.version,
        capabilities=["camera.frame.read", "event.write"],
    )
    try:
        await alpr.on_load(alpr_ctx)
    except Exception as e:  # pragma: no cover
        logger.warning("bootstrap alpr on_load err=%s", e)
    bus.register("fast-alpr", alpr, order=20)

    _bootstrapped = True
    logger.info("plugin_bootstrap.done registered=%s", [e.name for e in bus.list_entries()])
