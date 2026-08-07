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
_RESTART_BACKOFF_SEC = 1.0     # attente initiale entre 2 tentatives de restart
_RESTART_MAX_BACKOFF_SEC = 5.0 # v0.4.5.a — de 30s à 5s (moins d'accumulation de latence)
_READ_TIMEOUT_SEC = 20.0       # si aucune frame lue en 20s → considérer mort et redémarrer
# P0-5 (v0.7.c) : arrêt propre après N tentatives CONSÉCUTIVES sans aucune frame
# (au lieu d'une boucle infinie). Le worker est relancé quand la caméra repasse
# online (stop() + start() par _sync_frame_source_workers) ou si sa config change.
_MAX_CONSECUTIVE_FAILURES = 10


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


# Fenêtre glissante FPS (1 minute) : nombre de timestamps de frames récentes
_FPS_WINDOW_SEC = 60.0
_FPS_WINDOW_MAX = 1800   # cap : 30 fps × 60 s

def _use_gpu() -> bool:
    if _HWACCEL_MODE == "cuda":
        return True   # forcé (attention : plante si NVDEC indispo)
    if _HWACCEL_MODE == "none":
        return False
    return _HAS_CUVID   # auto


@dataclass
class _Worker:
    """État d'un worker FFmpeg persistant pour une caméra.

    v0.4.5.a — Ajout de métriques capture séparées de l'IA.
    """
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
    # P0-5 (v0.7.c) : compteur d'échecs consécutifs (0 frame produite) + drapeau
    consecutive_failures: int = 0
    gave_up: bool = False
    # ── métriques v0.4.5.a ─────────────────────────────
    frames_produced: int = 0         # total depuis start()
    frames_dropped: int = 0          # frames écrasées avant lecture par le consommateur
    consumed_ts: float = 0.0         # dernier ts où un consommateur a lu latest_frame
    started_at: float = 0.0
    first_frame_at: float = 0.0      # ts de la 1re frame (mesure temps de warm-up)
    last_capture_ms: float = 0.0     # intervalle entre 2 frames stdout (capture pace)
    frame_ts_window: list = field(default_factory=list)  # rolling window pour FPS_1min


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
            w.consecutive_failures += 1
            if w.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                w.gave_up = True
                logger.error("frame-source: %s ARRÊTÉ après %d échecs consécutifs (spawn) — dernière erreur: %s",
                             w.camera_id, w.consecutive_failures, w.last_error)
                break
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
        w.started_at = w.started_at or last_read_ts
        prev_frame_ts = 0.0
        frames_before_attempt = w.frames_produced
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
                now = time.monotonic()
                # v0.4.5.a · Métriques capture :
                #  - dropped : la frame précédente n'a jamais été consommée
                if w.latest_frame is not None and w.latest_ts > w.consumed_ts:
                    w.frames_dropped += 1
                #  - pace entre 2 frames stdout (capture_latency)
                if prev_frame_ts:
                    w.last_capture_ms = (now - prev_frame_ts) * 1000
                prev_frame_ts = now
                #  - rolling window FPS 1min
                w.frame_ts_window.append(now)
                cutoff = now - _FPS_WINDOW_SEC
                if len(w.frame_ts_window) > _FPS_WINDOW_MAX or w.frame_ts_window[0] < cutoff:
                    w.frame_ts_window = [t for t in w.frame_ts_window if t >= cutoff]
                # Écriture atomique de la ref (le lecteur voit soit l'ancienne, soit la nouvelle)
                w.latest_frame = frame
                w.latest_ts = now
                w.frames_produced += 1
                if not w.first_frame_at:
                    w.first_frame_at = now
                last_read_ts = now
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
        # P0-5 (v0.7.c) : condition d'arrêt — N tentatives consécutives sans frame
        if w.frames_produced > frames_before_attempt:
            w.consecutive_failures = 0
        else:
            w.consecutive_failures += 1
            if w.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                w.gave_up = True
                logger.error("frame-source: %s ARRÊTÉ après %d tentatives consécutives sans frame — dernière erreur: %s",
                             w.camera_id, w.consecutive_failures, w.last_error or "aucune frame reçue")
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
          width: int = 0, height: int = 0, allow_direct: bool = True) -> None:
    """Démarre (ou redémarre) un worker FFmpeg persistant pour une caméra.

    **v0.3 (Feb 2026)** — SÉPARATION IA/streaming : le worker peut désormais
    consommer **n'importe quelle URL RTSP** (native caméra IP, sous-flux dédié
    IA, ou relais go2rtc). Le garde-fou "go2rtc-only" de Phase 1 a été retiré
    car il empêchait le moteur IA d'accéder au flux RTSP natif (audit v0.3).

    Args:
        camera_id : identifiant unique (utilisé pour get_latest_frame).
        rtsp_url  : URL RTSP arbitraire (``rtsp://user:pass@cam-ip:554/...`` ou
                    ``rtsp://go2rtc:8554/cam_XXX``). En prod on privilégie le
                    flux natif ; go2rtc reste utilisable pour les démos.
        codec     : 'h264' | 'h265' | 'auto' (auto-détection ffmpeg).
        width, height : forcer la taille de sortie (0 = natif). Défaut 1280×720.
        allow_direct : conservé pour compat rétro-API — sans effet depuis v0.3.
    """
    _ = allow_direct  # rétro-compat : plus de garde-fou
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
        w.started_at = time.monotonic()
        w.reader_thread = threading.Thread(target=_reader_loop, args=(w,), daemon=True)
        _workers[camera_id] = w
        w.reader_thread.start()


