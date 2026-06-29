"""MG-VMS — Stream Manager (PRODUCTION, service `ffmpeg-service`).

⚠️ Artefact de production. NON exécuté dans la sandbox de dev (pas de FFmpeg/caméras).
Rôle :
- Lit l'inventaire caméras (PostgreSQL).
- Pour chaque caméra : lance/maintient un pipeline FFmpeg RTSP -> HLS (LL-HLS) et
  expose le flux WebRTC via go2rtc (cf. go2rtc.yaml).
- Détecte les coupures et reconnecte automatiquement (backoff).
- Fournit une API : snapshot à la volée, statut des flux, (re)démarrage.

Décodage matériel : ajouter `-hwaccel cuda` / `-hwaccel vaapi` selon le GPU.
"""
from __future__ import annotations
import os
import time
import signal
import asyncio
import subprocess
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, text

DB_URL = os.environ["DATABASE_URL"]
HLS_ROOT = Path(os.environ.get("HLS_ROOT", "/recordings/hls"))
GO2RTC_API = os.environ.get("GO2RTC_API", "http://localhost:1984")
RECONNECT_BACKOFF = [2, 5, 10, 20, 30]

engine = create_engine(DB_URL, pool_pre_ping=True)
app = FastAPI(title="MG-VMS Stream Manager")

_procs: dict[str, subprocess.Popen] = {}
_fail_count: dict[str, int] = {}


def _cameras() -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id::text, name, rtsp_url, codec FROM cameras WHERE rtsp_url IS NOT NULL"
        )).mappings().all()
    return [dict(r) for r in rows]


def _ffmpeg_cmd(cam: dict) -> list[str]:
    out_dir = HLS_ROOT / cam["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    # Copie le codec si H264/H265 (pas de réencodage) -> faible CPU.
    vcodec = ["-c:v", "copy"] if cam["codec"] in ("H264", "H265") else ["-c:v", "libx264", "-preset", "veryfast"]
    return [
        "ffmpeg", "-nostdin", "-rtsp_transport", "tcp", "-i", cam["rtsp_url"],
        *vcodec, "-c:a", "aac", "-f", "hls",
        "-hls_time", "2", "-hls_list_size", "6", "-hls_flags", "delete_segments+append_list",
        "-hls_segment_filename", str(out_dir / "seg_%05d.ts"), str(out_dir / "index.m3u8"),
    ]


def _start(cam: dict):
    cid = cam["id"]
    if cid in _procs and _procs[cid].poll() is None:
        return
    _procs[cid] = subprocess.Popen(_ffmpeg_cmd(cam), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[stream] started {cam['name']} ({cid})")


def _set_status(cid: str, status: str):
    with engine.begin() as c:
        c.execute(text("UPDATE cameras SET status=:s, last_seen=now() WHERE id=:id"), {"s": status, "id": cid})


async def supervisor_loop():
    while True:
        for cam in _cameras():
            cid = cam["id"]
            proc = _procs.get(cid)
            if proc is None or proc.poll() is not None:
                n = _fail_count.get(cid, 0)
                if proc is not None and proc.poll() is not None:
                    _set_status(cid, "offline")
                    delay = RECONNECT_BACKOFF[min(n, len(RECONNECT_BACKOFF) - 1)]
                    print(f"[stream] {cam['name']} down, reconnect in {delay}s (try {n+1})")
                    _fail_count[cid] = n + 1
                    await asyncio.sleep(delay)
                _start(cam)
            else:
                _fail_count[cid] = 0
                _set_status(cid, "online")
        await asyncio.sleep(5)


@app.on_event("startup")
async def _startup():
    HLS_ROOT.mkdir(parents=True, exist_ok=True)
    asyncio.create_task(supervisor_loop())


@app.get("/streams")
def list_streams():
    return [{"camera_id": cid, "alive": p.poll() is None} for cid, p in _procs.items()]


@app.post("/cameras/{camera_id}/snapshot")
async def snapshot(camera_id: str):
    cam = next((c for c in _cameras() if c["id"] == camera_id), None)
    if not cam:
        raise HTTPException(404, "camera not found")
    out = HLS_ROOT / camera_id / "snapshot.jpg"
    subprocess.run(["ffmpeg", "-y", "-rtsp_transport", "tcp", "-i", cam["rtsp_url"],
                    "-frames:v", "1", "-q:v", "2", str(out)], timeout=15, check=False)
    return {"snapshot": f"/hls/{camera_id}/snapshot.jpg", "captured_at": time.time()}


@app.get("/webrtc/{camera_id}")
async def webrtc_offer(camera_id: str):
    """Renvoie l'URL WebRTC go2rtc (signalisation gérée par go2rtc)."""
    return {"webrtc_url": f"{GO2RTC_API}/api/ws?src={camera_id}", "hls_url": f"/hls/{camera_id}/index.m3u8"}


def _graceful(*_):
    for p in _procs.values():
        p.terminate()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _graceful)
