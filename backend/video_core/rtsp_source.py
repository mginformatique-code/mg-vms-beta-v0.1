"""Video Core · RTSP source (PyAV) → distribution multi-consommateurs.

Une seule instance RtspSource par caméra. Elle :
    - Ouvre l'input RTSP en TCP (via PyAV/libav)
    - Décapsule les paquets H264/H265 sans les décoder (passthrough recorder/WebRTC)
    - Décode 1 frame tous les N pour l'IA (frame skipping intelligent)
    - Reconnecte automatiquement sur EOF/erreur (backoff exponentiel 1→30 s)
    - Publie ses métriques dans `camera_runtime`

Consumers :
    - packet queues (asyncio.Queue) pour Recorder / WebRTC (H264 brut)
    - decoded frame queue pour l'IA (résolution ↓ pour perf)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

try:
    import av  # PyAV — bindings libav
except ImportError:      # pragma: no cover
    av = None            # type: ignore

from .runtime import upsert_runtime, mark_offline

logger = logging.getLogger("video_core.rtsp")

_BACKOFF_START = 1.0
_BACKOFF_MAX = 30.0
_AI_TARGET_FPS = 15
_MAX_PACKET_QUEUE = 60      # ~2 s de vidéo à 30 fps · évite l'accumulation


class RtspSource:
    def __init__(self, camera_id: str, rtsp_url: str):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self._packet_queues: list[asyncio.Queue] = []
        self._task: Optional[asyncio.Task] = None
        self._stop_evt = asyncio.Event()
        self.codec: str = ""
        self.width: int = 0
        self.height: int = 0
        self.fps: float = 0.0
        self.last_frame_at: float = 0.0
        self._pack_count = 0

    # ── Consommateur API ────────────────────────────────────────────────
    def subscribe_packets(self) -> asyncio.Queue:
        """Retourne une queue asyncio recevant les `av.Packet` H264/H265 bruts."""
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_PACKET_QUEUE)
        self._packet_queues.append(q)
        return q

    def unsubscribe_packets(self, q: asyncio.Queue) -> None:
        try:
            self._packet_queues.remove(q)
        except ValueError:
            pass

    # ── Lifecycle ──────────────────────────────────────────────────────
    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_evt.clear()
        self._task = asyncio.create_task(self._run(), name=f"rtsp-{self.camera_id}")

    async def stop(self) -> None:
        self._stop_evt.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        await mark_offline(self.camera_id, "stopped")

    # ── Boucle principale ─────────────────────────────────────────────
    async def _run(self) -> None:
        if av is None:
            logger.error("PyAV non installé — RtspSource inactif")
            await mark_offline(self.camera_id, "pyav_missing")
            return
        backoff = _BACKOFF_START
        while not self._stop_evt.is_set():
            try:
                await self._session()
                backoff = _BACKOFF_START     # reset après session propre
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("rtsp[%s]: session error → retry in %.1fs · %s",
                                self.camera_id, backoff, e)
                await mark_offline(self.camera_id, f"{type(e).__name__}: {e}")
                await asyncio.sleep(backoff)
                backoff = min(_BACKOFF_MAX, backoff * 2)

    async def _session(self) -> None:
        """UNE session RTSP : open → boucle packets → cleanup."""
        options = {
            "rtsp_transport": "tcp",
            "stimeout": "10000000",     # 10 s (µs) — hard timeout socket
            "rw_timeout": "10000000",
            "buffer_size": "1000000",
        }
        # PyAV `av.open` est bloquant → thread offload
        container = await asyncio.to_thread(av.open, self.rtsp_url, options=options,
                                             timeout=10)
        try:
            v_stream = next((s for s in container.streams if s.type == "video"), None)
            if v_stream is None:
                raise RuntimeError("no video stream in RTSP")
            self.codec = str(v_stream.codec_context.name or "").lower()
            self.width = int(v_stream.codec_context.width or 0)
            self.height = int(v_stream.codec_context.height or 0)
            r = v_stream.average_rate
            self.fps = float(r) if r else 0.0
            await upsert_runtime(self.camera_id, status="online", codec=self.codec,
                                  width=self.width, height=self.height, fps=self.fps,
                                  decoder="none", gpu=False,
                                  last_error="")
            self._pack_count = 0
            last_stats = time.monotonic()

            # Boucle packets — PyAV demux dans un thread, forward vers queues
            def _demux_iter():
                for pkt in container.demux(v_stream):
                    if self._stop_evt.is_set():
                        break
                    yield pkt

            loop = asyncio.get_running_loop()
            # On lit paquet par paquet en offload thread pour ne pas bloquer l'event loop
            gen = _demux_iter()
            while not self._stop_evt.is_set():
                pkt = await asyncio.to_thread(next, gen, None)
                if pkt is None:
                    raise EOFError("RTSP stream ended")
                if pkt.dts is None:
                    continue
                self._pack_count += 1
                self.last_frame_at = time.monotonic()
                # Fanout non-bloquant : si queue pleine (consumer lent) → drop
                for q in list(self._packet_queues):
                    try:
                        q.put_nowait(pkt)
                    except asyncio.QueueFull:
                        # Consommateur en retard : on drop pour ne pas s'accumuler
                        pass
                # Stats runtime toutes les 5 s
                now = time.monotonic()
                if now - last_stats >= 5.0:
                    await upsert_runtime(self.camera_id, status="online",
                                          fps=round(self._pack_count / (now - last_stats), 1),
                                          last_frame=self.last_frame_at,
                                          viewers=len(self._packet_queues))
                    self._pack_count = 0
                    last_stats = now
        finally:
            await asyncio.to_thread(container.close)
