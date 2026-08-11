"""video-pipeline-v2 · Contrat commun aux 3 pipelines."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

PIPELINES = ("direct_rtsp", "mjpeg", "mediamtx", "go2rtc")
DEFAULT_PIPELINE = "mediamtx"

# Mapping legacy → v2 (migration douce, champ historique stream_mode)
_LEGACY_MAP = {
    "direct_rtsp": "direct_rtsp",
    "go2rtc": "mediamtx",
    "auto": "mediamtx",
}


def resolve_pipeline(cam: dict) -> str:
    """Pipeline effectif d'une caméra. Source de vérité : `stream_pipeline`.
    Compat lecture : mappe l'ancien `stream_mode` si le champ v2 est absent."""
    p = (cam.get("stream_pipeline") or "").lower()
    if p in PIPELINES:
        return p
    legacy = (cam.get("stream_mode") or "auto").lower()
    return _LEGACY_MAP.get(legacy, DEFAULT_PIPELINE)


def camera_source_url(cam: dict, pipeline: Optional[str] = None) -> str:
    """URL RTSP source de la caméra (credentials injectés, jamais exposée au frontend).

    Si un `pipeline` est précisé, la surcharge dédiée est utilisée si renseignée :
        - "direct_rtsp" → cam["direct_rtsp_url"]
        - "mjpeg"       → cam["mjpeg_source_url"]
        - "mediamtx"    → cam["mediamtx_source_url"]
    Fallback : `rtsp_url` (avec credentials injectés via streaming._build_rtsp_url).
    Les caméras démo sont servies par le relais RTSP go2rtc legacy (mires locales).
    """
    import os
    cam_id = cam.get("id", "")
    if cam_id.startswith("demo-") or cam_id.startswith("demo_"):
        return f"{os.environ.get('GO2RTC_RTSP', 'rtsp://localhost:8554')}/cam_{cam_id}"
    override_field = {
        "direct_rtsp": "direct_rtsp_url",
        "mjpeg": "mjpeg_source_url",
        "mediamtx": "mediamtx_source_url",
    }.get((pipeline or "").lower())
    if override_field:
        override = (cam.get(override_field) or "").strip()
        if override.lower().startswith(("rtsp://", "rtsps://")):
            return override
    from streaming import _build_rtsp_url
    return _build_rtsp_url(cam)


def video_status_payload(camera_id: str, pipeline: str, *,
                          status: str,
                          source: str = "rtsp",
                          codec: Optional[str] = None,
                          fps: Optional[float] = None,
                          last_frame_at: Optional[str] = None,
                          latency_ms: Optional[float] = None,
                          error: Optional[str] = None,
                          extra: Optional[dict] = None) -> dict:
    """Contrat JSON UNIQUE des 3 pipelines — GET /api/cameras/{id}/video-status."""
    out = {
        "camera_id": camera_id,
        "pipeline": pipeline,
        "status": status,           # online | offline | starting | unavailable
        "source": source,
        "codec": codec,
        "fps": fps,
        "last_frame_at": last_frame_at,
        "latency_ms": latency_ms,
        "error": error,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        out.update(extra)
    return out
