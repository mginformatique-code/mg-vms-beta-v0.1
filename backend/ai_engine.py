"""MG-VMS — Couche acquisition + modèles du moteur IA (v0.4.2 · Pipeline v2).

Depuis la refonte v0.4.2, ce module NE contient PLUS la logique métier.
Ses seules responsabilités :
  1. Acquisition RTSP (frame_source workers + fallback go2rtc)
  2. Chargement des modèles (YOLO / fast-alpr) + santé IA
  3. Config runtime (interval, confidence, ByteTrack, ANPR par caméra)
  4. Boucle ``ai_loop`` : crée les FrameContext et démarre les CameraWorker

Toute l'exécution du pipeline vit dans ``pipeline_v2`` :
  PipelineRuntime → CameraWorker → FrameContext → Stages → PluginBus
Les fonctions historiques (`_analyze_frame`, `_do_downstream_work`, scénarios…)
sont conservées comme wrappers/re-exports de compatibilité.
"""
import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

from database import db
from pipeline_metrics import pipeline_metrics

logger = logging.getLogger("ai-engine")

GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://localhost:1984")
AI_INTERVAL = float(os.environ.get("AI_INTERVAL_SECONDS", "2"))
AI_CONFIDENCE = float(os.environ.get("AI_CONFIDENCE", "0.45"))
AI_MIN_PLATE_PX = int(os.environ.get("AI_MIN_PLATE_PX", "24"))
AI_PLATE_CACHE_SECONDS = int(os.environ.get("AI_PLATE_CACHE_SECONDS", "8"))
AI_DEVICE = os.environ.get("AI_DEVICE", "auto")
EVENT_COOLDOWN = int(os.environ.get("AI_EVENT_COOLDOWN_SECONDS", "60"))
MOTION_THRESHOLD_PCT = float(os.environ.get("MOTION_THRESHOLD_PCT", "1.5"))
MOTION_COOLDOWN = int(os.environ.get("MOTION_COOLDOWN_SECONDS", "60"))

# ── Config runtime ──────────────────────────────────────────────────
_runtime_config: dict = {}
_bytetrack_cfg: dict = {}
_camera_anpr_cfg: dict[str, dict] = {}


def _cfg(key: str, default):
    return _runtime_config.get(key, default)


async def load_runtime_config():
    doc = await db.settings.find_one({"key": "ai_config"}, {"_id": 0})
    if doc and isinstance(doc.get("value"), dict):
        _runtime_config.update(doc["value"])
    bt = await db.settings.find_one({"key": "bytetrack_config"}, {"_id": 0})
    if bt and isinstance(bt.get("value"), dict):
        _bytetrack_cfg.update(bt["value"])
    logger.info("Config IA runtime chargée : %s (bytetrack=%s)",
                _runtime_config or "(défauts env)", _bytetrack_cfg.get("enabled", False))


async def refresh_per_camera_configs():
    cams = await db.cameras.find({"detect_enabled": True},
                                  {"_id": 0, "id": 1, "anpr_config": 1}).to_list(500)
    _camera_anpr_cfg.clear()
    for c in cams:
        cfg = c.get("anpr_config") or {}
        if cfg:
            _camera_anpr_cfg[c["id"]] = cfg


async def update_runtime_config(patch: dict) -> dict:
    _runtime_config.update({k: v for k, v in patch.items() if v is not None})
    await db.settings.update_one(
        {"key": "ai_config"},
        {"$set": {"key": "ai_config", "value": _runtime_config}},
        upsert=True,
    )
    return dict(_runtime_config)


def get_runtime_config() -> dict:
    return {
        "interval_seconds": _cfg("interval_seconds", AI_INTERVAL),
        "confidence": _cfg("confidence", AI_CONFIDENCE),
        "min_plate_px": _cfg("min_plate_px", AI_MIN_PLATE_PX),
        "plate_cache_seconds": _cfg("plate_cache_seconds", AI_PLATE_CACHE_SECONDS),
        "device": _cfg("device", AI_DEVICE),
        "device_effective": _detected_device(),
    }


CLASS_FR = {
    "person": "Personne", "car": "Voiture", "truck": "Camion", "bus": "Bus",
    "motorcycle": "Moto", "bicycle": "Vélo", "dog": "Animal", "cat": "Animal",
}
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle"}

