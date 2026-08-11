"""video-pipeline-v2 · Endpoints vidéo unifiés.

- GET  /api/cameras/{id}/video-status : contrat statut unique (3 pipelines)
- GET  /api/video/{id}/mjpeg          : flux MJPEG broker partagé (pipelines mjpeg & mediamtx)
- POST /api/video/{id}/whep           : signaling WebRTC WHEP proxifié → MediaMTX
- DELETE /api/video/{id}/whep         : fermeture propre de session WHEP

Le frontend ne connaît JAMAIS les credentials RTSP des caméras.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from auth import get_current_user

logger = logging.getLogger("routes.video")

video_router = APIRouter(prefix="/api", tags=["video-v2"])


async def _load_cam(user: dict, camera_id: str) -> dict:
    from streaming import _authorize_camera
    return await _authorize_camera(user, camera_id)


@video_router.get("/cameras/{camera_id}/video-status")
async def video_status(camera_id: str, user: dict = Depends(get_current_user)):
    """Statut vidéo pipeline-aware — même format pour direct_rtsp / mjpeg / mediamtx."""
    cam = await _load_cam(user, camera_id)
    from video_pipelines.status import get_video_status
    return await get_video_status(cam)


@video_router.get("/video/{camera_id}/mjpeg")
async def video_mjpeg(camera_id: str, request: Request):
    """Flux MJPEG multipart — broker ffmpeg PARTAGÉ (1 processus par caméra).

    - pipeline `mjpeg`    : source = RTSP caméra direct
    - pipeline `mediamtx` : source = relais RTSP MediaMTX (1 seule session caméra)
    - pipeline `direct_rtsp` : 409 — ce pipeline n'a pas de preview navigateur
    """
    from streaming import stream_user
    user = await stream_user(request, request.query_params.get("token"))
    cam = await _load_cam(user, camera_id)
    from video_pipelines import mjpeg as p_mjpeg
    from video_pipelines import mediamtx as p_mediamtx
    from video_pipelines.base import camera_source_url, resolve_pipeline
    pipeline = resolve_pipeline(cam)
    if pipeline == "direct_rtsp":
        raise HTTPException(409, "Pipeline direct_rtsp : flux RTSP natif uniquement — "
                                  "pas de preview navigateur (choisir MJPEG ou MediaMTX)")
    if pipeline == "mediamtx":
        source = p_mediamtx.rtsp_read_url(camera_id)
    else:
        source = camera_source_url(cam, pipeline=pipeline)
        if not source.lower().startswith("rtsp://"):
            raise HTTPException(502, "Aucune URL RTSP valide pour cette caméra")
    broker = p_mjpeg.ensure_broker(camera_id, source)
    if not await p_mjpeg.wait_first_frame(broker):
        raise HTTPException(502, f"Flux MJPEG indisponible ({broker.last_error or 'aucune frame reçue'})")
    return StreamingResponse(
        p_mjpeg.multipart_generator(broker),
        media_type=f"multipart/x-mixed-replace; boundary={p_mjpeg.BOUNDARY}",
        headers={"Cache-Control": "no-store, no-cache",
                 "X-Accel-Buffering": "no",
                 "X-Video-Pipeline": pipeline})


@video_router.post("/video/{camera_id}/whep")
async def video_whep(camera_id: str, request: Request,
                      user: dict = Depends(get_current_user)):
    """Signaling WebRTC WHEP officiel MediaMTX, proxifié et authentifié.
    Body = SDP offer (application/sdp) · Réponse 201 = SDP answer."""
    cam = await _load_cam(user, camera_id)
    from video_pipelines import mediamtx as p_mediamtx
    from video_pipelines.base import resolve_pipeline
    if resolve_pipeline(cam) != "mediamtx":
        raise HTTPException(409, "WebRTC disponible uniquement avec le pipeline MediaMTX")
    offer_sdp = (await request.body()).decode("utf-8", errors="replace")
    if "v=0" not in offer_sdp:
        raise HTTPException(400, "SDP offer invalide")
    # Path garanti (idempotent) + attente courte que la source soit prête
    # (évite un 502 transitoire si le path vient d'être créé/rechargé)
    await p_mediamtx.ensure_path(cam)
    path = p_mediamtx.whep_path(cam)   # `_web` (H264 dédié) si webrtc_rtsp_url défini
    import asyncio as _aio
    state = None
    for _ in range(10):
        state = await p_mediamtx.get_path_state_by_name(path)
        if state and state.get("ready"):
            break
        await _aio.sleep(0.5)
    # ── Garde codec : les navigateurs ne lisent pas H265/HEVC en WebRTC ──
    tracks = {str(t).upper() for t in ((state or {}).get("tracks") or [])}
    browser_ok = {"H264", "VP8", "VP9", "AV1"}
    if tracks and not (tracks & browser_ok):
        src_codec = ", ".join(sorted(t for t in tracks if t not in ("MPEG-4 AUDIO", "OPUS", "G711")))
        raise HTTPException(409,
            f"Caméra en {src_codec or 'H265'} : les navigateurs ne lisent pas ce codec en WebRTC. "
            "Renseignez « URL RTSP WebRTC (H264) » dans la fiche caméra (ex. Reolink : "
            "…/h264Preview_01_sub), passez le flux principal de la caméra en H264, "
            "ou choisissez le pipeline MJPEG.")
    try:
        answer, session = await p_mediamtx.whep_exchange(path, offer_sdp)
    except ValueError:
        # Retry unique (path en cours de warm-up côté MediaMTX)
        await _aio.sleep(0.8)
        try:
            answer, session = await p_mediamtx.whep_exchange(path, offer_sdp)
        except ValueError as e:
            raise HTTPException(502, str(e))
    headers = {"Content-Type": "application/sdp"}
    if session:
        headers["X-Whep-Session"] = session
    return Response(content=answer, status_code=201, headers=headers)


@video_router.delete("/video/{camera_id}/whep")
async def video_whep_close(camera_id: str, session: str = "",
                            user: dict = Depends(get_current_user)):
    """Ferme proprement une session WHEP (valeur du header X-Whep-Session)."""
    await _load_cam(user, camera_id)
    from video_pipelines import mediamtx as p_mediamtx
    await p_mediamtx.whep_close(session)
    return {"ok": True}
