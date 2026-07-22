"""MG-VMS — Moteur IA RÉEL : YOLO + détection de mouvement + LAPI locale (fast-alpr).

Boucle d'analyse : pour chaque caméra avec `detect_enabled`, une frame réelle est
extraite du flux (go2rtc) puis analysée :
- détection de mouvement réelle (différence d'images consécutives) ;
- détection d'objets YOLO (personnes, véhicules...) avec estimation réelle de la
  couleur dominante des véhicules ;
- LAPI locale (fast-alpr, ONNX) si un véhicule est présent : plaque + type +
  couleur du véhicule associé.
Événements, plaques et alertes liste noire sont réels (vignettes incluses).
"""
import asyncio
import base64
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from database import db
from realtime import broadcast_alert

logger = logging.getLogger("ai-engine")

GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://localhost:1984")
AI_INTERVAL = float(os.environ.get("AI_INTERVAL_SECONDS", "2"))
AI_CONFIDENCE = float(os.environ.get("AI_CONFIDENCE", "0.45"))
AI_MIN_PLATE_PX = int(os.environ.get("AI_MIN_PLATE_PX", "24"))  # côté min. plaque acceptée
AI_PLATE_CACHE_SECONDS = int(os.environ.get("AI_PLATE_CACHE_SECONDS", "8"))
AI_DEVICE = os.environ.get("AI_DEVICE", "auto")  # 'cpu' | 'cuda' | 'auto'
EVENT_COOLDOWN = int(os.environ.get("AI_EVENT_COOLDOWN_SECONDS", "60"))
MOTION_THRESHOLD_PCT = float(os.environ.get("MOTION_THRESHOLD_PCT", "1.5"))
MOTION_COOLDOWN = int(os.environ.get("MOTION_COOLDOWN_SECONDS", "60"))

# Réglages RUNTIME (surchargent les variables d'env quand présents en base)
_runtime_config: dict = {}


def _cfg(key: str, default):
    """Lit la config IA runtime (surchargée dynamiquement via /api/ai/config)."""
    return _runtime_config.get(key, default)


async def load_runtime_config():
    doc = await db.settings.find_one({"key": "ai_config"}, {"_id": 0})
    if doc and isinstance(doc.get("value"), dict):
        _runtime_config.update(doc["value"])
    # Config ByteTrack (P0 finalisation)
    bt = await db.settings.find_one({"key": "bytetrack_config"}, {"_id": 0})
    if bt and isinstance(bt.get("value"), dict):
        _bytetrack_cfg.update(bt["value"])
    logger.info("Config IA runtime chargée : %s (bytetrack=%s)",
                _runtime_config or "(défauts env)", _bytetrack_cfg.get("enabled", False))


async def refresh_per_camera_configs():
    """Recharge les configs ANPR par caméra depuis la base (rafraîchi à chaque cycle IA)."""
    cams = await db.cameras.find({"detect_enabled": True},
                                  {"_id": 0, "id": 1, "anpr_config": 1}).to_list(500)
    _camera_anpr_cfg.clear()
    for c in cams:
        cfg = c.get("anpr_config") or {}
        if cfg:
            _camera_anpr_cfg[c["id"]] = cfg


def _point_in_polygon(x_norm: float, y_norm: float, poly: list) -> bool:
    """Test point-in-polygon (algo ray casting) sur coordonnées normalisées 0-1."""
    if not poly or len(poly) < 3:
        return True  # pas de ROI → accepte partout
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if ((yi > y_norm) != (yj > y_norm)) and \
           (x_norm < (xj - xi) * (y_norm - yi) / ((yj - yi) or 1e-9) + xi):
            inside = not inside
        j = i
    return inside


async def update_runtime_config(patch: dict) -> dict:
    _runtime_config.update({k: v for k, v in patch.items() if v is not None})
    await db.settings.update_one(
        {"key": "ai_config"},
        {"$set": {"key": "ai_config", "value": _runtime_config}},
        upsert=True,
    )
    return dict(_runtime_config)


def get_runtime_config() -> dict:
    return {
        "interval_seconds": _cfg("interval_seconds", AI_INTERVAL),
        "confidence": _cfg("confidence", AI_CONFIDENCE),
        "min_plate_px": _cfg("min_plate_px", AI_MIN_PLATE_PX),
        "plate_cache_seconds": _cfg("plate_cache_seconds", AI_PLATE_CACHE_SECONDS),
        "device": _cfg("device", AI_DEVICE),
        "device_effective": _detected_device(),
    }

