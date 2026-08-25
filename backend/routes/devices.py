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
  GET  /api/devices/{camera_id}/storage       · supports SD/eMMC détectés
  GET  /api/devices/{camera_id}/recordings    · enregistrements locaux [start, end]
  GET  /api/devices/{camera_id}/recordings/stream?file=…   · proxy vidéo (ffmpeg, MP4)
  GET  /api/devices/{camera_id}/recordings/download?file=… · téléchargement local
  GET  /api/devices/_supported                · liste des vendors supportés

Endpoints v0.5.7 (Universal Camera API — Validator / Matrix / Health) :
  GET  /api/devices/matrix?group=vendor|driver|model|camera
  GET  /api/devices/drivers/health
  GET  /api/devices/{camera_id}/validate?persist=false   · idempotent
  POST /api/devices/{camera_id}/validate                  · persiste le rapport
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
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
    #   501 pour "unsupported_capability" (v0.7.c — capability absente = Not Implemented)
    #   400 pour "camera_missing_ip"
    #   401 pour "authentication_failed"
    #   404 pour "camera_not_found"
    #   503 pour "device_unreachable" / "command_timeout"
    mapping = {
        "unsupported_capability": 501,
        "no_driver_available": 501,
        "camera_missing_ip": 400,
        "authentication_failed": 401,
        "camera_not_found": 404,
        "device_locked": 423,       # v1.0-rc4.5 · protection brute-force caméra
        "device_unreachable": 503,
        "command_timeout": 503,
        "device_error": 502,
        "driver_error": 502,
    }
    return HTTPException(status_code=mapping.get(exc.code, 502), detail=payload)


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


@devices_router.get("/{camera_id}/network")
async def device_network(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    """Paramètres réseau détaillés (ports, protocoles, UID, WiFi…).

    Clés variables selon le constructeur — le frontend n'affiche que ce
    qui est réellement remonté. 501 si le driver ne l'implémente pas.
    """
    try:
        drv = await svc.get_driver(camera_id)
        return await drv.get_network()
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


# ── Codec du flux principal (v3.10) ───────────────────────────────
class EncodingBody(BaseModel):
    codec: str = Field(..., description="h264 | h265")


async def _camera_channel(camera_id: str) -> int:
    """Canal physique de cette caméra sur l'appareil.

    Un appareil multi-capteurs expose plusieurs canaux (`h264Preview_01_*`,
    `h264Preview_02_*`) que MG-VMS présente comme des caméras distinctes.
    Agir sur le canal 0 par défaut modifierait donc le mauvais objectif.
    """
    from database import db
    from streaming import _stream_channel_key
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0}) or {}
    key = _stream_channel_key(cam.get("rtsp_url") or "")
    if key and ":" in key:
        try:
            # "reolink:1" → canal 0 (Reolink numérote ses URL à partir de 1)
            return max(0, int(key.split(":", 1)[1]) - 1)
        except ValueError:
            pass
    return 0


@devices_router.get("/{camera_id}/encoding")
async def device_get_encoding(camera_id: str,
                               user: dict = Depends(require_permission("view_live"))):
    """Codec du flux principal + est-il réellement modifiable sur ce modèle."""
    try:
        drv = await svc.get_driver(camera_id)
        return await drv.get_encoding_info(await _camera_channel(camera_id))
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.post("/{camera_id}/encoding")
async def device_set_encoding(camera_id: str, body: EncodingBody,
                               user: dict = Depends(require_permission("manage_cameras"))):
    """Bascule le codec du flux principal entre H.264 et H.265."""
    try:
        drv = await svc.get_driver(camera_id)
        await drv.set_encoding(body.codec, await _camera_channel(camera_id))
        return {"success": True, "codec": body.codec.lower()}
    except CameraDriverError as e:
        raise _driver_error_response(e)


