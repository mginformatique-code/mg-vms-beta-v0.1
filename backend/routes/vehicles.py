"""MG-VMS v0.6 · Smart ANPR History — Vehicle Timeline API.

Cette route agrège la collection ``plates`` sans jamais modifier le
pipeline OCR ni les endpoints ``/api/plates`` existants.

Endpoints (tous read-only) :

  GET  /api/vehicles                           liste agrégée (cartes)
  GET  /api/vehicles/{plate}                   fiche complète
  GET  /api/vehicles/{plate}/passages          galerie paginée
  GET  /api/vehicles/{plate}/heatmap           by_hour[24] + by_dow[7]
  GET  /api/vehicles/{plate}/cameras           passages par caméra
  GET  /api/vehicles/{plate}/journey           transitions caméra→caméra
  GET  /api/vehicles/{plate}/habits            présence habituelle
  GET  /api/vehicles/{plate}/identity          stub v0.6 (préparation v0.7)
  GET  /api/vehicles/passage/{id}/thumb        image binaire JPEG (base64→bytes)

Le champ ``list_status`` (watchlist) et le moteur OCR ne sont **pas**
modifiés — cette couche est purement additive.
"""
from __future__ import annotations

import base64
import io
import logging
from collections import Counter
from datetime import datetime, timezone
from statistics import mean
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from auth import require_permission
from database import db

logger = logging.getLogger("routes.vehicles")

vehicles_router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════
def _majority(values: list) -> Optional[str]:
    """Retourne la valeur la plus fréquente, en ignorant None/empty."""
    filtered = [v for v in values if v]
    if not filtered:
        return None
    return Counter(filtered).most_common(1)[0][0]


def _iso_to_dt(iso: str) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None


def _to_hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


async def _base_match(user: dict, plate_filter: Optional[str] = None,
                       camera_id: Optional[str] = None,
                       date_from: Optional[str] = None,
                       date_to: Optional[str] = None) -> dict:
    """Construit le $match Mongo standard (avec site_scope)."""
    q: dict = {}
    if plate_filter:
        q["plate"] = {"$regex": plate_filter.upper().replace(" ", ""), "$options": "i"}
    if camera_id:
        q["camera_id"] = camera_id
    if date_from or date_to:
        rng = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["timestamp"] = rng
    # site_scope respecte l'appartenance de l'utilisateur.
    try:
        from routers import site_scope
        site_scope(q, user)
    except Exception:
        pass
    return q


async def _plate_or_404(plate: str, user: dict) -> str:
    """Normalise + vérifie qu'au moins une lecture existe pour cette plaque."""
    normalized = plate.upper().replace(" ", "").replace("-", "")
    q = await _base_match(user)
    q["plate"] = {"$regex": normalized, "$options": "i"}
    count = await db.plates.count_documents(q)
    if count == 0:
        raise HTTPException(status_code=404,
                            detail={"error": "vehicle_not_found",
                                    "message": f"Aucune lecture pour la plaque '{plate}'"})
    return normalized