CLASS_FR = {
    "person": "Personne", "car": "Voiture", "truck": "Camion", "bus": "Bus",
    "motorcycle": "Moto", "bicycle": "Vélo", "dog": "Animal", "cat": "Animal",
}
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle"}

_model = None
_alpr = None
_cooldowns: dict[str, datetime] = {}
_prev_gray: dict[str, "object"] = {}
# Cache LAPI : {(camera_id, plate) -> expiry_datetime}
_plate_cache: dict[tuple[str, str], datetime] = {}
_last_debug: dict[str, dict] = {}  # per-camera debug snapshot (mode #4)

# ByteTrack (P0 finalisation) : un tracker par caméra
_trackers: dict[str, "object"] = {}
_bytetrack_cfg: dict = {}
# Config ANPR par caméra (chargée à chaud)
_camera_anpr_cfg: dict[str, dict] = {}


def _detected_device() -> str:
    """Détecte la meilleure cible d'inférence : cuda si dispo, sinon cpu."""
    pref = _cfg("device", AI_DEVICE)
    if pref == "cpu":
        return "cpu"
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda:0"
    except Exception:
        pass
    return "cpu"


def _load_models():
    """Chargement paresseux (YOLO + ALPR) dans un thread — cible GPU si dispo."""
    global _model, _alpr
    device = _detected_device()
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO(os.environ.get("AI_MODEL", "yolo11n.pt"))
        try:
            _model.to(device)
        except Exception:
            device = "cpu"
        logger.info("Modèle YOLO chargé (device=%s) : %s", device, os.environ.get("AI_MODEL", "yolo11n.pt"))
    if _alpr is None:
        try:
            from fast_alpr import ALPR
            _alpr = ALPR(detector_model="yolo-v9-t-384-license-plate-end2end",
                         ocr_model="european-plates-mobile-vit-v2-model")
            logger.info("LAPI locale chargée (fast-alpr, CPU-ONNX)")
        except Exception:
            logger.exception("fast-alpr indisponible — LAPI désactivée")
            _alpr = False


def _jpeg_data_uri(bgr_img, max_width: int = 360):
    import cv2
    if bgr_img is None or bgr_img.size == 0:
        return None
    h, w = bgr_img.shape[:2]
    if w > max_width:
        bgr_img = cv2.resize(bgr_img, (max_width, int(h * max_width / w)))
    ok, buf = cv2.imencode(".jpg", bgr_img, [cv2.IMWRITE_JPEG_QUALITY, 60])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else None


def _dominant_color_fr(bgr_crop):
    """Couleur dominante réelle (analyse HSV) — nommage français."""
    import cv2
    import numpy as np
    if bgr_crop is None or bgr_crop.size == 0:
        return None
    hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
    h, s, v = (hsv[:, :, i].astype(np.float32) for i in range(3))
    mean_s, mean_v = float(s.mean()), float(v.mean())
    if mean_v < 60:
        return "Noir"
    if mean_s < 45:
        if mean_v > 170:
            return "Blanc"
        return "Gris"
    # Teinte dominante (histogramme pondéré par la saturation)
    hist = cv2.calcHist([hsv], [0], None, [180], [0, 180]).flatten()
    hue = int(hist.argmax())
    if hue < 8 or hue >= 168:
        return "Rouge"
    if hue < 20:
        return "Orange"
    if hue < 33:
        return "Jaune"
    if hue < 85:
        return "Vert"
    if hue < 130:
        return "Bleu"
    if hue < 150:
        return "Violet"
    return "Rose"


def _detect_motion(camera_id: str, img) -> float:
    """Détection de mouvement réelle : % de pixels changés entre deux frames."""
    import cv2
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)
    prev = _prev_gray.get(camera_id)
    _prev_gray[camera_id] = gray
    if prev is None or prev.shape != gray.shape:
        return 0.0
    diff = cv2.absdiff(prev, gray)
    changed = (diff > 25).sum()
    return round(changed * 100.0 / diff.size, 2)


