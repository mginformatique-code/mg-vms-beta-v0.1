"""MG-VMS — Moteur IA (PRODUCTION, service `ai-engine`).

⚠️ Artefact de production. NON exécuté dans la sandbox (pas de GPU/CUDA/flux RTSP).

Rôle :
- Consomme les flux des caméras (via le ffmpeg-service / RTSP direct).
- Inférence YOLOv11 (Ultralytics) + tracking ByteTrack pour générer des `events`
  (person/car/truck/...) avec ID de piste stable et confiance.
- Déduplique par piste (un event par objet, pas par frame) et écrit en base
  (table `events`), pousse une notification temps réel via Redis Pub/Sub.
- Délègue les véhicules au pipeline ANPR (anpr.py) pour lire la plaque.

GPU : `AI_DEVICE=cuda`. CPU possible (`cpu`) mais déconseillé en prod.
Mise à l'échelle : 1 worker par GPU, partition des caméras via `WORKER_CAMERAS`.
"""
from __future__ import annotations
import os
import json
import time
from datetime import datetime, timezone

import cv2
import redis
from ultralytics import YOLO
from sqlalchemy import create_engine, text

from anpr import ANPRPipeline

DB_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
MODEL = os.environ.get("AI_MODEL", "yolov11x.pt")
DEVICE = os.environ.get("AI_DEVICE", "cuda")
CONF = float(os.environ.get("AI_CONF", "0.4"))
# Classes COCO suivies (person, bicycle, car, motorcycle, bus, truck)
TRACK_CLASSES = [0, 1, 2, 3, 5, 7]
VEHICLE_CLASSES = {2, 3, 5, 7}

engine = create_engine(DB_URL, pool_pre_ping=True)
rds = redis.from_url(REDIS_URL)
model = YOLO(MODEL)
anpr = ANPRPipeline()

# pistes déjà enregistrées par caméra -> évite les doublons
_seen_tracks: dict[str, set[int]] = {}


def _cameras() -> list[dict]:
    only = os.environ.get("WORKER_CAMERAS")  # liste d'IDs séparés par des virgules
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id::text, site_id::text, name, rtsp_url FROM cameras "
            "WHERE rtsp_url IS NOT NULL AND status='online'"
        )).mappings().all()
    cams = [dict(r) for r in rows]
    if only:
        keep = set(only.split(","))
        cams = [c for c in cams if c["id"] in keep]
    return cams


def _save_event(cam: dict, label: str, conf: float, thumb_key: str | None):
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO events (camera_id, site_id, type, confidence, thumbnail, ts) "
            "VALUES (:cam, :site, :type, :conf, :thumb, :ts)"
        ), {"cam": cam["id"], "site": cam["site_id"], "type": label,
            "conf": conf, "thumb": thumb_key, "ts": datetime.now(timezone.utc)})
    rds.publish("events", json.dumps({
        "camera_id": cam["id"], "site_id": cam["site_id"],
        "type": label, "confidence": conf,
    }))


def process_camera(cam: dict):
    """Boucle d'inférence streaming sur une caméra (tracking persistant)."""
    seen = _seen_tracks.setdefault(cam["id"], set())
    # stream=True -> générateur ; persist=True -> ByteTrack conserve les IDs
    results = model.track(
        source=cam["rtsp_url"], stream=True, persist=True,
        tracker="bytetrack.yaml", classes=TRACK_CLASSES,
        conf=CONF, device=DEVICE, verbose=False,
    )
    for r in results:
        if r.boxes is None or r.boxes.id is None:
            continue
        for box, tid, cls, conf in zip(
            r.boxes.xyxy.cpu().numpy(),
            r.boxes.id.int().cpu().tolist(),
            r.boxes.cls.int().cpu().tolist(),
            r.boxes.conf.cpu().tolist(),
        ):
            if tid in seen:
                continue
            seen.add(tid)
            label = model.names[cls]
            x1, y1, x2, y2 = map(int, box)
            crop = r.orig_img[y1:y2, x1:x2]
            thumb_key = _store_thumb(cam["id"], tid, crop)
            _save_event(cam, label, float(conf), thumb_key)
            if cls in VEHICLE_CLASSES:
                anpr.handle_vehicle(cam, crop)


def _store_thumb(camera_id: str, tid: int, crop) -> str | None:
    try:
        path = f"/recordings/thumbs/{camera_id}_{tid}_{int(time.time())}.jpg"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, crop)
        return path
    except Exception:
        return None


def main():
    print(f"[ai-engine] YOLOv11 model={MODEL} device={DEVICE}")
    while True:
        cams = _cameras()
        if not cams:
            time.sleep(10)
            continue
        # En production : un process/thread par caméra (ici séquentiel pour l'exemple).
        for cam in cams:
            try:
                process_camera(cam)
            except Exception as e:
                print(f"[ai-engine] {cam['name']} error: {e}")
                time.sleep(5)


if __name__ == "__main__":
    main()
