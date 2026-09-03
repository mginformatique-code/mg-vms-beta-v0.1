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
import re
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

# v3.24 · Chantier séparation pipeline IA / serveur API, étape 2b : message
# uniforme utilisé par tous les endpoints de ce fichier qui lisent désormais
# pipeline_snapshot.get_snapshot() au lieu d'importer pipeline_v2/ai_engine
# en direct. Le snapshot peut être absent juste après un (re)démarrage du
# pipeline (premier tick pas encore écrit) ou si Redis est indisponible —
# dans les deux cas on dégrade proprement (jamais de 500 non géré).
_SNAPSHOT_UNAVAILABLE = {"error": "pipeline snapshot indisponible"}


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
    # v3.24 · Étape 2b séparation pipeline/API : lit le snapshot Redis
    # consolidé (pipeline_snapshot.py) au lieu d'importer ai_engine en
    # direct — get_ai_health() est catégorie (b), pur in-memory.
    from pipeline_snapshot import get_snapshot
    snap = await get_snapshot()
    if snap is None:
        return dict(_SNAPSHOT_UNAVAILABLE)
    return snap["ai_health"]


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
    # v3.24 · Étape 2b : `pipeline_metrics` + le bloc `runtime` (bytetrack,
    # ai_config, batch_infer) viennent du snapshot Redis consolidé au lieu
    # d'importer pipeline_metrics/ai_engine/pipeline_v2.batch_infer en
    # direct. `plugin_manager.bus` (comptage plugins dispatchables) et
    # `torch` (infos GPU) restent des imports directs : ni pipeline_v2 ni
    # ai_engine, hors périmètre de cette étape.
    from pipeline_snapshot import get_snapshot
    psnap = await get_snapshot()
    snap = psnap["pipeline_metrics"] if psnap else {}
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
    if psnap:
        runtime["bytetrack"] = psnap["bytetrack_cfg"]
        runtime["ai_config"] = psnap["ai_config_runtime"]
        # v3.12 · Efficacité réelle du regroupement d'inférence. `avg_batch`
        # proche de 1 signifie que les caméras n'arrivent PAS dans la même
        # fenêtre et que le regroupement ne sert à rien — information
        # nécessaire pour savoir s'il faut élargir la fenêtre ou chercher
        # ailleurs.
        runtime["batch_infer"] = psnap["batch_infer"]
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
    # v3.11 · Budget IA par caméra — dit POURQUOI le pipeline plafonne.
    #
    # Constat en production qui a motivé ce bloc : 5 caméras sur 6 tournaient
    # en `ai_resolution=native`, donc le pipeline IA décodait du 4K (et même
    # du 4512x2512) avant de le réduire. Mesures relevées côte à côte :
    #
    #     720p            realtime  138 ms   yolo 111 ms   0.4 fps
    #     native 2304px   realtime  921 ms   yolo 266 ms   0.4 fps
    #     native 3840px   realtime 6242 ms   yolo 418 ms   0.0 fps
    #
    # Soit un `realtime_ms` 45x pire en natif qu'en 720p, et un pipeline
    # effectivement à l'arrêt sur les 4K. Le moniteur affichait bien ces
    # chiffres mais rien n'indiquait la CAUSE : on l'expose ici.
    try:
        from database import db as _db
        _PRESET_PX = {"720p": 1280 * 720, "1080p": 1920 * 1080}
        async for cam in _db.cameras.find({}, {"_id": 0, "id": 1, "name": 1,
                                                "ai_resolution": 1, "resolution": 1,
                                                "enabled_plugins": 1}):
            entry = snap.get(cam.get("id"))
            if not isinstance(entry, dict):
                continue
            preset = (cam.get("ai_resolution") or "720p").lower()
            px = _PRESET_PX.get(preset)
            if px is None:  # "native" → résolution réelle de la caméra
                m = re.match(r"^(\d{2,5})x(\d{2,5})$",
                             (cam.get("resolution") or "").lower().replace(" ", ""))
                px = int(m.group(1)) * int(m.group(2)) if m else 0
            stages = entry.get("stages") or {}
            rt = float(((stages.get("realtime_ms") or {}).get("avg")) or 0)
            yolo = float(((stages.get("yolo_ms") or {}).get("avg")) or 0)

            # Goulot dominant : acquisition de l'image ou inférence ?
            if rt >= max(yolo * 2, 400):
                bottleneck = "acquisition"
            elif yolo >= 200:
                bottleneck = "inference"
            else:
                bottleneck = "ok"

            advice = ""
            if preset == "native" and px > _PRESET_PX["1080p"]:
                advice = ("Résolution IA « native » sur un flux à haute définition : "
                          "le pipeline décode l'image entière avant de la réduire. "
                          "Passer en 1080p (ou 720p) accélère fortement l'acquisition "
                          "sans dégrader la détection, les crops de plaque restant "
                          "générés à part.")
            elif bottleneck == "inference":
                advice = ("Temps d'inférence élevé : trop de plugins de détection "
                          "actifs simultanément sur cette caméra, ou modèle trop lourd.")

            entry["ai_budget"] = {
                "ai_resolution": preset,
                "ai_pixels": px,
                "plugins_enabled": len(cam.get("enabled_plugins") or []),
                "bottleneck": bottleneck,
                "advice": advice,
            }
    except Exception as e:
        logger.debug("ai_budget indisponible : %s", e)

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
    # v3.24 · Étape 2b : registry.all_graphs()/.stats() (catégorie b) via
    # snapshot Redis — remplace l'import direct de pipeline_v2.registry.
    from pipeline_snapshot import get_snapshot
    snap = await get_snapshot()
    if snap is None:
        return dict(_SNAPSHOT_UNAVAILABLE)
    return snap["pipeline_v2_graphs"]


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