def is_running(camera_id: str) -> bool:
    """v0.4.5.a · Utilisé par ai_engine pour éviter un start() redondant."""
    w = _workers.get(camera_id)
    return w is not None and bool(w.reader_thread and w.reader_thread.is_alive())


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

    v0.4.5.a · Zéro attente : renvoie IMMÉDIATEMENT la ref numpy déjà
    en mémoire (écriture atomique côté reader). Marque le timestamp
    de consommation pour le compteur ``frames_dropped``.
    """
    w = _workers.get(camera_id)
    if w is None or w.latest_frame is None:
        return None
    now = time.monotonic()
    if now - w.latest_ts > max_age_sec:
        return None
    w.consumed_ts = now
    return w.latest_frame   # zéro-copie : le lecteur écrit atomiquement une nouvelle ref


def status() -> dict:
    """Résumé de l'état de tous les workers (utilisable dans /api/diagnostics).

    v0.4.5.a · Métriques capture séparées :
      - fps_capture_1min : FPS effectif produit par ffmpeg (fenêtre 60s)
      - frames_produced / frames_dropped
      - warmup_ms : durée jusqu'à la 1re frame après start()
      - last_capture_interval_ms : pace entre 2 frames stdout
      - alive / last_frame_age_ms / last_error
    """
    out = {}
    now = time.monotonic()
    for cam_id, w in _workers.items():
        window = w.frame_ts_window
        # FPS calculé sur la fenêtre effective (peut être plus courte que 60s)
        if len(window) >= 2:
            span = window[-1] - window[0]
            fps = round((len(window) - 1) / span, 1) if span > 0 else 0.0
        else:
            fps = 0.0
        warmup_ms = round((w.first_frame_at - w.started_at) * 1000, 1) if (
            w.first_frame_at and w.started_at) else None
        last_age_ms = round((now - w.latest_ts) * 1000, 1) if w.latest_ts else None
        out[cam_id] = {
            "codec": w.codec,
            "resolution": f"{w.width}x{w.height}",
            "gpu": _use_gpu(),
            "restart_count": w.restart_count,
            "reconnect_count": max(0, w.restart_count - 1),
            "frames_produced": w.frames_produced,
            "frames_dropped": w.frames_dropped,
            "fps_capture_1min": fps,
            "warmup_ms": warmup_ms,
            "last_capture_interval_ms": round(w.last_capture_ms, 1) if w.last_capture_ms else None,
            "last_frame_age_ms": last_age_ms,
            "alive": bool(w.reader_thread and w.reader_thread.is_alive()),
            "gave_up": w.gave_up,
            "consecutive_failures": w.consecutive_failures,
            "last_error": w.last_error,
        }
    return {"workers": out, "cuvid_available": _HAS_CUVID, "mode": _HWACCEL_MODE}


async def get_latest_frame_async(camera_id: str, max_age_sec: float = 5.0,
                                  wait_timeout: float = 0.0) -> Optional[np.ndarray]:
    """Version async : retourne la dernière frame OU None (jamais d'attente longue).

    v0.4.5.a · `wait_timeout` défaut = 0.0 (zéro attente). Le pipeline IA
    saute cette itération plutôt que bloquer. Si `wait_timeout > 0`, poll
    court (50ms) — utile uniquement pour warm-up initial explicite.
    """
    frame = get_latest_frame(camera_id, max_age_sec=max_age_sec)
    if frame is not None or wait_timeout <= 0:
        return frame
    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        frame = get_latest_frame(camera_id, max_age_sec=max_age_sec)
        if frame is not None:
            return frame
    return None
