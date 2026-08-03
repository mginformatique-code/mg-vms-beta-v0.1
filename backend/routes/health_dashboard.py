"""Health Dashboard — endpoint agrégé pour la stabilisation P1.

Rassemble en une seule requête toutes les métriques critiques du VMS :
  - Système : CPU, RAM, disque, uptime backend, GPU (via ai_engine._ai_health)
  - Caméras : status live, coupures 24h, temps de reconnexion moyen, dernier
    segment d'enregistrement, erreurs récentes
  - Plugins : total, dispatchable, catégories, erreurs
  - Recorder : PID FFmpeg vivant, dernier segment par caméra
  - MongoDB : ping + counts collections critiques
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from auth import require_permission
from database import db

logger = logging.getLogger("routes.health_dashboard")

health_dashboard_router = APIRouter(prefix="/api", tags=["health-dashboard"])

_START_TIME = time.time()


async def _system_metrics() -> dict:
    """CPU, RAM, disque via psutil (déjà installé)."""
    try:
        import psutil
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_percent": psutil.virtual_memory().percent,
            "ram_used_gb": round(psutil.virtual_memory().used / (1024 ** 3), 2),
            "ram_total_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2),
            "disk_percent": psutil.disk_usage("/").percent,
            "disk_used_gb": round(psutil.disk_usage("/").used / (1024 ** 3), 1),
            "disk_total_gb": round(psutil.disk_usage("/").total / (1024 ** 3), 1),
            "uptime_seconds": int(time.time() - _START_TIME),
        }
    except Exception as e:
        return {"error": str(e)}


async def _mongo_health() -> dict:
    """Ping MongoDB + counts."""
    try:
        t = time.perf_counter()
        await db.command("ping")
        ping_ms = int((time.perf_counter() - t) * 1000)
        return {
            "status": "ok",
            "ping_ms": ping_ms,
            "collections": {
                "cameras": await db.cameras.count_documents({}),
                "events": await db.events.count_documents({}),
                "recordings": await db.recordings.count_documents({}),
                "diagnostics_events": await db.diagnostics_events.count_documents({}),
            },
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def _cameras_health() -> list:
    """État complet par caméra."""
    from diagnostics import camera_diagnostic_summary
    cams = []
    async for cam in db.cameras.find({}, {"_id": 0, "id": 1, "name": 1, "enabled": 1}):
        summary = await camera_diagnostic_summary(cam["id"])
        # Dernier segment
        last_segment = await db.recordings.find_one(
            {"camera_id": cam["id"]}, sort=[("start_ts", -1)],
            projection={"_id": 0, "start_ts": 1, "end_ts": 1, "duration_s": 1}
        )
        cams.append({
            "id": cam["id"],
            "name": cam.get("name"),
            "enabled": cam.get("enabled", True),
            **summary,
            "last_segment": last_segment,
        })
    return cams


async def _plugins_health() -> dict:
    """État Plugin Bus."""
    try:
        from plugin_manager import bus
        entries = bus.summary()
        by_iface = {}
        by_state = {}
        for e in entries:
            by_iface[e["interface"]] = by_iface.get(e["interface"], 0) + 1
            by_state[e["state"]] = by_state.get(e["state"], 0) + 1
        return {
            "total": len(entries),
            "dispatchable": sum(1 for e in entries if e["dispatchable"]),
            "by_interface": by_iface,
            "by_state": by_state,
            "errors": [{"name": e["name"], "state": e["state"], "msg": e["state_message"]}
                        for e in entries if e["state"] in ("error", "missing_dependency")][:10],
        }
    except Exception as e:
        return {"error": str(e)}


async def _ai_gpu_health() -> dict:
    try:
        from ai_engine import get_ai_health
        return get_ai_health()
    except Exception as e:
        return {"error": str(e)}


async def _recorder_health() -> list:
    """Par caméra : ffmpeg PID vivant ? dernier segment vieux ? gap ?"""
    try:
        import psutil
    except ImportError:
        psutil = None
    out = []
    try:
        from recorder import _load_pools  # noqa
    except Exception:
        pass
    # On lit les processus ffmpeg actifs
    ffmpeg_pids = []
    if psutil:
        for p in psutil.process_iter(["name", "pid", "cmdline"]):
            try:
                if "ffmpeg" in (p.info.get("name") or ""):
                    ffmpeg_pids.append({
                        "pid": p.info["pid"],
                        "cmd_snippet": " ".join((p.info.get("cmdline") or [])[:4])[:120],
                    })
            except Exception:
                pass
    now = datetime.now(timezone.utc)
    async for cam in db.cameras.find({"enabled": True}, {"_id": 0, "id": 1, "name": 1}):
        last = await db.recordings.find_one(
            {"camera_id": cam["id"]}, sort=[("end_ts", -1)],
            projection={"_id": 0, "end_ts": 1, "duration_s": 1, "path": 1}
        )
        gap_s = None
        if last and last.get("end_ts"):
            try:
                end_dt = datetime.fromisoformat(last["end_ts"].replace("Z", "+00:00"))
                gap_s = (now - end_dt).total_seconds()
            except Exception:
                pass
        out.append({
            "camera_id": cam["id"],
            "name": cam.get("name"),
            "last_segment_end": last.get("end_ts") if last else None,
            "gap_seconds": gap_s,
            "gap_warning": gap_s is not None and gap_s > 120,
            "last_duration_s": last.get("duration_s") if last else None,
        })
    return {"cameras": out, "ffmpeg_processes": ffmpeg_pids}


@health_dashboard_router.get("/diagnostics/health-dashboard")
async def health_dashboard(user: dict = Depends(require_permission("view_live"))):
    """Health dashboard agrégé — endpoint unique pour la page /diagnostics/dashboard.

    Retour :
    ```json
    {
      "timestamp": "...",
      "system": {cpu_percent, ram_percent, disk_percent, uptime_seconds, ...},
      "mongo":  {status, ping_ms, collections: {...}},
      "ai":     {yolo_loaded, alpr_loaded, device, ...},
      "plugins":{total, dispatchable, by_interface, by_state, errors: [...]},
      "cameras":[{id, name, status, coupures_24h, last_segment, ...}],
      "recorder":{cameras: [...], ffmpeg_processes: [...]}
    }
    ```
    """
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": await _system_metrics(),
        "mongo": await _mongo_health(),
        "ai": await _ai_gpu_health(),
        "plugins": await _plugins_health(),
        "cameras": await _cameras_health(),
        "recorder": await _recorder_health(),
    }


@health_dashboard_router.get("/diagnostics/camera/{camera_id}/events")
async def camera_diagnostic_events(
    camera_id: str,
    limit: int = 50,
    user: dict = Depends(require_permission("view_live")),
):
    """Historique paginé des événements diagnostic (déco/reco/erreurs) d'une caméra."""
    docs = await db.diagnostics_events.find(
        {"camera_id": camera_id},
        sort=[("timestamp", -1)],
        limit=min(500, max(1, limit)),
        projection={"_id": 0},
    ).to_list(None)
    return {"camera_id": camera_id, "count": len(docs), "events": docs}