# ── Modèles + santé IA ──────────────────────────────────────────────
_model = None
_alpr = None
_ai_health: dict = {
    "yolo_loaded": False,
    "yolo_error": None,
    "yolo_load_attempts": 0,
    "yolo_last_attempt_ts": None,
    "alpr_loaded": False,
    "alpr_error": None,
    "alpr_load_attempts": 0,
    "alpr_last_attempt_ts": None,
    "torch_available": None,
    "torch_cuda_available": None,
    "torch_version": None,
    "torch_error": None,
    "ultralytics_version": None,
    "fast_alpr_available": None,
    "device_effective": None,
    "cycles_total": 0,
    "cycles_errors_last_hour": 0,
    "last_cycle_ts": None,
    "last_cycle_error": None,
    "loop_alive": False,
    "loop_disabled_reason": None,
}


def _detected_device() -> str:
    if os.environ.get("MGVMS_AI_FORCE_CPU", "0") in ("1", "true", "yes"):
        return "cpu"
    pref = _cfg("device", AI_DEVICE)
    if pref == "cpu":
        return "cpu"
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda:0"
    except Exception:
        pass
    return "cpu"


def _capture_torch_info() -> None:
    if _ai_health["torch_available"] is not None:
        return
    try:
        import torch
        _ai_health["torch_available"] = True
        _ai_health["torch_version"] = getattr(torch, "__version__", "?")
        try:
            _ai_health["torch_cuda_available"] = bool(torch.cuda.is_available())
        except Exception as e:
            _ai_health["torch_cuda_available"] = False
            _ai_health["torch_error"] = f"cuda.is_available: {e!r}"
    except Exception as e:
        _ai_health["torch_available"] = False
        _ai_health["torch_error"] = f"import torch: {e!r}"
    try:
        import ultralytics
        _ai_health["ultralytics_version"] = getattr(ultralytics, "__version__", "?")
    except Exception:
        _ai_health["ultralytics_version"] = None
    try:
        import fast_alpr  # noqa: F401
        _ai_health["fast_alpr_available"] = True
    except Exception:
        _ai_health["fast_alpr_available"] = False


def _load_models():
    """Chargement paresseux résilient (YOLO + ALPR) — ne throw jamais."""
    global _model, _alpr
    _capture_torch_info()
    device = _detected_device()
    _ai_health["device_effective"] = device
    now = datetime.now(timezone.utc).isoformat()

    if _model is None:
        _ai_health["yolo_load_attempts"] += 1
        _ai_health["yolo_last_attempt_ts"] = now
        try:
            from ultralytics import YOLO
            model_path = os.environ.get("AI_MODEL", "yolo11n.pt")
            _model = YOLO(model_path)
            try:
                _model.to(device)
                effective_device = device
            except Exception as gpu_err:
                logger.warning("YOLO .to(%s) échec (%s) — fallback CPU", device, gpu_err)
                try:
                    _model.to("cpu")
                    effective_device = "cpu"
                    _ai_health["device_effective"] = "cpu"
                except Exception:
                    effective_device = "cpu"
            _ai_health["yolo_loaded"] = True
            _ai_health["yolo_error"] = None
            logger.info("Modèle YOLO chargé (device=%s) : %s", effective_device, model_path)
        except Exception as e:
            _model = None
            _ai_health["yolo_loaded"] = False
            _ai_health["yolo_error"] = f"{type(e).__name__}: {str(e)[:240]}"
            logger.exception("YOLO indisponible — détection d'objets désactivée (essai #%d)",
                             _ai_health["yolo_load_attempts"])

    if _alpr is None or _alpr is False:
        _ai_health["alpr_load_attempts"] += 1
        _ai_health["alpr_last_attempt_ts"] = now
        try:
            from fast_alpr import ALPR
            _alpr = ALPR(detector_model="yolo-v9-t-384-license-plate-end2end",
                         ocr_model="european-plates-mobile-vit-v2-model")
            _ai_health["alpr_loaded"] = True
            _ai_health["alpr_error"] = None
            logger.info("LAPI locale chargée (fast-alpr, CPU-ONNX)")
        except Exception as e:
            _alpr = False
            _ai_health["alpr_loaded"] = False
            _ai_health["alpr_error"] = f"{type(e).__name__}: {str(e)[:240]}"
            logger.exception("fast-alpr indisponible — LAPI désactivée (essai #%d)",
                             _ai_health["alpr_load_attempts"])