def _analyze_frame(camera_id: str, frame_bytes: bytes) -> dict:
    """Mouvement + YOLO d'abord (rapide), puis ALPR uniquement si véhicule détecté et hors-cache.
    Retourne aussi les timings ms par étape et un snapshot pour le mode debug."""
    import cv2
    import numpy as np
    import time
    _load_models()
    t0 = time.monotonic()
    img = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"detections": [], "plates": [], "motion_pct": 0.0}
    h, w = img.shape[:2]

    t_dec = (time.monotonic() - t0) * 1000
    t1 = time.monotonic()
    motion_pct = _detect_motion(camera_id, img)
    t_motion = (time.monotonic() - t1) * 1000

    # ---------- ÉTAPE 1 : YOLO (rapide) ----------
    t2 = time.monotonic()
    results = _model.predict(img, conf=_cfg("confidence", AI_CONFIDENCE),
                             device=_detected_device(), verbose=False)[0]
    t_yolo = (time.monotonic() - t2) * 1000
    detections, vehicles = [], []
    for box in results.boxes:
        cls_name = _model.names[int(box.cls)]
        if cls_name not in CLASS_FR:
            continue
        x1, y1, x2, y2 = (max(0, int(v)) for v in box.xyxy[0])
        crop = img[y1:y2, x1:x2]
        is_vehicle = cls_name in VEHICLE_CLASSES
        det = {
            "class": cls_name, "label": CLASS_FR[cls_name],
            "confidence": round(float(box.conf), 2),
            "thumbnail": _jpeg_data_uri(crop),
            "vehicle_color": _dominant_color_fr(crop) if is_vehicle else None,
            "bbox": (x1, y1, x2, y2),
        }
        detections.append(det)
        if is_vehicle:
            vehicles.append(det)

    # ---------- ÉTAPE 2 : ALPR uniquement si véhicule + hors cache ----------
    plates = []
    t_alpr = 0.0
    plate_debug = []
    anpr_cfg = _camera_anpr_cfg.get(camera_id, {}) or {}
    roi = anpr_cfg.get("roi_polygon") or []
    if vehicles and _alpr:
        now = datetime.now(timezone.utc)
        # Purge cache expiré
        for k, exp in list(_plate_cache.items()):
            if exp <= now:
                _plate_cache.pop(k, None)
        cache_ttl = int(_cfg("plate_cache_seconds", AI_PLATE_CACHE_SECONDS))
        min_side = int(_cfg("min_plate_px", AI_MIN_PLATE_PX))
        # Confiance minimum spécifique à cette caméra
        min_conf = float(anpr_cfg.get("min_confidence", 0.0) or 0.0)
        t3 = time.monotonic()
        try:
            for r in _alpr.predict(img):
                if not r.ocr or not r.ocr.text:
                    continue
                bb = r.detection.bounding_box
                pw, ph = bb.x2 - bb.x1, bb.y2 - bb.y1
                if pw < min_side or ph < min_side:
                    plate_debug.append({"plate": r.ocr.text.upper(), "skipped": "trop petit",
                                         "size": f"{pw}x{ph}"})
                    continue
                # ROI polygonale (test sur le centre de la plaque en coords normalisées)
                cx_norm = ((bb.x1 + bb.x2) / 2) / w
                cy_norm = ((bb.y1 + bb.y2) / 2) / h
                if roi and not _point_in_polygon(cx_norm, cy_norm, roi):
                    plate_debug.append({"plate": r.ocr.text.upper(), "skipped": "hors ROI",
                                         "size": f"{pw}x{ph}"})
                    continue
                if float(r.ocr.confidence) < min_conf:
                    plate_debug.append({"plate": r.ocr.text.upper(), "skipped": "conf<seuil",
                                         "size": f"{pw}x{ph}", "conf": round(float(r.ocr.confidence), 2)})
                    continue
                plate_text = r.ocr.text.upper().strip()
                if not plate_text:
                    continue
                if (camera_id, plate_text) in _plate_cache:
                    plate_debug.append({"plate": plate_text, "skipped": "cache",
                                         "expires_in": int((_plate_cache[(camera_id, plate_text)] - now).total_seconds())})
                    continue
                _plate_cache[(camera_id, plate_text)] = now + timedelta(seconds=cache_ttl)
                px, py = (bb.x1 + bb.x2) / 2, (bb.y1 + bb.y2) / 2
                owner = next((v for v in vehicles
                              if v["bbox"][0] <= px <= v["bbox"][2] and v["bbox"][1] <= py <= v["bbox"][3]),
                             max(vehicles, key=lambda v: (v["bbox"][2]-v["bbox"][0])*(v["bbox"][3]-v["bbox"][1])))
                vx1, vy1, vx2, vy2 = owner["bbox"]
                plate_crop = img[max(0, bb.y1):bb.y2, max(0, bb.x1):bb.x2]
                plates.append({
                    "plate": plate_text,
                    "confidence": round(float(r.ocr.confidence), 2),
                    "plate_crop": _jpeg_data_uri(plate_crop, 240),
                    "vehicle_crop": _jpeg_data_uri(img[vy1:vy2, vx1:vx2]),
                    "vehicle_type": owner["label"],
                    "vehicle_color": owner["vehicle_color"],
                })
                plate_debug.append({"plate": plate_text, "confidence": round(float(r.ocr.confidence), 2),
                                     "size": f"{pw}x{ph}", "kept": True})
        except Exception:
            logger.exception("Erreur LAPI")
        t_alpr = (time.monotonic() - t3) * 1000
    for d in detections:
        d["_bbox"] = d.pop("bbox", None)
    timings = {"decode_ms": round(t_dec, 1), "motion_ms": round(t_motion, 1),
               "yolo_ms": round(t_yolo, 1), "alpr_ms": round(t_alpr, 1),
               "total_ms": round((time.monotonic() - t0) * 1000, 1)}
    # Snapshot debug (mode #4)
    _last_debug[camera_id] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "resolution": f"{w}x{h}",
        "device": _detected_device(),
        "timings": timings,
        "vehicles": [{"label": v["label"], "confidence": v["confidence"], "bbox": v["_bbox"] if "_bbox" in v else v.get("bbox"),
                      "vehicle_color": v.get("vehicle_color")} for v in vehicles],
        "plate_attempts": plate_debug,
        "plates_ocr": [{"plate": p["plate"], "confidence": p["confidence"]} for p in plates],
        "motion_pct": motion_pct,
        "frame_preview": _jpeg_data_uri(img, 640),
    }
    # Overlay LIVE (P0.2) : bboxes normalisées 0-1 pour scaling côté client
    overlay_boxes = []
    for d in detections:
        bx = d.get("_bbox") or d.get("bbox")
        if not bx:
            continue
        x1, y1, x2, y2 = bx
        overlay_boxes.append({
            "cls": d["class"], "label": d["label"], "confidence": d["confidence"],
            "vehicle_color": d.get("vehicle_color"),
            "bbox_norm": [round(x1 / w, 4), round(y1 / h, 4), round(x2 / w, 4), round(y2 / h, 4)],
        })
    counts: dict = {}
    for d in detections:
        counts[d["label"]] = counts.get(d["label"], 0) + 1

    # ---------- ÉTAPE 3 : ByteTrack (tracking persistant si activé) ----------
    tracks_map: dict = {}
    if _bytetrack_cfg.get("enabled") and detections:
        try:
            import supervision as sv
            import numpy as np
            tracker = _trackers.get(camera_id)
            if tracker is None:
                tracker = sv.ByteTrack(
                    track_activation_threshold=float(_bytetrack_cfg.get("track_thresh", 0.5)),
                    lost_track_buffer=int(_bytetrack_cfg.get("track_buffer", 30)),
                    minimum_matching_threshold=float(_bytetrack_cfg.get("match_thresh", 0.8)),
                )
                _trackers[camera_id] = tracker
            # Construit Detections à partir des bboxes YOLO
            xyxy = np.array([d["_bbox"] for d in detections], dtype=float)
            confs = np.array([d["confidence"] for d in detections], dtype=float)
            class_ids = np.array([hash(d["class"]) % 1000 for d in detections], dtype=int)
            sv_dets = sv.Detections(xyxy=xyxy, confidence=confs, class_id=class_ids)
            tracked = tracker.update_with_detections(sv_dets)
            for i, tid in enumerate(tracked.tracker_id or []):
                if tid is None:
                    continue
                bbox = tuple(int(v) for v in tracked.xyxy[i])
                tracks_map[bbox] = int(tid)
            # Attache track_id à chaque détection matchée (par bbox proche)
            for d in detections:
                bx = tuple(d["_bbox"])
                d["track_id"] = tracks_map.get(bx)
            # Overlay boxes: append track_id label
            for i, ob in enumerate(overlay_boxes if False else []):
                pass  # fait plus bas via reconstruction
        except Exception:
            logger.exception("ByteTrack : erreur (désactivation temporaire)")
    # Attache track_id sur overlay_boxes également
    for i, d in enumerate(detections):
        if i < len(overlay_boxes):
            overlay_boxes[i]["track_id"] = d.get("track_id")

    return {"detections": detections, "plates": plates, "motion_pct": motion_pct,
            "frame_thumb": _jpeg_data_uri(img), "timings": timings,
            "overlay_boxes": overlay_boxes, "counts": counts}


