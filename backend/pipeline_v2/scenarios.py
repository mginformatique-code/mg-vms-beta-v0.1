"""Pipeline v2 · Scénarios d'alertes IA + armement — logique métier sortie de ai_engine.

Heuristiques réelles sur signaux YOLO/mouvement : intrusion nocturne, rôdeur,
attroupement, vive allure, collision, enfant sur route, vol de véhicule.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from database import db
from realtime import broadcast_alert

logger = logging.getLogger("pipeline_v2.scenarios")

_cooldowns: dict[str, datetime] = {}
_presence: dict[str, int] = {}


def cooldown_ok(key: str, seconds: int, now: datetime) -> bool:
    if key in _cooldowns and now - _cooldowns[key] < timedelta(seconds=seconds):
        return False
    _cooldowns[key] = now
    return True


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

DEFAULT_ARMING = {"mode": "always", "days": [0, 1, 2, 3, 4, 5, 6], "start_h": 0, "end_h": 24}


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


async def _raise_scenario_alert(cam: dict, scenario: str, rule: dict,
                                message: str, thumb) -> None:
    now = datetime.now(timezone.utc)
    if not cooldown_ok(f"{cam['id']}:scenario:{scenario}", 180, now):
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


async def _raise_blacklist_alert(cam: dict, plate_doc: dict, reason: str):
    from notifications import send_notification
    alert = {
        "id": str(uuid.uuid4()), "type": "anpr", "severity": "critical",
        "message": f"Plaque en liste noire détectée : {plate_doc['plate']} ({reason})",
        "camera_id": cam["id"], "camera_name": cam["name"],
        "site_id": cam.get("site_id", ""), "site_name": cam.get("site_name", ""),
        "plate": plate_doc["plate"], "plate_id": plate_doc["id"],
        "thumbnail": plate_doc.get("frame_thumb") or plate_doc.get("vehicle_crop") or plate_doc.get("plate_crop"),
        "plate_crop": plate_doc.get("plate_crop"),
        "vehicle_crop": plate_doc.get("vehicle_crop"),
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


async def _evaluate_scenarios(cam: dict, result: dict, now: datetime) -> None:
    if not await _is_armed(now):
        return
    import ai_engine as _ae  # lazy — respecte les monkeypatch de _ensure_frame_thumb
    rules = await _get_scenario_rules()
    dets = result["detections"]
    persons = [d for d in dets if d["class"] == "person" and d.get("_bbox")]
    vehicles = [d for d in dets if d["class"] in _ae.VEHICLE_CLASSES and d.get("_bbox")]
    thumb = lambda: _ae._ensure_frame_thumb(result)  # noqa: E731

    _presence[cam["id"]] = _presence.get(cam["id"], 0) + 1 if persons else 0

    r = rules["intrusion_nocturne"]
    if r["enabled"] and persons and _is_night(now, int(r["night_start"]), int(r["night_end"])):
        await _raise_scenario_alert(cam, "intrusion_nocturne", r,
                                    f"{len(persons)} personne(s) détectée(s) en période de surveillance", thumb())

    r = rules["vol_vehicule"]
    if r["enabled"] and persons and vehicles and _is_night(now, int(r["night_start"]), int(r["night_end"])):
        await _raise_scenario_alert(cam, "vol_vehicule", r,
                                    "personne à proximité d'un véhicule en période nocturne", thumb())

    r = rules["rodeur"]
    if r["enabled"] and _presence[cam["id"]] >= int(r["consecutive"]):
        await _raise_scenario_alert(cam, "rodeur", r,
                                    f"présence continue depuis ~{_presence[cam['id']] * int(_ae.AI_INTERVAL)} s", thumb())

    r = rules["attroupement"]
    if r["enabled"] and len(persons) >= int(r["min_persons"]):
        await _raise_scenario_alert(cam, "attroupement", r, f"{len(persons)} personnes simultanées", thumb())

    r = rules["vive_allure"]
    if r["enabled"] and vehicles and result["motion_pct"] >= float(r["motion_pct"]):
        await _raise_scenario_alert(cam, "vive_allure", r,
                                    f"mouvement {result['motion_pct']}% avec véhicule en scène", thumb())

    r = rules["collision"]
    if r["enabled"] and len(vehicles) >= 2:
        for i in range(len(vehicles)):
            done = False
            for j in range(i + 1, len(vehicles)):
                if _iou(vehicles[i]["_bbox"], vehicles[j]["_bbox"]) >= float(r["iou"]):
                    await _raise_scenario_alert(cam, "collision", r,
                                                f"chevauchement {vehicles[i]['label']}/{vehicles[j]['label']}", thumb())
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
                                        "silhouette de petite taille détectée près de véhicules", thumb())
