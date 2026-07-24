"""MG-VMS — Source de frames pour l'IA (subprocess FFmpeg persistant avec NVDEC).

Architecture :
    Caméra H.264/H.265 (RTSP TCP)
        │
        ▼
    FFmpeg -hwaccel cuda -c:v {hevc_cuvid,h264_cuvid} → BGR24 pipe stdout
        │
        ▼
    Reader thread : deque[latest_frame]   (garde uniquement la frame la plus récente)
        │
        ▼
    ai_engine.get_latest_frame(camera_id) → numpy.ndarray (H, W, 3)  ← consommateur

Points clés :
- Un seul processus FFmpeg par caméra (partagé entre YOLO + ANPR + éventuels autres).
- Décodage GPU direct via NVDEC (hevc_cuvid / h264_cuvid) : zéro passage par MJPEG.
- Fallback CPU automatique si NVDEC indisponible (log warning, pas de crash).
- Frame la plus récente uniquement (drop des anciennes) → latence minimale.
- Redémarrage automatique du subprocess sur crash upstream (RTSP décroché, ffmpeg mort).

Environnement :
- `MGVMS_AI_HW_ACCEL` : "auto" (défaut), "cuda", "none" — force le mode
- `MGVMS_AI_FRAME_WIDTH` / `MGVMS_AI_FRAME_HEIGHT` : force la résolution (défaut : natif)
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger("frame-source")

# Détection unique au boot du support NVDEC (via ffmpeg -decoders)
_HWACCEL_MODE = os.environ.get("MGVMS_AI_HW_ACCEL", "auto").lower()
_FRAME_WIDTH = int(os.environ.get("MGVMS_AI_FRAME_WIDTH", "0") or 0)
_FRAME_HEIGHT = int(os.environ.get("MGVMS_AI_FRAME_HEIGHT", "0") or 0)
_FFMPEG_PATH = os.environ.get("MGVMS_FFMPEG_PATH", shutil.which("ffmpeg") or "ffmpeg")
_RESTART_BACKOFF_SEC = 4.0     # attente initiale entre 2 tentatives de restart
_RESTART_MAX_BACKOFF_SEC = 30.0
_READ_TIMEOUT_SEC = 20.0       # si aucune frame lue en 20s → considérer mort et redémarrer


def _ffmpeg_supports_cuvid() -> bool:
    """Vérifie une fois au boot que ffmpeg a été compilé avec les décodeurs cuvid."""
    if _HWACCEL_MODE == "none":
        return False
    try:
        out = subprocess.run(
            [_FFMPEG_PATH, "-hide_banner", "-decoders"],
            capture_output=True, text=True, timeout=5,
        )
        text = (out.stdout or "") + (out.stderr or "")
        has = "hevc_cuvid" in text and "h264_cuvid" in text
        if has:
            logger.info("frame-source: FFmpeg NVDEC détecté (hevc_cuvid + h264_cuvid) ✅")
        else:
            logger.warning("frame-source: FFmpeg SANS support cuvid — fallback CPU (SW decode)")
        return has
    except Exception as e:
        logger.warning("frame-source: détection cuvid échec (%s) — fallback CPU", e)
        return False


_HAS_CUVID = _ffmpeg_supports_cuvid() if _HWACCEL_MODE in ("auto", "cuda") else False


def _use_gpu() -> bool:
    if _HWACCEL_MODE == "cuda":
        return True   # forcé (attention : plante si NVDEC indispo)
    if _HWACCEL_MODE == "none":
        return False
    return _HAS_CUVID   # auto


@dataclass
class _Worker:
    """État d'un worker FFmpeg persistant pour une caméra."""
    camera_id: str
    rtsp_url: str
    codec: str                       # 'h264' | 'h265' | 'auto'
    width: int
    height: int
    proc: Optional[subprocess.Popen] = None
    latest_frame: Optional[np.ndarray] = None
    latest_ts: float = 0.0
    stop_event: threading.Event = field(default_factory=threading.Event)
    reader_thread: Optional[threading.Thread] = None
    restart_count: int = 0
    last_error: str = ""


