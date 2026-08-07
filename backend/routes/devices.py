"""Routes API du Device Layer (v0.4.6 + enrichissement v0.5.7).

Toutes les commandes physiques d'une caméra passent par ces endpoints.
Aucun code appelant n'importe directement un driver.

Endpoints v0.4.6 :
  GET  /api/devices/{camera_id}/info
  GET  /api/devices/{camera_id}/capabilities
  GET  /api/devices/{camera_id}/status
  GET  /api/devices/{camera_id}/streams
  POST /api/devices/{camera_id}/discover      · probe + persist
  POST /api/devices/{camera_id}/light         · {enabled, brightness?, mode?}
  POST /api/devices/{camera_id}/ir            · {mode}
  POST /api/devices/{camera_id}/siren         · {enabled, duration?}
  POST /api/devices/{camera_id}/audio/start
  POST /api/devices/{camera_id}/audio/stop
  POST /api/devices/{camera_id}/ptz/move      · {direction, speed?}
  POST /api/devices/{camera_id}/ptz/zoom      · {value}
  POST /api/devices/{camera_id}/ptz/preset    · {id}
  GET  /api/devices/_supported                · liste des vendors supportés

Endpoints v0.5.7 (Universal Camera API — Validator / Matrix / Health) :
  GET  /api/devices/matrix?group=vendor|driver|model|camera
  GET  /api/devices/drivers/health
  GET  /api/devices/{camera_id}/validate?persist=false   · idempotent
  POST /api/devices/{camera_id}/validate                  · persiste le rapport
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from drivers import (
    CameraDriverError, UnsupportedCapabilityError, list_supported_vendors,
    IRMode, LightMode,
)
from auth import require_permission
from services.camera_device_service import camera_device_service as svc
from pipeline_v2.driver_validator import driver_validator
from pipeline_v2.capability_matrix import build_capability_matrix, build_driver_health

logger = logging.getLogger("routes.devices")

devices_router = APIRouter(prefix="/api/devices", tags=["devices"])


# ── Bodies ──────────────────────────────────────────────────────
class LightBody(BaseModel):
    enabled: bool
    brightness: Optional[int] = Field(default=None, ge=0, le=100)
    mode: LightMode = LightMode.ON


class IRBody(BaseModel):
    mode: IRMode


class SirenBody(BaseModel):
    enabled: bool
    duration: Optional[int] = Field(default=None, ge=1, le=600)


class PTZMoveBody(BaseModel):
    direction: str = Field(..., description="up|down|left|right|upleft|upright|downleft|downright|stop")
    speed: float = Field(default=0.5, ge=0.0, le=1.0)


class PTZZoomBody(BaseModel):
    value: float = Field(..., ge=-1.0, le=1.0)


class PTZPresetBody(BaseModel):
    id: int = Field(..., ge=1, le=255)


# ── Wrapper — retourne un dict {success/error/message} sur erreur driver ─
def _driver_error_response(exc: CameraDriverError) -> HTTPException:
    payload = exc.to_dict()
    # Code HTTP :
    #   400 pour "unsupported_capability" / "camera_missing_ip"
    #   401 pour "authentication_failed"
    #   404 pour "camera_not_found"
    #   503 pour "device_unreachable" / "command_timeout"
    mapping = {
        "unsupported_capability": 400,
        "camera_missing_ip": 400,
        "authentication_failed": 401,
        "camera_not_found": 404,
        "device_unreachable": 503,
        "command_timeout": 503,
    }
    return HTTPException(status_code=mapping.get(exc.code, 500), detail=payload)


# ── GET ─────────────────────────────────────────────────────────
@devices_router.get("/_supported")
async def supported_vendors(user: dict = Depends(require_permission("view_live"))):
    return {"vendors": list_supported_vendors()}


# ═════════════════════════════════════════════════════════════════
# v0.5.7 · Universal Camera API — Matrix / Health / Validator
# (déclarés AVANT `/{camera_id}/...` pour éviter tout shadowing)
# ═════════════════════════════════════════════════════════════════
@devices_router.get("/matrix")
async def devices_matrix(group: str = "vendor",
                          user: dict = Depends(require_permission("view_live"))):
    """Matrice de capacités de la flotte, groupée par ``group``.

    ``group`` ∈ {``vendor``, ``driver``, ``model``, ``camera``}.
    Lecture seule — aucune I/O caméra.
    """
    try:
        return await build_capability_matrix(group)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": "invalid_group", "message": str(e)})


@devices_router.get("/drivers/health")
async def devices_drivers_health(user: dict = Depends(require_permission("view_live"))):
    """Santé + manifest de chaque driver enregistré. Lecture seule."""
    return await build_driver_health()


@devices_router.get("/{camera_id}/validate")
async def device_validate_get(camera_id: str, persist: bool = False,
                               user: dict = Depends(require_permission("view_live"))):
    """Valide de manière **non destructive** les capacités du driver.

    - ``persist=false`` (défaut) : idempotent, ne modifie rien.
    - ``persist=true``           : sauvegarde le rapport dans ``cameras[id].last_validation``.
    """
    if persist:
        report = await driver_validator.run_and_persist(camera_id)
    else:
        report = await driver_validator.validate(camera_id)
    return report.to_dict()


@devices_router.post("/{camera_id}/validate")
async def device_validate_post(camera_id: str,
                                user: dict = Depends(require_permission("manage_cameras"))):
    """Validation persistée (POST) — équivalent à ``GET ?persist=true``."""
    report = await driver_validator.run_and_persist(camera_id)
    return report.to_dict()


@devices_router.get("/{camera_id}/info")
async def device_info(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    try:
        drv = await svc.get_driver(camera_id)
        info = await drv.get_device_info()
        return info.to_dict()
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.get("/{camera_id}/capabilities")
async def device_capabilities(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    try:
        drv = await svc.get_driver(camera_id)
        caps = await drv.get_capabilities()
        return caps.to_dict()
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.get("/{camera_id}/status")
async def device_status(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    try:
        drv = await svc.get_driver(camera_id)
        return (await drv.get_status()).to_dict()
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.get("/{camera_id}/streams")
async def device_streams(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    try:
        drv = await svc.get_driver(camera_id)
        streams = await drv.get_streams()
        return [s.to_dict() for s in streams]
    except CameraDriverError as e:
        raise _driver_error_response(e)


# ── POST ────────────────────────────────────────────────────────
@devices_router.post("/{camera_id}/discover")
async def device_discover(camera_id: str, user: dict = Depends(require_permission("manage_cameras"))):
    """Probe complète (connect → info → capabilities → streams) + persist Mongo."""
    try:
        return await svc.discover(camera_id)
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.post("/{camera_id}/light")
async def device_light(camera_id: str, body: LightBody,
                        user: dict = Depends(require_permission("manage_cameras"))):
    try:
        drv = await svc.get_driver(camera_id)
        await drv.set_light(enabled=body.enabled, brightness=body.brightness, mode=body.mode)
        return {"success": True}
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.post("/{camera_id}/ir")
async def device_ir(camera_id: str, body: IRBody,
                     user: dict = Depends(require_permission("manage_cameras"))):
    try:
        drv = await svc.get_driver(camera_id)
        await drv.set_ir_mode(body.mode)
        return {"success": True}
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.post("/{camera_id}/siren")
async def device_siren(camera_id: str, body: SirenBody,
                        user: dict = Depends(require_permission("manage_cameras"))):
    try:
        drv = await svc.get_driver(camera_id)
        await drv.set_siren(enabled=body.enabled, duration=body.duration)
        return {"success": True}
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.post("/{camera_id}/audio/start")
async def device_audio_start(camera_id: str,
                              user: dict = Depends(require_permission("manage_cameras"))):
    try:
        drv = await svc.get_driver(camera_id)
        await drv.start_audio()
        return {"success": True}
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.post("/{camera_id}/audio/stop")
async def device_audio_stop(camera_id: str,
                             user: dict = Depends(require_permission("manage_cameras"))):
    try:
        drv = await svc.get_driver(camera_id)
        await drv.stop_audio()
        return {"success": True}
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.post("/{camera_id}/ptz/move")
async def device_ptz_move(camera_id: str, body: PTZMoveBody,
                           user: dict = Depends(require_permission("manage_cameras"))):
    try:
        drv = await svc.get_driver(camera_id)
        await drv.ptz_move(body.direction, body.speed)
        return {"success": True}
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.post("/{camera_id}/ptz/zoom")
async def device_ptz_zoom(camera_id: str, body: PTZZoomBody,
                           user: dict = Depends(require_permission("manage_cameras"))):
    try:
        drv = await svc.get_driver(camera_id)
        await drv.ptz_zoom(body.value)
        return {"success": True}
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.post("/{camera_id}/ptz/preset")
async def device_ptz_preset(camera_id: str, body: PTZPresetBody,
                             user: dict = Depends(require_permission("manage_cameras"))):
    try:
        drv = await svc.get_driver(camera_id)
        await drv.ptz_preset(body.id)
        return {"success": True}
    except CameraDriverError as e:
        raise _driver_error_response(e)
