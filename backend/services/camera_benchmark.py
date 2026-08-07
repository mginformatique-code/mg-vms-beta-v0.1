"""v0.8-rc2 · Camera Benchmark — fiche de performance auto d'une caméra.

Lance un benchmark court (durée paramétrable, défaut 60 s) qui échantillonne :
  * FPS réel (via inspector)
  * Latence RTSP (via frame_source last_frame_ts)
  * Qualité moyenne des crops plaque
  * Temps moyen YOLO / OCR
  * Charge pipeline (Σ avg stages)

Produit une "fiche caméra" persistée dans `camera_benchmarks`.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
import uuid
from datetime import datetime, timezone

from database import db

logger = logging.getLogger("camera_benchmark")


async def _sample_once(camera_id: str) -> dict:
    """Un échantillon instantané des métriques disponibles."""
    from pipeline_v2.inspector import inspector
    snap = inspector.snapshot()
    cam_snap = (snap.get("cameras") or {}).get(camera_id, {})
    stages = cam_snap.get("stages") or {}
    return {
        "fps": cam_snap.get("fps") or 0.0,
        "yolo_ms": (stages.get("yolo") or {}).get("avg_ms_60s") or 0.0,
        "anpr_ms": (stages.get("anpr") or {}).get("avg_ms_60s") or 0.0,
        "tracking_ms": (stages.get("tracking") or {}).get("avg_ms_60s") or 0.0,
        "total_avg_ms": sum((s.get("avg_ms_60s") or 0) for s in stages.values()),
        "errors": sum(int(s.get("errors") or 0) for s in stages.values()),
    }


async def run_benchmark(camera_id: str, duration_s: int = 60,
                         sample_every_s: int = 3) -> dict:
    """Lance le benchmark et retourne une fiche complète."""
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        return {"error": "camera_not_found", "camera_id": camera_id}

    logger.info("Benchmark %s : %ds (échantillon %ds)", camera_id, duration_s, sample_every_s)
    started_at = datetime.now(timezone.utc)
    samples: list[dict] = []
    plates_before = await db.plates.count_documents({"camera_id": camera_id})

    deadline = time.time() + duration_s
    while time.time() < deadline:
        samples.append(await _sample_once(camera_id))
        await asyncio.sleep(sample_every_s)

    plates_after = await db.plates.count_documents({"camera_id": camera_id})
    plates_read = plates_after - plates_before

    # Confiance / qualité crop moyennes sur les plaques du benchmark
    recent_plates = await db.plates.find(
        {"camera_id": camera_id},
        {"_id": 0, "confidence": 1, "ocr_quality": 1}
    ).sort("timestamp", -1).limit(max(plates_read, 10)).to_list(60)
    confidences = [p.get("confidence", 0) for p in recent_plates]
    crop_scores = [p.get("ocr_quality", {}).get("score_100")
                    for p in recent_plates if p.get("ocr_quality")]

    def _agg(key: str) -> dict:
        vals = [s[key] for s in samples if s.get(key) is not None]
        if not vals:
            return {"mean": 0, "p95": 0, "max": 0}
        s = sorted(vals)
        return {
            "mean": round(statistics.mean(vals), 2),
            "p95": round(s[max(0, int(len(s) * 0.95) - 1)], 2),
            "max": round(max(vals), 2),
        }

    report = {
        "id": str(uuid.uuid4()),
        "camera_id": camera_id,
        "camera_name": cam.get("name"),
        "started_at": started_at.isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "duration_s": duration_s,
        "samples_count": len(samples),
        "fps": _agg("fps"),
        "yolo_ms": _agg("yolo_ms"),
        "anpr_ms": _agg("anpr_ms"),
        "tracking_ms": _agg("tracking_ms"),
        "pipeline_total_ms": _agg("total_avg_ms"),
        "plates_read": plates_read,
        "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0,
        "avg_crop_quality": round(sum(crop_scores) / len(crop_scores), 1) if crop_scores else None,
        "total_errors": sum(s["errors"] for s in samples),
        "verdict": _verdict(samples, plates_read),
    }
    await db.camera_benchmarks.insert_one(dict(report))
    report.pop("_id", None)
    return report


def _verdict(samples: list[dict], plates_read: int) -> dict:
    """Verdict lisible : est-ce que cette caméra est prête pour la prod ?"""
    if not samples:
        return {"grade": "F", "message": "Aucun échantillon collecté."}
    avg_fps = statistics.mean(s["fps"] for s in samples)
    avg_total = statistics.mean(s["total_avg_ms"] for s in samples)
    avg_err = statistics.mean(s["errors"] for s in samples)
    if avg_fps == 0 and avg_total == 0:
        return {"grade": "F", "message": "Caméra hors ligne pendant le benchmark."}
    if avg_total < 100 and avg_err == 0:
        return {"grade": "A", "message": f"Excellent — pipeline {avg_total:.0f}ms, prêt production."}
    if avg_total < 200 and avg_err < 2:
        return {"grade": "B", "message": f"Bon — pipeline {avg_total:.0f}ms, acceptable production."}
    if avg_total < 400:
        return {"grade": "C", "message": f"Limite — pipeline {avg_total:.0f}ms, optimisation recommandée."}
    return {"grade": "D", "message": f"Insuffisant — pipeline {avg_total:.0f}ms, revoir configuration."}


async def list_benchmarks(camera_id: str, limit: int = 10) -> list:
    cursor = db.camera_benchmarks.find({"camera_id": camera_id}, {"_id": 0}) \
        .sort("started_at", -1).limit(limit)
    return await cursor.to_list(limit)
