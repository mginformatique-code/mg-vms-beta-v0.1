"""v0.8-rc1 · Camera Health Score — score 0-100 par caméra.

Agrège en 1 métrique lisible les signaux suivants (déjà collectés
ailleurs dans le backend) :

  * FPS réel vs attendu                        (poids 25%)
  * Taux d'erreurs pipeline (60s glissantes)   (poids 20%)
  * Qualité moyenne des crops plaque            (poids 15%)
  * Fiabilité RTSP (frame_source last_ok)       (poids 15%)
  * Latence pipeline p95 vs SLA                 (poids 10%)
  * Fraîcheur ONVIF (dernier heartbeat)         (poids 10%)
  * Ancienneté du dernier événement             (poids  5%)

Retourne :
  {
    "score": 0-100,
    "band": "healthy" | "degraded" | "critical",
    "signals": {…}, "reasons": [ "…" ]
  }
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from database import db

logger = logging.getLogger("camera_health")


BANDS = [(80, "healthy"), (55, "degraded"), (0, "critical")]


def _band(score: float) -> str:
    for threshold, name in BANDS:
        if score >= threshold:
            return name
    return "critical"


async def compute_health(camera_id: str) -> dict:
    """Calcule le score de santé d'une caméra à partir des sources disponibles."""
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        return {"error": "camera_not_found", "camera_id": camera_id}

    signals: dict = {}
    reasons: list[str] = []
    total_weight = 0.0
    weighted_sum = 0.0

    def _add(label: str, value_pct: float, weight: float, hint: str = "") -> None:
        nonlocal weighted_sum, total_weight
        v = max(0.0, min(100.0, value_pct))
        signals[label] = {"pct": round(v, 1), "weight": weight, "hint": hint}
        weighted_sum += v * weight
        total_weight += weight
        if v < 40:
            reasons.append(f"{label}: {hint or f'{v:.0f}%'}")

    # ── 1) FPS réel vs attendu ────────────────────────────────
    try:
        from pipeline_v2.inspector import inspector
        snap = inspector.snapshot()
        cam_snap = (snap.get("cameras") or {}).get(camera_id, {})
        fps_real = cam_snap.get("fps") or 0.0
        fps_expected = cam.get("target_fps") or 10.0
        fps_pct = min(100.0, (fps_real / max(fps_expected, 0.1)) * 100)
        _add("fps", fps_pct, 25.0,
             hint=f"réel {fps_real:.1f} / attendu {fps_expected:.0f}")
        # ── 2) Erreurs pipeline ─────────────────────────────────
        stages = cam_snap.get("stages") or {}
        total_errors = sum(int(s.get("errors") or 0) for s in stages.values())
        total_calls = sum(int(s.get("calls") or 0) for s in stages.values()) or 1
        err_rate = total_errors / total_calls
        _add("pipeline_reliability", (1 - err_rate) * 100, 20.0,
             hint=f"{total_errors} err / {total_calls} calls")
        # ── 5) Latence p95 vs SLA 200ms ────────────────────────
        total_p95 = max((s.get("p95_60s") or 0) for s in stages.values()) if stages else 0
        sla_pct = 100.0 if total_p95 <= 100 else max(0.0, 100 - (total_p95 - 100) / 3)
        _add("latency_p95", sla_pct, 10.0, hint=f"p95 max {total_p95:.0f}ms (SLA 200)")
    except Exception as e:
        logger.debug("inspector snapshot unavailable: %s", e)
        _add("fps", 50, 25.0, hint="metric N/A")
        _add("pipeline_reliability", 50, 20.0, hint="metric N/A")
        _add("latency_p95", 50, 10.0, hint="metric N/A")

    # ── 3) Qualité moyenne crops plaque (60 dernières lectures) ──
    try:
        cursor = db.plates.find({"camera_id": camera_id},
                                 {"_id": 0, "confidence": 1, "timestamp": 1}
                                ).sort("timestamp", -1).limit(60)
        confs = [p.get("confidence", 0) async for p in cursor]
        avg_conf = (sum(confs) / len(confs)) * 100 if confs else 60
        _add("ocr_quality", avg_conf, 15.0,
             hint=f"conf moy. {avg_conf:.0f}% sur {len(confs)} plaques")
    except Exception:
        _add("ocr_quality", 60, 15.0, hint="pas de plaques récentes")

    # ── 4) Fiabilité RTSP (frame_source) ────────────────────
    try:
        import frame_source
        st = frame_source.status()
        w = (st.get("workers") or {}).get(camera_id)
        if w:
            last_ok = w.get("last_frame_ts") or 0
            age = time.time() - last_ok if last_ok else 999
            rtsp_pct = 100 if age < 5 else max(0.0, 100 - (age - 5) * 5)
            _add("rtsp", rtsp_pct, 15.0, hint=f"dernier frame il y a {age:.1f}s")
        else:
            _add("rtsp", 100 if cam.get("status") == "online" else 20, 15.0,
                 hint="worker non actif")
    except Exception:
        _add("rtsp", 60, 15.0, hint="metric N/A")

    # ── 6) Fraîcheur ONVIF (dernier heartbeat) ───────────────
    onvif_last = cam.get("onvif_last_seen") or cam.get("updated_at")
    if onvif_last:
        try:
            dt = datetime.fromisoformat(str(onvif_last).replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60
            onvif_pct = 100 if age_min < 5 else max(0.0, 100 - (age_min - 5))
            _add("onvif_freshness", onvif_pct, 10.0, hint=f"il y a {age_min:.0f} min")
        except Exception:
            _add("onvif_freshness", 60, 10.0, hint="parse ts échec")
    else:
        _add("onvif_freshness", 40, 10.0, hint="pas d'heartbeat ONVIF")

    # ── 7) Fraîcheur dernier événement ──────────────────────
    try:
        last_ev = await db.events.find_one({"camera_id": camera_id},
                                            {"_id": 0, "timestamp": 1},
                                            sort=[("timestamp", -1)])
        if last_ev and last_ev.get("timestamp"):
            dt = datetime.fromisoformat(str(last_ev["timestamp"]).replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60
            ev_pct = 100 if age_min < 60 else max(0.0, 100 - (age_min - 60) / 6)
            _add("event_freshness", ev_pct, 5.0, hint=f"dernier évt il y a {age_min:.0f} min")
        else:
            _add("event_freshness", 60, 5.0, hint="aucun événement")
    except Exception:
        _add("event_freshness", 60, 5.0, hint="metric N/A")

    score = round(weighted_sum / max(total_weight, 0.1), 1)
    return {
        "camera_id": camera_id,
        "camera_name": cam.get("name"),
        "score": score,
        "band": _band(score),
        "signals": signals,
        "reasons": reasons[:5],
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


async def compute_all_health() -> list[dict]:
    cams = await db.cameras.find({}, {"_id": 0, "id": 1}).to_list(500)
    out = []
    for c in cams:
        try:
            out.append(await compute_health(c["id"]))
        except Exception:
            logger.exception("compute_health failed for %s", c.get("id"))
    return out
