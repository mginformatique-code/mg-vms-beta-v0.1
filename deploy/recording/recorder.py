"""MG-VMS — Service d'enregistrement & timeline (PRODUCTION, `recording-service`).

⚠️ Artefact de production. NON exécuté dans la sandbox (pas de FFmpeg/RTSP/MinIO).

Rôle :
- Enregistre les flux caméra en segments MP4 (modes : continu / planning / mouvement / IA / manuel).
- Segmente par tranches (`SEGMENT_SECONDS`), pousse vers MinIO/S3, indexe en base (`recordings`).
- Applique la rétention (purge au-delà de `RETENTION_DAYS` ou du quota disque).
- Expose une API timeline : segments disponibles par caméra/plage horaire + export.
"""
from __future__ import annotations
import os
import threading
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, text

DB_URL = os.environ["DATABASE_URL"]
REC_ROOT = Path(os.environ.get("REC_ROOT", "/recordings/segments"))
SEGMENT_SECONDS = int(os.environ.get("SEGMENT_SECONDS", "300"))   # 5 min
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))
S3_BUCKET = os.environ.get("S3_BUCKET", "recordings")

engine = create_engine(DB_URL, pool_pre_ping=True)
app = FastAPI(title="MG-VMS Recording Service")
s3 = boto3.client(
    "s3", endpoint_url=os.environ.get("S3_ENDPOINT"),
    aws_access_key_id=os.environ.get("MINIO_ROOT_USER"),
    aws_secret_access_key=os.environ.get("MINIO_ROOT_PASSWORD"),
)
_recorders: dict[str, subprocess.Popen] = {}


def _cameras() -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id::text, name, rtsp_url FROM cameras "
            "WHERE rtsp_url IS NOT NULL AND status='online'"
        )).mappings().all()
    return [dict(r) for r in rows]


def _record_cmd(cam: dict, out_pattern: str) -> list[str]:
    return [
        "ffmpeg", "-nostdin", "-rtsp_transport", "tcp", "-i", cam["rtsp_url"],
        "-c", "copy", "-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
        "-segment_format", "mp4", "-reset_timestamps", "1",
        "-strftime", "1", out_pattern,
    ]


def _start(cam: dict):
    cid = cam["id"]
    if cid in _recorders and _recorders[cid].poll() is None:
        return
    out_dir = REC_ROOT / cid
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "%Y%m%d_%H%M%S.mp4")
    _recorders[cid] = subprocess.Popen(_record_cmd(cam, pattern),
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[recording] started {cam['name']} ({cid})")


def _index_segment(camera_id: str, path: Path):
    """Référence un segment finalisé en base + upload S3."""
    start_ts = datetime.strptime(path.stem, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    key = f"{camera_id}/{path.name}"
    try:
        s3.upload_file(str(path), S3_BUCKET, key)
    except Exception as e:
        print(f"[recording] upload failed {key}: {e}")
        return
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO recordings (camera_id, start_ts, end_ts, storage_key, size_bytes, mode) "
            "VALUES (:cam, :start, :end, :key, :size, 'continuous')"
        ), {"cam": camera_id, "start": start_ts,
            "end": start_ts + timedelta(seconds=SEGMENT_SECONDS),
            "key": key, "size": path.stat().st_size})
    path.unlink(missing_ok=True)


def indexer_loop():
    """Scanne les segments finalisés et les indexe (le plus récent reste en écriture)."""
    while True:
        for cam_dir in REC_ROOT.glob("*"):
            segs = sorted(cam_dir.glob("*.mp4"))
            for seg in segs[:-1]:   # garde le dernier (en cours d'écriture)
                _index_segment(cam_dir.name, seg)
        threading.Event().wait(SEGMENT_SECONDS)


def retention_loop():
    cutoff = lambda: datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    while True:
        with engine.begin() as c:
            old = c.execute(text(
                "SELECT id::text, storage_key FROM recordings WHERE start_ts < :cut"
            ), {"cut": cutoff()}).mappings().all()
            for r in old:
                try:
                    s3.delete_object(Bucket=S3_BUCKET, Key=r["storage_key"])
                except Exception:
                    pass
                c.execute(text("DELETE FROM recordings WHERE id=:id"), {"id": r["id"]})
        threading.Event().wait(3600)


@app.on_event("startup")
def _startup():
    REC_ROOT.mkdir(parents=True, exist_ok=True)
    for cam in _cameras():
        _start(cam)
    threading.Thread(target=indexer_loop, daemon=True).start()
    threading.Thread(target=retention_loop, daemon=True).start()


@app.get("/timeline/{camera_id}")
def timeline(camera_id: str, frm: str, to: str):
    """Segments enregistrés d'une caméra sur une plage [frm, to] (ISO 8601)."""
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id::text, start_ts, end_ts, storage_key, size_bytes, mode "
            "FROM recordings WHERE camera_id=:cam AND start_ts >= :frm AND start_ts <= :to "
            "ORDER BY start_ts"
        ), {"cam": camera_id, "frm": frm, "to": to}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/recordings/{recording_id}/url")
def playback_url(recording_id: str):
    with engine.connect() as c:
        row = c.execute(text("SELECT storage_key FROM recordings WHERE id=:id"),
                        {"id": recording_id}).first()
    if not row:
        raise HTTPException(404, "recording not found")
    url = s3.generate_presigned_url("get_object",
                                    Params={"Bucket": S3_BUCKET, "Key": row[0]}, ExpiresIn=3600)
    return {"url": url}


@app.post("/export")
def export_clip(camera_id: str, frm: str, to: str, fmt: str = "mp4"):
    """Assemble les segments d'une plage en un clip MP4 (concat FFmpeg) -> MinIO + URL présignée.
    PRODUCTION uniquement (FFmpeg requis). `fmt` : mp4 | zip."""
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id::text, storage_key, start_ts FROM recordings "
            "WHERE camera_id=:cam AND start_ts >= :frm AND start_ts <= :to ORDER BY start_ts"
        ), {"cam": camera_id, "frm": frm, "to": to}).mappings().all()
    if not rows:
        raise HTTPException(404, "aucun segment dans la plage")

    work = REC_ROOT / "exports"
    work.mkdir(parents=True, exist_ok=True)
    out_key = f"exports/{camera_id}/{frm}_{to}.{fmt}".replace(":", "-")

    # Télécharge les segments depuis MinIO et construit la liste de concaténation FFmpeg
    local = []
    for r in rows:
        p = work / Path(r["storage_key"]).name
        s3.download_file(S3_BUCKET, r["storage_key"], str(p))
        local.append(p)

    if fmt == "mp4":
        listfile = work / f"{camera_id}.txt"
        listfile.write_text("".join(f"file '{p}'\n" for p in local))
        out_local = work / Path(out_key).name
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
                        "-c", "copy", str(out_local)], check=True, timeout=600)
        s3.upload_file(str(out_local), S3_BUCKET, out_key)
    else:  # zip des segments bruts
        import zipfile
        out_local = work / Path(out_key).name
        with zipfile.ZipFile(out_local, "w", zipfile.ZIP_STORED) as zf:
            for p in local:
                zf.write(p, p.name)
        s3.upload_file(str(out_local), S3_BUCKET, out_key)

    url = s3.generate_presigned_url("get_object",
                                    Params={"Bucket": S3_BUCKET, "Key": out_key}, ExpiresIn=3600)
    return {"url": url, "segments": len(rows), "format": fmt}
