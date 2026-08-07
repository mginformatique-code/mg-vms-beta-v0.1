"""v0.7.h · Wave I · Axe QoS · Alertes automatiques Ops Center.

Surveille en continu les compteurs `pipeline_v2.inspector` et émet des
événements dans la collection `events` (visible dans Operations Center)
dès qu'un SLA est dépassé de façon soutenue (≥ 3 échantillons p95 sur
la fenêtre 60 s).

Seuils par défaut (surchargeables via `settings.qos_thresholds`) :

    pipeline_total_ms:  200     # Σ étages
    yolo_ms:             50     # extrapolation GPU cible
    tracking_ms:          5
    anpr_ms:            120
    fps_min:              5     # sous ce FPS on alerte
    ram_percent:         85
    gpu_vram_percent:    90

Anti-flap : une alerte n'est ré-émise que si l'incident dure ≥ 30 s
depuis la précédente notif. Sinon on ignore silencieusement.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from database import db

logger = logging.getLogger("pipeline_v2.qos_alerts")


DEFAULT_THRESHOLDS = {
    "pipeline_total_ms": 200.0,
    "yolo_ms": 50.0,
    "tracking_ms": 5.0,
    "anpr_ms": 120.0,
    "fps_min": 5.0,
    "ram_percent": 85.0,
    "gpu_vram_percent": 90.0,
}

_last_notified: dict[tuple[str, str], float] = {}  # (camera_id, kind) → epoch


async def _read_thresholds() -> dict:
    doc = await db.settings.find_one({"key": "qos_thresholds"}, {"_id": 0, "value": 1})
    if not doc or not isinstance(doc.get("value"), dict):
        return dict(DEFAULT_THRESHOLDS)
    return {**DEFAULT_THRESHOLDS, **doc["value"]}


async def _emit_alert(camera_id: Optional[str], kind: str, severity: str,
                       message: str, details: dict) -> None:
    """Écrit dans `events` (Ops Center) avec anti-flap 30 s."""
    now = time.time()
    key = (camera_id or "system", kind)
    if key in _last_notified and (now - _last_notified[key]) < 30.0:
        return
    _last_notified[key] = now
    doc = {
        "type": "qos_alert",
        "kind": kind,
        "severity": severity,
        "camera_id": camera_id,
        "camera_name": camera_id or "system",
        "message": message,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "resolved": False,
    }
    try:
        await db.events.insert_one(doc)
        logger.info("QoS alert emitted: %s / %s / %s", kind, severity, message)
    except Exception:
        logger.exception("Insertion QoS alert échouée (non bloquant)")


def _check_camera_stages(cam_id: str, stages: dict, thresholds: dict) -> list[dict]:
    """Retourne la liste des violations SLA pour une caméra."""
    violations = []
    total_avg = sum((s.get("avg_ms_60s") or 0) for s in stages.values())
    if total_avg > thresholds["pipeline_total_ms"] and any(
        (s.get("samples_60s") or 0) >= 3 for s in stages.values()
    ):
        violations.append({
            "kind": "pipeline_slow",
            "severity": "warning",
            "message": f"Pipeline total dépasse {thresholds['pipeline_total_ms']:.0f} ms (avg 60 s = {total_avg:.1f} ms)",
            "details": {"total_avg_ms": round(total_avg, 1)},
        })
    per_stage_map = {
        "yolo": ("yolo_ms", "warning"),
        "tracking": ("tracking_ms", "info"),
        "anpr": ("anpr_ms", "warning"),
    }
    for stage_name, (thr_key, sev) in per_stage_map.items():
        st = stages.get(stage_name)
        if not st or (st.get("samples_60s") or 0) < 3:
            continue
        p95 = st.get("p95_60s") or 0
        if p95 > thresholds[thr_key]:
            violations.append({
                "kind": f"{stage_name}_slow",
                "severity": sev,
                "message": f"Étage {stage_name} p95 = {p95:.1f} ms > seuil {thresholds[thr_key]:.0f} ms",
                "details": {"stage": stage_name, "p95_60s": round(p95, 1),
                            "threshold_ms": thresholds[thr_key]},
            })
    return violations


def _check_system(sys_info: dict, thresholds: dict) -> list[dict]:
    v = []
    ram_pct = (sys_info.get("ram") or {}).get("percent", 0)
    if ram_pct > thresholds["ram_percent"]:
        v.append({
            "kind": "ram_high", "severity": "warning",
            "message": f"RAM utilisation {ram_pct:.1f}% > {thresholds['ram_percent']:.0f}%",
            "details": {"ram_percent": ram_pct},
        })
    gpu = sys_info.get("gpu") or {}
    if gpu.get("available") and gpu.get("vram_total_mb"):
        pct = 100 * (gpu.get("vram_allocated_mb") or 0) / gpu["vram_total_mb"]
        if pct > thresholds["gpu_vram_percent"]:
            v.append({
                "kind": "gpu_vram_high", "severity": "warning",
                "message": f"VRAM GPU {pct:.1f}% > {thresholds['gpu_vram_percent']:.0f}%",
                "details": {"vram_percent": round(pct, 1)},
            })
    return v


async def qos_watcher_loop() -> None:
    """Boucle background lancée depuis lifecycle. Scan toutes les 15 s."""
    logger.info("QoS watcher : démarrage (intervalle 15 s)")
    while True:
        try:
            from pipeline_v2.inspector import inspector
            thresholds = await _read_thresholds()
            snap = inspector.snapshot()
            # Vérifs par caméra
            for cid, cam_snap in (snap.get("cameras") or {}).items():
                fps = cam_snap.get("fps") or 0
                if fps > 0 and fps < thresholds["fps_min"]:
                    await _emit_alert(cid, "fps_low", "info",
                                       f"FPS faible sur {cid} : {fps:.2f} < {thresholds['fps_min']:.1f}",
                                       {"fps": fps})
                for v in _check_camera_stages(cid, cam_snap.get("stages") or {}, thresholds):
                    await _emit_alert(cid, v["kind"], v["severity"], v["message"], v["details"])
            # Vérifs system
            for v in _check_system(snap.get("system") or {}, thresholds):
                await _emit_alert(None, v["kind"], v["severity"], v["message"], v["details"])
        except Exception:
            logger.exception("qos_watcher cycle : erreur non-bloquante")
        await asyncio.sleep(15)


def get_current_thresholds() -> dict:
    """Alias sync pour tests."""
    return dict(DEFAULT_THRESHOLDS)
