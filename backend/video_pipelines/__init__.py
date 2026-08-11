"""MG-VMS · video-pipeline-v2 — couche vidéo à 3 pipelines indépendants.

    CAMÉRA IP ── RTSP
       ├─► direct_rtsp : consommateurs RTSP natifs (probe réel, pas de preview navigateur)
       ├─► mjpeg       : broker ffmpeg partagé → HTTP multipart → <img>
       └─► mediamtx    : MediaMTX (paths dynamiques) → WebRTC WHEP / RTSP

Aucun pipeline ne dépend de Go2RTC. Go2RTC = legacy isolé.
"""
from .base import (DEFAULT_PIPELINE, PIPELINES, resolve_pipeline,
                   video_status_payload)
