"""video-pipeline-v2 · PIPELINE 3 — MediaMTX.

RTSP caméra → MediaMTX path `camera/{camera_id}` → WebRTC (WHEP) + RTSP.
- Paths créés/supprimés dynamiquement via la Control API v3 (jamais de
  credentials caméra côté frontend ni dans mediamtx.yml).
- Ingestion RTSP TCP par défaut. H.264 : copy/remux, zéro transcodage.
- Statut : Control API `/v3/paths/get/{name}` (ready, tracks, bytesReceived,
  readers) + détection de flux gelé via delta bytesReceived.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional
from urllib.parse import quote

import httpx

from .base import camera_source_url, video_status_payload

logger = logging.getLogger("video.mediamtx")

MEDIAMTX_API_URL = os.environ.get("MEDIAMTX_API_URL", "http://localhost:9997")
MEDIAMTX_RTSP_URL = os.environ.get("MEDIAMTX_RTSP_URL", "rtsp://localhost:8654")
MEDIAMTX_WHEP_URL = os.environ.get("MEDIAMTX_WHEP_URL", "http://localhost:8889")

# Détection flux gelé : dernier bytesReceived observé par caméra
_last_bytes: dict[str, tuple[float, int]] = {}


def path_name(camera_id: str) -> str:
    return f"camera/{camera_id}"


def web_path_name(camera_id: str) -> str:
    """Path H264 dédié au navigateur (source webrtc_rtsp_url) — consommé
    UNIQUEMENT par le WHEP. Le path principal reste le flux natif."""
    return f"camera/{camera_id}_web"


def whep_path(cam: dict) -> str:
    """Path servi au navigateur : `_web` (H264 dédié) si configuré, sinon principal."""
    return web_path_name(cam["id"]) if (cam.get("webrtc_rtsp_url") or "").strip() \
        else path_name(cam["id"])


def _api_path(camera_id: str) -> str:
    return quote(path_name(camera_id), safe="")


def rtsp_read_url(camera_id: str) -> str:
    """URL RTSP de LECTURE MediaMTX (recorder, consommateurs internes)."""
    return f"{MEDIAMTX_RTSP_URL}/{path_name(camera_id)}"


def _desired_conf(cam: dict) -> dict:
    return {
        "source": camera_source_url(cam),
        "rtspTransport": "tcp",
        "sourceOnDemand": False,
    }


async def ensure_path(cam: dict, *, force: bool = False) -> bool:
    """Déclare (ou met à jour) le(s) path(s) MediaMTX d'une caméra. Idempotent.
    Gère aussi le path `_web` (flux H264 dédié navigateur) si webrtc_rtsp_url est défini."""
    ok = await _ensure_one_path(path_name(cam["id"]), _desired_conf(cam), force=force)
    web_url = (cam.get("webrtc_rtsp_url") or "").strip()
    if web_url.lower().startswith("rtsp://"):
        await _ensure_one_path(web_path_name(cam["id"]),
                                {"source": web_url, "rtspTransport": "tcp",
                                 "sourceOnDemand": False}, force=force)
    else:
        await _delete_path(web_path_name(cam["id"]))
    return ok


async def _ensure_one_path(name: str, conf: dict, *, force: bool = False) -> bool:
    if not conf["source"].lower().startswith(("rtsp://", "rtsps://")):
        logger.warning("mediamtx.ensure_path %s : URL RTSP invalide", name)
        return False
    api_name = quote(name, safe="")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            if not force:
                r = await client.get(f"{MEDIAMTX_API_URL}/v3/config/paths/get/{api_name}")
                if r.status_code == 200:
                    existing = r.json() or {}
                    if existing.get("source") == conf["source"]:
                        return True
                    r2 = await client.patch(
                        f"{MEDIAMTX_API_URL}/v3/config/paths/patch/{api_name}", json=conf)
                    return r2.status_code == 200
            else:
                await client.delete(f"{MEDIAMTX_API_URL}/v3/config/paths/delete/{api_name}")
            r = await client.post(
                f"{MEDIAMTX_API_URL}/v3/config/paths/add/{api_name}", json=conf)
            if r.status_code == 200:
                logger.info("mediamtx: path %s enregistré", name)
                return True
            if "already exists" in (r.text or "").lower():
                r2 = await client.patch(
                    f"{MEDIAMTX_API_URL}/v3/config/paths/patch/{api_name}", json=conf)
                return r2.status_code == 200
            logger.warning("mediamtx: échec add path %s → HTTP %s %s",
                           name, r.status_code, (r.text or "")[:200])
            return False
    except httpx.HTTPError as e:
        logger.warning("mediamtx: injoignable (%s) pour %s", type(e).__name__, name)
        return False


async def _delete_path(name: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.delete(f"{MEDIAMTX_API_URL}/v3/config/paths/delete/{quote(name, safe='')}")
    except httpx.HTTPError:
        pass


async def remove_path(camera_id: str) -> None:
    _last_bytes.pop(camera_id, None)
    await _delete_path(path_name(camera_id))
    await _delete_path(web_path_name(camera_id))


async def get_path_state_by_name(name: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{MEDIAMTX_API_URL}/v3/paths/get/{quote(name, safe='')}")
            return r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


async def get_path_state(camera_id: str) -> Optional[dict]:
    """État runtime du path (`/v3/paths/get`). None si absent ou MediaMTX HS."""
    return await get_path_state_by_name(path_name(camera_id))


async def get_status(cam: dict) -> dict:
    """Statut pipeline MediaMTX au contrat video-status commun."""
    cam_id = cam["id"]
    state = await get_path_state(cam_id)
    if state is None:
        return video_status_payload(cam_id, "mediamtx", status="offline",
                                     error="path MediaMTX absent ou service injoignable")
    ready = bool(state.get("ready"))
    tracks = state.get("tracks") or []
    bytes_recv = int(state.get("bytesReceived") or 0)
    now = time.monotonic()
    prev = _last_bytes.get(cam_id)
    _last_bytes[cam_id] = (now, bytes_recv)
    frozen = bool(prev and bytes_recv == prev[1] and (now - prev[0]) >= 5 and ready)
    fps = None
    if ready and prev and bytes_recv > prev[1]:
        fps = None  # MediaMTX n'expose pas le FPS ; le débit prouve un flux vivant
    status = "online" if (ready and not frozen) else ("offline" if not ready else "offline")
    return video_status_payload(
        cam_id, "mediamtx",
        status=status,
        codec=(tracks[0].lower() if tracks else None),
        fps=fps,
        last_frame_at=state.get("readyTime"),
        error=("flux gelé (0 octet reçu depuis 5 s)" if frozen
               else (None if ready else "source RTSP non prête")),
        extra={"readers": len(state.get("readers") or []),
               "bytes_received": bytes_recv,
               "webrtc": f"/api/video/{cam_id}/whep",
               "rtsp_read": rtsp_read_url(cam_id).replace("mediamtx:8554", "<hôte>:8654")})


async def whep_exchange(camera_id_or_path: str, offer_sdp: str) -> tuple[str, Optional[str]]:
    """Négociation WebRTC WHEP officielle : POST SDP offer → (SDP answer, session path).
    Accepte un camera_id (path principal) ou un nom de path complet `camera/...`.
    Lève ValueError avec message explicite en cas d'échec."""
    path = camera_id_or_path if "/" in camera_id_or_path else path_name(camera_id_or_path)
    url = f"{MEDIAMTX_WHEP_URL}/{path}/whep"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, content=offer_sdp.encode(),
                                   headers={"Content-Type": "application/sdp"})
    except httpx.HTTPError as e:
        raise ValueError(f"MediaMTX WHEP injoignable ({type(e).__name__})")
    if r.status_code == 404:
        raise ValueError("path MediaMTX introuvable pour cette caméra")
    if r.status_code not in (200, 201):
        raise ValueError(f"MediaMTX WHEP HTTP {r.status_code} · {(r.text or '')[:200]}")
    return r.text, r.headers.get("location")