def get_ai_health() -> dict:
    import copy
    snap = copy.deepcopy(_ai_health)
    snap["yolo_model"] = os.environ.get("AI_MODEL", "yolo11n.pt")
    snap["alpr_models"] = _alpr_model_name() if _ai_health["alpr_loaded"] else None
    snap["force_cpu_env"] = os.environ.get("MGVMS_AI_FORCE_CPU", "0") in ("1", "true", "yes")
    return snap


def _model_name() -> str:
    return os.environ.get("AI_MODEL", "yolo11n.pt")


def _alpr_model_name() -> str:
    return "fast-alpr · yolo-v9-t-384-license-plate-end2end + european-plates-mobile-vit-v2-model"


# ── Utilitaires image (implémentation dans pipeline_v2.frame_context) ─
from pipeline_v2.frame_context import (encode_jpeg_data_uri as _jpeg_data_uri,  # noqa: E402
                                        dominant_color_fr as _dominant_color_fr,
                                        point_in_polygon as _point_in_polygon)


def _ensure_frame_thumb(result: dict):
    """Encode la scène HD à la demande, memoizé dans `result` (1 seul encodage)."""
    if "frame_thumb" in result:
        return result["frame_thumb"]
    ctx = result.get("_ctx")
    if ctx is not None:
        thumb = ctx.jpeg_data_uri()
    else:
        img = result.get("_img_bgr")
        thumb = _jpeg_data_uri(img) if img is not None else None
    result["frame_thumb"] = thumb
    return thumb


def get_debug_snapshot(camera_id: str) -> dict:
    from pipeline_v2.camera_worker import get_debug_snapshot as _snap
    return _snap(camera_id)


# ── Wrappers de compatibilité → pipeline_v2 ─────────────────────────

def _analyze_frame(camera_id: str, frame_bytes: bytes,
                   enabled_plugins: Optional[list] = None,
                   camera: Optional[dict] = None) -> dict:
    """Compat : délègue au CameraWorker de la caméra (pipeline v2)."""
    from pipeline_v2.camera_worker import runtime as _runtime
    return _runtime.worker(camera_id).analyze(
        frame_bytes, enabled_plugins=enabled_plugins, camera=camera)


async def _do_downstream_work(cam: dict, frame, result: dict) -> None:
    """Compat : délègue au downstream pipeline v2."""
    from pipeline_v2.downstream import run_downstream
    await run_downstream(cam, frame, result)


# Re-exports scénarios / armement (logique déplacée dans pipeline_v2.scenarios)
from pipeline_v2.scenarios import (DEFAULT_ARMING, DEFAULT_SCENARIOS,  # noqa: E402,F401
                                    _evaluate_scenarios, _get_scenario_rules,
                                    _is_armed, _is_night, _iou,
                                    _raise_blacklist_alert, _raise_scenario_alert,
                                    cooldown_ok as _cooldown_ok, get_arming_config)


def analyze_image_local(image_bytes: bytes) -> dict:
    """Analyse LOCALE d'une image (upload manuel) : YOLO + fast-alpr."""
    import cv2
    import numpy as np
    _load_models()
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"plate": "", "confidence": 0.0}
    result = {"plate": "", "country": "", "vehicle_color": "", "vehicle_make": "",
              "vehicle_model": "", "vehicle_type": "Inconnu", "confidence": 0.0, "plate_crop": ""}
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


# ── Acquisition ─────────────────────────────────────────────────────

async def _fetch_frame(camera_id: str) -> bytes | None:
    """Frame la plus récente d'une caméra (frame_source RTSP direct, fallback go2rtc)."""
    import cv2
    try:
        from frame_source import get_latest_frame_async
        frame = await get_latest_frame_async(camera_id, max_age_sec=5.0, wait_timeout=0.5)
        if frame is not None:
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if ok:
                return buf.tobytes()
    except Exception as e:
        logger.debug("_fetch_frame: frame_source indispo pour %s (%s)", camera_id, e)
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(f"{GO2RTC_URL}/api/frame.jpeg", params={"src": f"cam_{camera_id}"})
            if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
                return r.content
    except httpx.HTTPError:
        pass
    return None


