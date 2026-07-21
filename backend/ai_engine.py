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
AI_INTERVAL = float(os.environ.get("AI_INTERVAL_SECONDS", "6"))
AI_CONFIDENCE = float(os.environ.get("AI_CONFIDENCE", "0.45"))
EVENT_COOLDOWN = int(os.environ.get("AI_EVENT_COOLDOWN_SECONDS", "60"))
MOTION_THRESHOLD_PCT = float(os.environ.get("MOTION_THRESHOLD_PCT", "1.5"))
MOTION_COOLDOWN = int(os.environ.get("MOTION_COOLDOWN_SECONDS", "60"))

CLASS_FR = {
    "person": "Personne", "car": "Voiture", "truck": "Camion", "bus": "Bus",
    "motorcycle": "Moto", "bicycle": "Vélo", "dog": "Animal", "cat": "Animal",
}
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle"}

_model = None
_alpr = None
_cooldowns: dict[str, datetime] = {}
_prev_gray: dict[str, "object"] = {}


def _load_models():
    """Chargement paresseux (YOLO + ALPR) dans un thread."""
    global _model, _alpr
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO(os.environ.get("AI_MODEL", "yolo11n.pt"))
        logger.info("Modèle YOLO chargé : %s", os.environ.get("AI_MODEL", "yolo11n.pt"))
    if _alpr is None:
        try:
            from fast_alpr import ALPR
            _alpr = ALPR(detector_model="yolo-v9-t-384-license-plate-end2end",
                         ocr_model="european-plates-mobile-vit-v2-model")
            logger.info("LAPI locale chargée (fast-alpr)")
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
    """Mouvement + YOLO + LAPI sur une frame (bloquant → thread)."""
    import cv2
    import numpy as np
    _load_models()
    img = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"detections": [], "plates": [], "motion_pct": 0.0}

    motion_pct = _detect_motion(camera_id, img)

    results = _model.predict(img, conf=AI_CONFIDENCE, verbose=False)[0]
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

    plates = []
    if vehicles and _alpr:
        try:
            for r in _alpr.predict(img):
                if not r.ocr or not r.ocr.text:
                    continue
                bb = r.detection.bounding_box
                px, py = (bb.x1 + bb.x2) / 2, (bb.y1 + bb.y2) / 2
                # véhicule englobant la plaque (sinon le plus grand)
                owner = next((v for v in vehicles
                              if v["bbox"][0] <= px <= v["bbox"][2] and v["bbox"][1] <= py <= v["bbox"][3]),
                             max(vehicles, key=lambda v: (v["bbox"][2]-v["bbox"][0])*(v["bbox"][3]-v["bbox"][1])))
                vx1, vy1, vx2, vy2 = owner["bbox"]
                plate_crop = img[max(0, bb.y1):bb.y2, max(0, bb.x1):bb.x2]
                plates.append({
                    "plate": r.ocr.text.upper(),
                    "confidence": round(float(r.ocr.confidence), 2),
                    "plate_crop": _jpeg_data_uri(plate_crop, 240),
                    "vehicle_crop": _jpeg_data_uri(img[vy1:vy2, vx1:vx2]),
                    "vehicle_type": owner["label"],
                    "vehicle_color": owner["vehicle_color"],
                })
        except Exception:
            logger.exception("Erreur LAPI")
    for d in detections:
        d["_bbox"] = d.pop("bbox", None)
    return {"detections": detections, "plates": plates, "motion_pct": motion_pct,
            "frame_thumb": _jpeg_data_uri(img)}


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
    logger.info(
        "IA · %s (%s) : %d détection(s) [%s] · mouvement=%.1f%% · %d plaque(s)",
        cam["name"], cam["id"], len(dets),
        ",".join(f"{d['label']}:{d['confidence']}" for d in dets) or "aucune",
        result.get("motion_pct", 0.0), len(plates),
    )
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
        })

    # Scénarios d'alertes IA (accident, rôdeur, intrusion nocturne, vive allure...)
    await _evaluate_scenarios(cam, result, now)

    # Plaques LAPI
    for p in result["plates"]:
        recent = await db.plates.find_one({
            "plate": p["plate"], "camera_id": cam["id"],
            "timestamp": {"$gte": (now - timedelta(seconds=EVENT_COOLDOWN)).isoformat()},
        })
        if recent:
            continue
        wl = await db.watchlist.find_one({"plate": p["plate"]}, {"_id": 0})
        list_status = wl["list_type"] if wl else "none"
        doc = {
            "id": str(uuid.uuid4()), "plate": p["plate"], **base,
            "confidence": p["confidence"],
            "vehicle_color": p.get("vehicle_color"), "vehicle_make": None, "vehicle_model": None,
            "vehicle_type": p.get("vehicle_type"),
            "country": None, "direction": None,
            "lat": cam.get("lat"), "lng": cam.get("lng"),
            "list_status": list_status,
            "vehicle_crop": p.get("vehicle_crop"), "plate_crop": p.get("plate_crop"),
        }
        await db.plates.insert_one(dict(doc))
        doc.pop("_id", None)
        if list_status == "black":
            await _raise_blacklist_alert(cam, doc, wl.get("reason", ""))


async def ai_loop() -> None:
    """Boucle IA : analyse les caméras `detect_enabled` à intervalle régulier."""
    await asyncio.sleep(15)  # laisse les flux démarrer
    try:
        await asyncio.to_thread(_load_models)
    except Exception:
        logger.exception("Chargement des modèles IA impossible — boucle IA désactivée")
        return
    logger.info("Moteur IA démarré (YOLO + mouvement + scénarios + LAPI, intervalle %ss)", AI_INTERVAL)
    while True:
        try:
            cams = await db.cameras.find({"detect_enabled": True, "status": "online"}, {"_id": 0}).to_list(200)
            if cams:
                logger.info("IA · cycle : %d caméra(s) réelle(s) à analyser %s",
                            len(cams), [c["name"] for c in cams])
            for cam in cams:
                await _process_camera(cam)
        except Exception:
            logger.exception("ai_loop : erreur, reprise")
        await asyncio.sleep(AI_INTERVAL)
