"""Routes /api/camera-devices/* — API caméra AGNOSTIQUE du fabricant.

Le frontend ne connaît que ces endpoints. Le protocole propriétaire (Reolink
JSON API, Hikvision ISAPI, Dahua CGI, ONVIF…) est résolu par le registry
`camera_api.registry.resolve_provider`.

Cette couche est STRICTEMENT INDÉPENDANTE du pipeline vidéo — aucun impact
sur RTSP / MediaMTX / go2rtc / MJPEG / WebRTC.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user, require_permission
from database import db
from camera_api import (AuthenticationFailed, CameraApiError, DeviceUnreachable,
                          ProviderNotFound, UnsupportedCapability, resolve_provider,
                          list_providers)

logger = logging.getLogger("routes.camera_api")

camera_api_router = APIRouter(prefix="/api/camera-devices", tags=["camera-api"])


# ── Helpers ────────────────────────────────────────────────────────────────

async def _load_cam(camera_id: str, user: dict) -> dict:
    from streaming import _authorize_camera
    return await _authorize_camera(user, camera_id)


def _cam_to_config(cam: dict) -> dict:
    """Copie les champs API + retire les creds RTSP inutiles ici.
    Ne modifie JAMAIS le dict `cam` d'origine."""
    return {
        "id": cam.get("id"),
        "ip": cam.get("ip"),
        "manufacturer": cam.get("manufacturer") or cam.get("api_provider") or "",
        "model": cam.get("model", ""),
        "api_host": cam.get("api_host") or cam.get("ip"),
        "api_port": cam.get("api_port"),
        "api_scheme": cam.get("api_scheme") or "https",
        "api_verify_ssl": cam.get("api_verify_ssl", False),
        "api_username": cam.get("api_username") or cam.get("username"),
        "api_password": cam.get("api_password") or "",           # transitoire
        "api_password_enc": cam.get("api_password_enc") or cam.get("password"),
        "api_provider": cam.get("api_provider"),
    }


def _http_from_exc(e: Exception) -> HTTPException:
    if isinstance(e, AuthenticationFailed):
        return HTTPException(401, detail=e.to_dict())
    if isinstance(e, DeviceUnreachable):
        return HTTPException(503, detail=e.to_dict())
    if isinstance(e, UnsupportedCapability):
        return HTTPException(501, detail=e.to_dict())
    if isinstance(e, ProviderNotFound):
        return HTTPException(400, detail=e.to_dict())
    if isinstance(e, CameraApiError):
        return HTTPException(502, detail=e.to_dict())
    return HTTPException(500, detail={"error": "internal", "message": str(e)})


def _resolve_and_config(cam: dict):
    """Résout la classe provider + retourne la config nettoyée. Lève HTTPException."""
    conf = _cam_to_config(cam)
    if not conf["api_host"]:
        raise HTTPException(400, detail={"error": "api_host_required",
                                          "message": "Renseignez `api_host` (ou `ip`) sur la caméra"})
    try:
        cls = resolve_provider(provider_id=conf.get("api_provider") or "",
                                manufacturer=conf.get("manufacturer") or "",
                                model=conf.get("model") or "")
    except ProviderNotFound as e:
        raise _http_from_exc(e)
    return cls, conf


# ── Meta ───────────────────────────────────────────────────────────────────

@camera_api_router.get("/_providers")
async def api_providers(user: dict = Depends(get_current_user)):
    """Liste les providers HTTP/HTTPS supportés."""
    return {"providers": list_providers()}


# ── Discover / Info / Capabilities / Network / Users ───────────────────────

@camera_api_router.post("/{camera_id}/discover")
async def api_discover(camera_id: str,
                        user: dict = Depends(require_permission("manage_cameras"))):
    """Login + probe complet + persist en base (source de vérité côté MG-VMS).

    Retourne l'agrégation `device_info` + `capabilities` + `network` + `users`.
    Aucun contenu vidéo n'est téléchargé.
    """
    cam = await _load_cam(camera_id, user)
    cls, conf = _resolve_and_config(cam)
    try:
        async with cls(conf) as provider:
            info = await provider.get_device_info()
            caps = await provider.get_capabilities()
            try:
                net = (await provider.get_network_info()).to_dict()
            except UnsupportedCapability:
                net = None
            try:
                users = [u.to_dict() for u in await provider.get_users()]
            except UnsupportedCapability:
                users = None
    except Exception as e:
        logger.warning("discover %s: %s: %s", camera_id, type(e).__name__, e)
        raise _http_from_exc(e)

    # Persist les métadonnées API dans la fiche caméra (jamais le password).
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await db.cameras.update_one({"id": camera_id}, {"$set": {
        "manufacturer": info.manufacturer or cam.get("manufacturer") or "",
        "model": info.model or cam.get("model") or "",
        "firmware": info.firmware or cam.get("firmware") or "",
        "api_provider": cls.name,
        "api_capabilities": caps.to_dict(),
        "api_last_seen": now,
        "api_last_error": "",
    }})
    return {
        "device_info": info.to_dict(),
        "capabilities": caps.to_dict(),
        "network": net,
        "users": users,
        "provider": cls.name,
    }