@health_dashboard_router.get("/diagnostics/hot-reload")
async def diagnostics_hot_reload(user: dict = Depends(require_permission("view_live"))):
    """v0.7.e · Wave A · Preuve du Hot Reload chirurgical.

    Retourne les compteurs qui prouvent que :
      * une modification caméra = 1 seul worker rechargé (``topology_syncs_partial``)
      * aucun restart global (``topology_syncs_full`` ≈ 1 par TTL cycle)
      * les reloads de config sont signal-driven (``config_reloads`` +
        ``camera_config_reloads`` restent bornés par les signaux reçus)
      * pas de churn frame_source (``frame_source_starts / stops`` restent bas)
    """
    # v3.24 · Étape 2b : get_hot_reload_metrics() (catégorie b) via snapshot.
    from pipeline_snapshot import get_snapshot
    snap = await get_snapshot()
    if snap is None:
        return dict(_SNAPSHOT_UNAVAILABLE)
    return snap["hot_reload"]


@health_dashboard_router.get("/diagnostics/plate-quality")
async def diagnostics_plate_quality(user: dict = Depends(require_permission("view_live"))):
    """v0.7.e · Wave C · État du gate qualité crop plaque + mode debug."""
    # v3.24 · Étape 2b : seuils + engine_weights + debug_mode (catégorie b,
    # les seuils sont des constantes figées — voir pipeline_snapshot.py)
    # via snapshot Redis, plus d'import direct de pipeline_v2.plate_quality.
    from pipeline_snapshot import get_snapshot
    snap = await get_snapshot()
    if snap is None:
        return dict(_SNAPSHOT_UNAVAILABLE)
    return snap["plate_quality"]


@health_dashboard_router.put("/diagnostics/plate-quality/debug")
async def diagnostics_plate_quality_debug_toggle(
    enabled: bool,
    user: dict = Depends(require_permission("technician")),
):
    """v0.7.e · Active/désactive le mode debug OCR (bundle images + JSON)."""
    from pipeline_v2 import plate_quality as pq
    pq.set_debug_enabled(enabled)
    return {"enabled": pq.debug_enabled(), "output_dir": pq._DEBUG_DIR}


# ═════════════════════════════════════════════════════════════════════
# v0.7.h · Wave I · Axe QoS · endpoints reliability + alertes
# ═════════════════════════════════════════════════════════════════════
@health_dashboard_router.get("/diagnostics/engine-reliability")
async def diagnostics_engine_reliability(user: dict = Depends(require_permission("view_live"))):
    """Fiabilité par (camera × moteur OCR) — rolling accuracy 100 lectures."""
    # v3.24 · Étape 2b : engine_reliability.snapshot() (catégorie b) via
    # snapshot Redis. Repli sur {} (comme l'original, jamais d'exception ici)
    # plutôt qu'un dict `error` — cet endpoint n'a jamais eu de champ error.
    from pipeline_snapshot import get_snapshot
    snap = await get_snapshot()
    return snap["engine_reliability"] if snap else {}


