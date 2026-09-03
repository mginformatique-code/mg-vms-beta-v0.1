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
# v3.23 · Config armement/règles déplacée dans ai_rules_settings.py (étape 2a
# du chantier séparation pipeline/API — aucun état mutable par le pipeline
# dans ces fonctions, juste des constantes + de la config Mongo, aucune
# raison de les garder ici). Comportement inchangé, import direct.
from ai_rules_settings import (DEFAULT_ARMING, DEFAULT_SCENARIOS,  # noqa: F401
                                _get_scenario_rules, _is_armed, get_arming_config)

logger = logging.getLogger("pipeline_v2.scenarios")

_cooldowns: dict[str, datetime] = {}
_presence: dict[str, int] = {}


def cooldown_ok(key: str, seconds: int, now: datetime) -> bool:
    if key in _cooldowns and now - _cooldowns[key] < timedelta(seconds=seconds):
        return False
    _cooldowns[key] = now
    return True


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