async def _sync_frame_source_workers(cams: list[dict]) -> None:
    """Synchronise les workers ffmpeg persistants avec les caméras actives."""
    import frame_source
    go2rtc_rtsp = os.environ.get("GO2RTC_RTSP", "rtsp://go2rtc:8554")
    use_direct = os.environ.get("MGVMS_AI_DIRECT_RTSP", "1").lower() not in ("0", "false", "no")

    active_ids = set()
    for cam in cams:
        cam_id = cam["id"]
        ai_url = (cam.get("ai_rtsp_url") or "").strip()
        native_url = (cam.get("rtsp_url") or "").strip()
        is_demo = cam_id.startswith("demo-") or cam_id.startswith("demo_")

        if is_demo:
            rtsp_url = f"{go2rtc_rtsp}/cam_{cam_id}"
            source_type = "demo-go2rtc-relay"
        elif use_direct and ai_url:
            rtsp_url = ai_url
            source_type = "direct-ai"
        elif use_direct and native_url:
            rtsp_url = native_url
            source_type = "direct-native"
        elif native_url or ai_url:
            rtsp_url = f"{go2rtc_rtsp}/cam_{cam_id}"
            source_type = "go2rtc-relay"
        else:
            logger.warning("frame_source: skip %s (aucune URL RTSP configurée)", cam_id)
            continue

        active_ids.add(cam_id)
        codec = (cam.get("codec") or "auto").lower()
        if codec not in ("h264", "h265", "hevc", "auto"):
            codec = "auto"
        if codec == "hevc":
            codec = "h265"
        try:
            frame_source.start(cam_id, rtsp_url, codec=codec, width=1280, height=720)
            logger.info("frame_source.start %s src=%s codec=%s (%s)",
                        cam_id, source_type, codec, rtsp_url[:60] + ("…" if len(rtsp_url) > 60 else ""))
        except Exception as e:
            logger.warning("frame_source.start(%s) échec: %s", cam_id, e)

    current = set(frame_source.status().get("workers", {}).keys())
    for stale in current - active_ids:
        try:
            frame_source.stop(stale)
        except Exception:
            pass


# ── Boucle temps réel : Phase A sync + Phase B downstream ───────────
_downstream_inflight: dict[str, int] = {}
_MAX_DOWNSTREAM_INFLIGHT = int(os.environ.get("AI_MAX_DOWNSTREAM_INFLIGHT", "2"))


async def _process_camera(cam: dict) -> None:
    """Phase A : acquisition + CameraWorker (pipeline v2) + broadcast overlay."""
    from pipeline_v2.camera_worker import runtime as _runtime
    from pipeline_v2.inspector import inspector as _inspector

    t_start = time.perf_counter()
    frame = await _fetch_frame(cam["id"])
    if frame is None:
        logger.info("IA · %s (%s) : frame indisponible (flux offline)", cam["name"], cam["id"])
        return
    t_fetch_ms = (time.perf_counter() - t_start) * 1000
    _inspector.record(cam["id"], "fetch", t_fetch_ms)

    _enabled = cam.get("enabled_plugins") or []
    worker = _runtime.worker(cam["id"])
    result = await asyncio.to_thread(worker.analyze, frame, _enabled, cam)
    dets = result.get("detections", [])
    plates = result.get("plates", [])
    tim = result.get("timings", {})

    # Broadcast overlay (léger, <5 ms)
    t_ws = time.perf_counter()
    try:
        from realtime import broadcast_ai_detections
        await broadcast_ai_detections(cam["id"], cam.get("site_id", ""), {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "boxes": result.get("overlay_boxes", []),
            "counts": result.get("counts", {}),
            "motion_pct": result.get("motion_pct", 0.0),
        })
    except Exception:
        logger.exception("broadcast_ai_detections error")
    _inspector.record(cam["id"], "websocket", (time.perf_counter() - t_ws) * 1000)

    t_frontier_ms = (time.perf_counter() - t_start) * 1000
    pipeline_metrics.record_stage(cam["id"], "fetch_ms", t_fetch_ms)
    pipeline_metrics.record_stage(cam["id"], "yolo_ms", tim.get("yolo_ms", 0))
    pipeline_metrics.record_stage(cam["id"], "tracking_ms", tim.get("tracking_ms", 0))
    pipeline_metrics.record_stage(cam["id"], "alpr_ms", tim.get("alpr_ms", 0))
    pipeline_metrics.record_stage(cam["id"], "realtime_ms", t_frontier_ms)

    logger.info(
        "IA · %s (%s) : %d détection(s) [%s] · mouvement=%.1f%% · %d plaque(s) · "
        "fetch=%.0fms yolo=%.0fms tracking=%.0fms alpr=%.0fms rt=%.0fms",
        cam["name"], cam["id"], len(dets),
        ",".join(f"{d['label']}:{d['confidence']}" for d in dets) or "aucune",
        result.get("motion_pct", 0.0), len(plates),
        t_fetch_ms, tim.get("yolo_ms", 0), tim.get("tracking_ms", 0),
        tim.get("alpr_ms", 0), t_frontier_ms,
    )

    # Phase B : downstream fire-and-forget (backpressure)
    inflight = _downstream_inflight.get(cam["id"], 0)
    if inflight >= _MAX_DOWNSTREAM_INFLIGHT:
        pipeline_metrics.record_drop(cam["id"])
        logger.warning(
            "IA · %s : downstream saturé (%d en vol) — frame IA droppée pour préserver le live",
            cam["name"], inflight,
        )
        return
    _downstream_inflight[cam["id"]] = inflight + 1
    asyncio.create_task(_process_downstream(cam, frame, result))