@health_dashboard_router.get("/diagnostics/qos-thresholds")
async def diagnostics_qos_get(user: dict = Depends(require_permission("view_live"))):
    """Seuils SLA courants (surveillance permanente Wave I)."""
    # v3.23 · Import direct depuis ai_rules_settings (pas pipeline_v2) — étape
    # 2a séparation pipeline/API : constante figée, pas d'état pipeline.
    from ai_rules_settings import DEFAULT_QOS_THRESHOLDS as DEFAULT_THRESHOLDS
    doc = await db.settings.find_one({"key": "qos_thresholds"}, {"_id": 0, "value": 1})
    return {
        "defaults": DEFAULT_THRESHOLDS,
        "current": {**DEFAULT_THRESHOLDS, **((doc or {}).get("value") or {})},
    }


@health_dashboard_router.put("/diagnostics/qos-thresholds")
async def diagnostics_qos_put(
    payload: dict,
    user: dict = Depends(require_permission("technician")),
):
    from ai_rules_settings import DEFAULT_QOS_THRESHOLDS as DEFAULT_THRESHOLDS
    allowed = set(DEFAULT_THRESHOLDS.keys())
    cleaned = {k: float(v) for k, v in payload.items() if k in allowed and v is not None}
    await db.settings.update_one(
        {"key": "qos_thresholds"},
        {"$set": {"key": "qos_thresholds", "value": cleaned}},
        upsert=True,
    )
    return {"ok": True, "current": {**DEFAULT_THRESHOLDS, **cleaned}}


# ═════════════════════════════════════════════════════════════════════
# v0.8-rc1 · Camera Health Score + Capabilities Matrix
# ═════════════════════════════════════════════════════════════════════
@health_dashboard_router.get("/cameras/{camera_id}/health")
async def get_camera_health(camera_id: str,
                              user: dict = Depends(require_permission("view_live"))):
    from services.camera_health import compute_health
    return await compute_health(camera_id)


@health_dashboard_router.get("/cameras/health")
async def get_all_cameras_health(user: dict = Depends(require_permission("view_live"))):
    from services.camera_health import compute_all_health
    results = await compute_all_health()
    counts = {"healthy": 0, "degraded": 0, "critical": 0}
    for r in results:
        counts[r.get("band", "critical")] = counts.get(r.get("band", "critical"), 0) + 1
    return {
        "cameras": results,
        "summary": {"total": len(results), **counts},
    }


@health_dashboard_router.get("/cameras/capabilities-matrix")
async def get_capabilities_matrix(user: dict = Depends(require_permission("view_live"))):
    """Matrice vendor × capabilities (Priorité 1 v0.8 RC).

    Retourne pour chaque caméra un tuple (vendor, model, capabilities dict)
    permettant à l'UI d'afficher un tableau complet ✓/✗ par constructeur.
    """
    cams_cursor = db.cameras.find({}, {
        "_id": 0, "id": 1, "name": 1, "vendor": 1, "model": 1,
        "capabilities": 1, "status": 1, "driver": 1,
    })
    rows = []
    all_caps: set = set()
    async for c in cams_cursor:
        caps = c.get("capabilities") or {}
        # Ne pas exposer les clés internes (préfixées _)
        clean_caps = {k: v for k, v in caps.items() if not str(k).startswith("_")}
        all_caps.update(clean_caps.keys())
        rows.append({
            "camera_id": c["id"],
            "name": c.get("name"),
            "vendor": (c.get("vendor") or "unknown").lower(),
            "model": c.get("model") or "—",
            "driver": c.get("driver"),
            "status": c.get("status"),
            "capabilities": clean_caps,
        })
    return {
        "rows": rows,
        "capability_keys": sorted(all_caps),
        "vendor_summary": _summarize_by_vendor(rows, all_caps),
    }


# ═════════════════════════════════════════════════════════════════════
# v0.8-rc2 · Camera Benchmark + Camera Advisor
# ═════════════════════════════════════════════════════════════════════
@health_dashboard_router.post("/cameras/{camera_id}/benchmark")
async def post_camera_benchmark(
    camera_id: str,
    duration_s: int = 60,
    user: dict = Depends(require_permission("technician")),
):
    """Lance un benchmark bloquant durée `duration_s` (max 300 s)."""
    from services.camera_benchmark import run_benchmark
    duration_s = max(10, min(int(duration_s), 300))
    return await run_benchmark(camera_id, duration_s=duration_s)