@camera_api_router.get("/{camera_id}/info")
async def api_info(camera_id: str, user: dict = Depends(get_current_user)):
    cam = await _load_cam(camera_id, user)
    cls, conf = _resolve_and_config(cam)
    try:
        async with cls(conf) as provider:
            return (await provider.get_device_info()).to_dict()
    except Exception as e:
        raise _http_from_exc(e)


@camera_api_router.get("/{camera_id}/capabilities")
async def api_capabilities(camera_id: str, user: dict = Depends(get_current_user)):
    """Capacités LIVES (login réel). Pour la version cachée en base, utiliser
    `cameras[id].api_capabilities` mis à jour par /discover."""
    cam = await _load_cam(camera_id, user)
    cls, conf = _resolve_and_config(cam)
    try:
        async with cls(conf) as provider:
            return (await provider.get_capabilities()).to_dict()
    except Exception as e:
        raise _http_from_exc(e)


@camera_api_router.get("/{camera_id}/network")
async def api_network(camera_id: str, user: dict = Depends(get_current_user)):
    cam = await _load_cam(camera_id, user)
    cls, conf = _resolve_and_config(cam)
    try:
        async with cls(conf) as provider:
            return (await provider.get_network_info()).to_dict()
    except Exception as e:
        raise _http_from_exc(e)


@camera_api_router.get("/{camera_id}/users")
async def api_users(camera_id: str,
                     user: dict = Depends(require_permission("manage_cameras"))):
    cam = await _load_cam(camera_id, user)
    cls, conf = _resolve_and_config(cam)
    try:
        async with cls(conf) as provider:
            return [u.to_dict() for u in await provider.get_users()]
    except Exception as e:
        raise _http_from_exc(e)


# ── Controls (Vague 2 — stubs pour l'instant, remontent 501) ───────────────

class SetIRBody(BaseModel):
    mode: str    # auto | on | off


class SetLightBody(BaseModel):
    enabled: bool
    brightness: Optional[int] = None


class SetSirenBody(BaseModel):
    enabled: bool
    duration: Optional[int] = None


class PTZMoveBody(BaseModel):
    direction: str    # up|down|left|right|upleft|upright|downleft|downright|stop
    speed: float = 0.5


async def _with_provider(camera_id: str, user: dict, fn):
    cam = await _load_cam(camera_id, user)
    cls, conf = _resolve_and_config(cam)
    try:
        async with cls(conf) as provider:
            return await fn(provider)
    except Exception as e:
        raise _http_from_exc(e)


@camera_api_router.get("/{camera_id}/ir")
async def api_get_ir(camera_id: str, user: dict = Depends(get_current_user)):
    return await _with_provider(camera_id, user, lambda p: p.get_ir())


@camera_api_router.post("/{camera_id}/ir")
async def api_set_ir(camera_id: str, body: SetIRBody,
                      user: dict = Depends(require_permission("manage_cameras"))):
    await _with_provider(camera_id, user, lambda p: p.set_ir(body.mode))
    return {"ok": True}


@camera_api_router.post("/{camera_id}/ptz/move")
async def api_ptz_move(camera_id: str, body: PTZMoveBody,
                        user: dict = Depends(require_permission("ptz_control"))):
    await _with_provider(camera_id, user,
                          lambda p: p.ptz_move(body.direction, body.speed))
    return {"ok": True}


@camera_api_router.post("/{camera_id}/ptz/stop")
async def api_ptz_stop(camera_id: str,
                        user: dict = Depends(require_permission("ptz_control"))):
    await _with_provider(camera_id, user, lambda p: p.ptz_stop())
    return {"ok": True}


@camera_api_router.get("/{camera_id}/light")
async def api_get_light(camera_id: str, user: dict = Depends(get_current_user)):
    return await _with_provider(camera_id, user, lambda p: p.get_light())


@camera_api_router.post("/{camera_id}/light")
async def api_set_light(camera_id: str, body: SetLightBody,
                         user: dict = Depends(require_permission("manage_cameras"))):
    await _with_provider(camera_id, user,
                          lambda p: p.set_light(body.enabled, body.brightness))
    return {"ok": True}


@camera_api_router.get("/{camera_id}/siren")
async def api_get_siren(camera_id: str, user: dict = Depends(get_current_user)):
    return await _with_provider(camera_id, user, lambda p: p.get_siren())


@camera_api_router.post("/{camera_id}/siren")
async def api_set_siren(camera_id: str, body: SetSirenBody,
                         user: dict = Depends(require_permission("manage_cameras"))):
    await _with_provider(camera_id, user,
                          lambda p: p.set_siren(body.enabled, body.duration))
    return {"ok": True}


@camera_api_router.get("/{camera_id}/storage")
async def api_storage(camera_id: str, user: dict = Depends(get_current_user)):
    return await _with_provider(camera_id, user, lambda p: p.get_storage())


@camera_api_router.get("/{camera_id}/recordings")
async def api_recordings(camera_id: str, channel: int = 0,
                          start: str = "", end: str = "",
                          user: dict = Depends(get_current_user)):
    """Cherche les métadonnées d'enregistrements SD. **Aucun téléchargement**.

    Les résultats sont indexés en Mongo (`camera_recordings_index`) pour requêtage
    ultérieur — implémenté en Vague 3.
    """
    return await _with_provider(
        camera_id, user,
        lambda p: p.search_recordings(channel=channel, start=start or None, end=end or None))