def get_debug_snapshot(camera_id: str) -> dict:
    """Retourne le dernier snapshot debug (mode #4) pour une caméra donnée."""
    return _last_debug.get(camera_id, {})


def analyze_image_local(image_bytes: bytes) -> dict:
    """Analyse LOCALE d'une image (upload manuel) : YOLO + fast-alpr.
    Renvoie plate, country, vehicle_color, vehicle_make, vehicle_model, vehicle_type, confidence.
    Aucune dépendance cloud."""
    import cv2
    import numpy as np
    _load_models()
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"plate": "", "confidence": 0.0}
    result = {"plate": "", "country": "", "vehicle_color": "", "vehicle_make": "",
              "vehicle_model": "", "vehicle_type": "Inconnu", "confidence": 0.0, "plate_crop": ""}
    # Détection véhicule (YOLO) → type + couleur
    yr = _model.predict(img, conf=AI_CONFIDENCE, verbose=False)[0]
    best_vehicle = None
    for box in yr.boxes:
        cls_name = _model.names[int(box.cls)]
        if cls_name not in VEHICLE_CLASSES:
            continue
        x1, y1, x2, y2 = (max(0, int(v)) for v in box.xyxy[0])
        area = (x2 - x1) * (y2 - y1)
        if best_vehicle is None or area > best_vehicle[1]:
            best_vehicle = ((x1, y1, x2, y2), area, CLASS_FR.get(cls_name, "Inconnu"),
                            _dominant_color_fr(img[y1:y2, x1:x2]))
    if best_vehicle:
        result["vehicle_type"] = best_vehicle[2]
        result["vehicle_color"] = best_vehicle[3] or ""
    # Plaque via fast-alpr
    if _alpr:
        try:
            for r in _alpr.predict(img):
                if not r.ocr or not r.ocr.text:
                    continue
                bb = r.detection.bounding_box
                result["plate"] = r.ocr.text.upper()
                result["confidence"] = round(float(r.ocr.confidence), 2)
                crop = img[max(0, bb.y1):bb.y2, max(0, bb.x1):bb.x2]
                result["plate_crop"] = _jpeg_data_uri(crop, 240) or ""
                break
        except Exception:
            logger.exception("Erreur LAPI locale (upload)")
    return result


