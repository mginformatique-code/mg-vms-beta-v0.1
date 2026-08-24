"""WebRTC gateway v3.

Deux chemins, dans cet ordre :

1. **Passthrough natif go2rtc (v3.8, chemin normal).** L'offre SDP du
   navigateur est relayée telle quelle à `go2rtc /api/webrtc`, qui renvoie
   la réponse. Le H264 de la caméra part vers le navigateur SANS être
   décodé ni réencodé : le serveur ne fait plus aucun travail vidéo, et
   c'est le décodeur MATÉRIEL du poste client qui affiche le flux.
   Vérifié en conditions réelles : codec négocié `H264/90000`, 108 images
   reçues en 8 s.

2. **Pont aiortc (repli historique).** Conservé si go2rtc est indisponible.
   ⚠ Malgré ce que prétendait le commentaire d'origine ("zéro décode côté
   serveur, zéro transcodage"), ce chemin DÉCODE puis RÉENCODE en Python
   (voir `_H264RelayTrack`, dont la docstring le dit explicitement), dans
   le process qui sert aussi l'API. C'est précisément ce qui provoquait les
   « Délai de connexion WebRTC dépassé » sur les flux un peu lourds.

Limites connues du repli aiortc :
    - H264 SDP fmtp forcé baseline packetization-mode=1 pour compat browser
    - Pas de multi-tracks audio pour l'instant (video-only)
    - Codec H265 non supporté par WebRTC browsers → si source H265, on refuse
      avec 415 (le user doit fournir un sub H264 ou reencoder ailleurs)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

import httpx

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


async def _whep_via_go2rtc(camera_id: str, sdp_offer: str,
                            prefer_hd: bool = False,
                            main_codec: str = "") -> Optional[str]:
    """Relaie l'offre SDP à go2rtc et renvoie sa réponse (ou None).

    C'est le vrai passthrough : go2rtc réémet le H264 de la caméra sans le
    toucher, le navigateur le décode en matériel. Aucune charge vidéo côté
    serveur, contrairement au pont aiortc plus bas.

    Choix de la source :
      - par défaut, la variante `_preview` (sous-flux) : légère, et toujours
        en H264 même quand le flux principal est en HEVC ;
      - `prefer_hd` (bouton HD du mur vidéo) → flux principal, MAIS
        uniquement s'il est en H264 : WebRTC ne sait pas transporter du HEVC
        vers un navigateur, une caméra HEVC reste donc sur le sous-flux
        (mieux vaut une image fluide qu'un flux qui ne démarre pas).
    """
    try:
        from streaming import GO2RTC_URL, _stream_name, _stream_registered
        name = _stream_name(camera_id)
        codec = (main_codec or "").lower()
        hd_possible = prefer_hd and codec in ("h264", "avc", "")
        if hd_possible and await _stream_registered(name):
            src = name
        else:
            src = f"{name}_preview"
            if not await _stream_registered(src):
                src = name
            if prefer_hd and not hd_possible:
                logger.info("whep[%s]: HD demandé mais flux principal en %s — "
                            "WebRTC ne transporte pas ce codec, on reste sur le sous-flux",
                            camera_id, codec or "?")
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{GO2RTC_URL}/api/webrtc", params={"src": src},
                                   content=sdp_offer,
                                   headers={"Content-Type": "application/sdp"})
        # go2rtc répond 201 Created (pas 200) sur un handshake réussi.
        if r.status_code in (200, 201) and "v=0" in r.text:
            logger.info("whep[%s]: passthrough go2rtc via %s", camera_id, src)
            return r.text
        logger.warning("whep[%s]: go2rtc a refusé (%s) — repli sur le pont aiortc",
                        camera_id, r.status_code)
    except Exception as e:
        logger.warning("whep[%s]: go2rtc indisponible (%s) — repli sur le pont aiortc",
                        camera_id, e)
    return None


async def whep_offer(camera_id: str, sdp_offer: str,
                      prefer_hd: bool = False) -> tuple[str, str]:
    """WHEP handshake. Retourne (answer_sdp, session_id).

    Passthrough go2rtc en priorité (aucun transcodage), pont aiortc en repli.
    ``prefer_hd`` = bouton HD/SD du mur vidéo.
    """
    from database import db
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if cam is None:
        raise LookupError(f"camera {camera_id} not found")

    codec = str(cam.get("codec") or "")
    answer = await _whep_via_go2rtc(camera_id, sdp_offer, prefer_hd=prefer_hd,
                                     main_codec=codec)
    if answer:
        await upsert_runtime(camera_id, status="online")
        # Indique au client si le HD demandé n'a PAS pu être servi, pour qu'il
        # l'affiche au lieu de laisser croire à un bouton cassé.
        forced = prefer_hd and codec.lower() not in ("h264", "avc", "")
        session = f"whep-g2r-{uuid.uuid4().hex[:12]}"
        return answer, (f"{session}|sd_forced_{codec.lower()}" if forced else session)

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