@health_dashboard_router.get("/cameras/{camera_id}/benchmarks")
async def get_camera_benchmarks(
    camera_id: str, limit: int = 10,
    user: dict = Depends(require_permission("view_live")),
):
    from services.camera_benchmark import list_benchmarks
    return {"camera_id": camera_id,
            "benchmarks": await list_benchmarks(camera_id, limit=limit)}


@health_dashboard_router.get("/cameras/{camera_id}/advisor")
async def get_camera_advisor(
    camera_id: str,
    user: dict = Depends(require_permission("view_live")),
):
    from services.camera_advisor import advise
    return await advise(camera_id)


@health_dashboard_router.get("/cameras/advisor")
async def get_all_cameras_advisor(user: dict = Depends(require_permission("view_live"))):
    from services.camera_advisor import advise_all
    results = await advise_all()
    total_recs = sum(len(r.get("recommendations", [])) for r in results)
    return {"cameras": results, "total_recommendations": total_recs}


def _summarize_by_vendor(rows: list[dict], all_caps: set) -> dict:
    """Regroupe par vendor et compte les caps disponibles."""
    by_vendor: dict = {}
    for r in rows:
        v = r["vendor"]
        by_vendor.setdefault(v, {"count": 0, "caps_present": {}, "caps_total": len(all_caps)})
        by_vendor[v]["count"] += 1
        for k, val in r["capabilities"].items():
            if val:
                by_vendor[v]["caps_present"][k] = by_vendor[v]["caps_present"].get(k, 0) + 1
    return by_vendor



@health_dashboard_router.get("/diagnostics/pipeline-inspector")
async def diagnostics_pipeline_inspector(user: dict = Depends(require_permission("view_live"))):
    """v0.4.2 · **Pipeline Inspector** — diagnostic runtime par caméra × stage.

    Pour chaque caméra : fetch → decode → motion → yolo → tracking → roi →
    anpr → dispatch → multi_anpr → scenarios → persist → websocket, avec
    temps moyen/max, appels, erreurs, timeouts, FPS effectif. Snapshot
    système : CPU, RAM, GPU, VRAM. Inclut les workers et trackers actifs.
    """
    # v3.24 · Étape 2b : inspector.snapshot() + camera_worker.runtime.describe()
    # (catégorie b) via snapshot Redis, plus d'import direct pipeline_v2.
    from pipeline_snapshot import get_snapshot
    snap = await get_snapshot()
    if snap is None:
        return dict(_SNAPSHOT_UNAVAILABLE)
    return snap["pipeline_inspector"]


@health_dashboard_router.post("/diagnostics/pipeline-inspector/reset")
async def diagnostics_pipeline_inspector_reset(
    camera_id: Optional[str] = None,
    user: dict = Depends(require_permission("view_live")),
):
    from pipeline_v2.inspector import inspector as _inspector
    _inspector.reset(camera_id)
    return {"ok": True, "reset": camera_id or "all"}


@health_dashboard_router.get("/diagnostics/capture/stats")
async def diagnostics_capture_stats(user: dict = Depends(require_permission("view_live"))):
    """v0.4.5.a · **Métriques capture** — séparées de l'IA.

    Retourne par caméra :
      - ``fps_capture_1min`` : FPS effectif produit par ffmpeg (fenêtre 60s)
      - ``frames_produced`` / ``frames_dropped``
      - ``warmup_ms`` : durée jusqu'à la 1re frame (mesure temps de startup)
      - ``last_capture_interval_ms`` : pace entre 2 frames stdout
      - ``last_frame_age_ms`` : âge de la dernière frame disponible
      - ``reconnect_count`` : nombre de redémarrages ffmpeg
      - ``alive`` / ``last_error``

    Permet à l'UI de distinguer "caméra lente" (fps_capture bas) et
    "IA lente" (fps_capture normal + IA en retard).
    """
    try:
        from frame_source import status as _fs_status
        return _fs_status()
    except Exception as e:
        return {"error": str(e), "workers": {}}


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
    # v3.24 · Étape 2b : anpr_quality.config_dict()/.states() (catégorie b)
    # via snapshot Redis, plus d'import direct pipeline_v2.anpr_quality.
    from pipeline_snapshot import get_snapshot
    snap = await get_snapshot()
    if snap is None:
        return dict(_SNAPSHOT_UNAVAILABLE)
    return snap["anpr_quality"]


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




