"""v1.0-rc4 · Diagnostic pipeline vidéo multi-étages par caméra.

Endpoint unique : `GET /api/cameras/{camera_id}/pipeline-diagnostic`

Teste séparément chaque étape du pipeline vidéo pour distinguer précisément
où le flux échoue (règle du prompt v1.0-rc4 : messages d'erreur distincts,
pas de "Une erreur est survenue"). L'endpoint ne modifie AUCUN état, ne
crée AUCUN stream, ne redémarre AUCUN service — pur diagnostic.

Étapes retournées avec status PASS / FAIL / SKIP + latency_ms + détails :
  1. rtsp_tcp_reachable    : socket TCP vers ip:rtsp_port
  2. rtsp_stream_decodable : ffprobe (codec, resolution, fps, bitrate)
  3. go2rtc_api_reachable  : GET {GO2RTC_URL}/api
  4. go2rtc_stream_known   : GET {GO2RTC_URL}/api/streams → cam_{id} présent ?
  5. go2rtc_producer_alive : GET {GO2RTC_URL}/api/streams?src=cam_{id} → producers ?
  6. hevc_webrtc_compat    : décision statique (codec == h265 ⇒ WebRTC direct KO)

Réservé aux techniciens / admins.
"""
import asyncio
import logging
import time
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException

from auth import require_role
from database import db

logger = logging.getLogger("routes.pipeline_diagnostic")

pipeline_diag_router = APIRouter(prefix="/api", tags=["diagnostic"])


def _step(name: str, status: str, latency_ms: Optional[float] = None,
          detail: str = "", data: Optional[dict] = None) -> dict:
    return {
        "step": name,
        "status": status,  # PASS / FAIL / SKIP / WARN
        "latency_ms": round(latency_ms, 1) if latency_ms is not None else None,
        "detail": detail,
        "data": data or {},
    }


async def _step_rtsp_tcp(cam: dict) -> dict:
    """1. TCP connect sur ip:rtsp_port (défaut 554)."""
    from streaming import _tcp_check
    ip = (cam.get("ip") or "").strip()
    port = int(cam.get("rtsp_port") or 554)
    if not ip:
        return _step("rtsp_tcp_reachable", "SKIP",
                     detail="Pas d'IP caméra configurée (mode RTSP url seule).")
    t0 = time.perf_counter()
    ok = await asyncio.to_thread(_tcp_check, ip, port, 3.0)
    dt = (time.perf_counter() - t0) * 1000
    if ok:
        return _step("rtsp_tcp_reachable", "PASS", dt,
                     f"TCP {ip}:{port} accessible.")
    return _step("rtsp_tcp_reachable", "FAIL", dt,
                 f"TCP {ip}:{port} injoignable — vérifier IP/pare-feu/caméra allumée.")


async def _step_rtsp_decode(cam: dict) -> dict:
    """2. ffprobe sur l'URL RTSP native → codec/résolution/fps."""
    from streaming import _ffprobe, _mask_url_password
    rtsp_url = (cam.get("rtsp_url") or "").strip()
    if not rtsp_url:
        return _step("rtsp_stream_decodable", "SKIP",
                     detail="Pas d'URL RTSP validée pour cette caméra.")
    transport = (cam.get("rtsp_transport") or "tcp").lower()
    t0 = time.perf_counter()
    info = await asyncio.to_thread(_ffprobe, rtsp_url, transport)
    dt = (time.perf_counter() - t0) * 1000
    if not info:
        return _step("rtsp_stream_decodable", "FAIL", dt,
                     f"ffprobe échec sur {_mask_url_password(rtsp_url)} (transport={transport}). "
                     "Vérifier credentials, path, transport TCP/UDP.")
    return _step("rtsp_stream_decodable", "PASS", dt,
                 f"codec={info.get('codec_name')} · "
                 f"{info.get('width')}x{info.get('height')} @ {info.get('fps')}fps",
                 data=info)