# Registre des workers actifs : camera_id → _Worker
_workers: dict[str, _Worker] = {}
_workers_lock = threading.Lock()


def _build_ffmpeg_cmd(w: _Worker) -> list[str]:
    """Construit la commande ffmpeg optimale selon le codec et la disponibilité NVDEC.

    Sortie : BGR24 raw pipe (compatible cv2.imshow / numpy direct).
    Résolution : forcée à `width x height` (scale) OU native si 0.
    """
    use_gpu = _use_gpu()
    cmd = [
        _FFMPEG_PATH,
        "-hide_banner", "-loglevel", "warning",
        "-nostdin",
        # RTSP TCP (mandatory : évite les crashes H.265 UDP + timeouts)
        "-rtsp_transport", "tcp",
        "-fflags", "nobuffer",       # latence minimale
        "-flags", "low_delay",
        "-strict", "experimental",
    ]
    if use_gpu:
        # Décodage matériel CUDA (NVDEC)
        # `-hwaccel_output_format cuda` garde les frames en VRAM le plus longtemps possible
        cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        if w.codec == "h265":
            cmd += ["-c:v", "hevc_cuvid"]
        elif w.codec == "h264":
            cmd += ["-c:v", "h264_cuvid"]
        # 'auto' : laisse ffmpeg choisir en fonction du flux
    cmd += ["-i", w.rtsp_url]
    # Filtre GPU si scale demandé, sinon download brut
    vf_parts = []
    if use_gpu:
        # download vers CPU en fin de chaîne (nécessaire car on pipe vers numpy)
        if w.width > 0 and w.height > 0:
            vf_parts.append(f"scale_cuda={w.width}:{w.height}")
        vf_parts.append("hwdownload")
        vf_parts.append("format=nv12")   # convertit CUDA nv12 → CPU nv12
    elif w.width > 0 and w.height > 0:
        vf_parts.append(f"scale={w.width}:{w.height}")
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]
    # Sortie BGR24 raw sur stdout (format directement lisible par numpy)
    cmd += [
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-an", "-sn",   # ni audio ni sous-titres
        "pipe:1",
    ]
    return cmd