# ═════════════════════════════════════════════════════════════════════
# v0.8-rc6 · Sprint 3 · Camera State Fusion + Pipeline Trace End-to-End
# ═════════════════════════════════════════════════════════════════════
@health_dashboard_router.get("/diagnostics/camera-state/{camera_id}")
async def diagnostics_camera_state(
    camera_id: str,
    check_network: bool = True,
    user: dict = Depends(require_permission("view_live")),
):
    """v0.8-rc6 · État caméra fusionné multi-signaux.

    Retourne :
      - ``status`` : "online" | "degraded" | "offline"
      - ``confidence`` : 0..100 (proportion signaux positifs)
      - ``signals`` : liste des 4 capteurs (frame_source, pipeline_activity,
                       go2rtc_stream, tcp_reachable) avec détails
      - ``reasons`` : justifications textuelles

    Règle : une caméra qui produit des frames RTSP est TOUJOURS online, même
    si le probe go2rtc timeout. Fin des faux "Offline".
    """
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(status_code=404, detail="camera_not_found")
    # v3.24 · Étape 2b/3 : le signal pipeline_activity est désormais lu depuis
    # le snapshot Redis (pipeline_snapshot.camera_activity) et passé en
    # paramètre à fuse_camera_state() au lieu que camera_state.py aille lire
    # pipeline_v2.inspector lui-même. Note : fuse_camera_state() reste
    # importée depuis pipeline_v2.camera_state (frame_source local +
    # signaux réseau go2rtc/tcp restent hors périmètre de cette étape —
    # voir rapport de livraison 2b).
    from pipeline_v2.camera_state import fuse_camera_state
    from pipeline_snapshot import get_snapshot
    psnap = await get_snapshot()
    activity = ((psnap or {}).get("camera_activity") or {}).get(camera_id)
    fused = await fuse_camera_state(cam, check_network=check_network,
                                     pipeline_activity=activity)
    return fused.to_dict()


@health_dashboard_router.get("/diagnostics/camera-state")
async def diagnostics_camera_state_all(
    check_network: bool = False,   # défaut False pour éviter tempête réseau
    user: dict = Depends(require_permission("view_live")),
):
    """v0.8-rc6 · Fusion multi-signaux pour TOUTES les caméras.

    Par défaut ``check_network=False`` — signaux locaux uniquement (rapide).
    Passer ``check_network=true`` pour inclure go2rtc + TCP probe.
    """
    from pipeline_v2.camera_state import fuse_camera_state
    from pipeline_snapshot import get_snapshot
    psnap = await get_snapshot()
    activity_map = (psnap or {}).get("camera_activity") or {}
    cams = await db.cameras.find({}, {"_id": 0}).to_list(None)
    out = []
    for cam in cams:
        try:
            fused = await fuse_camera_state(cam, check_network=check_network,
                                             pipeline_activity=activity_map.get(cam.get("id")))
            out.append(fused.to_dict())
        except Exception as e:
            logger.warning("fuse_camera_state failed for %s: %s", cam.get("id"), e)
    summary = {
        "total": len(out),
        "online": sum(1 for f in out if f["status"] == "online"),
        "degraded": sum(1 for f in out if f["status"] == "degraded"),
        "offline": sum(1 for f in out if f["status"] == "offline"),
    }
    return {"cameras": out, "summary": summary}


@health_dashboard_router.get("/diagnostics/traces")
async def diagnostics_traces(
    camera_id: Optional[str] = None,
    limit: int = 50,
    user: dict = Depends(require_permission("view_live")),
):
    """v0.8-rc6 · Ring buffer des N derniers traces end-to-end.

    Chaque trace détaille les étapes réellement exécutées (fetch, decode,
    yolo, tracking, roi, anpr, crop_premium, dispatch, persist...) avec
    ``start_ms`` relatif au trace + ``duration_ms``.
    """
    # v3.24 · Étape 2b : le ring buffer complet (≤ MAX_TRACES=50, voir
    # pipeline_v2/trace.py) est dumped tel quel dans le snapshot — déjà
    # trié plus-récent-d'abord par collector.list_recent(). Le filtrage
    # camera_id/limit se fait ici, côté lecteur, au lieu de rappeler
    # collector.list_recent(camera_id=..., limit=...) en direct.
    from pipeline_snapshot import get_snapshot
    snap = await get_snapshot()
    if snap is None:
        return dict(_SNAPSHOT_UNAVAILABLE)
    all_traces = snap["traces"]["list"]
    if camera_id:
        all_traces = [t for t in all_traces if t.get("camera_id") == camera_id]
    return {
        "sampling_every_n_frames": snap["traces"]["sampling_every_n_frames"],
        "traces": all_traces[:max(1, limit)],
    }


