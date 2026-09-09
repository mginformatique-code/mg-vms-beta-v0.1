"""Suivi PTZ logiciel générique — "MG-VMS tracking" (v3.59).

Pour les PTZ SANS suivi natif (voir `drivers/reolink_driver.py` pour le
suivi natif Reolink, une bascule différente et plus simple — ce module ne
s'y substitue pas, il couvre le matériel qui n'a pas cette capacité).

Même architecture que `ptz_patrol.py` (déjà en place, lu en détail avant
d'écrire ce module) : une tâche asyncio par caméra en suivi (`_TASKS`),
démarrée/arrêtée via `set_tracking()`, re-hydratée au démarrage du
conteneur API (`startup_resume_all()`) pour que la config de suivi
survive à un redéploiement — l'utilisateur a explicitement demandé un
système "robuste" qui garde en mémoire le bon positionnement, pas un
réglage perdu au moindre redémarrage.

Alimentation en détections : `on_frame()` est appelée depuis
`pipeline_v2/downstream.py`, juste à côté de l'appel existant à
`smart_zones.engine.evaluate()` — mêmes détections déjà calculées par le
pipeline IA à chaque frame, aucun coût d'inférence supplémentaire.

Coordonnées de bbox : `détections`/`tracks` proviennent du MÊME pipeline
que Smart Zones — voir `smart_zones/engine.py::_bbox_in_polygon`, qui
gère déjà l'ambiguïté abs/rel (bbox absolu en pixels OU déjà normalisé
0..1 selon le point du pipeline). Réutilise ici EXACTEMENT la même
heuristique de détection plutôt que d'en inventer une nouvelle pour la
même donnée.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("ptz_tracking")

_LOOP_INTERVAL_S = 0.3
_DEFAULT_DEADZONE = 0.08
_DEFAULT_MAX_SPEED = 0.5
_DEFAULT_LOST_TIMEOUT_S = 2.0
_DEFAULT_FRAME_W = 1920
_DEFAULT_FRAME_H = 1080

_TASKS: dict[str, asyncio.Task] = {}
_PAUSED_UNTIL: dict[str, float] = {}
# Dernière bbox normalisée (cx, cy dans 0..1) vue pour la cible suivie de
# chaque caméra, avec l'horodatage — alimentée par on_frame(), consommée
# par la boucle de correction. Volontairement en mémoire (pas en base) :
# une donnée par frame, jamais utile après un redémarrage.
_LATEST: dict[str, tuple[float, float, float]] = {}  # camera_id -> (cx, cy, ts)
_AT_HOME: dict[str, bool] = {}


def pause(camera_id: str, seconds: float = 20.0) -> None:
    """Suspend le suivi de cette caméra pendant `seconds` — appelé par les
    mêmes routes move/preset manuelles qui appellent déjà ptz_patrol.pause()
    (anti-conflit joystick/automatisme, même mécanisme que la patrouille)."""
    if camera_id in _TASKS:
        _PAUSED_UNTIL[camera_id] = time.monotonic() + seconds


def _normalize_bbox(bbox, frame_w: int, frame_h: int) -> tuple[float, float]:
    x, y, w, h = bbox
    cx, cy = x + w / 2, y + h / 2
    if cx > 1 or cy > 1:  # déjà vu en absolu (voir smart_zones/engine.py)
        cx, cy = cx / max(frame_w, 1), cy / max(frame_h, 1)
    return cx, cy


def on_frame(camera_id: str, detections: list, tracks: list) -> None:
    """Mémorise la position de la meilleure cible correspondant à la
    config de suivi de cette caméra — no-op si le suivi n'est pas actif
    (évite tout travail inutile pour les caméras sans suivi en cours)."""
    if camera_id not in _TASKS:
        return
    cfg = _CONFIG.get(camera_id) or {}
    target_classes = set(cfg.get("target_classes") or ["person"])
    frame_w = cfg.get("frame_w") or _DEFAULT_FRAME_W
    frame_h = cfg.get("frame_h") or _DEFAULT_FRAME_H

    candidates = [t for t in (tracks or detections or [])
                  if (t.get("class") or "").lower() in target_classes and t.get("bbox")]
    if not candidates:
        return
    # Cible la plus grande (bbox la plus large = probablement la plus
    # proche) — heuristique simple, volontairement pas de logique de
    # ré-identification entre cibles multiples pour cette v1.
    best = max(candidates, key=lambda t: (t["bbox"][2] * t["bbox"][3]))
    cx, cy = _normalize_bbox(best["bbox"], frame_w, frame_h)
    _LATEST[camera_id] = (cx, cy, time.monotonic())


_CONFIG: dict[str, dict] = {}


def _direction_for(cx: float, cy: float, deadzone: float) -> str:
    dx, dy = cx - 0.5, cy - 0.5
    horiz = "right" if dx > deadzone else "left" if dx < -deadzone else ""
    vert = "down" if dy > deadzone else "up" if dy < -deadzone else ""
    if not horiz and not vert:
        return "stop"
    return (vert + horiz) or horiz or vert


async def _loop(camera_id: str) -> None:
    from database import db
    from services.camera_device_service import camera_device_service as svc
    from drivers import CameraDriverError

    logger.info("ptz_tracking: démarrage caméra=%s", camera_id)
    current_direction = "stop"
    try:
        while True:
            cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "ptz_tracking": 1})
            cfg = (cam or {}).get("ptz_tracking") or {}
            _CONFIG[camera_id] = cfg
            if not cfg.get("enabled"):
                await asyncio.sleep(2.0)
                continue

            paused_until = _PAUSED_UNTIL.get(camera_id, 0.0)
            now = time.monotonic()
            if now < paused_until:
                await asyncio.sleep(min(1.0, paused_until - now))
                continue

            deadzone = cfg.get("deadzone", _DEFAULT_DEADZONE)
            max_speed = cfg.get("max_speed", _DEFAULT_MAX_SPEED)
            lost_timeout = cfg.get("lost_timeout_s", _DEFAULT_LOST_TIMEOUT_S)
            home_preset_id = cfg.get("home_preset_id")

            latest = _LATEST.get(camera_id)
            has_target = bool(latest) and (now - latest[2]) < lost_timeout

            try:
                drv = await svc.get_driver(camera_id)
                if has_target:
                    _AT_HOME[camera_id] = False
                    cx, cy, _ = latest
                    direction = _direction_for(cx, cy, deadzone)
                    if direction != current_direction:
                        offset = max(abs(cx - 0.5), abs(cy - 0.5))
                        speed = min(max_speed, max(0.15, offset))
                        if direction == "stop":
                            await drv.ptz_move("stop", 0)
                        else:
                            await drv.ptz_move(direction, speed)
                        current_direction = direction
                else:
                    if current_direction != "stop":
                        await drv.ptz_move("stop", 0)
                        current_direction = "stop"
                    # Cible perdue : retour à la position de repos, une
                    # seule fois (pas à chaque cycle tant qu'aucune cible
                    # ne réapparaît) — demande explicite de l'utilisateur :
                    # un point de repos fiable, pas une caméra qui erre.
                    if home_preset_id and not _AT_HOME.get(camera_id):
                        await drv.ptz_preset(home_preset_id)
                        _AT_HOME[camera_id] = True
            except CameraDriverError as e:
                logger.warning("ptz_tracking: erreur driver caméra=%s (%s)", camera_id, e)
            except Exception:
                logger.exception("ptz_tracking: erreur inattendue caméra=%s", camera_id)

            await asyncio.sleep(_LOOP_INTERVAL_S)
    except asyncio.CancelledError:
        logger.info("ptz_tracking: arrêt caméra=%s", camera_id)
        raise


def start(camera_id: str) -> None:
    if camera_id in _TASKS and not _TASKS[camera_id].done():
        return
    _TASKS[camera_id] = asyncio.create_task(_loop(camera_id))


def stop(camera_id: str) -> None:
    task = _TASKS.pop(camera_id, None)
    _PAUSED_UNTIL.pop(camera_id, None)
    _LATEST.pop(camera_id, None)
    _AT_HOME.pop(camera_id, None)
    _CONFIG.pop(camera_id, None)
    if task and not task.done():
        task.cancel()


def is_running(camera_id: str) -> bool:
    task = _TASKS.get(camera_id)
    return bool(task and not task.done())


def set_tracking(camera_id: str, enabled: bool) -> None:
    """Démarre/arrête la boucle pour cette caméra — même contrat que
    ptz_patrol.set_patrol() : la config elle-même est déjà persistée par
    l'appelant avant ce call, la boucle la relit à chaque cycle."""
    if enabled:
        start(camera_id)
    else:
        stop(camera_id)


async def startup_resume_all() -> None:
    """Reprend au démarrage du conteneur les suivis marqués actifs en
    base — même raison que ptz_patrol.startup_resume_all() : un
    redéploiement ne doit jamais couper silencieusement un suivi en cours."""
    from database import db
    cams = await db.cameras.find(
        {"ptz_tracking.enabled": True}, {"_id": 0, "id": 1}
    ).to_list(1000)
    for cam in cams:
        start(cam["id"])
    if cams:
        logger.info("ptz_tracking: %d suivi(s) repris au démarrage", len(cams))