async def _step_go2rtc_api(client: httpx.AsyncClient) -> dict:
    """3. GET {GO2RTC_URL}/api — service atteignable ?"""
    from streaming import GO2RTC_URL
    t0 = time.perf_counter()
    try:
        r = await client.get(f"{GO2RTC_URL}/api", timeout=4.0)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            info = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            return _step("go2rtc_api_reachable", "PASS", dt,
                         f"Go2RTC v{info.get('version', '?')} joignable ({GO2RTC_URL}).",
                         data=info)
        return _step("go2rtc_api_reachable", "FAIL", dt,
                     f"Go2RTC HTTP {r.status_code} sur {GO2RTC_URL}/api.")
    except httpx.HTTPError as e:
        dt = (time.perf_counter() - t0) * 1000
        return _step("go2rtc_api_reachable", "FAIL", dt,
                     f"Go2RTC injoignable : {type(e).__name__} — vérifier conteneur go2rtc.")


async def _step_go2rtc_stream_known(client: httpx.AsyncClient, stream_name: str) -> dict:
    """4. Le stream cam_{id} est-il déclaré dans Go2RTC ?"""
    from streaming import GO2RTC_URL
    t0 = time.perf_counter()
    try:
        r = await client.get(f"{GO2RTC_URL}/api/streams", timeout=4.0)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            return _step("go2rtc_stream_known", "FAIL", dt,
                         f"GET /api/streams → HTTP {r.status_code}.")
        streams = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if stream_name not in streams:
            available = sorted(list(streams.keys()))[:10]
            return _step("go2rtc_stream_known", "FAIL", dt,
                         f"Stream '{stream_name}' non déclaré dans Go2RTC. "
                         f"Utiliser 'Réparer ce flux' pour ré-enregistrer.",
                         data={"available": available})
        entry = streams.get(stream_name)
        return _step("go2rtc_stream_known", "PASS", dt,
                     f"Stream '{stream_name}' enregistré dans Go2RTC.",
                     data={"entry": entry})
    except httpx.HTTPError as e:
        dt = (time.perf_counter() - t0) * 1000
        return _step("go2rtc_stream_known", "FAIL", dt,
                     f"GET /api/streams échec : {type(e).__name__}.")


async def _step_go2rtc_producer_alive(client: httpx.AsyncClient, stream_name: str) -> dict:
    """5. Le producer ffmpeg/RTSP de Go2RTC produit-il réellement des frames ?"""
    from streaming import GO2RTC_URL
    t0 = time.perf_counter()
    try:
        r = await client.get(f"{GO2RTC_URL}/api/streams?src={stream_name}", timeout=6.0)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            return _step("go2rtc_producer_alive", "FAIL", dt,
                         f"GET /api/streams?src={stream_name} → HTTP {r.status_code}.")
        info = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        producers = info.get("producers") or []
        if not producers:
            return _step("go2rtc_producer_alive", "FAIL", dt,
                         "Go2RTC n'a AUCUN producer actif pour ce stream — la source "
                         "RTSP ne s'ouvre pas côté Go2RTC (souvent : codec non "
                         "décodable par ffmpeg, credentials, ou transport UDP bloqué).",
                         data={"raw": info})
        # Détection anomalie : producer sans medias == décodage KO (souvent HEVC + ffmpeg SW)
        producer_ok = any((p.get("medias") or p.get("format") or p.get("state") in ("running", "connected"))
                          for p in producers)
        if not producer_ok:
            return _step("go2rtc_producer_alive", "WARN", dt,
                         f"{len(producers)} producer(s) mais aucun media/format publié — "
                         "typiquement échec de décodage (HEVC sans hwaccel, codec exotique). "
                         "Voir logs go2rtc.",
                         data={"producers": producers})
        return _step("go2rtc_producer_alive", "PASS", dt,
                     f"{len(producers)} producer(s) actif(s) avec media(s) publié(s).",
                     data={"producers_count": len(producers), "consumers": len(info.get("consumers") or [])})
    except httpx.HTTPError as e:
        dt = (time.perf_counter() - t0) * 1000
        return _step("go2rtc_producer_alive", "FAIL", dt,
                     f"GET producer state échec : {type(e).__name__}.")


