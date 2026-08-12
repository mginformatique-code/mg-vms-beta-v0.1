"""Video Core · Manager central (singleton).

Cycle typique :
    manager = VideoCoreManager.instance()
    await manager.ensure_camera(cam_doc)       # démarre la source RTSP
    queue = await manager.subscribe_packets(camera_id)
    async for pkt in ...                        # WebRTC / Recorder
    await manager.unsubscribe(camera_id, queue)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .rtsp_source import RtspSource

logger = logging.getLogger("video_core.manager")


class VideoCoreManager:
    _INSTANCE: Optional["VideoCoreManager"] = None

    def __init__(self) -> None:
        self._sources: dict[str, RtspSource] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def instance(cls) -> "VideoCoreManager":
        if cls._INSTANCE is None:
            cls._INSTANCE = cls()
        return cls._INSTANCE

    @staticmethod
    def _rtsp_url_of(cam: dict) -> str:
        """URL RTSP à utiliser pour cette caméra (creds injectés)."""
        url = (cam.get("rtsp_url") or "").strip()
        if url.lower().startswith(("rtsp://", "rtsps://")):
            # Injection creds si absentes et disponibles séparément
            if "@" not in url and cam.get("username"):
                from streaming import _build_rtsp_url
                return _build_rtsp_url(cam)
            return url
        from streaming import _build_rtsp_url
        return _build_rtsp_url(cam)

    @staticmethod
    def _webrtc_rtsp_url_of(cam: dict) -> str:
        """URL RTSP à utiliser pour WHEP navigateur (H264 obligatoire).

        Priorité : `webrtc_rtsp_url` (sub H264) > `rtsp_url` (si déjà H264).
        Retourne "" si aucun H264 dispo → WHEP refusera avec 415.
        """
        sub = (cam.get("webrtc_rtsp_url") or "").strip()
        if sub.lower().startswith(("rtsp://", "rtsps://")):
            return sub
        codec = str(cam.get("codec") or "").lower()
        if codec in ("h264", ""):
            return VideoCoreManager._rtsp_url_of(cam)
        return ""

    async def ensure_camera(self, cam: dict) -> RtspSource:
        """Démarre (ou renvoie) LA source RTSP principale (main) pour cette caméra.

        Utilisée par recorder + AI (H264 ou H265 acceptés, décodage en aval).
        Le WebRTC utilise une source séparée via `ensure_webrtc_source`.
        """
        cam_id = cam.get("id") or ""
        if not cam_id:
            raise ValueError("camera without id")
        async with self._lock:
            src = self._sources.get(cam_id)
            new_url = self._rtsp_url_of(cam)
            if src is not None and src.rtsp_url == new_url:
                return src
            # URL changée ou pas encore d'instance → recycle
            if src is not None:
                logger.info("video_core: %s URL changed, restarting", cam_id)
                await src.stop()
            src = RtspSource(cam_id, new_url)
            self._sources[cam_id] = src
            src.start()
            return src

    async def ensure_webrtc_source(self, cam: dict) -> RtspSource:
        """Source dédiée WHEP navigateur (H264 obligatoire, sub-stream)."""
        cam_id = cam.get("id") or ""
        webrtc_url = self._webrtc_rtsp_url_of(cam)
        if not webrtc_url:
            raise ValueError(
                "Aucune source H264 disponible pour WebRTC — "
                "renseignez `webrtc_rtsp_url` (sub-stream H264) sur la caméra")
        webrtc_key = f"{cam_id}::webrtc"
        async with self._lock:
            src = self._sources.get(webrtc_key)
            if src is not None and src.rtsp_url == webrtc_url:
                return src
            if src is not None:
                await src.stop()
            src = RtspSource(webrtc_key, webrtc_url)
            self._sources[webrtc_key] = src
            src.start()
            return src

    async def stop_camera(self, camera_id: str) -> None:
        async with self._lock:
            src = self._sources.pop(camera_id, None)
        if src is not None:
            await src.stop()

    def get_source(self, camera_id: str) -> Optional[RtspSource]:
        return self._sources.get(camera_id)

    async def subscribe_packets(self, camera_id: str) -> Optional[asyncio.Queue]:
        src = self._sources.get(camera_id)
        if src is None:
            return None
        return src.subscribe_packets()

    async def unsubscribe(self, camera_id: str, queue: asyncio.Queue) -> None:
        src = self._sources.get(camera_id)
        if src:
            src.unsubscribe_packets(queue)

    def list_cameras(self) -> list[str]:
        return list(self._sources.keys())