@health_dashboard_router.get("/diagnostics/traces/{trace_id}")
async def diagnostics_trace_detail(
    trace_id: str,
    user: dict = Depends(require_permission("view_live")),
):
    """v0.8-rc6 · Détail d'un trace précis (résolution UUID)."""
    # v3.24 · Étape 2b : recherche linéaire dans le ring buffer embarqué du
    # snapshot au lieu de collector.get(trace_id) en direct (≤ 50 entrées —
    # coût négligeable).
    from pipeline_snapshot import get_snapshot
    snap = await get_snapshot()
    traces = snap["traces"]["list"] if snap else []
    t = next((tr for tr in traces if tr.get("trace_id") == trace_id), None)
    if not t:
        raise HTTPException(status_code=404, detail="trace_not_found")
    return t


@health_dashboard_router.put("/diagnostics/traces/sampling")
async def diagnostics_traces_sampling(
    n: int,
    user: dict = Depends(require_permission("view_live")),
):
    """v0.8-rc6 · Ajuste le taux de sampling (1 trace / N frames).

    n=1 → toutes les frames (couteux, debug uniquement)
    n=100 → défaut, coût négligeable
    n=1000 → sampling très rare (production)
    """
    from pipeline_v2.trace import collector
    if n < 1 or n > 100000:
        raise HTTPException(status_code=400, detail="n doit être entre 1 et 100000")
    collector.set_sampling(n)
    return {"ok": True, "sampling_every_n_frames": collector.get_sampling()}


@health_dashboard_router.post("/diagnostics/traces/clear")
async def diagnostics_traces_clear(
    user: dict = Depends(require_permission("view_live")),
):
    """v0.8-rc6 · Vide le ring buffer des traces."""
    from pipeline_v2.trace import collector
    n = collector.clear()
    return {"ok": True, "purged": n}



# ═════════════════════════════════════════════════════════════════════
# v0.8-rc7 · Sprint 4 · Stability Watcher endpoints (Priorité #4)
# ═════════════════════════════════════════════════════════════════════
@health_dashboard_router.get("/diagnostics/stability")
async def diagnostics_stability(
    window: str = "1h",
    user: dict = Depends(require_permission("view_live")),
):
    """v0.8-rc7 · Retour agrégé Stability Watcher sur la fenêtre choisie.

    window ∈ {"1h", "6h", "24h", "72h"}

    Réponse : {window, snapshot_count, latest, aggregates{ram,cpu,rss,
    mongo_uptime_pct, go2rtc_uptime_pct}}.

    Le watcher tourne en background (tick 60 s) — voir server.on_startup.
    """
    # v3.24 · Étape 2b : watcher.snapshot(window) (catégorie b) via snapshot
    # Redis (toutes les fenêtres 1h/6h/24h/72h déjà agrégées à l'écriture),
    # plus d'import direct pipeline_v2.stability_watcher.
    from pipeline_snapshot import get_snapshot
    snap = await get_snapshot()
    if snap is None:
        return dict(_SNAPSHOT_UNAVAILABLE)
    windows = snap["stability"]["windows"]
    if window not in windows:
        raise HTTPException(status_code=400,
                             detail=f"window doit être dans {list(windows)}")
    return windows[window]


@health_dashboard_router.get("/diagnostics/stability/latest")
async def diagnostics_stability_latest(
    user: dict = Depends(require_permission("view_live")),
):
    """v0.8-rc7 · Dernier snapshot brut (utile pour dashboards temps réel)."""
    from pipeline_snapshot import get_snapshot
    snap = await get_snapshot()
    latest = (snap or {}).get("stability", {}).get("latest")
    if latest is None:
        raise HTTPException(status_code=404, detail="pas encore de snapshot (attendre 60s)")
    return latest


@health_dashboard_router.post("/diagnostics/stability/clear")
async def diagnostics_stability_clear(
    user: dict = Depends(require_permission("view_live")),
):
    """v0.8-rc7 · Purge le ring buffer (tests / redémarrage soft)."""
    from pipeline_v2.stability_watcher import watcher
    n = watcher.clear()
    return {"ok": True, "purged": n}
