"""video-pipeline-v2 · PIPELINE 2 — MJPEG simple et indépendant.

    RTSP caméra ─► 1 ffmpeg PARTAGÉ par caméra ─► dernière frame JPEG en mémoire
                                                    │
                                     fanout HTTP multipart/x-mixed-replace ─► <img> × N viewers

Garanties :
- 1 seul processus ffmpeg par caméra, partagé entre tous les viewers.
- Fraîcheur d'abord : seule la DERNIÈRE frame est conservée ; un client lent
  saute des frames, il n'accumule JAMAIS de retard.
- RTSP TCP, timeout, reconnect backoff, watchdog, arrêt propre à 0 viewer.
- Résolution plafonnée + FPS limité (charge CPU maîtrisée).
- Zéro dépendance Go2RTC / MediaMTX.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("video.mjpeg")

_SOI = b"\xff\xd8\xff"
_EOI = b"\xff\xd9"
BOUNDARY = "mgvms-mjpeg-v2"

_MAX_FPS = int(os.environ.get("MGVMS_MJPEG_FPS", "10"))
_MAX_WIDTH = int(os.environ.get("MGVMS_MJPEG_MAX_WIDTH", "1280"))
_JPEG_QUALITY = int(os.environ.get("MGVMS_MJPEG_QUALITY", "6"))   # 2..15, petit = mieux
_RTSP_TIMEOUT_SEC = 15
_WATCHDOG_NO_FRAME_SEC = 20.0      # aucune frame → restart ffmpeg
_IDLE_STOP_SEC = 30.0              # 0 viewer pendant 30 s → arrêt du broker
_BACKOFF_START = 1.0
_BACKOFF_MAX = 10.0


def _ffmpeg_cmd(source_url: str) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-rtsp_transport", "tcp",
        "-timeout", str(_RTSP_TIMEOUT_SEC * 1_000_000),   # µs (options RTSP)
        "-fflags", "nobuffer", "-flags", "low_delay",
        "-i", source_url,
        "-an", "-sn",
        "-r", str(_MAX_FPS),
        "-vf", f"scale=min({_MAX_WIDTH}\\,iw):-2",
        "-q:v", str(_JPEG_QUALITY),
        "-f", "image2pipe", "-vcodec", "mjpeg",
        "pipe:1",
    ]


@dataclass
class _Broker:
    camera_id: str
    source_url: str
    proc: Optional[subprocess.Popen] = None
    thread: Optional[threading.Thread] = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    # Dernière frame uniquement (fraîcheur > accumulation)
    latest: Optional[bytes] = None
    seq: int = 0
    last_frame_ts: float = 0.0
    # Observabilité
    viewers: int = 0
    last_viewer_ts: float = field(default_factory=time.monotonic)
    restarts: int = 0
    frames_total: int = 0
    fps_window: list = field(default_factory=list)
    last_error: str = ""
    started_at: float = field(default_factory=time.monotonic)

    def fps(self) -> float:
        w = [t for t in self.fps_window if t >= time.monotonic() - 10.0]
        return round(len(w) / 10.0, 1) if len(w) >= 2 else 0.0


_brokers: dict[str, _Broker] = {}
_lock = threading.Lock()


def _reader_loop(b: _Broker) -> None:
    """Thread : ffmpeg RTSP → JPEG, garde uniquement la dernière frame,
    reconnect backoff + watchdog, s'arrête seul après _IDLE_STOP_SEC sans viewer."""
    backoff = _BACKOFF_START
    while not b.stop_event.is_set():
        try:
            b.proc = subprocess.Popen(_ffmpeg_cmd(b.source_url),
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, bufsize=0)
            b.restarts += 1
            logger.info("mjpeg[%s]: ffmpeg démarré (pid=%s, tentative #%d) src=%s",
                        b.camera_id, b.proc.pid, b.restarts,
                        b.source_url.split("@")[-1])
        except Exception as e:
            b.last_error = f"spawn: {e}"
            if b.stop_event.wait(backoff):
                break
            backoff = min(backoff * 1.5, _BACKOFF_MAX)
            continue

        threading.Thread(target=_drain_stderr, args=(b,), daemon=True).start()
        buf = b""
        last_read = time.monotonic()
        got_frame_this_run = False
        while not b.stop_event.is_set() and b.proc.poll() is None:
            # Arrêt auto : plus aucun viewer depuis _IDLE_STOP_SEC
            if b.viewers == 0 and time.monotonic() - b.last_viewer_ts > _IDLE_STOP_SEC:
                logger.info("mjpeg[%s]: 0 viewer depuis %.0fs — arrêt propre",
                            b.camera_id, _IDLE_STOP_SEC)
                b.stop_event.set()
                break
            try:
                chunk = b.proc.stdout.read(65536)
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            last_read = time.monotonic()
            while True:
                soi = buf.find(_SOI)
                if soi < 0:
                    buf = buf[-2:]
                    break
                eoi = buf.find(_EOI, soi + 3)
                if eoi < 0:
                    if soi > 0:
                        buf = buf[soi:]
                    break
                frame = buf[soi:eoi + 2]
                buf = buf[eoi + 2:]
                # Écriture atomique de la ref : les viewers lisent latest+seq
                b.latest = frame
                b.seq += 1
                b.last_frame_ts = time.monotonic()
                b.frames_total += 1
                got_frame_this_run = True
                now = time.monotonic()
                b.fps_window.append(now)
                if len(b.fps_window) > 300:
                    b.fps_window = [t for t in b.fps_window if t >= now - 10.0]
            # Watchdog : ffmpeg vivant mais aucune frame → restart
            if time.monotonic() - last_read > _WATCHDOG_NO_FRAME_SEC:
                b.last_error = "watchdog: aucune frame reçue"
                logger.warning("mjpeg[%s]: watchdog — restart ffmpeg", b.camera_id)
                break

        _kill_proc(b)
        rc = b.proc.returncode if b.proc else None
        if not got_frame_this_run:
            logger.warning("mjpeg[%s]: ffmpeg terminé rc=%s sans frame · stderr=%s",
                           b.camera_id, rc, b.last_error or "(vide)")
        if b.stop_event.is_set():
            break
        backoff = _BACKOFF_START if got_frame_this_run else min(backoff * 1.5, _BACKOFF_MAX)
        logger.info("mjpeg[%s]: reconnexion dans %.1fs", b.camera_id, backoff)
        if b.stop_event.wait(backoff):
            break
    _kill_proc(b)
    with _lock:
        if _brokers.get(b.camera_id) is b:
            _brokers.pop(b.camera_id, None)
    logger.info("mjpeg[%s]: broker terminé (%d frames, %d restarts)",
                b.camera_id, b.frames_total, b.restarts)