def _step_hevc_webrtc_compat(cam: dict, probe_info: Optional[dict]) -> dict:
    """6. Décision statique compat HEVC/WebRTC navigateur."""
    codec = (probe_info or {}).get("codec_name", "").lower() or (cam.get("codec") or "").lower()
    if not codec:
        return _step("hevc_webrtc_compat", "SKIP",
                     detail="Codec inconnu (probe ffprobe non disponible).")
    if codec in ("h265", "hevc"):
        return _step("hevc_webrtc_compat", "WARN",
                     detail=("Codec HEVC/H.265 : WebRTC ne supporte QUE H.264 dans "
                             "les navigateurs actuels. Le preview passe donc par le "
                             "transcodage MJPEG (variantes {name}_hd / _sd générées "
                             "par Go2RTC). Vérifier que ffmpeg dispose du décodeur "
                             "HEVC (hwaccel NVDEC recommandé pour 4K)."),
                     data={"codec_detected": codec, "webrtc_direct": False, "preview_via": "mjpeg"})
    if codec in ("h264", "avc", "avc1"):
        return _step("hevc_webrtc_compat", "PASS",
                     detail=f"Codec {codec} compatible WebRTC direct.",
                     data={"codec_detected": codec, "webrtc_direct": True})
    return _step("hevc_webrtc_compat", "WARN",
                 detail=f"Codec {codec} non standard pour WebRTC — preview via MJPEG.",
                 data={"codec_detected": codec, "webrtc_direct": False})


def _global_verdict(steps: list) -> str:
    """OK si tout PASS/SKIP/WARN, FAIL si au moins une étape critique en FAIL."""
    if any(s["status"] == "FAIL" for s in steps):
        return "FAIL"
    if any(s["status"] == "WARN" for s in steps):
        return "WARN"
    return "PASS"


@pipeline_diag_router.get("/cameras/{camera_id}/pipeline-diagnostic")
async def pipeline_diagnostic(
    camera_id: str,
    user: dict = Depends(require_role("technician")),
):
    """Diagnostic bout-en-bout du pipeline vidéo d'une caméra.

    Ne modifie AUCUN état côté MG-VMS/Go2RTC/caméra — 100% lecture.
    Utilisation : identifier précisément QUELLE étape échoue quand une
    caméra ONVIF fonctionne mais Go2RTC ne présente pas le flux.
    """
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "password": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")

    from streaming import _stream_name, GO2RTC_URL

    stream_name = _stream_name(camera_id)
    steps: list = []
    probe_info: Optional[dict] = None

    # Étape 1 & 2 : RTSP réel côté caméra
    steps.append(await _step_rtsp_tcp(cam))
    step2 = await _step_rtsp_decode(cam)
    steps.append(step2)
    if step2["status"] == "PASS":
        probe_info = step2.get("data") or {}

    # Étape 3-5 : Go2RTC
    async with httpx.AsyncClient() as client:
        step3 = await _step_go2rtc_api(client)
        steps.append(step3)
        if step3["status"] == "PASS":
            steps.append(await _step_go2rtc_stream_known(client, stream_name))
            steps.append(await _step_go2rtc_producer_alive(client, stream_name))
        else:
            steps.append(_step("go2rtc_stream_known", "SKIP",
                               detail="Go2RTC API injoignable — étapes suivantes ignorées."))
            steps.append(_step("go2rtc_producer_alive", "SKIP",
                               detail="Go2RTC API injoignable — étapes suivantes ignorées."))

    # Étape 6 : Compat HEVC/WebRTC
    steps.append(_step_hevc_webrtc_compat(cam, probe_info))

    return {
        "camera_id": camera_id,
        "camera_name": cam.get("name"),
        "stream_mode": cam.get("stream_mode", "auto"),
        "go2rtc_url": GO2RTC_URL,
        "stream_name": stream_name,
        "steps": steps,
        "verdict": _global_verdict(steps),
    }
