"""MG-VMS · Routes video v3 (RTSP-native only).

Endpoints uniques post-refonte :
    GET  /api/live/{camera_id}/status     → runtime snapshot Mongo
    POST /api/live/{camera_id}/start      → force ensure_camera (démarrage RTSP)
    POST /api/live/{camera_id}/stop       → arrêt manuel
    POST /api/live/{camera_id}/whep       → WHEP handshake (SDP offer → answer)

Cette route est la SEULE source live navigateur post-V3. Remplace :
    - /api/pipeline/webrtc/{id}           (go2rtc)  · SUPPRIMÉ
    - /api/video/{id}/whep                (mediamtx) · SUPPRIMÉ
    - /api/stream/{id}/live.mjpeg         (legacy)  · SUPPRIMÉ
    - /api/video/{id}/mjpeg               (v2)      · SUPPRIMÉ
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from auth import get_current_user
from database import db
from video_core import VideoCoreManager, runtime_snapshot

logger = logging.getLogger("routes.live_v3")

live_v3_router = APIRouter(prefix="/api/live", tags=["live-v3"])


async def _load_cam(camera_id: str, user: dict) -> dict:
    from streaming import _authorize_camera
    return await _authorize_camera(user, camera_id)


@live_v3_router.get("/{camera_id}/status")
async def live_status(camera_id: str, user: dict = Depends(get_current_user)):
    await _load_cam(camera_id, user)
    snap = await runtime_snapshot(camera_id) or {"camera_id": camera_id,
                                                    "status": "unknown"}
    return snap


@live_v3_router.post("/{camera_id}/start")
async def live_start(camera_id: str, user: dict = Depends(get_current_user)):
    cam = await _load_cam(camera_id, user)
    await VideoCoreManager.instance().ensure_camera(cam)
    return {"ok": True, "camera_id": camera_id}


@live_v3_router.post("/{camera_id}/stop")
async def live_stop(camera_id: str, user: dict = Depends(get_current_user)):
    await _load_cam(camera_id, user)
    await VideoCoreManager.instance().stop_camera(camera_id)
    return {"ok": True, "camera_id": camera_id}


@live_v3_router.post("/{camera_id}/whep")
async def live_whep(camera_id: str, request: Request, hd: int = 0,
                     user: dict = Depends(get_current_user)):
    """WHEP handshake · Content-Type: application/sdp · retourne l'answer SDP.

    ``hd=1`` demande le flux principal plutôt que le sous-flux (bouton HD/SD
    du mur vidéo) — ignoré si le principal est en HEVC, non transportable par
    WebRTC vers un navigateur.
    """
    await _load_cam(camera_id, user)
    sdp = (await request.body()).decode("utf-8", errors="ignore")
    if "v=0" not in sdp:
        raise HTTPException(400, "SDP offer requis (Content-Type: application/sdp)")
    from webrtc_gateway import whep_offer
    try:
        answer_sdp, session = await whep_offer(camera_id, sdp, prefer_hd=bool(hd))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(415, str(e))
    except Exception as e:
        logger.exception("whep %s error", camera_id)
        raise HTTPException(502, f"WHEP échec: {type(e).__name__}: {e}")
    from fastapi.responses import Response
    return Response(content=answer_sdp, media_type="application/sdp",
                     headers={"X-Whep-Session": session,
                              "Access-Control-Expose-Headers": "X-Whep-Session"})
