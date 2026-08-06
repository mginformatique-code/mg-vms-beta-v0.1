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
from typing import Optional

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


async def _recorder_health() -> dict:
    """Par caméra : ffmpeg vivant ? dernier segment ? gaps 24h ?
    Utilise `recorder.get_recorder_health` qui lit les vrais processus tracks
    (`recorder._processes`) et les vrais champs de collection `recordings`."""
    try:
        from recorder import get_recorder_health
        return await get_recorder_health()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


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



@health_dashboard_router.get("/diagnostics/recorder-health")
async def diagnostics_recorder_health(
    camera_id: str | None = None,
    user: dict = Depends(require_permission("view_live")),
):
    """État détaillé des enregistreurs (ffmpeg + continuité 24h) par caméra.

    Utile pour la page maintenance : sait si un ffmpeg est mort silencieusement,
    combien de trous d'enregistrement dans les dernières 24h, et le taux de
    couverture (en mode continuous).
    """
    from recorder import get_recorder_health
    return await get_recorder_health(camera_id)


@health_dashboard_router.get("/diagnostics/pipeline-metrics")
async def diagnostics_pipeline_metrics(user: dict = Depends(require_permission("view_live"))):
    """P9+ Monitoring IA temps réel — FPS + latence par caméra + plugins utilisés.

    Utile pour identifier quel plugin ralentit le pipeline (bug fix Feb 2026).
    Retourne pour chaque caméra active :
      - `fps_5s`            : FPS moyen sur les 5 dernières secondes
      - `pipeline_ms_avg/max/p95` : latence du dispatch pipeline
      - `success_count / error_count` : compteurs cumulés
      - `last_plugins`      : {detectors, trackers, segmenters, business, notifiers}
    """
    from pipeline_metrics import pipeline_metrics
    snap = pipeline_metrics.snapshot()
    # Enrichit avec état du bus (nombre de plugins par interface)
    try:
        from plugin_manager.bus import bus
        counts = {
            iface: sum(1 for e in bus.list_entries(iface) if e.is_dispatchable())
            for iface in ("FrameAnalyzer", "Tracker", "Segmenter",
                          "PlateRecognizer", "PipelineConsumer", "EventConsumer")
        }
    except Exception:
        counts = {}
    # v0.4 · Runtime state réellement appliqué au moteur IA (fix bug
    # "ByteTrack=False dans le monitoring alors qu'il est activé en config")
    runtime: dict = {}
    try:
        import ai_engine as _ae
        runtime["bytetrack"] = (dict(_ae._bytetrack_cfg) if _ae._bytetrack_cfg
                                 else {"enabled": True, "source": "defaults"})
        runtime["ai_config"] = dict(_ae._runtime_config) if _ae._runtime_config else {}
    except Exception:
        pass
    try:
        import torch
        runtime["gpu"] = {
            "torch": torch.__version__,
            "cuda_available": torch.cuda.is_available(),
            "cuda_version": torch.version.cuda,
            "device_name": (torch.cuda.get_device_name(0) if torch.cuda.is_available() else None),
        }
    except Exception:
        runtime["gpu"] = {"error": "torch unavailable"}
    return {"cameras": snap, "plugins_dispatchable": counts, "runtime": runtime}


@health_dashboard_router.get("/diagnostics/frame-source")
async def diagnostics_frame_source(user: dict = Depends(require_permission("view_live"))):
    """v0.3 · Frame Grabber — état des workers ffmpeg persistants.

    Retourne :
      - workers : dict par camera_id avec codec, resolution, gpu, restart_count,
        last_frame_age_s, alive, last_error
      - cuvid_available : NVDEC dispo (H.265 GPU decode)
      - mode : GPU / auto / CPU

    Un ``last_frame_age_s`` < 2s = worker actif et alimente le pipeline IA
    en RTSP direct (plus de fallback go2rtc HTTP).
    """
    import frame_source
    return frame_source.status()


