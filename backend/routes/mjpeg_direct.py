"""v1.0-rc4 · MJPEG multipart streaming DIRECT (bypass Go2RTC).

Endpoint : `GET /api/cameras/{camera_id}/mjpeg-direct`

Ouvre un subprocess ffmpeg qui lit RTSP directement depuis la caméra
(camera.ai_rtsp_url ou camera.rtsp_url) et produit une séquence de JPEGs
au format `multipart/x-mixed-replace` — lisible nativement par
`<img src="...">` dans tous les navigateurs modernes.

Différence CRITIQUE avec `/api/stream/{id}/frame.jpeg` (endpoint existant) :
  - frame.jpeg → passe par GO2RTC_URL/api/frame.jpeg (relais Go2RTC)
  - mjpeg-direct → ffmpeg subprocess local, ZÉRO call Go2RTC

Utilisé par le frontend quand `camera.live_preview_source == "direct"`.
"""
import asyncio
import logging
import os
import shlex
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from auth import require_permission
from database import db

logger = logging.getLogger("routes.mjpeg_direct")

mjpeg_direct_router = APIRouter(prefix="/api", tags=["preview"])

# Frontière multipart utilisée par tous les navigateurs pour x-mixed-replace
_BOUNDARY = "mgvms-mjpeg-boundary"
_SOI = b"\xff\xd8\xff"   # Start Of Image JPEG
_EOI = b"\xff\xd9"       # End Of Image JPEG


def _build_ffmpeg_cmd(rtsp_url: str, transport: str, target_fps: int, quality: int,
                       max_width: int = 0, codec: str = "") -> list:
    """Construit la commande ffmpeg : RTSP → JPEGs consécutifs sur stdout.

    -q:v 2..8 (JPEG quality, plus petit = meilleur). Défaut 5 = équilibre.
    -r fps limite le débit de sortie pour ne pas saturer le réseau/navigateur.
    -an drop audio (économie CPU).
    max_width > 0 → scale à cette largeur (variante SD faible bande passante).

    `codec` ("h264"/"h265"/"hevc") : si un GPU NVDEC est disponible (même détection
    que frame_source.py — pas de 2e sonde), décode via hwaccel cuda au lieu du
    logiciel. Seul le DÉCODAGE passe sur GPU (`hwdownload` immédiat) ; le scale et
    l'encodage JPEG restent inchangés (logiciel, comme avant) — changement minimal,
    cible uniquement le goulot d'étranglement CPU du décodage 4K/HEVC.
    """
    quality = max(2, min(int(quality or 5), 15))
    fps = max(1, min(int(target_fps or 8), 15))  # 1-15 fps pour preview navigateur

    use_gpu = False
    codec = (codec or "").lower()
    if codec in ("h264", "h265", "hevc"):
        try:
            from frame_source import _use_gpu as _fs_use_gpu
            use_gpu = _fs_use_gpu()
        except Exception:
            use_gpu = False

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", transport]
    if use_gpu:
        # Même pattern que frame_source.py : décode NVDEC, frame rapatriée en CPU
        # immédiatement après (hwdownload) — le reste du pipeline ne change pas.
        cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        cmd += ["-c:v", "hevc_cuvid" if codec in ("h265", "hevc") else "h264_cuvid"]
    cmd += ["-i", rtsp_url, "-an", "-r", str(fps)]

    vf_parts = []
    if use_gpu:
        vf_parts += ["hwdownload", "format=nv12"]
    if max_width and int(max_width) > 0:
        vf_parts.append(f"scale={int(max_width)}:-2")
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]

    cmd += [
        "-q:v", str(quality),
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "pipe:1",
    ]
    return cmd


async def _mjpeg_stream_generator(cmd: list) -> AsyncGenerator[bytes, None]:
    """Lit stdout ffmpeg (JPEGs concaténés), détecte SOI/EOI, yield chaque
    frame emballée en multipart/x-mixed-replace.

    Le protocole HTTP multipart-x-mixed-replace attend :
        --boundary\r\n
        Content-Type: image/jpeg\r\n
        Content-Length: N\r\n
        \r\n
        <bytes JPEG>\r\n
    """
    logger.info("mjpeg-direct: spawn %s", " ".join(shlex.quote(c) for c in cmd[:6]))
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    buf = b""
    try:
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            buf += chunk
            # Découpe chaque frame JPEG (SOI ... EOI) et yield
            while True:
                soi_idx = buf.find(_SOI)
                if soi_idx < 0:
                    break
                eoi_idx = buf.find(_EOI, soi_idx + 3)
                if eoi_idx < 0:
                    break
                frame = buf[soi_idx:eoi_idx + 2]
                buf = buf[eoi_idx + 2:]
                header = (
                    f"--{_BOUNDARY}\r\n"
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(frame)}\r\n\r\n"
                ).encode()
                yield header + frame + b"\r\n"
    finally:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except (ProcessLookupError, asyncio.TimeoutError):
            try: proc.kill()
            except Exception: pass
        logger.info("mjpeg-direct: subprocess terminé")


@mjpeg_direct_router.get("/cameras/{camera_id}/mjpeg-direct")
async def mjpeg_direct(
    camera_id: str,
    fps: int = 8,
    q: int = 5,
    user: dict = Depends(require_permission("view_live")),
):
    """Streaming MJPEG multipart depuis RTSP direct — 0 Go2RTC.

    Query params :
      - fps : cible d'images/seconde (1-15, défaut 8)
      - q   : qualité JPEG (2-15, plus petit = meilleur, défaut 5)
    """
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")

    # v1.0-rc4.6 · Builder canonique : injecte les credentials déchiffrés (Fernet)
    # dans l'URL RTSP — cohérent avec le reste du pipeline. ai_rtsp_url (sous-flux
    # dédié, supposé complet) garde la priorité, comme dans ai_engine.
    from streaming import _build_rtsp_url
    rtsp_url = (cam.get("ai_rtsp_url") or "").strip() or _build_rtsp_url(cam)
    if not rtsp_url:
        raise HTTPException(
            400,
            "URL RTSP absente sur cette caméra — le mode DIRECT nécessite une URL "
            "RTSP renseignée. Utilisez le mode GO2RTC ou renseignez rtsp_url.",
        )
    transport = (cam.get("rtsp_transport") or "tcp").lower()
    if transport not in ("tcp", "udp"):
        transport = "tcp"

    cmd = _build_ffmpeg_cmd(rtsp_url, transport, fps, q, codec=cam.get("codec") or "")
    return StreamingResponse(
        _mjpeg_stream_generator(cmd),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
        headers={
            "Cache-Control": "no-store, no-cache",
            "X-Accel-Buffering": "no",
            "X-Preview-Source": "direct-ffmpeg",  # preuve côté client que
                                                   # le stream ne passe PAS par Go2RTC
        },
    )