# ═══════════════════════════════════════════════════════════════════
# 1. Liste agrégée — /api/vehicles
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("")
async def list_vehicles(
    q: Optional[str] = Query(None, description="Substring plaque"),
    camera_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_permission("read_plates")),
):
    """Liste agrégée des véhicules détectés (une entrée par plaque)."""
    match = await _base_match(user, plate_filter=q, camera_id=camera_id,
                                date_from=date_from, date_to=date_to)

    pipeline = [
        {"$match": match},
        # On trie déjà par timestamp desc pour que $first == dernière lecture.
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id": "$plate",
            "passages_count": {"$sum": 1},
            "last_seen":  {"$first": "$timestamp"},
            "first_seen": {"$last":  "$timestamp"},
            "cameras":    {"$addToSet": "$camera_id"},
            "makes":      {"$push": "$vehicle_make"},
            "models":     {"$push": "$vehicle_model"},
            "colors":     {"$push": "$vehicle_color"},
            "types":      {"$push": "$vehicle_type"},
            "confidences": {"$push": "$confidence"},
            # 3 dernières passes (thumbnails preview)
            "preview_docs": {"$push": {
                "id": "$id",
                "confidence": "$confidence",
                "has_frame": {"$gt": [{"$strLenBytes": {"$ifNull": ["$frame_thumb", ""]}}, 100]},
                "has_vehicle": {"$gt": [{"$strLenBytes": {"$ifNull": ["$vehicle_crop", ""]}}, 100]},
                "has_plate": {"$gt": [{"$strLenBytes": {"$ifNull": ["$plate_crop", ""]}}, 100]},
            }},
            "watch": {"$first": "$list_status"},
        }},
        {"$sort": {"last_seen": -1}},
        {"$skip": offset},
        {"$limit": limit},
    ]

    docs = await db.plates.aggregate(pipeline).to_list(length=limit)

    # Total pour pagination (compte les plaques distinctes).
    distinct_count_pipeline = [
        {"$match": match},
        {"$group": {"_id": "$plate"}},
        {"$count": "total"},
    ]
    tot_docs = await db.plates.aggregate(distinct_count_pipeline).to_list(1)
    total = tot_docs[0]["total"] if tot_docs else 0

    items = []
    for d in docs:
        preview = list(d.get("preview_docs") or [])[:3]  # 3 plus récents
        best = preview[0] if preview else None
        conf_list = [c for c in (d.get("confidences") or []) if isinstance(c, (int, float))]
        items.append({
            "plate": d["_id"],
            "passages_count": d["passages_count"],
            "first_seen": d.get("first_seen"),
            "last_seen": d.get("last_seen"),
            "cameras_count": len(d.get("cameras") or []),
            "vehicle_make": _majority(d.get("makes") or []),
            "vehicle_model": _majority(d.get("models") or []),
            "vehicle_color": _majority(d.get("colors") or []),
            "vehicle_type": _majority(d.get("types") or []),
            "avg_confidence": round(mean(conf_list), 3) if conf_list else None,
            "best_thumb_id": (best or {}).get("id"),
            "preview_thumb_ids": [p["id"] for p in preview if p.get("has_frame") or p.get("has_vehicle") or p.get("has_plate")],
            "list_status": d.get("watch") or "none",
        })
    return {"total": total, "count": len(items), "items": items}


# ═══════════════════════════════════════════════════════════════════
# 2. Fiche véhicule — /api/vehicles/{plate}
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}")
async def vehicle_detail(plate: str,
                          user: dict = Depends(require_permission("read_plates"))):
    normalized = await _plate_or_404(plate, user)
    match = await _base_match(user)
    match["plate"] = {"$regex": normalized, "$options": "i"}

    pipeline = [
        {"$match": match},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id": "$plate",
            "passages_count": {"$sum": 1},
            "last_seen":  {"$first": "$timestamp"},
            "first_seen": {"$last":  "$timestamp"},
            "cameras":    {"$addToSet": "$camera_id"},
            "makes":      {"$push": "$vehicle_make"},
            "models":     {"$push": "$vehicle_model"},
            "colors":     {"$push": "$vehicle_color"},
            "types":      {"$push": "$vehicle_type"},
            "confidences": {"$push": "$confidence"},
            "best_thumb_id": {"$first": "$id"},
            "engines":    {"$addToSet": "$engine"},
            "watch": {"$first": "$list_status"},
        }},
    ]
    docs = await db.plates.aggregate(pipeline).to_list(1)
    d = docs[0]
    conf = [c for c in (d.get("confidences") or []) if isinstance(c, (int, float))]

    # Durée moyenne de présence (approx : temps entre 1re et dernière passe par jour).
    daily_pipeline = [
        {"$match": match},
        {"$sort": {"timestamp": 1}},
        {"$project": {"day": {"$substr": ["$timestamp", 0, 10]}, "ts": "$timestamp"}},
        {"$group": {"_id": "$day",
                    "first": {"$min": "$ts"}, "last": {"$max": "$ts"}}},
    ]
    daily = await db.plates.aggregate(daily_pipeline).to_list(length=None)
    durations_min = []
    for row in daily:
        a = _iso_to_dt(row["first"])
        b = _iso_to_dt(row["last"])
        if a and b and b > a:
            durations_min.append((b - a).total_seconds() / 60.0)
    avg_visit = int(round(mean(durations_min))) if durations_min else None

    return {
        "plate": d["_id"],
        "passages_count": d["passages_count"],
        "first_seen": d.get("first_seen"),
        "last_seen": d.get("last_seen"),
        "cameras_count": len(d.get("cameras") or []),
        "avg_confidence": round(mean(conf), 3) if conf else None,
        "vehicle_make": _majority(d.get("makes") or []),
        "vehicle_model": _majority(d.get("models") or []),
        "vehicle_color": _majority(d.get("colors") or []),
        "vehicle_type": _majority(d.get("types") or []),
        "avg_visit_duration_min": avg_visit,
        "best_thumb_id": d.get("best_thumb_id"),
        "engines": [e for e in (d.get("engines") or []) if e],
        "list_status": d.get("watch") or "none",
    }


