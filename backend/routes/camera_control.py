"""Route module — Contrôle caméra avancé + Audio (P9 & P10, Feb 2026).

Fonctionnalités exposées via ONVIF :
  - `GET  /device-info`       : marque, modèle, firmware, serial
  - `GET  /capabilities`      : ce que la caméra supporte (PTZ, audio, IO, imaging…)
  - `POST /ir/{on|off}`       : bascule IR Cut Filter (via Imaging)
  - `POST /light/{on|off}`    : bascule projecteur / lumière (via DeviceIO relais)
  - `POST /reboot`            : redémarre la caméra (SystemReboot)
  - `POST /audio/tts`         : joue un message TTS (envoie vers plugin `tts-notifier`
                                 avec métadonnées camera_id → à l'installateur de router
                                 vers un haut-parleur relié à la caméra ou physiquement à côté)
  - `POST /audio/announce`    : équivalent audio via workflow (chaînable actions)

Les endpoints qui manipulent l'ONVIF sont bloquants → wrappés `asyncio.to_thread`.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException

from auth import log_audit, require_permission
from database import db

camera_control_router = APIRouter(prefix="/api", tags=["camera-control"])


async def _get_cam_credentials(camera_id: str):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    if (cam.get("mode") or "rtsp") != "onvif" or not cam.get("ip"):
        raise HTTPException(400, "Cette caméra nécessite le mode ONVIF avec IP configurée")
    from crypto_utils import decrypt_secret
    pwd = decrypt_secret(cam.get("password", ""))
    return cam, cam["ip"], int(cam.get("onvif_port") or 80), cam.get("username", ""), pwd


def _onvif_device_info(ip, port, user, pwd) -> dict:
    from wsdl_path import onvif_camera
    cam = onvif_camera(ip, port, user, pwd)
    dev = cam.create_devicemgmt_service()
    info = dev.GetDeviceInformation()
    return {
        "manufacturer": getattr(info, "Manufacturer", None),
        "model": getattr(info, "Model", None),
        "firmware": getattr(info, "FirmwareVersion", None),
        "serial": getattr(info, "SerialNumber", None),
        "hardware": getattr(info, "HardwareId", None),
    }


def _onvif_capabilities(ip, port, user, pwd) -> dict:
    from wsdl_path import onvif_camera
    cam = onvif_camera(ip, port, user, pwd)
    dev = cam.create_devicemgmt_service()
    caps = dev.GetCapabilities({"Category": "All"})
    out = {}
    for section in ("Analytics", "Device", "Events", "Imaging", "Media", "PTZ", "Extension"):
        if hasattr(caps, section):
            v = getattr(caps, section)
            out[section.lower()] = bool(v) if v is not None else False
    # Détection support audio
    try:
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        out["audio_output"] = any(getattr(p, "AudioOutputConfiguration", None) for p in profiles)
        out["audio_source"] = any(getattr(p, "AudioSourceConfiguration", None) for p in profiles)
    except Exception:
        out["audio_output"] = False
        out["audio_source"] = False
    return out


def _onvif_ir_cut(ip, port, user, pwd, on: bool) -> dict:
    """Bascule le filtre IR de la caméra."""
    from wsdl_path import onvif_camera
    cam = onvif_camera(ip, port, user, pwd)
    media = cam.create_media_service()
    img = cam.create_imaging_service()
    src = media.GetVideoSources()[0]
    settings = img.create_type("SetImagingSettings")
    settings.VideoSourceToken = src.token
    settings.ImagingSettings = {"IrCutFilter": "ON" if on else "OFF"}
    settings.ForcePersistence = True
    img.SetImagingSettings(settings)
    return {"ok": True, "ir_cut": "ON" if on else "OFF"}


def _onvif_reboot(ip, port, user, pwd) -> dict:
    from wsdl_path import onvif_camera
    cam = onvif_camera(ip, port, user, pwd)
    dev = cam.create_devicemgmt_service()
    result = dev.SystemReboot()
    return {"ok": True, "message": str(result)}


def _onvif_set_ntp(ip, port, user, pwd, ntp_server: str) -> dict:
    """v3.19 · Pousse le serveur MG-VMS comme source de temps NTP sur la
    caméra — beaucoup de caméras IP dérivent ou perdent l'heure après un
    reboot. Opération ONVIF standard (même WSDL devicemgmt que
    GetDeviceInformation/SystemReboot ci-dessus)."""
    from wsdl_path import onvif_camera
    cam = onvif_camera(ip, port, user, pwd)
    dev = cam.create_devicemgmt_service()
    ntp = dev.create_type("SetNTP")
    ntp.FromDHCP = False
    ntp.NTPManual = [{"Type": "IPv4", "IPv4Address": ntp_server}]
    dev.SetNTP(ntp)
    return {"ok": True, "ntp_server": ntp_server}


def _onvif_set_relay(ip, port, user, pwd, relay_token: str, state: bool) -> dict:
    """Active/désactive un relais ONVIF (projecteur, sirène, gyrophare, GPIO…)."""
    from wsdl_path import onvif_camera
    cam = onvif_camera(ip, port, user, pwd)
    dev = cam.create_devicemgmt_service()
    dev.SetRelayOutputState({"RelayOutputToken": relay_token,
                              "LogicalState": "active" if state else "inactive"})
    return {"ok": True, "relay": relay_token, "state": "active" if state else "inactive"}


def _onvif_list_relays(ip, port, user, pwd) -> list:
    from wsdl_path import onvif_camera
    cam = onvif_camera(ip, port, user, pwd)
    dev = cam.create_devicemgmt_service()
    try:
        outs = dev.GetRelayOutputs() or []
    except Exception:
        return []
    return [{"token": getattr(o, "token", None),
             "mode": str(getattr(getattr(o, "Properties", None), "Mode", None) or ""),
             "state": str(getattr(o, "PresentState", "") or "")}
            for o in outs]


# ── Endpoints ─────────────────────────────────────────────────────────
@camera_control_router.get("/cameras/{camera_id}/device-info")
async def device_info(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    cam, ip, port, u, pwd = await _get_cam_credentials(camera_id)
    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(_onvif_device_info, ip, port, u, pwd), timeout=12)
    except Exception as e:
        raise HTTPException(502, f"ONVIF error: {type(e).__name__}: {str(e)[:200]}")
    return {"camera_id": camera_id, **info}


@camera_control_router.get("/cameras/{camera_id}/capabilities")
async def capabilities(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    cam, ip, port, u, pwd = await _get_cam_credentials(camera_id)
    try:
        caps = await asyncio.wait_for(
            asyncio.to_thread(_onvif_capabilities, ip, port, u, pwd), timeout=12)
    except Exception as e:
        raise HTTPException(502, f"ONVIF error: {type(e).__name__}: {str(e)[:200]}")
    return {"camera_id": camera_id, **caps}


@camera_control_router.get("/cameras/{camera_id}/relays")
async def list_relays(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    cam, ip, port, u, pwd = await _get_cam_credentials(camera_id)
    try:
        relays = await asyncio.wait_for(
            asyncio.to_thread(_onvif_list_relays, ip, port, u, pwd), timeout=12)
    except Exception as e:
        raise HTTPException(502, f"ONVIF error: {type(e).__name__}: {str(e)[:200]}")
    return {"relays": relays}


@camera_control_router.post("/cameras/{camera_id}/ir/{state}")
async def ir_control(camera_id: str, state: str,
                      user: dict = Depends(require_permission("ptz_control"))):
    if state not in ("on", "off"):
        raise HTTPException(400, "state doit être 'on' ou 'off'")
    cam, ip, port, u, pwd = await _get_cam_credentials(camera_id)
    try:
        r = await asyncio.wait_for(
            asyncio.to_thread(_onvif_ir_cut, ip, port, u, pwd, state == "on"),
            timeout=12)
    except Exception as e:
        raise HTTPException(502, f"IR ctrl error: {type(e).__name__}: {str(e)[:200]}")
    await log_audit(user, "camera_ir", cam.get("name", camera_id), state)
    return r


@camera_control_router.post("/cameras/{camera_id}/relay/{relay_token}/{state}")
async def relay_control(camera_id: str, relay_token: str, state: str,
                         user: dict = Depends(require_permission("ptz_control"))):
    """Contrôle un relais (projecteur, sirène, lumière blanche, GPIO…)."""
    if state not in ("on", "off"):
        raise HTTPException(400, "state doit être 'on' ou 'off'")
    cam, ip, port, u, pwd = await _get_cam_credentials(camera_id)
    try:
        r = await asyncio.wait_for(
            asyncio.to_thread(_onvif_set_relay, ip, port, u, pwd, relay_token, state == "on"),
            timeout=12)
    except Exception as e:
        raise HTTPException(502, f"Relay error: {type(e).__name__}: {str(e)[:200]}")
    await log_audit(user, "camera_relay", cam.get("name", camera_id), f"{relay_token}={state}")
    return r


@camera_control_router.post("/cameras/{camera_id}/reboot")
async def reboot_camera(camera_id: str,
                         confirm: bool = False,
                         user: dict = Depends(require_permission("admin"))):
    if not confirm:
        raise HTTPException(400, "Confirmation requise : `?confirm=true`")
    cam, ip, port, u, pwd = await _get_cam_credentials(camera_id)
    try:
        r = await asyncio.wait_for(
            asyncio.to_thread(_onvif_reboot, ip, port, u, pwd), timeout=15)
    except Exception as e:
        raise HTTPException(502, f"Reboot error: {type(e).__name__}: {str(e)[:200]}")
    await log_audit(user, "camera_reboot", cam.get("name", camera_id))
    return r


@camera_control_router.post("/cameras/{camera_id}/ntp")
async def set_camera_ntp(camera_id: str,
                          body: dict = Body(...),
                          user: dict = Depends(require_permission("admin"))):
    """v3.19 · "Définir comme serveur de temps" — pousse l'IP du serveur
    MG-VMS (fournie par le frontend, qui la connaît déjà via l'URL utilisée
    pour s'y connecter) comme source NTP de la caméra, et marque la caméra
    pour la resynchronisation automatique toutes les 24h (auto_ntp_loop)."""
    ntp_server = (body or {}).get("ntp_server", "").strip()
    if not ntp_server:
        raise HTTPException(400, "ntp_server requis")
    cam, ip, port, u, pwd = await _get_cam_credentials(camera_id)
    try:
        r = await asyncio.wait_for(
            asyncio.to_thread(_onvif_set_ntp, ip, port, u, pwd, ntp_server), timeout=15)
    except Exception as e:
        raise HTTPException(502, f"NTP error: {type(e).__name__}: {str(e)[:200]}")
    await db.cameras.update_one({"id": camera_id}, {"$set": {"ntp_managed": True, "ntp_server": ntp_server}})
    await log_audit(user, "camera_ntp_set", cam.get("name", camera_id), ntp_server)
    return r


@camera_control_router.post("/cameras/{camera_id}/audio/tts")
async def play_tts(camera_id: str,
                    body: dict = Body(...),
                    user: dict = Depends(require_permission("ptz_control"))):
    """P9 · TTS sur haut-parleur relié à la caméra.

    Route l'ordre via le plugin `tts-notifier` (à installer par l'utilisateur — non
    fourni par défaut car dépend du hardware audio). L'opérateur passe :
      {"text": "...", "voice"?: "...", "language"?: "fr-FR"}

    Le plugin TTS est libre de générer l'audio via ElevenLabs / Piper / Google TTS
    puis de le publier sur le haut-parleur (via MQTT, HTTP, ONVIF SetAudioOutput…).
    """
    text = (body or {}).get("text", "").strip()
    if not text:
        raise HTTPException(400, "text requis")
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")

    from smart_zones.actuators import dispatch_action
    result = await dispatch_action({
        "type": "tts",
        "config": {
            "text": text,
            "voice": (body or {}).get("voice"),
            "language": (body or {}).get("language") or "fr-FR",
            "plugin_name": (body or {}).get("plugin_name") or "tts-notifier",
        },
    }, {"camera_id": camera_id, "camera_name": cam.get("name")})
    await log_audit(user, "camera_tts", cam.get("name", camera_id), text[:80])
    return result
