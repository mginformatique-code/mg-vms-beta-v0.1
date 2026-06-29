"""MG-VMS — Pipeline ANPR réel (PRODUCTION).

⚠️ Artefact de production. NON exécuté dans la sandbox.

Lecture automatique de plaques (LAPI) :
- Détection de la plaque + OCR via fast-alpr (modèles ONNX, CPU/GPU).
- Normalisation du texte, score de confiance.
- Détermination liste blanche/noire (table `watchlist`).
- Écriture en base (`plates`) + déclenchement d'alerte critique si liste noire
  (publication Redis -> notification-service relaie Discord/Telegram/Email).
"""
from __future__ import annotations
import os
import re
import json
from datetime import datetime, timezone

import cv2
import redis
from sqlalchemy import create_engine, text

try:
    from fast_alpr import ALPR
except Exception:  # le module n'est dispo qu'en prod
    ALPR = None

DB_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
MIN_CONF = float(os.environ.get("ANPR_MIN_CONF", "0.55"))

_PLATE_RE = re.compile(r"[^A-Z0-9]")


class ANPRPipeline:
    def __init__(self):
        self.engine = create_engine(DB_URL, pool_pre_ping=True)
        self.rds = redis.from_url(REDIS_URL)
        self.alpr = ALPR(
            detector_model="yolo-v9-t-384-license-plate-end2end",
            ocr_model="global-plates-mobile-vit-v2-model",
        ) if ALPR else None

    @staticmethod
    def _normalize(text_: str) -> str:
        return _PLATE_RE.sub("", text_.upper())

    def _watch_status(self, plate: str) -> str:
        with self.engine.connect() as c:
            row = c.execute(text(
                "SELECT list_type FROM watchlist WHERE plate=:p"
            ), {"p": plate}).first()
        return row[0] if row else "none"

    def handle_vehicle(self, cam: dict, crop):
        if self.alpr is None:
            return
        results = self.alpr.predict(crop)
        for res in results:
            if not res.ocr or res.ocr.confidence < MIN_CONF:
                continue
            plate = self._normalize(res.ocr.text)
            if len(plate) < 4:
                continue
            status = self._watch_status(plate)
            crop_key = self._store_crop(cam["id"], plate, crop)
            self._save_plate(cam, plate, float(res.ocr.confidence), status, crop_key)
            if status == "black":
                self._raise_alert(cam, plate, crop_key)

    def _store_crop(self, camera_id: str, plate: str, crop) -> str | None:
        try:
            path = f"/recordings/anpr/{camera_id}_{plate}_{int(datetime.now().timestamp())}.jpg"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            cv2.imwrite(path, crop)
            return path
        except Exception:
            return None

    def _save_plate(self, cam: dict, plate: str, conf: float, status: str, crop_key):
        with self.engine.begin() as c:
            c.execute(text(
                "INSERT INTO plates (plate, camera_id, site_id, confidence, list_status, vehicle_crop, ts) "
                "VALUES (:plate, :cam, :site, :conf, :status, :crop, :ts)"
            ), {"plate": plate, "cam": cam["id"], "site": cam["site_id"],
                "conf": conf, "status": status, "crop": crop_key,
                "ts": datetime.now(timezone.utc)})
        self.rds.publish("plates", json.dumps({
            "plate": plate, "camera_id": cam["id"], "list_status": status,
        }))

    def _raise_alert(self, cam: dict, plate: str, crop_key):
        msg = f"Plaque en liste noire détectée : {plate} ({cam['name']})"
        with self.engine.begin() as c:
            c.execute(text(
                "INSERT INTO alerts (type, severity, message, camera_id, site_id, ts) "
                "VALUES ('anpr_blacklist', 'critical', :msg, :cam, :site, :ts)"
            ), {"msg": msg, "cam": cam["id"], "site": cam["site_id"],
                "ts": datetime.now(timezone.utc)})
        self.rds.publish("alerts", json.dumps({
            "type": "anpr_blacklist", "severity": "critical", "message": msg,
            "camera_id": cam["id"], "site_id": cam["site_id"],
            "plate": plate, "image": crop_key,
        }))