# ═══════════════════════════════════════════════════════════════════
# 3. Galerie chronologique — /passages
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}/passages")
async def vehicle_passages(plate: str,
                            limit: int = Query(50, ge=1, le=200),
                            offset: int = Query(0, ge=0),
                            user: dict = Depends(require_permission("read_plates"))):
    normalized = await _plate_or_404(plate, user)
    q = await _base_match(user)
    q["plate"] = {"$regex": normalized, "$options": "i"}

    total = await db.plates.count_documents(q)
    docs = await db.plates.find(q, {"_id": 0}).sort("timestamp", -1) \
                          .skip(offset).limit(limit).to_list(limit)

    items = []
    for p in docs:
        items.append({
            "id": p.get("id"),
            "timestamp": p.get("timestamp"),
            "camera_id": p.get("camera_id"),
            "camera_name": p.get("camera_name"),
            "confidence": p.get("confidence"),
            "engine": p.get("engine") or "fast-alpr",
            "direction": p.get("direction"),
            "has_frame": bool((p.get("frame_thumb") or "").strip()),
            "has_vehicle": bool((p.get("vehicle_crop") or "").strip()),
            "has_plate": bool((p.get("plate_crop") or "").strip()),
        })
    return {"total": total, "count": len(items), "offset": offset, "items": items}


# ═══════════════════════════════════════════════════════════════════
# 4. Heatmap — /heatmap
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}/heatmap")
async def vehicle_heatmap(plate: str,
                           user: dict = Depends(require_permission("read_plates"))):
    normalized = await _plate_or_404(plate, user)
    q = await _base_match(user)
    q["plate"] = {"$regex": normalized, "$options": "i"}

    by_hour = [0] * 24
    by_dow = [0] * 7  # 0 = Lundi
    docs = await db.plates.find(q, {"timestamp": 1, "_id": 0}).to_list(length=None)
    for d in docs:
        dt = _iso_to_dt(d.get("timestamp"))
        if not dt:
            continue
        by_hour[dt.hour] += 1
        # Python weekday() : Monday=0
        by_dow[dt.weekday()] += 1

    return {
        "by_hour": by_hour,
        "by_dow": by_dow,
        "dow_labels": ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"],
    }


# ═══════════════════════════════════════════════════════════════════
# 5. Caméras visitées — /cameras
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}/cameras")
async def vehicle_cameras(plate: str,
                           user: dict = Depends(require_permission("read_plates"))):
    normalized = await _plate_or_404(plate, user)
    match = await _base_match(user)
    match["plate"] = {"$regex": normalized, "$options": "i"}
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": "$camera_id",
            "camera_name": {"$first": "$camera_name"},
            "count": {"$sum": 1},
            "last_seen": {"$max": "$timestamp"},
            "first_seen": {"$min": "$timestamp"},
        }},
        {"$sort": {"count": -1}},
    ]
    docs = await db.plates.aggregate(pipeline).to_list(length=None)
    return {"items": [
        {"camera_id": d["_id"], "camera_name": d.get("camera_name"),
         "count": d["count"], "last_seen": d.get("last_seen"),
         "first_seen": d.get("first_seen")}
        for d in docs
    ]}


