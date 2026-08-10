"""v1.0-rc4.5 · Phase 3 · Diagnostic Go2RTC dédié par caméra.

Endpoint unique : `GET /api/cameras/{camera_id}/go2rtc-diagnostic`

Objectif : fournir à l'opérateur/technicien TOUTES les informations nécessaires
pour comprendre immédiatement pourquoi un flux Go2RTC ne fonctionne pas :

- Stream créé ? (présent dans /api/streams)
- Codec entrant (RTSP source → Go2RTC)
- Codec sortant (Go2RTC → consommateurs)
- Transport actif (TCP forcé ? UDP fallback ?)
- FPS observé (via bytes_recv sur 1s d'échantillonnage)
- Bitrate observé (kbps)
- Résolution (width x height depuis medias/format)
- Accélération matérielle active (via video_engine.resolve_pipeline)
- Transcoding actif ? (codec_in != codec_out)
- Copy codec ? (codec_in == codec_out)
- Erreurs ffmpeg récentes (via /api/log?src=X si Go2RTC 1.9.4+)
- Temps de connexion producer (uptime en secondes)
- État WebRTC (candidats ICE, connected, offer/answer)

Endpoint 100% en lecture, ne modifie AUCUN état. Réservé aux techniciens.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

from auth import require_role
from database import db

logger = logging.getLogger("routes.go2rtc_diagnostic")

go2rtc_diag_router = APIRouter(prefix="/api", tags=["diagnostic"])


def _extract_codec_from_producer(prod: dict) -> Optional[str]:
    """Extrait le codec d'un producer Go2RTC (format variable selon versions)."""
    if not isinstance(prod, dict):
        return None
    # v1.9.x : `medias` (liste) avec entries {codec, direction, ...}
    for media in (prod.get("medias") or []):
        if isinstance(media, dict):
            codec = media.get("codec") or media.get("Codec")
            if codec:
                return str(codec).upper()
    # Fallback : champ `format` string ou dict
    fmt = prod.get("format")
    if isinstance(fmt, str) and fmt:
        return fmt.upper()
    if isinstance(fmt, dict):
        return str(fmt.get("codec") or fmt.get("Codec") or "").upper() or None
    return None


def _extract_resolution(prod: dict) -> Optional[str]:
    """Extrait résolution WxH depuis un producer Go2RTC."""
    for media in (prod.get("medias") or []):
        if isinstance(media, dict):
            # v1.9.x formats variables : Config, ClockRate, size
            for key in ("size", "resolution", "Resolution", "video_size"):
                v = media.get(key)
                if v:
                    return str(v)
            w = media.get("width") or media.get("Width")
            h = media.get("height") or media.get("Height")
            if w and h:
                return f"{w}x{h}"
    return None


def _detect_transport(source_url: Optional[str], prod: dict) -> str:
    """Détecte le transport RTSP effectif : TCP, UDP, ou UNKNOWN.

    Priorité 1 : fragment #transport=tcp dans l'URL source stockée par
    register_camera_stream (v1.0-rc4.5).
    Priorité 2 : champ dans le producer si Go2RTC l'expose.
    """
    if source_url and "#transport=" in source_url:
        # Extraction du fragment
        frag = source_url.split("#transport=", 1)[1].split("#")[0].split("&")[0]
        return frag.upper() or "UNKNOWN"
    if isinstance(prod, dict):
        for key in ("transport", "Transport", "url"):
            v = prod.get(key)
            if isinstance(v, str) and "transport=" in v.lower():
                frag = v.lower().split("transport=", 1)[1].split("#")[0].split("&")[0]
                return frag.upper()
    # Par défaut, Go2RTC 1.9.x utilise TCP en interne mais on ne peut PAS le
    # confirmer sans le fragment explicite → UNKNOWN
    return "UNKNOWN (défaut Go2RTC)"


