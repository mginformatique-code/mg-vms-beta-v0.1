"""Pipeline v2 · Consommateur de commandes Redis — pont API → pipeline (v3.25).

Chantier séparation pipeline IA / serveur API, étape 2c. L'étape 2b
(v3.24, pipeline_snapshot.py) a traité la catégorie (b) : l'état runtime
pipeline en LECTURE SEULE, publié périodiquement par le pipeline et lu
par l'API via une clé Redis. Ce module traite la catégorie (c) :
écriture/commande — les endpoints qui jusqu'ici importaient
pipeline_v2.*/ai_engine EN DIRECT pour MUTER un état pipeline (invalidate
un registry, reset un compteur, reconfigurer un contrôleur qualité...).

Principe : plutôt qu'un import Python direct (qui ne survit pas à une
scission en process/conteneurs séparés), l'API publie une commande dans
une file Redis (``redis_bus.QUEUE_PIPELINE_COMMANDS``, BLPOP — voir
redis_bus.py pour le choix BLPOP vs pub/sub) et ce module la consomme
côté pipeline, exécute la mutation, et répond sur une clé Redis dédiée
(RPC synchrone) — ou, pour les signaux fire-and-forget (hot-reload dirty
flags), l'exécute sans répondre.

Découpage strict — même principe que pipeline_snapshot.py :
    _handle_cmd()      → PIPELINE-SIDE uniquement. Importe librement
                          pipeline_v2.*/ai_engine — ne tourne que dans la
                          boucle background du process pipeline.
    _handle_signal()    → PIPELINE-SIDE. Idem, pour les signal_* de
                          ai_engine (hot reload).
    command_loop()      → PIPELINE-SIDE. Boucle background, consomme la
                          file Redis (BLPOP), jamais côté API.

Chaque endpoint API migré (voir routes/health_dashboard.py, routers.py)
appelle ``redis_bus.send_pipeline_command()`` et, si la réponse est
``None`` (Redis indisponible, pipeline pas démarré, timeout), REPLIE sur
son ancien appel Python direct — comportement historique garanti
inchangé tant que pipeline et API partagent le même process. Ce module
est donc, pour l'instant, un chemin best-effort EN PLUS du fallback, pas
un remplacement — il deviendra le seul mécanisme une fois le pipeline
scindé dans un process/conteneur séparé.

Catégorie (d) calcul lourd à la demande reste hors périmètre (audit 2a) —
voir rapport de livraison.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from redis_bus import get_redis, QUEUE_PIPELINE_COMMANDS

logger = logging.getLogger("pipeline_commands")


async def _handle_cmd(cmd: str, payload: dict) -> dict:
    """Dispatch des commandes RPC catégorie (c). PIPELINE-SIDE UNIQUEMENT.

    Un ``cmd`` inconnu lève ValueError — le caller (command_loop) capture
    et répond ``{"error": ...}`` sans jamais faire planter la boucle.
    """
    if cmd == "registry_invalidate":
        from pipeline_v2.registry import registry as _graph_registry
        camera_id = payload.get("camera_id")
        if camera_id:
            _graph_registry.invalidate(camera_id)
        else:
            _graph_registry.bump_bus_version()
            _graph_registry.invalidate()
        return {"ok": True, "invalidated": camera_id or "all"}

    if cmd == "plate_quality_set_debug":
        from pipeline_v2 import plate_quality as pq
        pq.set_debug_enabled(payload.get("enabled"))
        return {"enabled": pq.debug_enabled(), "output_dir": pq._DEBUG_DIR}

    if cmd == "inspector_reset":
        from pipeline_v2.inspector import inspector as _inspector
        camera_id = payload.get("camera_id")
        _inspector.reset(camera_id)
        return {"ok": True, "reset": camera_id or "all"}

    if cmd == "anpr_quality_configure":
        from pipeline_v2.anpr_quality import anpr_quality
        patch = payload.get("patch") or {}
        anpr_quality.configure(**patch)
        return {"ok": True, "config": anpr_quality.config_dict()}

    if cmd == "anpr_quality_reset":
        from pipeline_v2.anpr_quality import anpr_quality
        camera_id = payload.get("camera_id")
        anpr_quality.reset(camera_id)
        return {"ok": True, "reset": camera_id or "all"}

    if cmd == "traces_set_sampling":
        from pipeline_v2.trace import collector
        # Validation (1<=n<=100000) reste API-side (input sanitization) —
        # voir PUT /diagnostics/traces/sampling. n est déjà validé ici.
        collector.set_sampling(payload.get("n"))
        return {"ok": True, "sampling_every_n_frames": collector.get_sampling()}

    if cmd == "traces_clear":
        from pipeline_v2.trace import collector
        n = collector.clear()
        return {"ok": True, "purged": n}

    if cmd == "stability_clear":
        from pipeline_v2.stability_watcher import watcher
        n = watcher.clear()
        return {"ok": True, "purged": n}

    if cmd == "update_runtime_config":
        # v3.25 · update_runtime_config() retourne dict(_runtime_config) —
        # seulement les clés explicitement surchargées. L'endpoint PUT
        # /ai/config a toujours renvoyé get_runtime_config() (les 6 clés
        # complétées par leurs défauts + device_effective) : reproduire
        # exactement ce comportement ici, pas le retour brut de la mutation.
        from ai_engine import update_runtime_config, get_runtime_config
        await update_runtime_config(payload.get("patch") or {})
        return get_runtime_config()

    raise ValueError(f"commande pipeline inconnue: {cmd!r}")


def _handle_signal(signal: str, payload: dict) -> None:
    """Dispatch des signaux fire-and-forget (hot reload). PIPELINE-SIDE.

    Sync, pas async — les signal_* de ai_engine sont sync (simples dirty
    flags in-process).
    """
    if signal == "config_changed":
        from ai_engine import signal_config_changed
        signal_config_changed()
    elif signal == "camera_config_changed":
        from ai_engine import signal_camera_config_changed
        signal_camera_config_changed(payload.get("camera_id"))
    elif signal == "camera_topology_changed":
        from ai_engine import signal_camera_topology_changed
        signal_camera_topology_changed(payload.get("camera_id"),
                                        removed=bool(payload.get("removed", False)))
    else:
        logger.warning("pipeline_commands: signal inconnu %s", signal)


async def command_loop() -> None:
    """Boucle background PIPELINE-SIDE — consomme la file de commandes Redis.

    Même schéma que pipeline_snapshot.snapshot_loop : une itération en
    échec ne doit jamais arrêter la boucle.
    """
    logger.info("pipeline_commands: démarrage (file %s)", QUEUE_PIPELINE_COMMANDS)
    while True:
        try:
            r = get_redis()
            item = await r.blpop(QUEUE_PIPELINE_COMMANDS, timeout=5)
            if item is None:
                continue
            _, raw = item
            data = json.loads(raw)
            if "cmd" in data:
                try:
                    result = await _handle_cmd(data["cmd"], data.get("payload") or {})
                except Exception as e:
                    result = {"error": str(e)}
                reply_key = data.get("reply_key")
                if reply_key:
                    try:
                        await r.rpush(reply_key, json.dumps(result, default=str))
                        await r.expire(reply_key, 30)  # nettoyage si jamais rien ne lit la réponse
                    except Exception:
                        logger.exception("pipeline_commands: échec réponse pour reply_key=%s", reply_key)
            elif "signal" in data:
                try:
                    _handle_signal(data["signal"], data.get("payload") or {})
                except Exception:
                    logger.exception("pipeline_commands: échec traitement signal %s", data.get("signal"))
        except Exception:
            logger.exception("pipeline_commands.command_loop: itération en échec (non bloquant)")
            await asyncio.sleep(1)
