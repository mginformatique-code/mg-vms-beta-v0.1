"""MG-VMS — Enregistrement vidéo RÉEL (FFmpeg → segments MP4 sur disque).

Chaque caméra avec `record_enabled` est enregistrée en continu depuis go2rtc
(RTSP) en segments MP4 copiés sans réencodage. Les fichiers sont indexés en
base (timeline réelle), avec rétention automatique.
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import db

logger = logging.getLogger("recorder")

RECORDINGS_DIR = Path(os.environ.get("RECORDINGS_DIR", "/app/recordings"))
GO2RTC_RTSP = os.environ.get("GO2RTC_RTSP", "rtsp://127.0.0.1:8554")
SEGMENT_SECONDS = int(os.environ.get("RECORD_SEGMENT_SECONDS", "120"))
RETENTION_DAYS = int(os.environ.get("RECORD_RETENTION_DAYS", "7"))
MIN_FREE_GB = float(os.environ.get("RECORD_MIN_FREE_GB", "2"))

_processes: dict[str, asyncio.subprocess.Process] = {}


def _cam_dir(camera_id: str) -> Path:
    d = RECORDINGS_DIR / camera_id
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _start_ffmpeg(camera_id: str) -> None:
    out = _cam_dir(camera_id) / "%Y%m%d_%H%M%S.mp4"
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-i", f"{GO2RTC_RTSP}/cam_{camera_id}",
        "-c", "copy", "-f", "segment",
        "-segment_time", str(SEGMENT_SECONDS),
        "-reset_timestamps", "1", "-strftime", "1",
        str(out),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True, start_new_session=True)  # ne pas hériter du socket uvicorn (passé en stdin par le reloader)
    _processes[camera_id] = proc
    logger.info("Enregistrement démarré : caméra %s (pid %s)", camera_id, proc.pid)


def _probe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, timeout=10)
        return float(json.loads(out.stdout or "{}").get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


async def _event_flags(camera_id: str, start_iso: str, end_iso: str) -> dict:
    """Corrèle les événements IA/mouvement réels avec un segment."""
    evts = await db.events.find(
        {"camera_id": camera_id, "timestamp": {"$gte": start_iso, "$lte": end_iso}},
        {"_id": 0, "type": 1},
    ).to_list(200)
    if not evts:
        return {"has_event": False, "event_type": None, "mode": "continuous", "event_count": 0}
    ai_types = [e["type"] for e in evts if e["type"] != "Mouvement"]
    return {
        "has_event": True,
        "event_type": ai_types[0] if ai_types else "Mouvement",
        "mode": "ai" if ai_types else "motion",
        "event_count": len(evts),
    }


async def _index_segments(cam: dict) -> None:
    """Indexe en base les segments MP4 clos (fichiers réels sur disque)."""
    cam_dir = _cam_dir(cam["id"])
    files = sorted(cam_dir.glob("*.mp4"))
    if not files:
        return
    newest = files[-1]
    for f in files:
        if f == newest and _processes.get(cam["id"]) and _processes[cam["id"]].returncode is None:
            continue  # segment en cours d'écriture
        if await db.recordings.find_one({"file_path": str(f)}):
            continue
        try:
            start = datetime.strptime(f.stem, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        duration = await asyncio.to_thread(_probe_duration, f)
        if duration <= 0:
            continue
        end = start + timedelta(seconds=duration)
        flags = await _event_flags(cam["id"], start.isoformat(), end.isoformat())
        size_mb = round(f.stat().st_size / 1e6, 1)
        await db.recordings.insert_one({
            "id": str(uuid.uuid4()),
            "camera_id": cam["id"], "camera_name": cam["name"],
            "site_id": cam.get("site_id", ""), "site_name": cam.get("site_name", ""),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "duration_sec": int(duration),
            "size_mb": size_mb,
            "file_path": str(f),
            "thumbnail": None,
            **flags,
        })


async def _refresh_recent_flags() -> None:
    """Met à jour la corrélation événements des segments récents (2 h)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    recent = await db.recordings.find({"start": {"$gte": since}}, {"_id": 0, "id": 1, "camera_id": 1, "start": 1, "end": 1}).to_list(500)
    for rec in recent:
        flags = await _event_flags(rec["camera_id"], rec["start"], rec["end"])
        await db.recordings.update_one({"id": rec["id"]}, {"$set": flags})


async def _apply_retention() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    old = await db.recordings.find({"start": {"$lt": cutoff}, "file_path": {"$ne": None}}, {"_id": 0}).to_list(2000)
    for rec in old:
        try:
            Path(rec["file_path"]).unlink(missing_ok=True)
        except OSError:
            pass
    await db.recordings.delete_many({"start": {"$lt": cutoff}})


async def recorder_loop() -> None:
    """Boucle superviseur : démarre/répare les enregistreurs et indexe les segments."""
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg introuvable — enregistrement désactivé")
        return
    await asyncio.sleep(10)  # laisse go2rtc/flux démarrer
    tick = 0
    while True:
        try:
            free_gb = shutil.disk_usage(RECORDINGS_DIR).free / 1e9
            if free_gb < MIN_FREE_GB:
                if _processes:
                    logger.error("Espace disque insuffisant (%.1f Go libres) — enregistrement suspendu", free_gb)
                    for cam_id, proc in list(_processes.items()):
                        if proc.returncode is None:
                            proc.terminate()
                    _processes.clear()
                await _apply_retention()
                await asyncio.sleep(60)
                continue
            cams = await db.cameras.find({"record_enabled": True}, {"_id": 0}).to_list(500)
            active_ids = set()
            for cam in cams:
                active_ids.add(cam["id"])
                proc = _processes.get(cam["id"])
                if proc is None or proc.returncode is not None:
                    await _start_ffmpeg(cam["id"])
                await _index_segments(cam)
            # stoppe les enregistreurs des caméras désactivées/supprimées
            for cam_id, proc in list(_processes.items()):
                if cam_id not in active_ids and proc.returncode is None:
                    proc.terminate()
                    _processes.pop(cam_id, None)
                    logger.info("Enregistrement arrêté : caméra %s", cam_id)
            tick += 1
            if tick % 4 == 0:
                await _refresh_recent_flags()
            if tick % 20 == 0:
                await _apply_retention()
        except Exception:
            logger.exception("recorder_loop : erreur, reprise dans 30s")
        await asyncio.sleep(30)
