"""Patrouille PTZ automatique (v3.44).

Cycle un ensemble de presets PTZ enregistrés côté caméra, dans l'ordre
choisi par l'utilisateur (glisse/réorganise dans l'UI — pas de distinction
"pré-défini" / "manuel" côté backend : c'est le même champ `preset_ids`,
juste dans l'ordre qu'on lui donne).

Une tâche asyncio par caméra en patrouille (``_TASKS``), démarrée/arrêtée
via ``set_patrol()`` (appelé par la route ``PUT .../ptz/patrol``) et
re-hydratée au démarrage du serveur (``startup_resume_all``) pour survivre
à un redémarrage du conteneur API.

Anti-conflit manuel/auto (comportement "à la Reolink") : toute commande PTZ
manuelle (move ou goto preset explicite depuis le joystick) appelle
``pause()``, qui met la caméra en pause de patrouille ``_PAUSE_SECONDS``
— la boucle ne fait rien pendant ce délai, puis reprend automatiquement
là où elle en était. Évite que la patrouille "arrache" la caméra des
mains de l'opérateur juste après qu'il l'ait positionnée manuellement.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("ptz_patrol")

_PAUSE_SECONDS = 20.0

_TASKS: dict[str, asyncio.Task] = {}
_PAUSED_UNTIL: dict[str, float] = {}


def pause(camera_id: str, seconds: float = _PAUSE_SECONDS) -> None:
    """Suspend la patrouille de cette caméra pendant `seconds` (no-op si
    aucune patrouille active — appelé inconditionnellement par les routes
    move/preset manuelles, peu importe si la patrouille tourne ou non)."""
    if camera_id in _TASKS:
        _PAUSED_UNTIL[camera_id] = time.monotonic() + seconds


async def _loop(camera_id: str) -> None:
    from database import db
    from services.camera_device_service import camera_device_service as svc
    from drivers import CameraDriverError

    idx = 0
    logger.info("ptz_patrol: démarrage caméra=%s", camera_id)
    try:
        while True:
            cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "ptz_patrol": 1})
            patrol = (cam or {}).get("ptz_patrol") or {}
            if not patrol.get("enabled") or not patrol.get("preset_ids"):
                await asyncio.sleep(5.0)
                continue

            paused_until = _PAUSED_UNTIL.get(camera_id, 0.0)
            now = time.monotonic()
            if now < paused_until:
                await asyncio.sleep(min(2.0, paused_until - now))
                continue

            presets = patrol["preset_ids"]
            dwell = max(2, int(patrol.get("dwell_seconds", 8)))
            # v3.64 · Vitesse de transition entre presets, réglable par
            # caméra (défaut 0.5, comme la vitesse manuelle) — auparavant
            # aucun réglage n'existait, la patrouille utilisait toujours la
            # vitesse par défaut de la caméra.
            speed = patrol.get("speed", 0.5)
            idx %= len(presets)
            preset_id = presets[idx]
            try:
                drv = await svc.get_driver(camera_id)
                # v3.47 · NE PAS convertir en int : un token ONVIF réel
                # ("000", "004"...) perd ses zéros de tête via int() puis
                # str(), et ne correspond alors plus à aucun preset réel
                # sur la caméra — la patrouille "marchait" (aucune erreur)
                # mais n'allait jamais au bon endroit.
                await drv.ptz_preset(preset_id, speed)
            except CameraDriverError as e:
                logger.warning("ptz_patrol: échec goto preset %s caméra=%s (%s)",
                               preset_id, camera_id, e)
            except Exception:
                logger.exception("ptz_patrol: erreur inattendue caméra=%s", camera_id)
            idx += 1
            await asyncio.sleep(dwell)
    except asyncio.CancelledError:
        logger.info("ptz_patrol: arrêt caméra=%s", camera_id)
        raise


def start(camera_id: str) -> None:
    if camera_id in _TASKS and not _TASKS[camera_id].done():
        return
    _TASKS[camera_id] = asyncio.create_task(_loop(camera_id))


def stop(camera_id: str) -> None:
    task = _TASKS.pop(camera_id, None)
    _PAUSED_UNTIL.pop(camera_id, None)
    if task and not task.done():
        task.cancel()


def is_running(camera_id: str) -> bool:
    task = _TASKS.get(camera_id)
    return bool(task and not task.done())


def set_patrol(camera_id: str, enabled: bool) -> None:
    """Démarre/arrête la boucle pour cette caméra selon `enabled`.

    La boucle elle-même relit `ptz_patrol` en base à chaque cycle — cette
    fonction ne fait que gérer le cycle de vie de la tâche asyncio (créer
    une tâche pour rien tant que la patrouille est désactivée serait
    inutile), pas la config (déjà persistée par l'appelant avant ce call).
    """
    if enabled:
        start(camera_id)
    else:
        stop(camera_id)


async def startup_resume_all() -> None:
    """Redémarre les patrouilles marquées actives en base au boot du
    conteneur API — sans ça, un redéploiement/restart couperait
    silencieusement toute patrouille en cours jusqu'à ce qu'un utilisateur
    rouvre la page et re-sauvegarde la config."""
    from database import db
    cams = await db.cameras.find(
        {"ptz_patrol.enabled": True}, {"_id": 0, "id": 1}
    ).to_list(1000)
    for cam in cams:
        start(cam["id"])
    if cams:
        logger.info("ptz_patrol: %d patrouille(s) reprise(s) au démarrage", len(cams))