async def whep_close(session_location: str) -> None:
    """Ferme proprement une session WHEP (DELETE sur la ressource session)."""
    if not session_location:
        return
    url = session_location if session_location.startswith("http") \
        else f"{MEDIAMTX_WHEP_URL}{session_location}"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.delete(url)
    except httpx.HTTPError:
        pass


async def sync_paths(cams: list[dict]) -> int:
    """Au démarrage : garantit un path par caméra pipeline=mediamtx, purge les
    paths `camera/*` orphelins (caméra supprimée ou passée sur un autre pipeline)."""
    from .base import resolve_pipeline
    wanted_cams = {c["id"]: c for c in cams if resolve_pipeline(c) == "mediamtx"}
    wanted_paths = set()
    for cam in wanted_cams.values():
        wanted_paths.add(path_name(cam["id"]))
        if (cam.get("webrtc_rtsp_url") or "").strip():
            wanted_paths.add(web_path_name(cam["id"]))
    n = 0
    for cam in wanted_cams.values():
        if await ensure_path(cam):
            n += 1
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{MEDIAMTX_API_URL}/v3/config/paths/list?itemsPerPage=500")
            items = (r.json() or {}).get("items", []) if r.status_code == 200 else []
        for item in items:
            name = item.get("name", "")
            if name.startswith("camera/") and name not in wanted_paths:
                await _delete_path(name)
                logger.info("mediamtx: path orphelin purgé — %s", name)
    except httpx.HTTPError:
        pass
    return n