async def _process_downstream(cam: dict, frame, result: dict) -> None:
    """Phase B : downstream pipeline v2 en arrière-plan."""
    from pipeline_v2.inspector import inspector as _inspector
    t_down = time.perf_counter()
    try:
        await _do_downstream_work(cam, frame, result)
        t_down_ms = (time.perf_counter() - t_down) * 1000
        pipeline_metrics.record_stage(cam["id"], "downstream_ms", t_down_ms)
        _inspector.record(cam["id"], "downstream", t_down_ms)
    except Exception:
        _inspector.record(cam["id"], "downstream",
                          (time.perf_counter() - t_down) * 1000, error=True)
        logger.exception("_process_downstream error for %s", cam.get("id"))
    finally:
        _downstream_inflight[cam["id"]] = max(0, _downstream_inflight.get(cam["id"], 1) - 1)


async def ai_loop() -> None:
    """Boucle IA : un CameraWorker par caméra `detect_enabled`, en parallèle."""
    await asyncio.sleep(15)
    _ai_health["loop_alive"] = True
    _ai_health["loop_disabled_reason"] = None
    try:
        await asyncio.to_thread(_load_models)
    except Exception as e:
        logger.exception("Premier chargement des modèles IA a échoué — la boucle continue")
        _ai_health["last_cycle_error"] = f"initial _load_models: {type(e).__name__}: {str(e)[:200]}"
    await load_runtime_config()
    logger.info(
        "Moteur IA démarré (device=%s · intervalle=%.1fs · yolo=%s · alpr=%s · pipeline=v2)",
        _detected_device(), _cfg("interval_seconds", AI_INTERVAL),
        "ok" if _ai_health["yolo_loaded"] else f"KO ({_ai_health['yolo_error']})",
        "ok" if _ai_health["alpr_loaded"] else f"KO ({_ai_health['alpr_error']})",
    )
    while True:
        _ai_health["cycles_total"] += 1
        _ai_health["last_cycle_ts"] = datetime.now(timezone.utc).isoformat()
        try:
            if not _ai_health["yolo_loaded"] or not _ai_health["alpr_loaded"]:
                try:
                    await asyncio.to_thread(_load_models)
                except Exception as reload_err:
                    logger.debug("Retry _load_models: %s", reload_err)
            await refresh_per_camera_configs()
            await load_runtime_config()
            cams = await db.cameras.find({"detect_enabled": True, "status": "online"}, {"_id": 0}).to_list(200)
            await _sync_frame_source_workers(cams)
            if cams:
                logger.info("IA · cycle : %d caméra(s) réelle(s) en parallèle %s",
                            len(cams), [c["name"] for c in cams])
                await asyncio.gather(*[_process_camera(cam) for cam in cams], return_exceptions=True)
        except Exception as e:
            _ai_health["last_cycle_error"] = f"{type(e).__name__}: {str(e)[:200]}"
            logger.exception("ai_loop : erreur, reprise")
        await asyncio.sleep(float(_cfg("interval_seconds", AI_INTERVAL)))