# ═══════════════════════════════════════════════════════════════════
# 6. Parcours — /journey
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}/journey")
async def vehicle_journey(plate: str,
                           limit: int = Query(50, ge=5, le=200),
                           user: dict = Depends(require_permission("read_plates"))):
    normalized = await _plate_or_404(plate, user)
    q = await _base_match(user)
    q["plate"] = {"$regex": normalized, "$options": "i"}
    docs = await db.plates.find(
        q, {"_id": 0, "timestamp": 1, "camera_id": 1, "camera_name": 1, "direction": 1}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    # Renvoyé chronologique décroissant (plus récent en tête).
    return {"items": docs}


# ═══════════════════════════════════════════════════════════════════
# 7. Habitudes — /habits
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}/habits")
async def vehicle_habits(plate: str,
                          user: dict = Depends(require_permission("read_plates"))):
    normalized = await _plate_or_404(plate, user)
    q = await _base_match(user)
    q["plate"] = {"$regex": normalized, "$options": "i"}

    docs = await db.plates.find(q, {"timestamp": 1, "_id": 0}).to_list(length=None)
    times: list[datetime] = []
    for d in docs:
        dt = _iso_to_dt(d.get("timestamp"))
        if dt:
            times.append(dt)
    if not times:
        return {"typical": None, "typical_days": [], "nocturnal_first_seen": None,
                "nocturnal_note": None}

    # Sépare arrivées (heures matinales < 12h) et départs (>= 12h) — heuristique simple.
    arrivals = [t for t in times if t.hour < 12]
    departures = [t for t in times if t.hour >= 12]

    def _range(hs: list[datetime]) -> Optional[str]:
        if not hs:
            return None
        minutes = [t.hour * 60 + t.minute for t in hs]
        lo = min(minutes)
        hi = max(minutes)
        return f"{lo//60:02d}:{lo%60:02d} → {hi//60:02d}:{hi%60:02d}"

    # Jours d'activité prédominants (>10 % du total).
    dow_counter = Counter(t.weekday() for t in times)
    total = len(times)
    labels = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    typical_days = [labels[d] for d, c in dow_counter.items() if c / total >= 0.10]
    typical_days.sort(key=lambda x: labels.index(x))

    # Première apparition nocturne (22h-06h) sans historique nocturne préalable.
    nocturnal = [t for t in times if t.hour >= 22 or t.hour < 6]
    nocturnal_first = None
    nocturnal_note = None
    if nocturnal:
        nocturnal_first = min(nocturnal).isoformat()
        # Ce véhicule est-il "nocturne habituel" ?
        if len(nocturnal) / total < 0.05:
            nocturnal_note = "Rare — jamais observé auparavant entre 22h et 06h"

    return {
        "typical_arrival": _range(arrivals),
        "typical_departure": _range(departures),
        "typical_days": typical_days,
        "nocturnal_first_seen": nocturnal_first,
        "nocturnal_note": nocturnal_note,
    }


# ═══════════════════════════════════════════════════════════════════
# 8. Vehicle Identity — STUB v0.6 (préparation v0.7)
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/{plate}/identity")
async def vehicle_identity(plate: str,
                            user: dict = Depends(require_permission("read_plates"))):
    """Stub v0.6 — l'agrégation d'identité cross-plate est prévue pour v0.7.

    L'architecture retourne actuellement une identité 1:1 avec la plaque.
    En v0.7, ``identity_id`` regroupera plusieurs plaques (changement
    de plaque tout en reconnaissant le même véhicule via couleur / marque /
    silhouette).
    """
    normalized = await _plate_or_404(plate, user)
    return {
        "identity_id": None,
        "plate": normalized,
        "linked_plates": [],
        "enabled": False,
        "reason": "vehicle_identity_disabled_v06",
        "note": "Architecture prête — matching cross-plate activé en v0.7.",
    }