async def _fetch_frame(camera_id: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(f"{GO2RTC_URL}/api/frame.jpeg", params={"src": f"cam_{camera_id}"})
            if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
                return r.content
    except httpx.HTTPError:
        pass
    return None


async def _raise_blacklist_alert(cam: dict, plate_doc: dict, reason: str):
    from notifications import send_notification
    alert = {
        "id": str(uuid.uuid4()), "type": "anpr", "severity": "critical",
        "message": f"Plaque en liste noire détectée : {plate_doc['plate']} ({reason})",
        "camera_id": cam["id"], "camera_name": cam["name"],
        "site_id": cam.get("site_id", ""), "site_name": cam.get("site_name", ""),
        "plate": plate_doc["plate"], "plate_id": plate_doc["id"],
        "plate_crop": plate_doc.get("plate_crop"),
        "acknowledged": False, "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await db.alerts.insert_one(dict(alert))
    alert.pop("_id", None)
    await broadcast_alert(alert)
    try:
        await send_notification("ALERTE LAPI — LISTE NOIRE",
                                f"Plaque {plate_doc['plate']} détectée sur {cam['name']} ({alert['site_name']})\n{reason}")
    except Exception:
        pass


def _cooldown_ok(key: str, seconds: int, now: datetime) -> bool:
    if key in _cooldowns and now - _cooldowns[key] < timedelta(seconds=seconds):
        return False
    _cooldowns[key] = now
    return True


# ============ Scénarios d'alertes IA (heuristiques réelles sur signaux YOLO/mouvement) ============
DEFAULT_SCENARIOS = {
    "intrusion_nocturne": {"enabled": True, "severity": "critical", "night_start": 22, "night_end": 6,
                           "label": "Intrusion / effraction possible (présence nocturne)"},
    "rodeur": {"enabled": True, "severity": "warning", "consecutive": 3,
               "label": "Comportement suspect (personne qui s'attarde)"},
    "attroupement": {"enabled": True, "severity": "warning", "min_persons": 4,
                     "label": "Attroupement de personnes"},
    "vive_allure": {"enabled": True, "severity": "warning", "motion_pct": 12.0,
                    "label": "Véhicule à vive allure"},
    "collision": {"enabled": True, "severity": "critical", "iou": 0.15,
                  "label": "Collision possible entre véhicules (accident)"},
    "enfant_route": {"enabled": True, "severity": "critical", "ratio": 0.55,
                     "label": "Enfant possible sur la chaussée"},
    "vol_vehicule": {"enabled": True, "severity": "critical", "night_start": 22, "night_end": 6,
                     "label": "Vol / cambriolage possible (personne près d'un véhicule la nuit)"},
}


async def _get_scenario_rules() -> dict:
    doc = await db.settings.find_one({"key": "ai_alert_rules"}, {"_id": 0})
    rules = {k: dict(v) for k, v in DEFAULT_SCENARIOS.items()}
    if doc:
        for key, override in (doc.get("value") or {}).items():
            if key in rules and isinstance(override, dict):
                rules[key].update(override)
    return rules


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union else 0.0


def _is_night(now: datetime, start_h: int, end_h: int) -> bool:
    h = now.hour
    return h >= start_h or h < end_h if start_h > end_h else start_h <= h < end_h


_presence: dict[str, int] = {}


async def _raise_scenario_alert(cam: dict, scenario: str, rule: dict, message: str, thumb) -> None:
    now = datetime.now(timezone.utc)
    if not _cooldown_ok(f"{cam['id']}:scenario:{scenario}", 180, now):
        return
    alert = {
        "id": str(uuid.uuid4()), "type": "ai_scenario", "scenario": scenario,
        "severity": rule.get("severity", "warning"),
        "message": f"{rule['label']} — {cam['name']}" + (f" · {message}" if message else ""),
        "camera_id": cam["id"], "camera_name": cam["name"],
        "site_id": cam.get("site_id", ""), "site_name": cam.get("site_name", ""),
        "thumbnail": thumb,
        "acknowledged": False, "timestamp": now.isoformat(),
    }
    await db.alerts.insert_one(dict(alert))
    alert.pop("_id", None)
    await broadcast_alert(alert)
    if alert["severity"] == "critical":
        try:
            from notifications import send_notification
            await send_notification(f"ALERTE IA — {rule['label']}",
                                    f"Caméra {cam['name']} ({cam.get('site_name','')})\n{message}")
        except Exception:
            pass


# ============ Armement planifié (les scénarios ne sonnent que si le système est armé) ============
DEFAULT_ARMING = {"mode": "always", "days": [0, 1, 2, 3, 4, 5, 6], "start_h": 0, "end_h": 24}


async def get_arming_config() -> dict:
    doc = await db.settings.find_one({"key": "arming_schedule"}, {"_id": 0})
    return {**DEFAULT_ARMING, **((doc or {}).get("value") or {})}


async def _is_armed(now: datetime) -> bool:
    cfg = await get_arming_config()
    if cfg["mode"] == "off":
        return False
    if cfg["mode"] == "always":
        return True
    if now.weekday() not in (cfg.get("days") or []):
        return False
    h, s, e = now.hour, int(cfg["start_h"]), int(cfg["end_h"])
    return s <= h < e if s < e else (h >= s or h < e)


async def _evaluate_scenarios(cam: dict, result: dict, now: datetime) -> None:
    if not await _is_armed(now):
        return
    rules = await _get_scenario_rules()
    dets = result["detections"]
    persons = [d for d in dets if d["class"] == "person" and d.get("_bbox")]
    vehicles = [d for d in dets if d["class"] in VEHICLE_CLASSES and d.get("_bbox")]
    thumb = result.get("frame_thumb")

    # Persistance de présence humaine (rôdeur)
    _presence[cam["id"]] = _presence.get(cam["id"], 0) + 1 if persons else 0

    r = rules["intrusion_nocturne"]
    if r["enabled"] and persons and _is_night(now, int(r["night_start"]), int(r["night_end"])):
        await _raise_scenario_alert(cam, "intrusion_nocturne", r,
                                    f"{len(persons)} personne(s) détectée(s) en période de surveillance", thumb)

    r = rules["vol_vehicule"]
    if r["enabled"] and persons and vehicles and _is_night(now, int(r["night_start"]), int(r["night_end"])):
        await _raise_scenario_alert(cam, "vol_vehicule", r,
                                    "personne à proximité d'un véhicule en période nocturne", thumb)

    r = rules["rodeur"]
    if r["enabled"] and _presence[cam["id"]] >= int(r["consecutive"]):
        await _raise_scenario_alert(cam, "rodeur", r,
                                    f"présence continue depuis ~{_presence[cam['id']] * int(AI_INTERVAL)} s", thumb)

    r = rules["attroupement"]
    if r["enabled"] and len(persons) >= int(r["min_persons"]):
        await _raise_scenario_alert(cam, "attroupement", r, f"{len(persons)} personnes simultanées", thumb)

    r = rules["vive_allure"]
    if r["enabled"] and vehicles and result["motion_pct"] >= float(r["motion_pct"]):
        await _raise_scenario_alert(cam, "vive_allure", r,
                                    f"mouvement {result['motion_pct']}% avec véhicule en scène", thumb)

    r = rules["collision"]
    if r["enabled"] and len(vehicles) >= 2:
        for i in range(len(vehicles)):
            done = False
            for j in range(i + 1, len(vehicles)):
                if _iou(vehicles[i]["_bbox"], vehicles[j]["_bbox"]) >= float(r["iou"]):
                    await _raise_scenario_alert(cam, "collision", r,
                                                f"chevauchement {vehicles[i]['label']}/{vehicles[j]['label']}", thumb)
                    done = True
                    break
            if done:
                break

    r = rules["enfant_route"]
    if r["enabled"] and vehicles and len(persons) >= 2:
        heights = sorted((p["_bbox"][3] - p["_bbox"][1]) for p in persons)
        median = heights[len(heights) // 2]
        if median > 0 and heights[0] < median * float(r["ratio"]):
            await _raise_scenario_alert(cam, "enfant_route", r,
                                        "silhouette de petite taille détectée près de véhicules", thumb)


async def _process_camera(cam: dict) -> None:
    frame = await _fetch_frame(cam["id"])
    if frame is None:
        logger.info("IA · %s (%s) : frame indisponible (flux offline)", cam["name"], cam["id"])
        return
    result = await asyncio.to_thread(_analyze_frame, cam["id"], frame)
    dets = result.get("detections", [])
    plates = result.get("plates", [])
    tim = result.get("timings", {})
    logger.info(
        "IA · %s (%s) : %d détection(s) [%s] · mouvement=%.1f%% · %d plaque(s) · yolo=%.0fms alpr=%.0fms",
        cam["name"], cam["id"], len(dets),
        ",".join(f"{d['label']}:{d['confidence']}" for d in dets) or "aucune",
        result.get("motion_pct", 0.0), len(plates),
        tim.get("yolo_ms", 0), tim.get("alpr_ms", 0),
    )
    # Diffuse l'overlay au frontend (Live View)
    try:
        from realtime import broadcast_ai_detections
        await broadcast_ai_detections(cam["id"], cam.get("site_id", ""), {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "boxes": result.get("overlay_boxes", []),
            "counts": result.get("counts", {}),
            "motion_pct": result.get("motion_pct", 0.0),
        })
    except Exception:
        logger.exception("broadcast_ai_detections error")
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    base = {
        "camera_id": cam["id"], "camera_name": cam["name"],
        "site_id": cam.get("site_id", ""), "site_name": cam.get("site_name", ""),
        "timestamp": now_iso,
    }

    # Mouvement réel
    if result["motion_pct"] >= MOTION_THRESHOLD_PCT and _cooldown_ok(f"{cam['id']}:motion", MOTION_COOLDOWN, now):
        await db.events.insert_one({
            "id": str(uuid.uuid4()), "type": "Mouvement", **base,
            "confidence": None, "motion_pct": result["motion_pct"],
            "thumbnail": result.get("frame_thumb"), "vehicle_color": None,
        })

    # Détections YOLO
    for det in result["detections"]:
        if not _cooldown_ok(f"{cam['id']}:{det['class']}", EVENT_COOLDOWN, now):
            continue
        await db.events.insert_one({
            "id": str(uuid.uuid4()), "type": det["label"], **base,
            "confidence": det["confidence"], "thumbnail": det["thumbnail"],
            "vehicle_color": det.get("vehicle_color"),
            "track_id": det.get("track_id"),
        })

    # Scénarios d'alertes IA (accident, rôdeur, intrusion nocturne, vive allure...)
    await _evaluate_scenarios(cam, result, now)

    # Plaques LAPI
    anpr_cfg_cam = _camera_anpr_cfg.get(cam["id"], {}) or {}
    wl_local = set(anpr_cfg_cam.get("whitelist_local", []) or [])
    bl_local = set(anpr_cfg_cam.get("blacklist_local", []) or [])
    for p in result["plates"]:
        recent = await db.plates.find_one({
            "plate": p["plate"], "camera_id": cam["id"],
            "timestamp": {"$gte": (now - timedelta(seconds=EVENT_COOLDOWN)).isoformat()},
        })
        if recent:
            continue
        # Priorité liste locale caméra > liste globale watchlist
        if p["plate"] in bl_local:
            list_status = "black"; wl = {"reason": "Liste noire locale caméra"}
        elif p["plate"] in wl_local:
            list_status = "white"; wl = None
        else:
            wl = await db.watchlist.find_one({"plate": p["plate"]}, {"_id": 0})
            list_status = wl["list_type"] if wl else "none"
        doc = {
            "id": str(uuid.uuid4()), "plate": p["plate"], **base,
            "confidence": p["confidence"],
            "vehicle_color": p.get("vehicle_color"), "vehicle_make": None, "vehicle_model": None,
            "vehicle_type": p.get("vehicle_type"),
            "country": (anpr_cfg_cam.get("country_override")
                         or (await _get_global_anpr_country())),
            "direction": None,
            "lat": cam.get("lat"), "lng": cam.get("lng"),
            "list_status": list_status,
            "vehicle_crop": p.get("vehicle_crop"), "plate_crop": p.get("plate_crop"),
        }
        await db.plates.insert_one(dict(doc))
        doc.pop("_id", None)
        if list_status == "black":
            await _raise_blacklist_alert(cam, doc, (wl or {}).get("reason", ""))


async def _get_global_anpr_country() -> str | None:
    doc = await db.settings.find_one({"key": "anpr_config"}, {"_id": 0})
    return ((doc or {}).get("value", {}) or {}).get("country")


async def ai_loop() -> None:
    """Boucle IA : analyse en parallèle chaque caméra `detect_enabled`.
    Chaque caméra devient un worker indépendant → une caméra lente ne bloque plus les autres."""
    await asyncio.sleep(15)  # laisse les flux démarrer
    try:
        await asyncio.to_thread(_load_models)
    except Exception:
        logger.exception("Chargement des modèles IA impossible — boucle IA désactivée")
        return
    await load_runtime_config()
    logger.info("Moteur IA démarré (YOLO+ALPR/caméra en parallèle · device=%s · intervalle=%.1fs)",
                _detected_device(), _cfg("interval_seconds", AI_INTERVAL))
    while True:
        try:
            await refresh_per_camera_configs()
            await load_runtime_config()  # rafraîchit bytetrack + IA globale
            cams = await db.cameras.find({"detect_enabled": True, "status": "online"}, {"_id": 0}).to_list(200)
            if cams:
                logger.info("IA · cycle : %d caméra(s) réelle(s) en parallèle %s",
                            len(cams), [c["name"] for c in cams])
                # Workers indépendants : une caméra lente ne bloque pas les autres
                await asyncio.gather(*[_process_camera(cam) for cam in cams], return_exceptions=True)
        except Exception:
            logger.exception("ai_loop : erreur, reprise")
        await asyncio.sleep(float(_cfg("interval_seconds", AI_INTERVAL)))