@health_dashboard_router.get("/diagnostics/anpr-tracker")
async def diagnostics_anpr_tracker(user: dict = Depends(require_permission("view_live"))):
    """v0.3 · ANPR Tracker — état des véhicules suivis par caméra.

    Retourne pour chaque caméra :
      - Config actuelle (min_readings, lost_cycles, min_confidence)
      - Liste des véhicules trackés : track_id, state (ENTERED/PRESENT/LEFT),
        nb de lectures OCR accumulées, timestamps first/last_seen, meilleure
        plaque consensuelle.

    Permet de valider en live que :
      - Les véhicules stationnés génèrent **1 seul événement**.
      - Les véhicules en mouvement bénéficient de **plusieurs OCR** avant émission.
    """
    from anpr_tracker import anpr_tracker
    return anpr_tracker.snapshot()


@health_dashboard_router.get("/diagnostics/streaming-metrics")
async def diagnostics_streaming_metrics(user: dict = Depends(require_permission("view_live"))):
    """v0.3 · Métriques streaming (go2rtc) — séparées du pipeline IA.

    Interroge go2rtc pour obtenir : nb de clients WebRTC, débit, uptime par
    caméra. Le pipeline IA et le streaming sont désormais **indépendants**.
    """
    import httpx

    go2rtc_url = os.environ.get("GO2RTC_URL", "http://localhost:1984")
    result = {"streams": {}, "go2rtc_reachable": False}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{go2rtc_url}/api/streams")
            if r.status_code == 200:
                result["go2rtc_reachable"] = True
                streams = r.json() or {}
                for name, info in streams.items():
                    if not name.startswith("cam_"):
                        continue
                    cam_id = name[4:]
                    producers = info.get("producers", []) or []
                    consumers = info.get("consumers", []) or []
                    result["streams"][cam_id] = {
                        "producers": len(producers),
                        "consumers": len(consumers),
                        "clients_webrtc": sum(
                            1 for c in consumers
                            if isinstance(c, dict) and "webrtc" in str(c.get("format", "")).lower()
                        ),
                        "url": info.get("url", ""),
                    }
    except Exception as e:
        logger.debug("streaming-metrics: go2rtc unreachable (%s)", e)
    return result




@health_dashboard_router.get("/diagnostics/wsdl")
async def diagnostics_wsdl(user: dict = Depends(require_permission("view_live"))):
    """État des fichiers WSDL ONVIF embarqués dans MG-VMS.

    Retourne ``{ok, path, found, missing_required[], missing_optional[]}``.
    Utilisé par l'UI Diagnostics pour signaler visuellement si les WSDL
    sont manquants dans l'image Docker.
    """
    from wsdl_path import validate_wsdl_dir
    return validate_wsdl_dir()



# ═══════════════════════════════════════════════════════════════════
# Pipeline v2 · P0 (Feb 2026) — Per-camera execution graphs + stats
# ═══════════════════════════════════════════════════════════════════

@health_dashboard_router.get("/diagnostics/pipeline-v2")
async def diagnostics_pipeline_v2(user: dict = Depends(require_permission("view_live"))):
    """v0.4.1 · P0 · **Pipeline IA par caméra** — état des graphes d'exécution.

    Retourne pour chaque caméra en cache :
      - ``enabled_plugins`` : la whitelist configurée
      - ``needs`` : quelles étapes tournent réellement (detection, tracking,
        segmentation, business, anpr) — les étapes False sont **complètement
        skippées** (zéro CPU / VRAM / compteur de plugin incrémenté)
      - ``plugins`` : les plugin names dispatchables par étape
      - ``total_active_plugins`` : nombre total de plugins en activité pour
        cette caméra
      - ``is_empty`` : True si la caméra n'a AUCUN plugin pipeline actif
        → le dispatch complet est court-circuité pour elle

    Utilisé par l'UI Pipeline Designer + le monitoring pour prouver que les
    plugins désactivés ne consomment aucune ressource.
    """
    from pipeline_v2.registry import registry as _graph_registry
    return {
        "cameras": _graph_registry.all_graphs(),
        "stats": _graph_registry.stats(),
    }


