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
from pydantic import BaseModel, Field

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


# ── Identité système (menu Réseau > Certificat SSL) ───────────────────
# v3.51 · Nom affiché, purement déclaratif (aucune modification de la
# config réseau OS). Le nom d'hôte n'est PAS dupliqué ici : celui déjà
# déclaré dans Réseau > Certificat SSL (domaine local/externe, voir
# routes/tls.py::_read_domains) fait référence — évite deux réglages
# concurrents pour la même notion.
_DEFAULT_IDENTITY = {"system_name": "MG-VMS"}


class SystemIdentityIn(BaseModel):
    system_name: str = Field("", max_length=80)


async def load_system_identity() -> dict:
    doc = await db.settings.find_one({"key": "system_identity"}, {"_id": 0, "value": 1})
    return {**_DEFAULT_IDENTITY, **((doc or {}).get("value") or {})}


@system_admin_router.get("/identity")
async def get_system_identity(user: dict = Depends(get_current_user)):
    return await load_system_identity()


@system_admin_router.put("/identity")
async def put_system_identity(data: SystemIdentityIn, user: dict = Depends(require_role("admin"))):
    value = {"system_name": data.system_name.strip() or _DEFAULT_IDENTITY["system_name"]}
    await db.settings.update_one({"key": "system_identity"}, {"$set": {"key": "system_identity", "value": value}}, upsert=True)
    await log_audit(user, "system_identity_updated", value["system_name"])
    return value


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


# ── Paramètres réseau machine/VM (Réseau → Paramètres réseau) ─────────
# v3.51 · IP/passerelle/DNS de la MACHINE/VM qui héberge MG-VMS — PAS une
# option de l'application. Même principe que le reboot ci-dessus : le
# conteneur backend n'a jamais d'accès réseau à l'hôte (pas de NET_ADMIN,
# pas de host networking) — il dépose une demande dans /logs, et
# network-watch.sh (timer systemd hôte, 15s, voir install.sh) l'applique
# via nmcli. Filet de sécurité : la nouvelle config n'est définitive que
# si confirmée depuis l'UI sous 90s, sinon l'ancienne est restaurée
# automatiquement (une IP/passerelle fausse ne doit jamais couper l'accès
# à la machine sans retour en arrière possible).
_NETWORK_STATUS_PATH = "/logs/network_status.json"
_NETWORK_REQUEST_PATH = "/logs/host-network-requested.json"
_NETWORK_CONFIRM_FLAG_PATH = "/logs/host-network-confirm.flag"
_NETWORK_STATUS_STALE_AFTER_S = 30  # timer hôte tourne toutes les 15s


class NetworkConfigIn(BaseModel):
    method: str = Field(..., pattern="^(auto|manual)$")
    ip: str = ""
    prefix: int = Field(24, ge=1, le=32)
    gateway: str = ""
    dns: list[str] = Field(default_factory=list, max_length=4)

    def validate_static(self) -> None:
        import ipaddress
        if self.method != "manual":
            return
        try:
            ipaddress.ip_address(self.ip)
            ipaddress.ip_address(self.gateway)
            for d in self.dns:
                ipaddress.ip_address(d)
        except ValueError as e:
            raise HTTPException(400, f"Adresse invalide : {e}")


@system_admin_router.get("/network")
async def get_network_status(user: dict = Depends(require_role("admin"))):
    """État réseau réel de la machine/VM (lecture seule) + confirmation
    en attente le cas échéant — voir network-watch.sh."""
    try:
        stat = os.stat(_NETWORK_STATUS_PATH)
    except FileNotFoundError:
        return {"available": False,
                "error": "Aucun instantané disponible — le timer hôte "
                         "mgvms-network-watch a-t-il été installé (nmcli requis) ?"}
    age_s = time.time() - stat.st_mtime
    try:
        with open(_NETWORK_STATUS_PATH) as f:
            snap = json.load(f)
    except Exception:
        return {"available": False, "error": "Instantané illisible (JSON invalide)"}
    return {
        "available": True,
        "current": snap.get("current"),
        "pending_confirm": snap.get("pending_confirm"),
        "updated_at": snap.get("updated_at"),
        "stale": age_s > _NETWORK_STATUS_STALE_AFTER_S,
    }


@system_admin_router.put("/network")
async def request_network_config(data: NetworkConfigIn, user: dict = Depends(require_role("admin"))):
    data.validate_static()
    payload = data.model_dump()
    payload["requested_at"] = datetime.now(timezone.utc).isoformat()
    payload["requested_by"] = user.get("email", "?")
    os.makedirs(os.path.dirname(_NETWORK_REQUEST_PATH), exist_ok=True)
    with open(_NETWORK_REQUEST_PATH, "w") as f:
        json.dump(payload, f)
    await log_audit(user, "network_config_requested",
                     f"method={data.method} ip={data.ip or '(dhcp)'} gateway={data.gateway}")
    return {"ok": True, "confirm_timeout_seconds": 90}