# ═══════════════════════════════════════════════════════════════════
# 8b. Anomalies (Habitudes → Alertes) — v0.6b
# ═══════════════════════════════════════════════════════════════════
async def _compute_anomaly(plate: str, user: dict) -> dict:
    """Calcule un rapport d'anomalie pour la **dernière** passe d'un véhicule.

    Compare le dernier timestamp aux habitudes calculées (arrivée typique,
    départ typique, jours prédominants, historique nocturne) et renvoie :

        {
          "plate": "...",
          "last_seen": "...",
          "anomalies": ["off_hours", "off_days", "nocturnal_first", ...],
          "severity": "info" | "warning" | "high",
          "message": "phrase explicative",
          "habits": {typical_arrival, typical_departure, typical_days, ...},
        }
    """
    normalized = plate.upper().replace(" ", "").replace("-", "")
    q = await _base_match(user)
    q["plate"] = {"$regex": normalized, "$options": "i"}

    docs = await db.plates.find(
        q, {"_id": 0, "timestamp": 1, "camera_name": 1}
    ).sort("timestamp", -1).limit(2000).to_list(2000)
    if not docs:
        return {"plate": normalized, "anomalies": [], "severity": "info",
                "message": "aucune donnée"}

    last_iso = docs[0].get("timestamp")
    last_dt = _iso_to_dt(last_iso)
    if not last_dt:
        return {"plate": normalized, "anomalies": [], "severity": "info",
                "message": "timestamp illisible"}

    # Historique (hors dernière passe) pour calcul de norme.
    history = [d for d in docs[1:] if _iso_to_dt(d.get("timestamp"))]
    if len(history) < 5:
        return {
            "plate": normalized, "last_seen": last_iso,
            "anomalies": ["insufficient_history"], "severity": "info",
            "message": "Historique insuffisant pour évaluer les habitudes (< 5 passes).",
            "habits": None,
        }

    hist_dts = [_iso_to_dt(d["timestamp"]) for d in history]
    hours = [d.hour * 60 + d.minute for d in hist_dts]
    dows = Counter(d.weekday() for d in hist_dts)
    total = len(hist_dts)

    # Arrivées/départs habituels
    arrivals = [h for h, dt in zip(hours, hist_dts) if dt.hour < 12]
    departures = [h for h, dt in zip(hours, hist_dts) if dt.hour >= 12]
    arr_min = min(arrivals) if arrivals else None
    arr_max = max(arrivals) if arrivals else None
    dep_min = min(departures) if departures else None
    dep_max = max(departures) if departures else None

    labels = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    typical_days = [labels[d] for d, c in dows.items() if c / total >= 0.10]

    # Analyse du LAST passage
    last_min = last_dt.hour * 60 + last_dt.minute
    last_dow = last_dt.weekday()
    anomalies = []
    reasons = []

    # 1. Hors des heures habituelles ? (>60 min hors fenêtre arr/dep)
    in_arr = arr_min is not None and arr_max is not None and arr_min - 60 <= last_min <= arr_max + 60
    in_dep = dep_min is not None and dep_max is not None and dep_min - 60 <= last_min <= dep_max + 60
    if not in_arr and not in_dep and last_dt.hour >= 6 and last_dt.hour < 22:
        anomalies.append("off_hours")
        reasons.append(f"Passage à {last_dt.strftime('%H:%M')} hors des créneaux habituels")

    # 2. Jour inhabituel ? (dow avec < 5 % de l'historique)
    if dows[last_dow] / total < 0.05:
        anomalies.append("off_days")
        reasons.append(f"Passage un {labels[last_dow]} — jour rarement observé")

    # 3. Nocturne (22h–06h) alors que rarement observé nocturne ?
    if last_dt.hour >= 22 or last_dt.hour < 6:
        nocturnal_count = sum(1 for d in hist_dts if d.hour >= 22 or d.hour < 6)
        if nocturnal_count == 0:
            anomalies.append("nocturnal_first")
            reasons.append("Première apparition nocturne (22h–06h) jamais observée auparavant")
        elif nocturnal_count / total < 0.05:
            anomalies.append("nocturnal_rare")
            reasons.append("Passage nocturne rare")

    # Sévérité
    if "nocturnal_first" in anomalies or ("off_hours" in anomalies and "off_days" in anomalies):
        severity = "high"
    elif anomalies:
        severity = "warning"
    else:
        severity = "info"

    return {
        "plate": normalized,
        "last_seen": last_iso,
        "camera_name": docs[0].get("camera_name"),
        "anomalies": anomalies,
        "severity": severity,
        "message": " · ".join(reasons) if reasons else "Aucune anomalie détectée.",
        "habits": {
            "typical_arrival": (
                f"{arr_min//60:02d}:{arr_min%60:02d} → {arr_max//60:02d}:{arr_max%60:02d}"
                if arr_min is not None else None),
            "typical_departure": (
                f"{dep_min//60:02d}:{dep_min%60:02d} → {dep_max//60:02d}:{dep_max%60:02d}"
                if dep_min is not None else None),
            "typical_days": typical_days,
        },
    }


@vehicles_router.get("/{plate}/anomaly")
async def vehicle_anomaly(plate: str,
                           user: dict = Depends(require_permission("read_plates"))):
    """Analyse d'anomalie de la dernière passe (lecture seule)."""
    await _plate_or_404(plate, user)
    return await _compute_anomaly(plate, user)