def _reader_loop(w: _Worker):
    """Thread lecteur : lit les frames BGR24 depuis ffmpeg stdout en boucle continue.

    Frame la plus récente uniquement (drop des anciennes) → latence min.
    Redémarrage automatique du subprocess si mort ou timeout.
    """
    backoff = _RESTART_BACKOFF_SEC
    while not w.stop_event.is_set():
        # Démarrer le subprocess ffmpeg
        cmd = _build_ffmpeg_cmd(w)
        try:
            w.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0,   # unbuffered
            )
            w.restart_count += 1
            logger.info(
                "frame-source: worker %s démarré (pid=%s, gpu=%s, codec=%s, %dx%d, restart#%d)",
                w.camera_id, w.proc.pid, _use_gpu(), w.codec, w.width, w.height, w.restart_count,
            )
        except Exception as e:
            w.last_error = f"spawn error: {e}"
            logger.warning("frame-source: impossible de démarrer ffmpeg pour %s: %s", w.camera_id, e)
            if not w.stop_event.wait(backoff):
                backoff = min(backoff * 1.5, _RESTART_MAX_BACKOFF_SEC)
            continue

        # Boucle de lecture : besoin de connaître la taille frame pour lire un chunk complet
        # → On lit un premier chunk pour déterminer les dimensions via probe séparé si scale=0.
        # Simplification : on force toujours une résolution en sortie (défaut 1280×720).
        w_out = w.width if w.width > 0 else 1280
        h_out = w.height if w.height > 0 else 720
        frame_bytes = w_out * h_out * 3
        stderr_thread = threading.Thread(target=_drain_stderr, args=(w,), daemon=True)
        stderr_thread.start()

        last_read_ts = time.monotonic()
        try:
            while not w.stop_event.is_set() and w.proc.poll() is None:
                # Lecture bloquante d'une frame complète
                buf = _read_exact(w.proc.stdout, frame_bytes, timeout_sec=_READ_TIMEOUT_SEC)
                if buf is None:
                    logger.warning("frame-source: %s timeout lecture frame — redémarrage", w.camera_id)
                    break
                if len(buf) != frame_bytes:
                    logger.warning("frame-source: %s stream ended (read %d/%d) — redémarrage",
                                   w.camera_id, len(buf), frame_bytes)
                    break
                # Convertit en numpy BGR24 sans copie
                frame = np.frombuffer(buf, dtype=np.uint8).reshape((h_out, w_out, 3))
                w.latest_frame = frame
                w.latest_ts = time.monotonic()
                last_read_ts = w.latest_ts
                backoff = _RESTART_BACKOFF_SEC   # reset backoff après succès
        finally:
            # Cleanup ffmpeg
            try:
                if w.proc and w.proc.poll() is None:
                    w.proc.terminate()
                    try:
                        w.proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        w.proc.kill()
            except Exception:
                pass

        if w.stop_event.is_set():
            break
        # Backoff progressif entre redémarrages
        logger.info("frame-source: %s en attente %.1fs avant redémarrage", w.camera_id, backoff)
        if not w.stop_event.wait(backoff):
            backoff = min(backoff * 1.5, _RESTART_MAX_BACKOFF_SEC)