def _drain_stderr(b: _Broker) -> None:
    try:
        proc = b.proc
        if not proc or not proc.stderr:
            return
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                b.last_error = (b.last_error.split(" · ")[-1] + " · " + line)[-400:] \
                    if b.last_error else line[:200]
    except Exception:
        pass


def _kill_proc(b: _Broker) -> None:
    try:
        if b.proc and b.proc.poll() is None:
            b.proc.terminate()
            try:
                b.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                b.proc.kill()
    except Exception:
        pass


def ensure_broker(camera_id: str, source_url: str) -> _Broker:
    """Démarre (ou réutilise) LE broker partagé de la caméra. Idempotent."""
    with _lock:
        b = _brokers.get(camera_id)
        if b is not None and not b.stop_event.is_set() \
                and b.thread and b.thread.is_alive() and b.source_url == source_url:
            return b
        if b is not None:
            b.stop_event.set()
            _kill_proc(b)
        b = _Broker(camera_id=camera_id, source_url=source_url)
        b.thread = threading.Thread(target=_reader_loop, args=(b,), daemon=True)
        _brokers[camera_id] = b
        b.thread.start()
        return b


def stop_broker(camera_id: str) -> None:
    with _lock:
        b = _brokers.pop(camera_id, None)
    if b:
        b.stop_event.set()
        _kill_proc(b)


def stop_all() -> None:
    for cid in list(_brokers.keys()):
        stop_broker(cid)


async def wait_first_frame(b: _Broker, timeout: float = 12.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if b.latest is not None and time.monotonic() - b.last_frame_ts < 10.0:
            return True
        if b.stop_event.is_set():
            return False
        await asyncio.sleep(0.1)
    return False


async def multipart_generator(b: _Broker):
    """Fanout HTTP : envoie chaque NOUVELLE frame dès disponibilité.
    Un client lent saute des frames (on n'envoie que la dernière), jamais de file."""
    b.viewers += 1
    b.last_viewer_ts = time.monotonic()
    last_seq_sent = 0
    poll = 1.0 / (_MAX_FPS * 2)
    try:
        while not b.stop_event.is_set():
            if b.seq != last_seq_sent and b.latest is not None:
                frame = b.latest          # ref atomique — toujours la plus récente
                last_seq_sent = b.seq
                yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                       f"Content-Length: {len(frame)}\r\n\r\n").encode() + frame + b"\r\n"
            else:
                await asyncio.sleep(poll)
                # Si le flux est mort depuis > 30s côté broker, on ferme (le
                # <img> du navigateur retentera → nouveau broker si besoin)
                if b.last_frame_ts and time.monotonic() - b.last_frame_ts > 30.0:
                    return
    finally:
        b.viewers = max(0, b.viewers - 1)
        b.last_viewer_ts = time.monotonic()


def get_status(camera_id: str) -> dict:
    """Statut broker au contrat video-status (fragment)."""
    b = _brokers.get(camera_id)
    if b is None:
        return {"state": "stopped", "fps": 0.0, "viewers": 0,
                "last_frame_at": None, "error": None}
    alive = bool(b.thread and b.thread.is_alive())
    fresh = bool(b.last_frame_ts and time.monotonic() - b.last_frame_ts < 10.0)
    last_iso = None
    if b.last_frame_ts:
        age = time.monotonic() - b.last_frame_ts
        last_iso = datetime.fromtimestamp(time.time() - age, tz=timezone.utc).isoformat()
    return {
        "state": "online" if (alive and fresh) else ("starting" if alive else "stopped"),
        "fps": b.fps(),
        "viewers": b.viewers,
        "frames_total": b.frames_total,
        "restarts": max(0, b.restarts - 1),
        "last_frame_at": last_iso,
        "error": b.last_error or None,
    }