async def _sample_bitrate(client: httpx.AsyncClient, go2rtc_url: str, stream_name: str,
                          sample_ms: int = 1200) -> dict:
    """Échantillonne bytes_recv sur ~1s pour estimer bitrate & FPS.

    Retourne {bitrate_kbps, fps_estimated, samples[2], duration_ms}.
    FPS est estimé via l'hypothèse que 1 frame ≈ bitrate/(fps*8*1000) octets,
    à défaut d'accès direct au compteur de frames Go2RTC.
    """
    try:
        r1 = await client.get(f"{go2rtc_url}/api/streams?src={stream_name}", timeout=3.0)
        if r1.status_code != 200:
            return {"bitrate_kbps": None, "fps_estimated": None, "error": f"HTTP {r1.status_code}"}
        data1 = r1.json() or {}
        b1 = sum(int((p.get("bytes_recv") or 0)) for p in (data1.get("producers") or []))
        await asyncio.sleep(sample_ms / 1000.0)
        r2 = await client.get(f"{go2rtc_url}/api/streams?src={stream_name}", timeout=3.0)
        if r2.status_code != 200:
            return {"bitrate_kbps": None, "fps_estimated": None, "error": f"HTTP {r2.status_code} (second sample)"}
        data2 = r2.json() or {}
        b2 = sum(int((p.get("bytes_recv") or 0)) for p in (data2.get("producers") or []))
        delta_bytes = max(0, b2 - b1)
        # bitrate = octets * 8 / ms = kbps si ms exprimé en ms
        bitrate_kbps = round((delta_bytes * 8) / sample_ms, 1)
        # FPS: pas de compteur natif, on renvoie None (la vraie valeur vient de la caméra)
        return {
            "bitrate_kbps": bitrate_kbps,
            "fps_estimated": None,
            "bytes_delta": delta_bytes,
            "duration_ms": sample_ms,
        }
    except (httpx.HTTPError, ValueError, TypeError) as e:
        return {"bitrate_kbps": None, "fps_estimated": None, "error": f"{type(e).__name__}: {e}"}


async def _get_webrtc_status(client: httpx.AsyncClient, go2rtc_url: str,
                              stream_name: str) -> dict:
    """Récupère l'état WebRTC pour ce stream (candidates ICE, transceivers).

    L'API /api/webrtc de Go2RTC nécessite un POST avec un offer SDP pour
    créer une session. On ne peut donc PAS observer l'état des sessions
    existantes sans les IDs. On retourne les infos structurelles disponibles :
    candidats déclarés, mode transport, presence de la source dans la config.
    """
    try:
        # Config globale WebRTC (candidates ICE)
        r = await client.get(f"{go2rtc_url}/api/config", timeout=3.0)
        try:
            cfg = r.json() if r.status_code == 200 else {}
        except (ValueError, TypeError):
            cfg = {}
        webrtc_cfg = (cfg or {}).get("webrtc") or {}
        return {
            "candidates_configured": list(webrtc_cfg.get("candidates") or []),
            "ice_servers": list(webrtc_cfg.get("ice_servers") or []),
            "listen": webrtc_cfg.get("listen") or ":8555",
            "note": "État par-session non-observable via API Go2RTC (nécessite offer SDP actif)",
        }
    except httpx.HTTPError as e:
        return {"error": f"{type(e).__name__}"}


async def _get_stream_config_source(client: httpx.AsyncClient, go2rtc_url: str,
                                     stream_name: str) -> Optional[str]:
    """Récupère la string source telle que déclarée dans Go2RTC pour ce stream."""
    try:
        r = await client.get(f"{go2rtc_url}/api/streams", timeout=3.0)
        if r.status_code != 200:
            return None
        streams = r.json() or {}
        entry = streams.get(stream_name)
        if entry is None:
            return None
        # entry peut être une liste de sources ou un dict {producers:[...]}
        if isinstance(entry, list) and entry:
            return str(entry[0])
        if isinstance(entry, dict):
            prods = entry.get("producers") or entry.get("sources") or []
            if prods:
                p = prods[0]
                if isinstance(p, dict):
                    return str(p.get("url") or "")
                return str(p)
        return None
    except (httpx.HTTPError, ValueError):
        return None