# ── Stockage local / enregistrements SD card (v3.5) ───────────────
@devices_router.get("/{camera_id}/storage")
async def device_storage(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    """Supports de stockage locaux détectés sur la caméra (carte SD/eMMC)."""
    try:
        drv = await svc.get_driver(camera_id)
        return {"storage": await drv.get_storage()}
    except CameraDriverError as e:
        raise _driver_error_response(e)


@devices_router.get("/{camera_id}/recordings")
async def device_recordings(camera_id: str,
                             start: Optional[datetime] = None,
                             end: Optional[datetime] = None,
                             stream: str = "main",
                             user: dict = Depends(require_permission("view_live"))):
    """Enregistrements présents sur le stockage local caméra sur ``[start, end]``.

    Par défaut : 24 dernières heures. ``stream`` = "main" (HD) ou "sub" (SD).
    """
    end = end or datetime.now(timezone.utc)
    start = start or (end - timedelta(hours=24))
    if stream not in ("main", "sub"):
        raise HTTPException(status_code=400,
                            detail={"error": "invalid_stream",
                                    "message": "stream doit valoir 'main' (HD) ou 'sub' (SD)"})
    try:
        drv = await svc.get_driver(camera_id)
        return {"recordings": await drv.search_recordings(start, end, stream=stream)}
    except CameraDriverError as e:
        raise _driver_error_response(e)


async def _recording_stream_generator(cmd: list) -> AsyncGenerator[bytes, None]:
    """Lit stdout ffmpeg (MP4 fragmenté) et le relaie tel quel au client.

    Même pattern que ``routes/mjpeg_direct.py`` (subprocess ffmpeg, lecture
    par chunks, arrêt propre du process quand le client se déconnecte).
    """
    logger.info("recording-stream: spawn ffmpeg (source masquée — contient les identifiants caméra)")
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            yield chunk
    finally:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except (ProcessLookupError, asyncio.TimeoutError):
            try: proc.kill()
            except Exception: pass
        logger.info("recording-stream: subprocess terminé")


@devices_router.get("/{camera_id}/recordings/stream")
async def device_recording_stream(camera_id: str, file: str, quality: str = "main",
                                   user: dict = Depends(require_permission("view_live"))):
    """Proxy vidéo (remux ffmpeg, ``-c copy`` sans transcodage) d'un
    enregistrement carte SD — quel que soit le protocole/vendor source
    (RTSP Digest pour Hikvision, HTTP MP4/FLV crédentialé pour Reolink,
    HTTP Digest .dav pour Dahua). Ne renvoie JAMAIS l'URL source réelle
    (identifiants caméra inclus) au client — ffmpeg tourne côté serveur,
    seul le flux MP4 fragmenté (lisible directement par ``<video>``) sort.

    ``file`` = identifiant renvoyé par ``GET .../recordings`` (``file_name``).
    """
    try:
        drv = await svc.get_driver(camera_id)
        src_url = await drv.get_recording_source(file, stream=quality)
    except CameraDriverError as e:
        raise _driver_error_response(e)

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if src_url.lower().startswith("rtsp"):
        cmd += ["-rtsp_transport", "tcp"]
    cmd += [
        "-i", src_url, "-c", "copy",
        "-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "pipe:1",
    ]
    return StreamingResponse(
        _recording_stream_generator(cmd),
        media_type="video/mp4",
        headers={"Cache-Control": "no-store, no-cache", "X-Accel-Buffering": "no"},
    )


@devices_router.get("/{camera_id}/recordings/download")
async def device_recording_download(camera_id: str, file: str, quality: str = "main",
                                     user: dict = Depends(require_permission("view_live"))):
    """Téléchargement local d'un enregistrement carte SD (fichier tel quel).

    Contrairement à ``/stream`` (remux ffmpeg à la volée pour la lecture
    navigateur), on relaie ici les octets bruts servis par la caméra, sans
    ré-encodage. L'URL source (avec identifiants/token) reste côté serveur.
    """
    try:
        drv = await svc.get_driver(camera_id)
        src_url = await drv.get_recording_source(file, stream=quality)
    except CameraDriverError as e:
        raise _driver_error_response(e)

    safe_name = (file.rsplit("/", 1)[-1] or "recording.mp4")
    if not safe_name.lower().endswith((".mp4", ".dav", ".flv")):
        safe_name += ".mp4"

    async def _proxy() -> AsyncGenerator[bytes, None]:
        if src_url.lower().startswith("rtsp"):
            # Pas de fichier téléchargeable en RTSP (Hikvision) : on remux
            # vers un MP4 avec ffmpeg, sans ré-encodage vidéo.
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
                   "-rtsp_transport", "tcp", "-i", src_url, "-c", "copy",
                   "-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                   "pipe:1"]
            async for chunk in _recording_stream_generator(cmd):
                yield chunk
            return
        import httpx
        async with httpx.AsyncClient(verify=False, timeout=None, follow_redirects=True) as client:
            async with client.stream("GET", src_url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(65536):
                    yield chunk

    return StreamingResponse(
        _proxy(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Cache-Control": "no-store, no-cache",
            "X-Accel-Buffering": "no",
        },
    )