@system_admin_router.post("/network/confirm")
async def confirm_network_config(user: dict = Depends(require_role("admin"))):
    """Valide la config réseau appliquée — sans cet appel sous 90s,
    network-watch.sh restaure automatiquement la config précédente."""
    with open(_NETWORK_CONFIRM_FLAG_PATH, "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())
    await log_audit(user, "network_config_confirmed", "confirmé depuis l'UI")
    return {"ok": True}


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


async def _resync_all_ntp_cameras() -> dict:
    """v3.60 · Repousse le serveur NTP MG-VMS à TOUTES les caméras `ntp_managed`,
    immédiatement. Factorisé depuis `ntp_resync_loop` (même logique, appelée
    aussi bien par la boucle périodique que par le bouton "Forcer la
    synchro" — un seul chemin de code, pas de divergence possible entre
    les deux déclencheurs."""
    from routes.camera_control import dispatch_set_ntp, _get_cam_credentials
    ok, errors = [], []
    async for cam in db.cameras.find({"ntp_managed": True}, {"_id": 0, "id": 1, "name": 1}):
        name = cam.get("name", cam["id"])
        try:
            _cam, ip, port, u, pwd = await _get_cam_credentials(cam["id"])
            server = (_cam.get("ntp_server") or "").strip()
            if not server:
                continue
            await dispatch_set_ntp(_cam, ip, port, u, pwd, server)
            logger.info("system_admin · NTP resynchronisé : %s", name)
            ok.append(name)
        except Exception as e:
            logger.exception("system_admin · échec resync NTP caméra %s", name)
            errors.append({"camera": name, "error": str(e)[:200]})
    return {"ok": ok, "errors": errors}


async def ntp_resync_loop() -> None:
    """v3.19 · Repousse périodiquement le serveur NTP MG-VMS aux caméras
    marquées `ntp_managed` (voir POST /cameras/{id}/ntp) — les caméras
    dérivent avec le temps ou perdent l'heure après un reboot, un "set"
    ponctuel ne suffit pas dans la durée. Intervalle configurable depuis
    Date et heure → Serveur de temps (24h/48h/72h/personnalisé), relu à
    chaque vérification pour qu'un changement s'applique sans redémarrage."""
    last_resync = 0.0
    while True:
        await asyncio.sleep(_NTP_RESYNC_CHECK_EVERY_S)
        try:
            hours = await _load_ntp_resync_hours()
            if time.monotonic() - last_resync < hours * 3600:
                continue
            await _resync_all_ntp_cameras()
            last_resync = time.monotonic()
        except Exception:
            logger.exception("system_admin · erreur boucle ntp_resync_loop")


@system_admin_router.post("/ntp-resync-now")
async def force_ntp_resync_now(user: dict = Depends(require_role("admin"))):
    """v3.60 · Bouton "Forcer la synchro" (Date et heure → Serveur de temps) —
    repousse immédiatement l'heure à toutes les caméras `ntp_managed`, sans
    attendre le prochain cycle programmé (24h/48h/72h)."""
    result = await _resync_all_ntp_cameras()
    await log_audit(user, "ntp_resync_forced", f"{len(result['ok'])} caméra(s), {len(result['errors'])} échec(s)")
    return result


class NtpApplyBulkIn(BaseModel):
    camera_ids: list[str]
    ntp_server: str


@system_admin_router.post("/ntp-apply-bulk")
async def ntp_apply_bulk(data: NtpApplyBulkIn, user: dict = Depends(require_role("admin"))):
    """v3.60 · Bouton "Ajouter des caméras" (Date et heure → Serveur de temps) —
    active la gestion NTP MG-VMS sur plusieurs caméras ONVIF non encore
    synchronisées en une seule action, au lieu de répéter "Appareils →
    modifier la caméra → Définir comme serveur de temps" une par une.
    Même logique que `POST /cameras/{id}/ntp` (camera_control.py), juste
    appliquée à une liste plutôt qu'à une seule caméra."""
    from routes.camera_control import dispatch_set_ntp, _get_cam_credentials
    ntp_server = (data.ntp_server or "").strip()
    if not ntp_server:
        raise HTTPException(400, "ntp_server requis")
    ok, errors = [], []
    for camera_id in data.camera_ids:
        cam_doc = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "name": 1})
        name = (cam_doc or {}).get("name", camera_id)
        try:
            cam, ip, port, u, pwd = await _get_cam_credentials(camera_id)
            await dispatch_set_ntp(cam, ip, port, u, pwd, ntp_server)
            await db.cameras.update_one({"id": camera_id}, {"$set": {"ntp_managed": True, "ntp_server": ntp_server}})
            ok.append(name)
        except Exception as e:
            errors.append({"camera": name, "error": str(e)[:200]})
    await log_audit(user, "ntp_apply_bulk", f"{len(ok)} caméra(s), {len(errors)} échec(s)")
    return {"ok": ok, "errors": errors}