@vehicles_router.get("/anomalies/recent")
async def vehicles_anomalies_recent(
    since_hours: int = Query(24, ge=1, le=720),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_permission("read_plates")),
):
    """Liste des véhicules avec anomalies détectées sur les X dernières heures.

    Retourne uniquement ceux dont le rapport a une sévérité `warning` ou `high`.
    """
    since_dt = datetime.now(timezone.utc).timestamp() - since_hours * 3600
    match = await _base_match(user)
    # Distinct plates seen since_hours ago
    pipe = [
        {"$match": match},
        {"$sort": {"timestamp": -1}},
        {"$group": {"_id": "$plate", "last_seen": {"$first": "$timestamp"}}},
        {"$sort": {"last_seen": -1}},
        {"$limit": 300},  # borne dure pour la charge CPU
    ]
    recent_plates = await db.plates.aggregate(pipe).to_list(300)
    out = []
    for row in recent_plates:
        last = _iso_to_dt(row.get("last_seen"))
        if not last or last.timestamp() < since_dt:
            continue
        try:
            report = await _compute_anomaly(row["_id"], user)
        except Exception:
            continue
        if report.get("severity") in ("warning", "high"):
            out.append(report)
        if len(out) >= limit:
            break
    # Sort by severity + last_seen
    order = {"high": 0, "warning": 1, "info": 2}
    out.sort(key=lambda r: (order.get(r["severity"], 3), -(_iso_to_dt(r["last_seen"]).timestamp())))
    return {"count": len(out), "items": out}


@vehicles_router.post("/{plate}/notify-anomaly")
async def vehicle_notify_anomaly(plate: str,
                                  user: dict = Depends(require_permission("read_plates"))):
    """Envoie une notification (SMTP/Discord/Telegram) sur les anomalies
    détectées pour ce véhicule. Ne modifie pas le pipeline OCR — appel manuel
    depuis le drawer véhicule."""
    await _plate_or_404(plate, user)
    report = await _compute_anomaly(plate, user)
    if not report.get("anomalies") or report["severity"] == "info":
        raise HTTPException(status_code=400,
                            detail={"error": "no_anomaly",
                                    "message": "Aucune anomalie à notifier."})

    from notifications import send_notification
    subject = f"Anomalie véhicule {plate} · {report['severity'].upper()}"
    body = (f"Plaque : {plate}\n"
            f"Dernière détection : {report.get('last_seen')} sur {report.get('camera_name') or 'caméra inconnue'}\n"
            f"Anomalies : {', '.join(report['anomalies'])}\n"
            f"{report['message']}")
    results = await send_notification(subject=subject, body=body)
    return {"sent": results, "report": report}


# ═══════════════════════════════════════════════════════════════════
# 9. Thumbnail binaire — /passage/{id}/thumb
# ═══════════════════════════════════════════════════════════════════
@vehicles_router.get("/passage/{passage_id}/thumb")
async def passage_thumb(passage_id: str,
                         kind: str = Query("frame", regex="^(frame|vehicle|plate)$"),
                         user: dict = Depends(require_permission("read_plates"))):
    """Sert le thumbnail JPEG (binaire) associé à une passe ANPR.

    Le champ stocké en base64 (data URL) est décodé et streamé comme
    ``image/jpeg`` — évite de faire transiter du base64 dans les listes.
    """
    field = {"frame": "frame_thumb", "vehicle": "vehicle_crop", "plate": "plate_crop"}[kind]
    doc = await db.plates.find_one({"id": passage_id}, {field: 1, "plate": 1, "_id": 0})
    if not doc or not doc.get(field):
        raise HTTPException(status_code=404, detail={"error": "thumb_not_found"})

    b64 = doc[field]
    # Supprime le préfixe "data:image/…;base64," si présent
    if isinstance(b64, str) and "," in b64:
        b64 = b64.split(",", 1)[1]
    try:
        blob = base64.b64decode(b64)
    except Exception:
        raise HTTPException(status_code=500, detail={"error": "thumb_decode_error"})
    headers = {"Cache-Control": "public, max-age=86400, immutable"}
    return StreamingResponse(io.BytesIO(blob), media_type="image/jpeg", headers=headers)
