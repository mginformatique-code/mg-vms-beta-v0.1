"""video-pipeline-v2 · PIPELINE 1 — DIRECT RTSP.

Pour les consommateurs compatibles RTSP (VLC, NVR, moteur IA MG-VMS).
Un navigateur ne lit PAS le RTSP directement : ce pipeline ne prétend
JAMAIS fournir une preview navigateur. Le frontend affiche honnêtement
DISPONIBLE / NON DISPONIBLE + l'URL RTSP masquée.

Statut = vrai test RTSP :
- TCP connect (temps de connexion mesuré)
- DESCRIBE ffprobe léger, mis en cache 30 s (évite d'épuiser les sessions
  RTSP des caméras qui les limitent — Reolink & co).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Optional

from .base import camera_source_url, video_status_payload

logger = logging.getLogger("video.direct_rtsp")

_PROBE_TTL = 30.0
_probe_cache: dict[str, tuple[float, dict]] = {}


def masked_url(cam: dict) -> str:
    url = camera_source_url(cam)
    return re.sub(r"(rtsp://[^:@/]+):([^@/]+)@", r"\1:******@", url, count=1,
                  flags=re.IGNORECASE)


def tcp_target(cam: dict) -> Optional[tuple]:
    url = camera_source_url(cam)
    m = re.match(r"^rtsp://(?:[^@/]*@)?([^:/?#]+)(?::(\d+))?", url, re.IGNORECASE)
    return (m.group(1), int(m.group(2) or 554)) if m else None


async def _ffprobe_describe(url: str, timeout: float = 8.0) -> dict:
    """DESCRIBE réel via ffprobe (TCP). Retourne codec/résolution/fps ou erreur classée."""
    cmd = ["ffprobe", "-v", "error", "-rtsp_transport", "tcp",
           "-select_streams", "v:0",
           "-show_entries", "stream=codec_name,width,height,avg_frame_rate",
           "-of", "json", url]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return {"ok": False, "error": "timeout RTSP (DESCRIBE sans réponse)"}
    if proc.returncode != 0:
        text = (err or b"").decode(errors="replace")
        if "401" in text or "unauthorized" in text.lower():
            return {"ok": False, "error": "401 Unauthorized (identifiants RTSP refusés)"}
        if "404" in text or "not found" in text.lower():
            return {"ok": False, "error": "404 chemin RTSP introuvable"}
        if "connection refused" in text.lower():
            return {"ok": False, "error": "connexion refusée (port RTSP fermé)"}
        return {"ok": False, "error": (text.strip().splitlines() or ["échec RTSP"])[-1][:160]}
    try:
        streams = (json.loads(out or b"{}").get("streams") or [{}])[0]
    except ValueError:
        streams = {}
    fps = None
    afr = streams.get("avg_frame_rate") or ""
    if "/" in afr:
        num, den = afr.split("/", 1)
        try:
            fps = round(int(num) / int(den), 1) if int(den) else None
        except ValueError:
            pass
    return {"ok": True, "codec": streams.get("codec_name"),
            "resolution": (f"{streams.get('width')}x{streams.get('height')}"
                           if streams.get("width") else None),
            "fps": fps}


async def probe(cam: dict, *, use_cache: bool = True) -> dict:
    """Probe RTSP complet (TCP + DESCRIBE), cache 30 s par caméra."""
    cam_id = cam["id"]
    now = time.monotonic()
    if use_cache:
        hit = _probe_cache.get(cam_id)
        if hit and now - hit[0] < _PROBE_TTL:
            return hit[1]
    url = camera_source_url(cam)
    if not url.lower().startswith("rtsp://"):
        result = {"available": False, "connect_ms": None,
                  "error": "aucune URL RTSP configurée"}
        _probe_cache[cam_id] = (now, result)
        return result
    target = tcp_target(cam)
    connect_ms = None
    if target:
        t0 = time.monotonic()
        from streaming import _tcp_check
        ok = await asyncio.to_thread(_tcp_check, target[0], int(target[1]), 3.0)
        connect_ms = round((time.monotonic() - t0) * 1000, 1)
        if not ok:
            result = {"available": False, "connect_ms": connect_ms,
                      "error": f"caméra injoignable (TCP {target[0]}:{target[1]})"}
            _probe_cache[cam_id] = (now, result)
            return result
    d = await _ffprobe_describe(url)
    result = {"available": d["ok"], "connect_ms": connect_ms,
              "codec": d.get("codec"), "resolution": d.get("resolution"),
              "fps": d.get("fps"), "error": d.get("error")}
    _probe_cache[cam_id] = (time.monotonic(), result)
    return result


async def tcp_only_check(cam: dict) -> tuple[bool, str]:
    """Check léger pour la boucle de statut périodique (AUCUNE session RTSP)."""
    target = tcp_target(cam)
    if target is None:
        return True, ""
    from streaming import _tcp_check
    ok = await asyncio.to_thread(_tcp_check, target[0], int(target[1]), 3.0)
    return ok, ("" if ok else f"caméra injoignable (TCP {target[0]}:{target[1]})")


async def get_status(cam: dict) -> dict:
    p = await probe(cam)
    return video_status_payload(
        cam["id"], "direct_rtsp",
        status="online" if p["available"] else "offline",
        codec=p.get("codec"), fps=p.get("fps"),
        latency_ms=p.get("connect_ms"),
        error=p.get("error"),
        extra={"browser_playable": False,
               "note": "direct_rtsp est destiné aux consommateurs RTSP "
                       "(VLC, NVR, IA) — pas de preview navigateur",
               "rtsp_url_masked": masked_url(cam),
               "resolution": p.get("resolution")})