# ═══════════════════════════════════════════════════════════════════════
# Nettoyage disque système (cache de build Docker)
# ═══════════════════════════════════════════════════════════════════════
# v3.60 · Root cause réelle d'un disque système qui grossissait vite
# (constaté en conditions réelles : 75% de `/`, dont 32 Go de cache de
# build Docker jamais purgé — chaque redéploiement en ajoute) : rien ne
# nettoyait jamais ce cache. Même mécanisme que le redémarrage programmé
# ci-dessus — le conteneur backend n'a JAMAIS accès à Docker ni à l'hôte
# (pas de socket Docker monté, décision de sécurité déjà actée) : il
# dépose un fichier marqueur dans /logs, lu par reboot-watch.sh (timer
# systemd hôte, toutes les minutes) qui exécute le nettoyage réel.
_DOCKER_CLEANUP_FLAG_PATH = "/logs/host-docker-cleanup-requested"


def _write_docker_cleanup_flag(reason: str) -> None:
    os.makedirs(os.path.dirname(_DOCKER_CLEANUP_FLAG_PATH), exist_ok=True)
    with open(_DOCKER_CLEANUP_FLAG_PATH, "w") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} · {reason}\n")


class DockerCleanupSettingsIn(BaseModel):
    enabled: bool
    interval_hours: int = 24


async def _load_docker_cleanup_settings() -> dict:
    doc = await db.settings.find_one({"key": "docker_cleanup"}, {"_id": 0})
    val = (doc or {}).get("value") or {}
    return {
        "enabled": bool(val.get("enabled", False)),
        "interval_hours": max(1, min(int(val.get("interval_hours", 24)), 24 * 30)),
    }


@system_admin_router.get("/docker-cleanup-settings")
async def get_docker_cleanup_settings(user: dict = Depends(require_role("admin"))):
    return await _load_docker_cleanup_settings()


@system_admin_router.put("/docker-cleanup-settings")
async def put_docker_cleanup_settings(data: DockerCleanupSettingsIn, user: dict = Depends(require_role("admin"))):
    hours = max(1, min(int(data.interval_hours), 24 * 30))
    await db.settings.update_one(
        {"key": "docker_cleanup"},
        {"$set": {"key": "docker_cleanup", "value": {"enabled": data.enabled, "interval_hours": hours}}},
        upsert=True,
    )
    await log_audit(user, "docker_cleanup_settings_updated", f"enabled={data.enabled} interval={hours}h")
    return {"enabled": data.enabled, "interval_hours": hours}


@system_admin_router.post("/docker-cleanup-now")
async def docker_cleanup_now(user: dict = Depends(require_role("admin"))):
    """v3.60 · Bouton "Nettoyer maintenant" (Stockage → Nettoyage disque système) —
    dépose la demande, exécutée par reboot-watch.sh dans la minute qui suit."""
    _write_docker_cleanup_flag(f"manuel par {user.get('email', '?')}")
    await log_audit(user, "docker_cleanup_requested", "manuel")
    return {"ok": True, "note": "Nettoyage lancé côté hôte, effectif sous 1 minute."}


_DOCKER_CLEANUP_CHECK_EVERY_S = 1800  # vérifie l'intervalle configuré toutes les 30 min


async def docker_cleanup_loop() -> None:
    """v3.60 · Dépose périodiquement une demande de nettoyage du cache de
    build Docker si activé (Stockage → Nettoyage disque système). Même
    structure que `ntp_resync_loop` ci-dessus."""
    last_run = 0.0
    while True:
        await asyncio.sleep(_DOCKER_CLEANUP_CHECK_EVERY_S)
        try:
            cfg = await _load_docker_cleanup_settings()
            if not cfg["enabled"]:
                continue
            if time.monotonic() - last_run < cfg["interval_hours"] * 3600:
                continue
            _write_docker_cleanup_flag("automatique (programmé)")
            last_run = time.monotonic()
        except Exception:
            logger.exception("system_admin · erreur boucle docker_cleanup_loop")


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
