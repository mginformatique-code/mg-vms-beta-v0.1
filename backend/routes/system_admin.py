"""v3.19 · Paramètres système — date/heure serveur, redémarrage machine.

Périmètre volontairement réduit à un reboot complet de l'hôte (pas de
contrôle fin par conteneur MG-VMS) — décision explicite du 31 août pour
éviter de monter le socket Docker ou d'élever les privilèges du
conteneur backend. Le déclenchement passe par un simple fichier
marqueur déposé dans /logs (déjà monté en écriture-lecture, côté hôte
${LOGS_PATH:-/mnt/storage/logs}/host-reboot-requested) ; un minuteur
côté hôte (hors conteneur, voir install.sh) le surveille et exécute
`reboot` lui-même — le conteneur backend ne touche jamais directement
à l'hôte.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_role, get_current_user, log_audit
from database import db

system_admin_router = APIRouter(prefix="/api/system", tags=["system-admin"])
logger = logging.getLogger("mg-vms")

_REBOOT_FLAG_PATH = "/logs/host-reboot-requested"
_NTP_UPSTREAM_FLAG_PATH = "/logs/host-ntp-upstream-requested"
_WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAY_CHOICES = _WEEKDAY_NAMES + ("daily",)


class AutoRebootIn(BaseModel):
    enabled: bool = False
    day: str = "daily"  # "daily" ou un jour de _WEEKDAY_NAMES
    time: str = "04:00"  # HH:MM, heure serveur (TZ du conteneur, cf. Europe/Paris)


@system_admin_router.get("/info")
async def system_info(user: dict = Depends(get_current_user)):
    now = datetime.now().astimezone()
    return {
        "server_time": now.isoformat(),
        "timezone": str(now.tzinfo),
        "utc_offset": now.strftime("%z"),
    }


_CONTAINER_STATUS_PATH = "/logs/container_status.json"
_CONTAINER_STATUS_STALE_AFTER_S = 30  # timer hôte tourne toutes les 10s (voir install.sh)


@system_admin_router.get("/containers")
async def get_container_status(user: dict = Depends(require_role("admin"))):
    """v3.22 · État des conteneurs Docker MG-VMS (panneau Debug, Suivi des
    performances). Même principe que le reboot ci-dessous : le conteneur
    backend n'a jamais d'accès direct à Docker (pas de socket monté) — un
    script hôte (container-status-watch.sh, timer systemd toutes les 10s,
    voir install.sh) écrit un instantané JSON dans /logs ; on se contente
    de le relire."""
    try:
        stat = os.stat(_CONTAINER_STATUS_PATH)
    except FileNotFoundError:
        return {"containers": [], "stale": True,
                "error": "Aucun instantané disponible — le timer hôte "
                         "mgvms-container-status-watch a-t-il été installé ?"}
    age_s = time.time() - stat.st_mtime
    try:
        with open(_CONTAINER_STATUS_PATH) as f:
            containers = json.load(f)
    except Exception:
        return {"containers": [], "stale": True, "error": "Instantané illisible (JSON invalide)"}
    return {
        "containers": containers,
        "stale": age_s > _CONTAINER_STATUS_STALE_AFTER_S,
        "age_seconds": round(age_s, 1),
    }


def _write_reboot_flag(reason: str) -> None:
    os.makedirs(os.path.dirname(_REBOOT_FLAG_PATH), exist_ok=True)
    with open(_REBOOT_FLAG_PATH, "w") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} · {reason}\n")


@system_admin_router.post("/reboot")
async def reboot_now(user: dict = Depends(require_role("admin"))):
    _write_reboot_flag(f"manuel par {user.get('email', '?')}")
    await log_audit(user, "system_reboot_requested", "manuel")
    return {"ok": True}


async def _load_auto_reboot() -> dict:
    doc = await db.settings.find_one({"key": "auto_reboot"}, {"_id": 0})
    val = (doc or {}).get("value") or {}
    return {
        "enabled": bool(val.get("enabled", False)),
        "day": val.get("day") or "daily",
        "time": val.get("time") or "04:00",
    }


@system_admin_router.get("/auto-reboot")
async def get_auto_reboot(user: dict = Depends(require_role("admin"))):
    return await _load_auto_reboot()


@system_admin_router.put("/auto-reboot")
async def put_auto_reboot(data: AutoRebootIn, user: dict = Depends(require_role("admin"))):
    if data.day not in _DAY_CHOICES:
        raise HTTPException(400, "Jour invalide")
    try:
        hh, mm = data.time.split(":")
        assert 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
    except Exception:
        raise HTTPException(400, "Heure invalide (attendu HH:MM)")
    value = {"enabled": data.enabled, "day": data.day, "time": data.time}
    await db.settings.update_one({"key": "auto_reboot"}, {"$set": {"key": "auto_reboot", "value": value}}, upsert=True)
    await log_audit(user, "auto_reboot_updated", str(value))
    return value


class NtpUpstreamIn(BaseModel):
    upstream: str = ""


async def _load_ntp_upstream() -> str:
    doc = await db.settings.find_one({"key": "ntp_upstream"}, {"_id": 0})
    return (doc or {}).get("value") or ""


@system_admin_router.get("/ntp-upstream")
async def get_ntp_upstream(user: dict = Depends(require_role("admin"))):
    return {"upstream": await _load_ntp_upstream()}


@system_admin_router.put("/ntp-upstream")
async def put_ntp_upstream(data: NtpUpstreamIn, user: dict = Depends(require_role("admin"))):
    """v3.19 · Serveur NTP amont utilisé par chrony (l'hôte) pour se
    synchroniser avant de diffuser l'heure aux caméras — vide = pool Debian
    par défaut. Le conteneur backend n'édite jamais /etc/chrony directement
    (pas d'accès hôte) : il dépose un fichier marqueur dans /logs, repris
    par le même timer hôte que le reboot (reboot-watch.sh)."""
    value = data.upstream.strip()
    await db.settings.update_one({"key": "ntp_upstream"}, {"$set": {"key": "ntp_upstream", "value": value}}, upsert=True)
    os.makedirs(os.path.dirname(_NTP_UPSTREAM_FLAG_PATH), exist_ok=True)
    with open(_NTP_UPSTREAM_FLAG_PATH, "w") as f:
        f.write(value + "\n")
    await log_audit(user, "ntp_upstream_updated", value or "(défaut)")
    return {"upstream": value}


class NtpResyncIntervalIn(BaseModel):
    hours: int = 24


async def _load_ntp_resync_hours() -> int:
    doc = await db.settings.find_one({"key": "ntp_resync_interval"}, {"_id": 0})
    val = (doc or {}).get("value") or {}
    try:
        h = int(val.get("hours", 24))
        return h if h > 0 else 24
    except Exception:
        return 24


@system_admin_router.get("/ntp-resync-interval")
async def get_ntp_resync_interval(user: dict = Depends(require_role("admin"))):
    return {"hours": await _load_ntp_resync_hours()}


@system_admin_router.put("/ntp-resync-interval")
async def put_ntp_resync_interval(data: NtpResyncIntervalIn, user: dict = Depends(require_role("admin"))):
    hours = max(1, min(int(data.hours), 24 * 30))  # garde-fou : 1h à 30j
    await db.settings.update_one({"key": "ntp_resync_interval"}, {"$set": {"key": "ntp_resync_interval", "value": {"hours": hours}}}, upsert=True)
    await log_audit(user, "ntp_resync_interval_updated", f"{hours}h")
    return {"hours": hours}


_NTP_RESYNC_CHECK_EVERY_S = 1800  # vérifie l'intervalle configuré toutes les 30 min


async def ntp_resync_loop() -> None:
    """v3.19 · Repousse périodiquement le serveur NTP MG-VMS aux caméras
    marquées `ntp_managed` (voir POST /cameras/{id}/ntp) — les caméras
    dérivent avec le temps ou perdent l'heure après un reboot, un "set"
    ponctuel ne suffit pas dans la durée. Intervalle configurable depuis
    Date et heure → Serveur de temps (24h/48h/72h/personnalisé), relu à
    chaque vérification pour qu'un changement s'applique sans redémarrage."""
    from routes.camera_control import dispatch_set_ntp, _get_cam_credentials
    last_resync = 0.0
    while True:
        await asyncio.sleep(_NTP_RESYNC_CHECK_EVERY_S)
        try:
            hours = await _load_ntp_resync_hours()
            if time.monotonic() - last_resync < hours * 3600:
                continue
            async for cam in db.cameras.find({"ntp_managed": True}, {"_id": 0, "id": 1, "name": 1}):
                try:
                    _cam, ip, port, u, pwd = await _get_cam_credentials(cam["id"])
                    server = (_cam.get("ntp_server") or "").strip()
                    if not server:
                        continue
                    await dispatch_set_ntp(_cam, ip, port, u, pwd, server)
                    logger.info("system_admin · NTP resynchronisé : %s", cam.get("name", cam["id"]))
                except Exception:
                    logger.exception("system_admin · échec resync NTP caméra %s", cam.get("name", cam["id"]))
            last_resync = time.monotonic()
        except Exception:
            logger.exception("system_admin · erreur boucle ntp_resync_loop")


async def auto_reboot_loop() -> None:
    """Vérifie chaque minute si l'heure programmée du reboot auto est atteinte."""
    last_triggered_date = None
    while True:
        try:
            cfg = await _load_auto_reboot()
            if cfg["enabled"]:
                now = datetime.now()
                today_key = now.strftime("%Y-%m-%d")
                weekday_name = _WEEKDAY_NAMES[now.weekday()]
                due_day = cfg["day"] == "daily" or cfg["day"] == weekday_name
                due_time = now.strftime("%H:%M") == cfg["time"]
                if due_day and due_time and last_triggered_date != today_key:
                    logger.warning("system_admin · reboot automatique programmé déclenché (%s %s)", cfg["day"], cfg["time"])
                    _write_reboot_flag("automatique (programmé)")
                    last_triggered_date = today_key
        except Exception:
            logger.exception("system_admin · erreur boucle auto-reboot")
        await asyncio.sleep(30)