def _read_exact(stream, nbytes: int, timeout_sec: float) -> Optional[bytes]:
    """Lit exactement `nbytes` octets. Retourne None sur timeout / EOF."""
    buf = bytearray()
    deadline = time.monotonic() + timeout_sec
    while len(buf) < nbytes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            chunk = stream.read(min(nbytes - len(buf), 65536))
        except Exception:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _drain_stderr(w: _Worker):
    """Absorbe le stderr ffmpeg (évite le blocage buffer) et logge les erreurs graves."""
    if not w.proc or not w.proc.stderr:
        return
    try:
        for raw in iter(w.proc.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            low = line.lower()
            if "error" in low or "fatal" in low or "cannot" in low:
                w.last_error = line[:200]
                logger.warning("[ffmpeg %s] %s", w.camera_id, line)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════
# API publique
# ══════════════════════════════════════════════════════════════════════════

def start(camera_id: str, rtsp_url: str, codec: str = "auto",
          width: int = 0, height: int = 0, allow_direct: bool = False) -> None:
    """Démarre (ou redémarre) un worker FFmpeg persistant pour une caméra.

    Phase 1 (go2rtc = unique gateway) :
      Refuse les URLs RTSP directes vers une caméra IP par défaut. Toutes les
      sessions RTSP doivent passer par go2rtc pour garantir 1 seule connexion
      caméra ↔ NVR (partagée viewers/recorder/IA). Bypass explicite via
      `allow_direct=True` uniquement pour outillage/tests hors production.

    Args:
        camera_id : identifiant unique (utilisé pour get_latest_frame).
        rtsp_url  : URL RTSP DOIT commencer par `rtsp://go2rtc:` ou `rtsp://127.0.0.1:8554/`
                    (ou pointer sur `$GO2RTC_RTSP`). Sinon → ValueError.
        codec     : 'h264' | 'h265' | 'auto' (auto-détection ffmpeg).
        width, height : forcer la taille de sortie (0 = natif). Recommandé
                        640×360 pour YOLO YOLOv11s = compromis vitesse/qualité.
        allow_direct : bypass la garde go2rtc (usage tests uniquement).
    """
    # ── Garde-fou Phase 1 : go2rtc-only ─────────────────────────────────
    if not allow_direct:
        go2rtc_prefix = os.environ.get("GO2RTC_RTSP", "rtsp://go2rtc:8554").rstrip("/")
        allowed_prefixes = (
            go2rtc_prefix + "/",
            "rtsp://go2rtc:",
            "rtsp://127.0.0.1:8554/",
            "rtsp://localhost:8554/",
        )
        if not any(rtsp_url.startswith(p) for p in allowed_prefixes):
            raise ValueError(
                f"frame_source.start refuse une URL RTSP hors go2rtc : {rtsp_url[:60]}... "
                "Phase 1 (go2rtc = unique gateway) — utilisez rtsp://go2rtc:8554/cam_XXX. "
                "Pour bypass en test : passer allow_direct=True."
            )
    # Défaut résolution : 1280×720 pour YOLO
    if width == 0 or height == 0:
        width = _FRAME_WIDTH or 1280
        height = _FRAME_HEIGHT or 720

    with _workers_lock:
        existing = _workers.get(camera_id)
        if existing is not None:
            # Redémarrage si config différente, sinon no-op
            if (existing.rtsp_url == rtsp_url and existing.codec == codec
                    and existing.width == width and existing.height == height):
                return
            stop(camera_id)
        w = _Worker(camera_id=camera_id, rtsp_url=rtsp_url, codec=codec,
                     width=width, height=height)
        w.reader_thread = threading.Thread(target=_reader_loop, args=(w,), daemon=True)
        _workers[camera_id] = w
        w.reader_thread.start()


def stop(camera_id: str) -> None:
    """Arrête proprement un worker (utilisé quand une caméra est désactivée/supprimée)."""
    with _workers_lock:
        w = _workers.pop(camera_id, None)
    if w is None:
        return
    w.stop_event.set()
    try:
        if w.proc and w.proc.poll() is None:
            w.proc.terminate()
    except Exception:
        pass
    if w.reader_thread and w.reader_thread.is_alive():
        w.reader_thread.join(timeout=5)
    logger.info("frame-source: worker %s arrêté", camera_id)


def stop_all() -> None:
    for cam_id in list(_workers.keys()):
        stop(cam_id)


def get_latest_frame(camera_id: str, max_age_sec: float = 5.0) -> Optional[np.ndarray]:
    """Retourne la dernière frame BGR24 pour une caméra, ou None si :
    - le worker n'existe pas ;
    - aucune frame n'a été produite ;
    - la dernière frame est plus vieille que `max_age_sec` (worker mort).
    """
    w = _workers.get(camera_id)
    if w is None or w.latest_frame is None:
        return None
    if time.monotonic() - w.latest_ts > max_age_sec:
        return None
    return w.latest_frame   # zéro-copie : le lecteur écrit atomiquement une nouvelle ref


def status() -> dict:
    """Résumé de l'état de tous les workers (utilisable dans /api/diagnostics)."""
    out = {}
    now = time.monotonic()
    for cam_id, w in _workers.items():
        out[cam_id] = {
            "codec": w.codec,
            "resolution": f"{w.width}x{w.height}",
            "gpu": _use_gpu(),
            "restart_count": w.restart_count,
            "last_frame_age_s": round(now - w.latest_ts, 1) if w.latest_ts else None,
            "alive": bool(w.reader_thread and w.reader_thread.is_alive()),
            "last_error": w.last_error,
        }
    return {"workers": out, "cuvid_available": _HAS_CUVID, "mode": _HWACCEL_MODE}


async def get_latest_frame_async(camera_id: str, max_age_sec: float = 5.0,
                                  wait_timeout: float = 3.0) -> Optional[np.ndarray]:
    """Version async avec attente : si aucune frame encore disponible (worker vient de
    démarrer), attend jusqu'à `wait_timeout` avant de retourner None."""
    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        frame = get_latest_frame(camera_id, max_age_sec=max_age_sec)
        if frame is not None:
            return frame
        await asyncio.sleep(0.2)
    return None
