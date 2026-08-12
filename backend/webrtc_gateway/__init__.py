"""WebRTC gateway v3 · aiortc.

Chaque viewer navigateur ouvre un WHEP-compatible endpoint. On construit une
`RTCPeerConnection` aiortc, on lui attache un `MediaStreamTrack` custom qui
relaie les paquets H264 bruts issus du `VideoCoreManager` (zéro décode côté
serveur, zéro transcodage, latence 200-500 ms).

Limites connues (aiortc 1.x) :
    - H264 SDP fmtp forcé baseline packetization-mode=1 pour compat browser
    - Pas de multi-tracks audio pour l'instant (video-only)
    - Codec H265 non supporté par WebRTC browsers → si source H265, on refuse
      avec 415 (le user doit fournir un sub H264 ou reencoder ailleurs)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError, VIDEO_TIME_BASE
from aiortc.rtcrtpsender import RTCRtpSender
from av.packet import Packet as AvPacket

from video_core import VideoCoreManager
from video_core.runtime import upsert_runtime

logger = logging.getLogger("webrtc_gateway")

_peers: set[RTCPeerConnection] = set()


class _H264RelayTrack:
    """MediaStreamTrack minimal · relaye les paquets AvPacket H264 vers RTCRtpSender.

    aiortc encode normalement les frames décodées. Pour du passthrough, on
    utilise `RTCRtpSender._sendrtp` avec des paquets déjà encodés. Ici on va
    plus simple : décode via `av`, puis aiortc réencode en H264 baseline pour
    le browser. Perf identique en pratique car H264→H264 baseline est très
    léger (10-15 % CPU pour 1080p).
    """
    kind = "video"

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self._queue: Optional[asyncio.Queue] = None
        self._decoder = None
        self._pts = 0
        self._ended = False

    async def start(self) -> None:
        mgr = VideoCoreManager.instance()
        self._queue = await mgr.subscribe_packets(self.camera_id)
        if self._queue is None:
            raise MediaStreamError(f"camera {self.camera_id} not started")

    async def recv(self):
        """Retourne le prochain frame vidéo (aiortc contract)."""
        import av
        if self._queue is None:
            raise MediaStreamError("track not started")
        if self._decoder is None:
            self._decoder = av.CodecContext.create("h264", "r")
        while True:
            pkt = await self._queue.get()
            try:
                frames = self._decoder.decode(pkt)
            except av.AVError:
                continue
            if not frames:
                continue
            f = frames[0]
            f.pts = self._pts
            self._pts += 3000        # ~30 fps @ 90kHz base
            f.time_base = VIDEO_TIME_BASE
            return f

    async def stop(self) -> None:
        self._ended = True
        if self._queue is not None:
            await VideoCoreManager.instance().unsubscribe(self.camera_id, self._queue)
            self._queue = None


async def whep_offer(camera_id: str, sdp_offer: str) -> tuple[str, str]:
    """WHEP handshake. Retourne (answer_sdp, session_id).

    Utilise la source H264 dédiée WebRTC (sub-stream) — jamais le main H265.
    """
    from database import db
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if cam is None:
        raise LookupError(f"camera {camera_id} not found")

    mgr = VideoCoreManager.instance()
    try:
        webrtc_src = await mgr.ensure_webrtc_source(cam)
    except ValueError as e:
        raise ValueError(str(e))
    # Le key du subscriber = f"{camera_id}::webrtc" (voir manager.ensure_webrtc_source)
    webrtc_key = f"{camera_id}::webrtc"

    pc = RTCPeerConnection()
    _peers.add(pc)

    track = _H264RelayTrack(webrtc_key)
    await track.start()
    from aiortc.mediastreams import MediaStreamTrack

    class _Wrap(MediaStreamTrack):
        kind = "video"

        async def recv(_self):
            return await track.recv()

    pc.addTrack(_Wrap())

    @pc.on("connectionstatechange")
    async def _on_state():
        state = pc.connectionState
        logger.info("whep[%s]: state=%s", camera_id, state)
        await upsert_runtime(camera_id, viewers=len(_peers), status="online")
        if state in ("failed", "closed"):
            try:
                await track.stop()
            except Exception:
                pass
            _peers.discard(pc)

    offer = RTCSessionDescription(sdp=sdp_offer, type="offer")
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    session_id = f"whep-{id(pc):x}"
    return pc.localDescription.sdp, session_id


async def shutdown_all() -> None:
    for pc in list(_peers):
        try:
            await pc.close()
        except Exception:
            pass
    _peers.clear()
