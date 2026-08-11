"""video-pipeline-v2 · Statut UNIFIÉ pipeline-aware.

GET /api/cameras/{id}/video-status — même contrat JSON pour les 3 pipelines.
Le statut d'une caméra ne dépend JAMAIS de Go2RTC.
"""
from __future__ import annotations

from . import direct_rtsp as p_direct
from . import mediamtx as p_mediamtx
from . import mjpeg as p_mjpeg
from .base import resolve_pipeline, video_status_payload


async def get_video_status(cam: dict) -> dict:
    pipeline = resolve_pipeline(cam)
    if pipeline == "mediamtx":
        return await p_mediamtx.get_status(cam)
    if pipeline == "direct_rtsp":
        return await p_direct.get_status(cam)
    if pipeline == "go2rtc":
        status, err = await _go2rtc_probe(cam)
        return video_status_payload(cam["id"], "go2rtc", status=status, error=err or None,
                                     extra={"legacy": True})
    # MJPEG : broker actif → métriques réelles ; broker arrêté (0 viewer) →
    # pipeline "à la demande", disponibilité prouvée par TCP check léger.
    frag = p_mjpeg.get_status(cam["id"])
    if frag["state"] in ("online", "starting"):
        return video_status_payload(
            cam["id"], "mjpeg",
            status="online" if frag["state"] == "online" else "starting",
            codec="mjpeg", fps=frag["fps"],
            last_frame_at=frag["last_frame_at"], error=frag["error"],
            extra={"viewers": frag["viewers"], "restarts": frag.get("restarts", 0)})
    ok, err = await p_direct.tcp_only_check(cam)
    return video_status_payload(
        cam["id"], "mjpeg",
        status="online" if ok else "offline",
        codec="mjpeg", fps=0.0, error=(err or frag["error"]),
        extra={"viewers": 0, "state": "on-demand" if ok else "stopped"})


async def _go2rtc_probe(cam: dict) -> tuple[str, str]:
    """Pipeline legacy go2rtc (choix explicite admin) : statut via go2rtc."""
    from streaming import _stream_registered, _stream_bytes_recv, _stream_name
    name = _stream_name(cam["id"])
    if not await _stream_registered(name):
        return "offline", "flux non enregistré dans go2rtc — cliquer Réparer"
    if await _stream_bytes_recv(name) > 0:
        return "online", ""
    ok, err = await p_direct.tcp_only_check(cam)
    return ("online", "") if ok else ("offline", err)


async def quick_probe(cam: dict) -> tuple[str, str]:
    """Probe LÉGER pour la boucle périodique de statut (camera_status_loop).
    Retourne (status, error). Jamais de session RTSP supplémentaire, jamais Go2RTC.
    """
    pipeline = resolve_pipeline(cam)
    if pipeline == "go2rtc":
        return await _go2rtc_probe(cam)
    if pipeline == "mediamtx":
        state = await p_mediamtx.get_path_state(cam["id"])
        if state is None:
            return "offline", "path MediaMTX absent ou service injoignable"
        if state.get("ready"):
            return "online", ""
        return "offline", "source RTSP non prête côté MediaMTX"
    if pipeline == "mjpeg":
        frag = p_mjpeg.get_status(cam["id"])
        if frag["state"] == "online":
            return "online", ""
        ok, err = await p_direct.tcp_only_check(cam)
        return ("online", "") if ok else ("offline", err)
    ok, err = await p_direct.tcp_only_check(cam)
    return ("online", "") if ok else ("offline", err)