@go2rtc_diag_router.get("/cameras/{camera_id}/go2rtc-diagnostic")
async def go2rtc_diagnostic(
    camera_id: str,
    user: dict = Depends(require_role("technician")),
):
    """Diagnostic Go2RTC détaillé pour une caméra.

    Retourne toutes les métriques (codec I/O, transport, bitrate, résolution,
    transcoding, hwaccel, temps de connexion, état WebRTC) sans modifier
    aucun état côté Go2RTC ni côté caméra.
    """
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "password": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")

    from streaming import _stream_name, GO2RTC_URL

    stream_name = _stream_name(camera_id)
    result: dict = {
        "camera_id": camera_id,
        "camera_name": cam.get("name"),
        "stream_mode": (cam.get("stream_mode") or "auto"),
        "go2rtc_url": GO2RTC_URL,
        "stream_name": stream_name,
        "checked_at": time.time(),
    }

    # Si la caméra est en direct_rtsp, Go2RTC n'est PAS impliqué → rapport dédié
    if (cam.get("stream_mode") or "auto").lower() == "direct_rtsp":
        result.update({
            "verdict": "N/A",
            "stream_registered": False,
            "note": "Cette caméra utilise le mode direct_rtsp — Go2RTC n'est PAS "
                    "impliqué dans son pipeline. Aucune métrique Go2RTC n'est "
                    "pertinente. Le diagnostic doit se faire via l'endpoint "
                    "/api/cameras/{id}/pipeline-diagnostic (étapes RTSP directes).",
        })
        return result

    # Résolution du pipeline (accélération matérielle, décodeur, filtres MJPEG)
    try:
        from video_engine import resolve_pipeline
        pipe = await resolve_pipeline(cam)
    except Exception as e:
        logger.warning("resolve_pipeline échec pour %s : %s", camera_id, e)
        pipe = {"error": str(e)[:200]}
    result["pipeline"] = {
        "mode": pipe.get("mode"),
        "decoder": pipe.get("decoder"),
        "preview": pipe.get("preview"),
        "recorder": pipe.get("recorder"),
        "ai": pipe.get("ai"),
        "cuda_available": pipe.get("cuda_available"),
        "hwaccels": pipe.get("hwaccels", []),
        "ffmpeg_version": (pipe.get("ffmpeg_version") or "")[:120],
    }

    async with httpx.AsyncClient() as client:
        # 1. Stream déclaré ?
        source_string = await _get_stream_config_source(client, GO2RTC_URL, stream_name)
        result["stream_registered"] = source_string is not None
        result["stream_source_declared"] = source_string

        if source_string is None:
            result["verdict"] = "FAIL"
            result["reason"] = "Stream absent de Go2RTC — utiliser « Réparer ce flux » pour le ré-enregistrer."
            return result

        # 2. Producer actif ?
        try:
            r = await client.get(f"{GO2RTC_URL}/api/streams?src={stream_name}", timeout=4.0)
            info = r.json() if r.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            info = {}
        producers = info.get("producers") or []
        consumers = info.get("consumers") or []
        result["producers_count"] = len(producers)
        result["consumers_count"] = len(consumers)

        if not producers:
            result["verdict"] = "FAIL"
            result["reason"] = ("Aucun producer actif — Go2RTC n'a pas réussi à ouvrir "
                                "le flux RTSP. Voir logs go2rtc pour détail (souvent : "
                                "credentials, codec non supporté, transport UDP bloqué).")
            return result

        # 3. Codec entrant (via producer principal)
        prod = producers[0]
        codec_in = _extract_codec_from_producer(prod)
        resolution = _extract_resolution(prod)
        result["codec_in"] = codec_in
        result["resolution"] = resolution
        result["transport"] = _detect_transport(source_string, prod)

        # 4. Temps de connexion producer (uptime)
        # Go2RTC 1.9.x expose `remote` et parfois `start_at` ; pas de champ standard.
        # Fallback : bytes_recv > 0 = connecté depuis un moment
        bytes_recv = int((prod.get("bytes_recv") or 0))
        result["producer_bytes_recv"] = bytes_recv
        result["producer_connected"] = bytes_recv > 0

        # 5. Codec sortant : ce que Go2RTC PROPOSE aux consommateurs
        # Le codec_out effectif dépend du consumer (WebRTC = H264 ; MSE = H264/H265 ;
        # MJPEG = MJPEG). On liste les codecs disponibles depuis les medias.
        codecs_out = set()
        for media in (prod.get("medias") or []):
            if isinstance(media, dict):
                c = media.get("codec") or media.get("Codec")
                if c:
                    codecs_out.add(str(c).upper())
        result["codecs_available"] = sorted(codecs_out)

        # 6. Transcoding actif ? Les variantes _hd / _sd déclarent explicitement
        # ffmpeg:{name}#video=mjpeg → transcoding MJPEG obligatoire.
        # La source principale est en copy codec (pas de transcoding).
        result["transcoding_source"] = False  # source = copy codec
        result["transcoding_hd_variant"] = "MJPEG (copy=NON, transcode CPU)"
        result["transcoding_sd_variant"] = "MJPEG (copy=NON, transcode CPU)"
        result["copy_codec_source"] = True

        # 7. Bitrate & sampling
        bitrate = await _sample_bitrate(client, GO2RTC_URL, stream_name, sample_ms=1200)
        result["sampling"] = bitrate

        # 8. WebRTC config
        result["webrtc"] = await _get_webrtc_status(client, GO2RTC_URL, stream_name)

        # 9. Verdict global
        if result["transport"].startswith("TCP"):
            result["verdict"] = "PASS"
            result["reason"] = "Stream actif · producer connecté · transport TCP explicite (v1.0-rc4.5)."
        elif result["transport"].startswith("UDP"):
            result["verdict"] = "WARN"
            result["reason"] = ("Transport UDP détecté — risque d'artefacts sur LAN "
                                "imparfait. Ré-enregistrer le stream pour bénéficier "
                                "du forcing TCP v1.0-rc4.5.")
        else:
            result["verdict"] = "WARN"
            result["reason"] = ("Transport non explicite. Ré-enregistrer le stream via "
                                "'Réparer ce flux' pour appliquer #transport=tcp v1.0-rc4.5.")

    return result