@health_dashboard_router.get("/diagnostics/pipeline-v2/stats")
async def diagnostics_pipeline_v2_stats(user: dict = Depends(require_permission("view_live"))):
    """v0.4.1 · P1 · **Stats plugins fidèles** (par-caméra × plugin).

    Retourne les compteurs runtime réellement mesurés :
      - ``per_camera`` : {camera_id: {plugin_name: {calls, errors, timeouts,
        last_ms, last_error}}}
      - ``per_plugin`` : compteurs globaux du bus (calls / errors / timeouts /
        last_ms / consecutive_errors / state / quarantined_at)

    Le champ ``per_camera`` prouve visuellement dans l'UI que les plugins
    désactivés pour une caméra n'incrémentent jamais leur compteur
    ``calls`` pour elle. Corrige le bug "0 calls même quand des plaques
    sont détectées" (rapport audit v0.4.1).
    """
    try:
        from plugin_manager.bus import bus
        per_plugin = [e.summary() for e in bus.list_entries()]
        per_camera = bus.per_camera_stats()
    except Exception as e:
        return {"error": str(e), "per_camera": {}, "per_plugin": []}
    return {"per_camera": per_camera, "per_plugin": per_plugin}


@health_dashboard_router.post("/diagnostics/pipeline-v2/invalidate")
async def diagnostics_pipeline_v2_invalidate(
    camera_id: Optional[str] = None,
    user: dict = Depends(require_permission("view_live")),
):
    """v0.4.1 · P0 · Force le rebuild des graphes per-camera.

    Utile après un toggle admin d'un plugin global ou un reload du plugin
    manager. Sans arg → invalide TOUS les graphes.
    """
    from pipeline_v2.registry import registry as _graph_registry
    if camera_id:
        _graph_registry.invalidate(camera_id)
    else:
        _graph_registry.bump_bus_version()
        _graph_registry.invalidate()
    return {"ok": True, "invalidated": camera_id or "all"}


@health_dashboard_router.get("/diagnostics/anpr-quality")
async def diagnostics_anpr_quality(user: dict = Depends(require_permission("view_live"))):
    """v0.4.2 · P1 · **ANPR Auto-suspension qualité** — état par caméra.

    Retourne pour chaque caméra ayant subi une évaluation :
      - ``suspended`` : True si l'OCR est actuellement suspendu
      - ``last_score`` : dernier score qualité (0-1)
      - ``consecutive_bad/good`` : compteurs d'hystérésis
      - ``suspended_since`` : timestamp epoch (si suspendu)
      - ``total_suspensions`` : nombre total de bascules ACTIVE→SUSPENDED
      - ``is_specialized`` + ``specialized_model`` : True pour Dahua ITC /
        Hikvision DeepInView → OCR toujours actif (bypass auto-suspend)
      - ``last_reason`` : message court affichable dans l'UI
        ("ANPR suspendu automatiquement — sharpness=42 < 100 (flou)")

    Le seuil et l'hystérésis sont configurables via
    ``PUT /api/diagnostics/anpr-quality/config``.
    """
    from pipeline_v2.anpr_quality import anpr_quality
    return {
        "config": anpr_quality.config_dict(),
        "cameras": anpr_quality.states(),
    }


@health_dashboard_router.put("/diagnostics/anpr-quality/config")
async def diagnostics_anpr_quality_configure(
    patch: dict,
    user: dict = Depends(require_permission("view_live")),
):
    """v0.4.2 · Reconfigure le contrôleur qualité ANPR à chaud.

    Champs acceptés : ``min_score``, ``suspend_after_bad``, ``resume_after_good``,
    ``brightness_min/max``, ``sharpness_min``, ``contrast_min``,
    ``night_hour_start/end``.
    """
    from pipeline_v2.anpr_quality import anpr_quality
    anpr_quality.configure(**(patch or {}))
    return {"ok": True, "config": anpr_quality.config_dict()}


@health_dashboard_router.post("/diagnostics/anpr-quality/reset")
async def diagnostics_anpr_quality_reset(
    camera_id: Optional[str] = None,
    user: dict = Depends(require_permission("view_live")),
):
    """v0.4.2 · Reset l'état d'auto-suspension (force reprise immédiate)."""
    from pipeline_v2.anpr_quality import anpr_quality
    anpr_quality.reset(camera_id)
    return {"ok": True, "reset": camera_id or "all"}

