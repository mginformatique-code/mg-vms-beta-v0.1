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
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

from database import db
from pipeline_metrics import pipeline_metrics

logger = logging.getLogger("ai-engine")

GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://localhost:1984")

# v0.5.6 P0-1 · Verrous globaux protégeant les singletons YOLO/ALPR.
#
# Contexte : `_model` et `_alpr` sont des singletons partagés par toutes les
# caméras (`_stage_detection` dans `camera_worker.py` et `_stage_anpr_fast`
# les appellent en concurrence via `asyncio.to_thread`). Ultralytics et
# fast-alpr mutent leur état interne (batch buffers, predictor state) à
# chaque `predict()` — sans verrou, on risque des détections mélangées
# entre caméras voire des crashes CUDA à haute charge.
#
# Ces locks *threading* sont acquis SYNC dans le thread où l'inférence
# tourne (via `asyncio.to_thread`), donc ils ne bloquent PAS l'event loop
# asyncio principal. Sérialisent uniquement les appels au modèle.
#
# v3.19 · ALPR_INFERENCE_LOCK pointait vers un second `threading.Lock()`
# distinct : chaque moteur était bien sérialisé CONTRE LUI-MÊME, mais
# YOLO (torch) et ALPR (fast-alpr, backend PaddleOCR) pouvaient toujours
# tourner EN MÊME TEMPS sur le même GPU. À 14 caméras, ça a fini par
# provoquer des "CUDA error: operation not permitted when stream is
# capturing" suivis de segfaults fatals côté runtime C++ de Paddle
# (process entier tué, conteneur redémarré — observé plusieurs fois/heure
# en conditions réelles). Les deux noms restent distincts (contrat déjà
# testé), mais pointent maintenant vers LE MÊME verrou : YOLO et ALPR ne
# touchent plus jamais le GPU en même temps.
YOLO_INFERENCE_LOCK = threading.Lock()
ALPR_INFERENCE_LOCK = YOLO_INFERENCE_LOCK
AI_INTERVAL = float(os.environ.get("AI_INTERVAL_SECONDS", "0.15"))  # v0.4.5.a · ~6-7 FPS/cam
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

# v0.7.e · Hot Reload chirurgical — signal-driven reloads.
#   * `_config_dirty` : mis à True par les routes qui touchent ai_config /
#     bytetrack_config → la boucle IA rechargera au prochain cycle uniquement.
#   * `_camera_config_dirty` : idem pour anpr_config par-caméra.
#   * `_cameras_topology_dirty` : signale que la liste des workers doit être
#     resynchronisée (ajout / suppression / changement d'URL RTSP).
#   * `_camera_dirty_set` : quand un seul cam_id est ciblé (ajout/PUT/DELETE),
#     seul ce worker est re-synchronisé — pas de balayage global.
#   * `_last_*_reload_ts` : TTL de sûreté (10s) — si aucun signal reçu depuis
#     N secondes on rescanne quand même (défense en profondeur pour rattraper
#     un changement externe passé sous le radar).
_config_dirty: bool = True                # rechargé au 1er cycle
_camera_config_dirty: bool = True         # idem
_cameras_topology_dirty: bool = True      # idem
_camera_dirty_set: set[str] = set()
_last_config_reload_ts: float = 0.0
_last_camera_config_reload_ts: float = 0.0
_last_topology_sync_ts: float = 0.0
_HOT_RELOAD_TTL_SEC = float(os.environ.get("MGVMS_HOT_RELOAD_TTL_SEC", "10.0"))

# Compteurs de preuve (exposés par get_hot_reload_metrics)
_hot_reload_metrics: dict = {
    "config_reloads": 0,
    "camera_config_reloads": 0,
    "topology_syncs_full": 0,
    "topology_syncs_partial": 0,
    "frame_source_starts": 0,
    "frame_source_stops": 0,
    "cycles_since_boot": 0,
    "signals_received": {
        "config": 0,
        "camera_config": 0,
        "camera_topology": 0,
    },
}


def signal_config_changed() -> None:
    """Signale qu'un paramètre IA global (ai_config / bytetrack_config) a changé.

    Le prochain cycle de la boucle IA rechargera la config depuis Mongo.
    """
    global _config_dirty
    _config_dirty = True
    _hot_reload_metrics["signals_received"]["config"] += 1


def signal_camera_config_changed(camera_id: Optional[str] = None) -> None:
    """Signale qu'une config par-caméra (anpr_config, enabled_plugins, ...) a
    changé. Optionnellement ciblée sur un ``camera_id`` — sinon full refresh.
    """
    global _camera_config_dirty
    _camera_config_dirty = True
    _hot_reload_metrics["signals_received"]["camera_config"] += 1


def signal_camera_topology_changed(camera_id: Optional[str] = None,
                                    removed: bool = False) -> None:
    """Signale un changement de topologie flotte (ajout / suppression / URL
    RTSP modifiée). Si ``camera_id`` est fourni, seul ce worker sera resync
    au prochain cycle — le reste du pipeline continue à fonctionner sans
    interruption.
    """
    global _cameras_topology_dirty
    _cameras_topology_dirty = True
    _hot_reload_metrics["signals_received"]["camera_topology"] += 1
    if camera_id:
        _camera_dirty_set.add(camera_id)
    # removed=True est passé pour référence — le sync detectera l'absence et
    # arrêtera le worker orphelin.


def get_hot_reload_metrics() -> dict:
    """Compteurs exposés par ``/api/diagnostics/hot-reload`` (Wave A preuves)."""
    return {
        **_hot_reload_metrics,
        "camera_dirty_pending": sorted(_camera_dirty_set),
        "flags": {
            "config_dirty": _config_dirty,
            "camera_config_dirty": _camera_config_dirty,
            "cameras_topology_dirty": _cameras_topology_dirty,
        },
        "last_reload_ts": {
            "config": _last_config_reload_ts,
            "camera_config": _last_camera_config_reload_ts,
            "topology": _last_topology_sync_ts,
        },
        "ttl_sec": _HOT_RELOAD_TTL_SEC,
    }


def _cfg(key: str, default):
    return _runtime_config.get(key, default)


async def load_runtime_config():
    """Recharge ai_config + bytetrack_config depuis Mongo.

    v0.7.e · Appelée UNIQUEMENT sur signal ou expiration TTL — plus jamais
    à chaque cycle IA. Voir ``signal_config_changed()``.
    """
    global _last_config_reload_ts, _config_dirty
    doc = await db.settings.find_one({"key": "ai_config"}, {"_id": 0})
    if doc and isinstance(doc.get("value"), dict):
        _runtime_config.update(doc["value"])
    bt = await db.settings.find_one({"key": "bytetrack_config"}, {"_id": 0})
    if bt and isinstance(bt.get("value"), dict):
        _bytetrack_cfg.update(bt["value"])
    _last_config_reload_ts = time.time()
    _config_dirty = False
    _hot_reload_metrics["config_reloads"] += 1
    logger.info("Config IA runtime chargée : %s (bytetrack=%s)",
                _runtime_config or "(défauts env)", _bytetrack_cfg.get("enabled", False))


async def refresh_per_camera_configs():
    """Recharge la map ``anpr_config`` par-caméra depuis Mongo.

    v0.7.e · Appelée UNIQUEMENT sur signal ou TTL — plus par cycle IA.
    """
    global _last_camera_config_reload_ts, _camera_config_dirty
    cams = await db.cameras.find({"detect_enabled": True},
                                  {"_id": 0, "id": 1, "anpr_config": 1}).to_list(500)
    _camera_anpr_cfg.clear()
    for c in cams:
        cfg = c.get("anpr_config") or {}
        if cfg:
            _camera_anpr_cfg[c["id"]] = cfg
    _last_camera_config_reload_ts = time.time()
    _camera_config_dirty = False
    _hot_reload_metrics["camera_config_reloads"] += 1


async def update_runtime_config(patch: dict) -> dict:
    _runtime_config.update({k: v for k, v in patch.items() if v is not None})
    await db.settings.update_one(
        {"key": "ai_config"},
        {"$set": {"key": "ai_config", "value": _runtime_config}},
        upsert=True,
    )
    signal_config_changed()  # v0.7.e · autres process/watchers voient direct
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
_pose_model = None  # yolo11n-pose — chargé au 1er besoin (retail-suspicious-behavior)
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
            # v3.1.9 · Root cause d'une latence API généralisée (TOUS les
            # endpoints touchés, pas seulement ANPR) : ce process tourne en
            # un seul worker Uvicorn (--workers 1), donc tout travail CPU
            # lourd exécuté via asyncio.to_thread() sature quand même le GIL
            # et affame la boucle asyncio (et les autres threads) pendant sa
            # durée. `ALPR(...)` était instancié SANS jamais préciser de
            # provider ONNX Runtime — confirmé en prod : GPU à 3% d'utilisation
            # pendant que le conteneur backend tournait à 461% CPU (sur 6
            # coeurs). `CUDAExecutionProvider` est bien disponible
            # (confirmé via onnxruntime.get_available_providers()) mais
            # jamais demandé — chaque inférence fast-alpr (détection +
            # OCR plaque) tournait donc entièrement sur CPU. Passage explicite
            # sur CUDA (avec repli CPU si l'appel échoue, ex. environnement
            # sans GPU) — décharge ce travail sur le GPU qui était
            # quasiment inactif, libère le CPU pour le reste de l'API.
            try:
                _alpr = ALPR(detector_model="yolo-v9-t-384-license-plate-end2end",
                             detector_providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                             ocr_model="european-plates-mobile-vit-v2-model",
                             ocr_device="cuda")
                logger.info("LAPI locale chargée (fast-alpr, GPU-ONNX/CUDA)")
            except Exception as gpu_err:
                logger.warning("fast-alpr GPU indisponible (%s) — repli CPU", gpu_err)
                _alpr = ALPR(detector_model="yolo-v9-t-384-license-plate-end2end",
                             ocr_model="european-plates-mobile-vit-v2-model")
                logger.info("LAPI locale chargée (fast-alpr, CPU-ONNX)")
            _ai_health["alpr_loaded"] = True
            _ai_health["alpr_error"] = None
        except Exception as e:
            _alpr = False
            _ai_health["alpr_loaded"] = False
            _ai_health["alpr_error"] = f"{type(e).__name__}: {str(e)[:240]}"
            logger.exception("fast-alpr indisponible — LAPI désactivée (essai #%d)",
                             _ai_health["alpr_load_attempts"])


def _load_pose_model():
    """Chargement paresseux du modèle de pose (squelette Camera Center,
    plugin retail-suspicious-behavior). Séparé de `_load_models()` : ne se
    déclenche que si une caméra a réellement ce plugin actif — pas de coût
    (VRAM/démarrage) pour une installation qui ne l'utilise pas.

    `yolo11n-pose.pt` suit la même convention que `yolo11n.pt` (poids
    vendorisés dans `backend/`, cf. AI_MODEL) — si absent, ultralytics tente
    un téléchargement automatique depuis ses releases GitHub officielles
    (nécessite un accès réseau sortant sur le serveur, à vérifier)."""
    global _pose_model
    if _pose_model is not None:
        return _pose_model or None  # _pose_model peut être `False` (échec déjà tenté)
    try:
        from ultralytics import YOLO
        model_path = os.environ.get("AI_POSE_MODEL", "yolo11n-pose.pt")
        model = YOLO(model_path)
        device = _detected_device()
        try:
            model.to(device)
        except Exception as gpu_err:
            logger.warning("YOLO-pose .to(%s) échec (%s) — fallback CPU", device, gpu_err)
            model.to("cpu")
        _pose_model = model
        logger.info("Modèle pose chargé : %s", model_path)
    except Exception as e:
        _pose_model = False
        logger.exception("Modèle pose indisponible — squelette overlay désactivé (%s)", e)
    return _pose_model or None


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
    # v3.1.2 · 1920 au lieu du défaut 1280 : la source peut désormais être
    # capturée en natif (ai_resolution="native", ex. 3840x2160) mais la
    # vignette restait bridée à 1280px quel que soit le réglage — la montée
    # en résolution ne se voyait jamais dans les captures/miniatures UI.
    # 1920 plutôt que le natif complet : ces images sont stockées en base64
    # DANS les documents Mongo (pas des fichiers), pousser au 4K partout
    # multiplierait leur poids par ~9 au lieu de ~2.
    if ctx is not None:
        thumb = ctx.jpeg_data_uri(max_width=1920)
    else:
        img = result.get("_img_bgr")
        thumb = _jpeg_data_uri(img, max_width=1920) if img is not None else None
    result["frame_thumb"] = thumb
    return thumb


def _ensure_frame_thumb_sm(result: dict):
    """Miniature légère pour la grille de la page Événements (galerie).

    v3.1.4 · La galerie affiche des cartes d'à peine ~200px de large mais
    transportait la même image que la vue détaillée (1920px) — chaque
    chargement de la page Événements retéléchargeait des centaines de Ko
    d'images pour un rendu minuscule. Variante dédiée, même source (même
    ctx, un seul décodage), juste redimensionnée plus petit. La vue
    détaillée (EventViewer) continue d'utiliser `frame_thumb` (1920px).
    """
    if "frame_thumb_sm" in result:
        return result["frame_thumb_sm"]
    ctx = result.get("_ctx")
    if ctx is not None:
        thumb = ctx.jpeg_data_uri(max_width=384, quality=70)
    else:
        img = result.get("_img_bgr")
        thumb = _jpeg_data_uri(img, max_width=384, quality=70) if img is not None else None
    result["frame_thumb_sm"] = thumb
    return thumb


def get_debug_snapshot(camera_id: str) -> dict:
    from pipeline_v2.camera_worker import get_debug_snapshot as _snap
    return _snap(camera_id)


# ── Wrappers de compatibilité → pipeline_v2 ─────────────────────────

def _analyze_frame(camera_id: str, frame_bytes: bytes,
                   enabled_plugins: Optional[list] = None,
                   camera: Optional[dict] = None) -> dict:
    """Compat : délègue au CameraWorker de la caméra (pipeline v2)."""
    # P0-2 (v0.7.c) : garde lazy — appelé via asyncio.to_thread par les routes
    # on-demand (benchmark, test-détection) ; charge les modèles si absents.
    if _model is None or _alpr is None or _alpr is False:
        _load_models()
    from pipeline_v2.camera_worker import runtime as _runtime
    return _runtime.worker(camera_id).analyze(
        frame_bytes, enabled_plugins=enabled_plugins, camera=camera)


async def _do_downstream_work(cam: dict, frame, result: dict) -> None:
    """Compat : délègue au downstream pipeline v2."""
    from pipeline_v2.downstream import run_downstream
    await run_downstream(cam, frame, result)


# Re-exports scénarios / armement (logique déplacée dans pipeline_v2.scenarios ;
# la config armement/règles elle-même vit dans ai_rules_settings.py depuis le
# 02/09 — étape 2a séparation pipeline/API, zéro état pipeline dans ces
# fonctions, pas de raison de les garder dans ai_engine/pipeline_v2)
from pipeline_v2.scenarios import (_evaluate_scenarios,  # noqa: E402,F401
                                    _is_night, _iou,
                                    _raise_blacklist_alert, _raise_scenario_alert,
                                    cooldown_ok as _cooldown_ok)
from ai_rules_settings import (DEFAULT_ARMING, DEFAULT_SCENARIOS,  # noqa: E402,F401
                                _get_scenario_rules, _is_armed, get_arming_config)


def analyze_image_local(image_bytes: bytes) -> dict:
    """Analyse LOCALE d'une image (upload manuel) via le CameraWorker unique.

    v0.4.3 · P7 · L'analyse d'une image uploadée passe EXACTEMENT par le
    même pipeline (decode → motion → yolo → tracking → roi → anpr) que
    les frames RTSP. Zéro duplication : `analyze_image_local` = wrapper
    thin autour de `CameraWorker("__upload__").analyze(bytes,
    enabled_plugins=["fast-alpr"])`.
    """
    # P0-2 (v0.7.c) : garde lazy — l'analyse d'upload doit fonctionner même si
    # aucune caméra detect_enabled n'a déclenché le chargement des modèles.
    if _model is None or _alpr is None or _alpr is False:
        _load_models()
    from pipeline_v2.camera_worker import CameraWorker
    worker = CameraWorker("__upload__")
    # Enable fast-alpr explicitement : le CameraWorker est fail-safe strict —
    # sans whitelist, aucun plugin ANPR ne tournerait.
    res = worker.analyze(image_bytes, enabled_plugins=["fast-alpr"], camera=None)
    out = {"plate": "", "country": "", "vehicle_color": "", "vehicle_make": "",
           "vehicle_model": "", "vehicle_type": "Inconnu", "confidence": 0.0,
           "plate_crop": ""}
    dets = res.get("detections") or []
    veh = next((d for d in dets if d.get("class") in VEHICLE_CLASSES), None)
    if veh:
        out["vehicle_type"] = veh.get("label", "Inconnu")
        out["vehicle_color"] = veh.get("vehicle_color") or ""
    plates = res.get("plates") or []
    if plates:
        p = plates[0]
        out["plate"] = (p.get("plate") or "").upper()
        out["confidence"] = float(p.get("confidence", 0.0))
        out["plate_crop"] = p.get("plate_crop") or ""
    return out


# ── Acquisition ─────────────────────────────────────────────────────

async def _fetch_frame(camera_id: str):
    """Frame la plus récente d'une caméra.

    v0.4.5.a · Pipeline non-bloquant strict :
      1. ``frame_source.get_latest_frame_async(wait_timeout=0)`` — retour
         immédiat de la ref numpy (zéro copie, zéro attente).
      2. Fallback go2rtc HTTP réservé UNIQUEMENT au worker sévèrement mort
         (>10 s sans frame, restart_count > 0) : dernière chance snapshot,
         jamais dans le chemin nominal.
      3. Si rien : renvoie None, le pipeline saute cette itération.
    """
    try:
        from frame_source import get_latest_frame_async, status as _fs_status
        frame = await get_latest_frame_async(camera_id, max_age_sec=5.0, wait_timeout=0.0)
        if frame is not None:
            return frame  # chemin nominal — zéro fallback
        # Fallback strict : worker en crash persistant seulement.
        w = _fs_status().get("workers", {}).get(camera_id, {})
        age_ms = w.get("last_frame_age_ms")
        restart = w.get("restart_count", 0) or 0
        if not (restart > 0 and (age_ms is None or age_ms > 10000)):
            return None
    except Exception as e:
        logger.debug("_fetch_frame: frame_source indispo pour %s (%s)", camera_id, e)
        return None
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{GO2RTC_URL}/api/frame.jpeg", params={"src": f"cam_{camera_id}"})
            if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
                logger.warning("_fetch_frame: fallback go2rtc utilisé (worker %s crashé)", camera_id)
                return r.content
    except httpx.HTTPError:
        pass
    return None


# v3.1.3 · Étape 0 de la refonte GPU (voir plan "cœur vidéo") : remettre
# ``ai_resolution`` au pilotage de la résolution de DÉCODAGE CONTINU,
# maintenant que frame_source.py limite le débit de sortie AVANT
# hwdownload (voir _OUTPUT_FPS dans frame_source.py) — le problème mesuré
# n'était pas "natif = trop lourd", c'était "décoder/télécharger à ~20-25 fps
# alors que la boucle IA ne consomme qu'à ~6,7 fps" (>70% des frames jetées
# sans jamais être lues). Avec le débit limité, natif redevient jouable en
# continu. La récupération HD à la demande (_stage_roi) reste en place comme
# filet de sécurité pour les caméras encore en 1080p/native si ce test ne
# suffisait pas — sans effet si ctx.image est déjà natif.
AI_RESOLUTION_PRESETS = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}


def _resolve_ai_resolution(cam: dict) -> tuple[int, int]:
    """(width, height) pour frame_source.start() selon ``cam.ai_resolution``.

    "native" résout la résolution réelle depuis ``cam.resolution`` (déjà
    sondée à la création/ONVIF, ex. "3840x2160") plutôt que de passer
    width=0/height=0 : le thread lecteur de frame_source.py suppose une
    taille de buffer fixe (1280×720 par défaut) quand width/height=0, donc
    un vrai "0 = natif" désynchroniserait la lecture au lieu de fonctionner
    (voir frame_source.py::_reader_loop, commentaire "Simplification").
    """
    preset = (cam.get("ai_resolution") or "720p").lower()
    if preset in AI_RESOLUTION_PRESETS:
        return AI_RESOLUTION_PRESETS[preset]
    if preset == "native":
        res = (cam.get("resolution") or "").lower().replace(" ", "")
        m = re.match(r"^(\d{2,5})x(\d{2,5})$", res)
        if m:
            return int(m.group(1)), int(m.group(2))
        logger.warning(
            "ai_resolution=native mais cam.resolution absent/invalide (%s) pour %s — fallback 720p",
            res or "vide", cam.get("id"),
        )
    return AI_RESOLUTION_PRESETS["720p"]


async def _sync_frame_source_workers(cams: list[dict], *,
                                       only: Optional[set[str]] = None) -> None:
    """Synchronise les workers ffmpeg persistants avec les caméras actives.

    v0.7.e · Wave A · Hot Reload chirurgical.
        * ``only=None``   → sync FULL (audit périodique, boot). Marque
          ``topology_syncs_full``.
        * ``only={ids}``  → sync PARTIEL : seuls les cam_ids listés sont
          traités (start ou stop). Le reste du pipeline continue à tourner
          intact. Marque ``topology_syncs_partial``.
    """
    import frame_source
    from streaming import _is_direct_rtsp, _stream_name
    go2rtc_rtsp = os.environ.get("GO2RTC_RTSP", "rtsp://go2rtc:8554")

    partial = only is not None
    if partial:
        _hot_reload_metrics["topology_syncs_partial"] += 1
    else:
        _hot_reload_metrics["topology_syncs_full"] += 1

    active_ids = set()
    for cam in cams:
        cam_id = cam["id"]
        if partial and cam_id not in only:
            # En mode partiel on saute les caméras non-ciblées mais on garde
            # leur ID dans ``active_ids`` pour ne pas les stopper par erreur.
            active_ids.add(cam_id)
            continue
        ai_url = (cam.get("ai_rtsp_url") or "").strip()
        native_url = (cam.get("rtsp_url") or "").strip()
        # `ai_rtsp_url` reste prioritaire si l'admin a configuré un flux DÉDIÉ IA
        # (profil caméra distinct, ex. sub H264 low-res) — ce flux n'est pas
        # enregistré dans Go2RTC, donc reste une connexion directe assumée.
        #
        # P0-fix · Connexion RTSP mutualisée : sinon (flux natif), on partage la
        # connexion Go2RTC déjà ouverte pour le recorder/preview/statut au lieu
        # d'ouvrir une 2e connexion directe vers la caméra — certaines caméras
        # (Reolink notamment) refusent plusieurs connexions RTSP concurrentes,
        # ce qui faisait échouer frame_source en boucle (0 FPS, reconnects).
        # stream_mode=direct_rtsp reste la seule exception (Go2RTC non utilisé).
        if ai_url:
            rtsp_url = ai_url
            source_type = "direct-ai"
        elif native_url and not _is_direct_rtsp(cam):
            rtsp_url = f"{go2rtc_rtsp}/{_stream_name(cam_id)}"
            source_type = "go2rtc-shared"
        elif native_url:
            rtsp_url = native_url
            source_type = "direct-native"
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
            ai_w, ai_h = _resolve_ai_resolution(cam)
            # v3.1.2 · frame_source.start() appelle stop() en interne si la
            # config a changé — stop() fait un `reader_thread.join(timeout=5)`
            # BLOQUANT, déporté sur un thread via asyncio.to_thread pour ne
            # jamais geler la boucle asyncio principale (/health, /auth/me...)
            # même si un redémarrage de worker se produit (résolution/RTSP
            # URL/codec changés).
            await asyncio.to_thread(frame_source.start, cam_id, rtsp_url,
                                     codec=codec, width=ai_w, height=ai_h)
            _hot_reload_metrics["frame_source_starts"] += 1
            logger.info("frame_source.start %s src=%s codec=%s %dx%d (%s)",
                        cam_id, source_type, codec, ai_w, ai_h,
                        rtsp_url[:60] + ("…" if len(rtsp_url) > 60 else ""))
        except Exception as e:
            logger.warning("frame_source.start(%s) échec: %s", cam_id, e)

    # En mode partiel : on ne stoppe que les workers explicitement retirés
    # (i.e. présents dans ``only`` mais ABSENTS de la liste ``cams`` fournie).
    # En mode FULL : on stoppe tous les workers orphelins.
    current = set(frame_source.status().get("workers", {}).keys())
    if partial:
        stale = only - active_ids
    else:
        stale = current - active_ids
    for cid in stale:
        if cid in current:
            try:
                await asyncio.to_thread(frame_source.stop, cid)  # v3.1.2 · voir commentaire start() ci-dessus
                _hot_reload_metrics["frame_source_stops"] += 1
            except Exception:
                pass


# ── Boucle temps réel : Phase A sync + Phase B downstream ───────────
_downstream_inflight: dict[str, int] = {}
_MAX_DOWNSTREAM_INFLIGHT = int(os.environ.get("AI_MAX_DOWNSTREAM_INFLIGHT", "2"))


def _ensure_frame_source_running(cam: dict) -> None:
    """v0.4.5.a · Warm-start persistant du worker ffmpeg pour cette caméra.

    Appelé au début de chaque itération de la boucle IA. Idempotent :
    ``frame_source.start()`` compare la config et fait no-op si identique.
    Le résultat est que dès l'activation ``detect_enabled=True``, le thread
    ffmpeg tourne en arrière-plan et remplit ``latest_frame`` en continu —
    l'IA ne provoque JAMAIS l'ouverture d'un RTSP à la volée.
    """
    try:
        from frame_source import start as _fs_start
        # P0-5 (v0.7.c) : les caméras démo sont servies par go2rtc — utiliser le
        # relais GO2RTC_RTSP (même logique que _sync_frame_source_workers). Sinon,
        # en Docker, l'URL seedée 127.0.0.1 pointe hors du conteneur backend et
        # provoque un churn stop/recréation du worker à chaque cycle IA.
        cam_id = cam["id"]
        if cam_id.startswith("demo-") or cam_id.startswith("demo_"):
            rtsp_url = f"{os.environ.get('GO2RTC_RTSP', 'rtsp://go2rtc:8554')}/cam_{cam_id}"
        else:
            rtsp_url = cam.get("ai_rtsp_url") or cam.get("rtsp_url")
        if not rtsp_url:
            return
        codec = (cam.get("ai_codec") or cam.get("codec") or "auto").lower()
        if codec not in ("h264", "h265", "auto"):
            codec = "auto"
        w = int(cam.get("ai_frame_width") or 0)
        h = int(cam.get("ai_frame_height") or 0)
        _fs_start(cam["id"], rtsp_url, codec=codec, width=w, height=h)
    except Exception:
        logger.debug("frame-source warm-start failed for %s", cam.get("id"), exc_info=True)


#: v3.14 · Horodatage de la dernière ligne de journal écrite par caméra
#: (limitation de débit — voir plus bas dans `_process_camera`).
_last_log_ts: dict = {}


async def _process_camera(cam: dict, frame=None) -> bool:
    """Phase A : acquisition + CameraWorker (pipeline v2) + broadcast overlay.

    v3.14 · `frame` peut être fourni par l'appelant. La boucle par caméra
    (`_camera_loop`) a déjà attendu une image FRAÎCHE et non encore analysée ;
    la re-demander ici rouvrirait la porte à l'analyse d'une image périmée.
    Sans argument, le comportement historique (acquisition non bloquante) est
    conservé pour les autres appelants.

    v3.36 · Retourne True si `_camera_loop` doit enchaîner immédiatement des
    passages supplémentaires pour cette caméra (échantillonnage en rafale
    sur mouvement) — False sinon, y compris sur toute sortie anticipée.
    """
    from pipeline_v2.camera_worker import runtime as _runtime
    from pipeline_v2.inspector import inspector as _inspector

    # v0.7.e · Wave A · Hot Reload chirurgical : le warm-start du worker
    # ffmpeg est désormais assuré UNIQUEMENT par ``_sync_frame_source_workers``
    # (appelé au démarrage + sur signal). Ne plus appeler `_ensure_frame_source_running`
    # ici évite un import + un appel `frame_source.start()` par caméra
    # par cycle — 100% redondant (idempotent, même config).

    t_start = time.perf_counter()
    if frame is None:
        frame = await _fetch_frame(cam["id"])
    if frame is None:
        logger.debug("IA · %s (%s) : frame indisponible (skip iteration)", cam["name"], cam["id"])
        return False
    t_fetch_ms = (time.perf_counter() - t_start) * 1000
    _inspector.record(cam["id"], "fetch", t_fetch_ms)

    _enabled = cam.get("enabled_plugins") or []
    worker = _runtime.worker(cam["id"])
    result = await asyncio.to_thread(worker.analyze, frame, _enabled, cam)
    dets = result.get("detections", [])
    plates = result.get("plates", [])
    tim = result.get("timings", {})

    # v3.36 · Échantillonnage en rafale sur mouvement — réutilise EXACTEMENT
    # le même signal que l'alerte "vive_allure" déjà en prod (motion_pct +
    # véhicule détecté ce cycle), pas un nouveau seuil inventé. Purement
    # informatif ici : ne modifie ni le résultat ni le comportement de ce
    # cycle, seulement ce que _camera_loop fait APRÈS. Aucune conséquence
    # si _get_scenario_rules() échoue (config indisponible) — pas de rafale,
    # comportement historique.
    burst_recommended = False
    try:
        _rules = await _get_scenario_rules()
        _r = _rules.get("vive_allure") or {}
        _vehicles_present = any(d.get("class") in VEHICLE_CLASSES for d in dets)
        if _r.get("enabled") and _vehicles_present and \
                result.get("motion_pct", 0.0) >= float(_r.get("motion_pct", 12.0)):
            burst_recommended = True
            logger.info("IA · %s : rafale mouvement déclenchée (mouvement=%.1f%%, %d véhicule(s))",
                        cam["name"], result.get("motion_pct", 0.0), sum(1 for d in dets if d.get("class") in VEHICLE_CLASSES))
    except Exception:
        pass

    # Broadcast overlay (léger, <5 ms)
    t_ws = time.perf_counter()
    try:
        from realtime import broadcast_ai_detections
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "boxes": result.get("overlay_boxes", []),
            "counts": result.get("counts", {}),
            "motion_pct": result.get("motion_pct", 0.0),
        }
        # État live du plugin retail (dwell-time/passages répétés par track) —
        # injecté seulement si le plugin est chargé et actif sur cette caméra,
        # pour ne pas payer le coût sur les caméras qui ne l'utilisent pas.
        if "retail-suspicious-behavior" in _enabled:
            try:
                from plugin_manager.bus import bus as _plugin_bus
                _entry = _plugin_bus._entries.get("retail-suspicious-behavior")
                if _entry is not None and _entry.instance is not None:
                    payload["retail"] = _entry.instance.live_state(cam["id"])
            except Exception:
                logger.exception("retail live_state error")
        await broadcast_ai_detections(cam["id"], cam.get("site_id", ""), payload)
    except Exception:
        logger.exception("broadcast_ai_detections error")
    _inspector.record(cam["id"], "websocket", (time.perf_counter() - t_ws) * 1000)

    t_frontier_ms = (time.perf_counter() - t_start) * 1000
    pipeline_metrics.record_stage(cam["id"], "fetch_ms", t_fetch_ms)
    pipeline_metrics.record_stage(cam["id"], "yolo_ms", tim.get("yolo_ms", 0))
    pipeline_metrics.record_stage(cam["id"], "tracking_ms", tim.get("tracking_ms", 0))
    pipeline_metrics.record_stage(cam["id"], "alpr_ms", tim.get("alpr_ms", 0))
    pipeline_metrics.record_stage(cam["id"], "realtime_ms", t_frontier_ms)
    # v3.12 · `total_ms` = durée mesurée DANS worker.analyze() (somme réelle
    # de tous ses stages, y compris decode/motion/roi qui n'étaient chronométrés
    # nulle part). L'écart entre `realtime_ms` et `total_ms` isole donc le temps
    # passé HORS analyse — attente d'un thread du pool, ordonnancement, broadcast.
    # Sans cette mesure, plusieurs secondes restaient inexpliquées entre la somme
    # des étapes (~200 ms) et le total remonté (~5500 ms).
    pipeline_metrics.record_stage(cam["id"], "total_ms", tim.get("total_ms", 0))
    for _st in ("decode_ms", "motion_ms", "roi_ms"):
        pipeline_metrics.record_stage(cam["id"], _st, tim.get(_st, 0))

    # v3.14 · Journal limité à 1 ligne par caméra et par seconde.
    # Cette ligne était écrite à CHAQUE image. Tant que le pipeline plafonnait
    # à 0,4 img/s c'était indolore ; avec une boucle par caméra à 10-15 img/s
    # sur 6 caméras, ça ferait ~90 écritures/s — le journal deviendrait
    # lui-même un goulot (I/O + GIL) sur le chemin critique vidéo.
    # Une détection ou une plaque force l'écriture : on ne perd aucun
    # événement réellement intéressant, seulement la répétition du ralenti.
    _now_log = time.monotonic()
    if dets or plates or (_now_log - _last_log_ts.get(cam["id"], 0.0)) >= 1.0:
        _last_log_ts[cam["id"]] = _now_log
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
        # v3.36 · Jamais de rafale quand le système est déjà en backpressure
        # — ce serait précisément le mauvais moment pour ajouter des passages.
        return False
    _downstream_inflight[cam["id"]] = inflight + 1
    asyncio.create_task(_process_downstream(cam, frame, result))
    return burst_recommended


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


# ══════════════════════════════════════════════════════════════════════
# v3.14 · Une boucle INDÉPENDANTE par caméra
# ══════════════════════════════════════════════════════════════════════
# Avant, le cycle faisait `await asyncio.gather(*[_process_camera(c) ...])`
# puis dormait `interval_seconds`. Le `gather` attend TOUTES les caméras :
# la période du cycle valait donc celle de la caméra la plus lente, et toutes
# les autres retombaient à ce débit-là.
#
# Symptôme qui l'a trahi : les 6 caméras affichaient EXACTEMENT 0,4 img/s,
# y compris celle en 720p dont le chemin critique ne dure que 200 ms, pendant
# que deux caméras 1080p étaient à 1734 et 1998 ms. Des charges très
# différentes qui donnent le même chiffre, c'est un point de rendez-vous, pas
# une saturation de calcul (le GPU était à 11 %).
#
# Désormais chaque caméra a sa propre tâche, cadencée par ses PROPRES images :
# elle attend qu'une image fraîche arrive (`wait_for_new_frame`), l'analyse,
# et repart. Aucune caméra n'attend une autre, aucune image n'est analysée
# deux fois, et on n'analyse jamais une image périmée.
_camera_tasks: dict = {}
#: Dernier document caméra connu, relu par la boucle à chaque itération pour
#: que les changements de config (plugins, résolution IA) s'appliquent sans
#: redémarrer la tâche.
_camera_specs: dict = {}

#: Délai d'attente d'une image avant de reboucler. Ce n'est PAS une cadence :
#: à son expiration on se contente de réessayer. Il sert à ne pas rester
#: bloqué indéfiniment si le worker ffmpeg est en train de redémarrer.
_FRAME_WAIT_TIMEOUT_S = 2.0

#: v3.36 · Échantillonnage en rafale sur mouvement (voir _process_camera pour
#: la condition de déclenchement). Nombre de passages IMMÉDIATS supplémentaires
#: pour la caméra concernée quand un mouvement de véhicule est détecté —
#: purement additif, chaque passage attend une VRAIE nouvelle image (jamais
#: la même analysée deux fois). Timeout plus court que la cadence normale :
#: si aucune image fraîche n'arrive vite, on arrête la rafale plutôt que de
#: bloquer la boucle de cette caméra.
_BURST_EXTRA_PASSES = 2
_BURST_FRAME_TIMEOUT_S = 1.0

#: v3.39 · Plafond de rafales SIMULTANÉES, toutes caméras confondues.
#: Constaté en prod le 04/09 : un événement de mouvement synchronisé sur
#: plusieurs caméras (vent, patrouille PTZ...) a déclenché ~94 rafales en
#: 10 min — sans plafond, chaque caméra ajoutait jusqu'à 2 passages EN PLUS
#: pile au moment où le système est déjà sous tension (mouvement généralisé
#: partout à la fois). A contribué à un pic de charge sévère (load 99,74
#: sur 12 cœurs) qui a lui-même déclenché une vague de redémarrages
#: frame_source (le mécanisme même que la rafale cherche à mieux servir —
#: cercle vicieux). Même principe que le sémaphore de reconnexion
#: frame_source (v3.33) mais délai d'acquisition volontairement quasi nul :
#: une rafale ratée n'est pas grave (le cycle normal a déjà tourné), mieux
#: vaut la sauter que faire la queue — une rafale qui attend son tour n'a
#: plus grand intérêt, l'objet est probablement déjà sorti du champ.
_MAX_CONCURRENT_BURSTS = int(os.environ.get("MGVMS_AI_MAX_CONCURRENT_BURSTS", "3"))
_burst_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_BURSTS)
_BURST_SEM_ACQUIRE_TIMEOUT_S = 0.05

#: Période du superviseur : relecture de la config et de la liste des caméras.
#: 1 s suffit — l'analyse, elle, n'attend plus ce tour de boucle.
_SUPERVISOR_PERIOD_S = 1.0


async def _camera_loop(camera_id: str) -> None:
    """Boucle d'analyse d'UNE caméra, cadencée par ses images."""
    from frame_source import wait_for_new_frame

    last_seq = -1
    idle_logged = False
    while True:
        cam = _camera_specs.get(camera_id)
        if cam is None:
            return  # caméra retirée : la tâche s'arrête d'elle-même

        frame, seq = await wait_for_new_frame(camera_id, last_seq,
                                              timeout=_FRAME_WAIT_TIMEOUT_S)
        if frame is None:
            if not idle_logged:
                logger.debug("IA · %s : aucune image depuis %.0fs — en attente",
                             cam.get("name", camera_id), _FRAME_WAIT_TIMEOUT_S)
                idle_logged = True
            continue
        idle_logged = False
        last_seq = seq

        try:
            burst = await _process_camera(cam, frame=frame)
            if burst:
                # v3.36 · Échantillonnage en rafale sur mouvement — voir
                # _process_camera pour la condition (même signal que
                # l'alerte "vive_allure" déjà en prod : motion_pct + véhicule
                # détecté ce cycle). Preuve du besoin (audit tracking
                # MG-VMS) : 7 événements Voiture sur 8 avec track_id=null au
                # moment précis où cette même alerte se déclenche — un seul
                # point de détection par passage rapide, ByteTrack ne peut
                # JAMAIS confirmer de piste avec un seul point, quel que
                # soit l'algorithme. Objectif : donner au moins un 2e point
                # tout de suite, pendant que le véhicule est encore dans le
                # champ, plutôt que d'attendre le prochain tour normal.
                #
                # v3.39 · Plafond global (voir _MAX_CONCURRENT_BURSTS) —
                # jamais plus de N caméras en rafale simultanément, quel que
                # soit le nombre de caméras qui qualifient au même instant
                # (événement de mouvement synchronisé). Acquisition quasi
                # non bloquante : une rafale ratée passe son tour plutôt que
                # de faire la queue.
                _burst_got_slot = False
                try:
                    await asyncio.wait_for(_burst_semaphore.acquire(), timeout=_BURST_SEM_ACQUIRE_TIMEOUT_S)
                    _burst_got_slot = True
                except asyncio.TimeoutError:
                    logger.info("IA · %s : rafale sautée — plafond de %d rafales simultanées atteint",
                                cam.get("name", camera_id), _MAX_CONCURRENT_BURSTS)
                if _burst_got_slot:
                    try:
                        for _burst_i in range(_BURST_EXTRA_PASSES):
                            b_frame, b_seq = await wait_for_new_frame(
                                camera_id, last_seq, timeout=_BURST_FRAME_TIMEOUT_S)
                            if b_frame is None:
                                logger.info("IA · %s : rafale arrêtée après %d passage(s) — pas de nouvelle image sous %.1fs",
                                            cam.get("name", camera_id), _burst_i, _BURST_FRAME_TIMEOUT_S)
                                break  # rien de frais rapidement — le véhicule est probablement déjà sorti du champ
                            last_seq = b_seq
                            try:
                                await _process_camera(cam, frame=b_frame)
                            except Exception:
                                logger.exception("IA · %s : erreur pendant la rafale mouvement",
                                                 cam.get("name", camera_id))
                                break
                    finally:
                        _burst_semaphore.release()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _ai_health["last_cycle_error"] = f"{type(e).__name__}: {str(e)[:200]}"
            logger.exception("IA · %s : erreur d'analyse, reprise", cam.get("name", camera_id))
            # Petit répit pour ne pas boucler à pleine vitesse sur une erreur
            # permanente (modèle non chargé, caméra qui renvoie du corrompu…).
            await asyncio.sleep(0.5)


def _reconcile_camera_tasks(cams: list) -> None:
    """Aligne l'ensemble des tâches sur la liste des caméras actives."""
    active = set()
    for cam in cams:
        cid = cam.get("id")
        if not cid:
            continue
        active.add(cid)
        _camera_specs[cid] = cam          # config à jour, lue au tour suivant
        task = _camera_tasks.get(cid)
        if task is None or task.done():
            _camera_tasks[cid] = asyncio.create_task(
                _camera_loop(cid), name=f"ai-cam-{cid}")
            logger.info("IA · boucle démarrée pour %s (%s)", cam.get("name"), cid)

    for cid in list(_camera_tasks):
        if cid in active:
            continue
        task = _camera_tasks.pop(cid, None)
        _camera_specs.pop(cid, None)      # fait sortir la boucle proprement
        if task is not None and not task.done():
            task.cancel()
        logger.info("IA · boucle arrêtée pour %s (caméra inactive)", cid)


async def ai_loop() -> None:
    """Superviseur IA : découverte des caméras + une boucle d'analyse par caméra.

    Ne fait PLUS le travail d'analyse lui-même — il maintient les tâches et
    recharge la configuration. Voir `_camera_loop` pour le pourquoi.
    """
    await asyncio.sleep(15)
    _ai_health["loop_alive"] = True
    _ai_health["loop_disabled_reason"] = None
    # P0-2 (v0.7.c) : chargement LAZY — YOLO + fast-alpr (et leurs téléchargements
    # de modèles) ne sont chargés QUE si au moins une caméra detect_enabled existe.
    try:
        _n_detect = await db.cameras.count_documents({"detect_enabled": True})
    except Exception:
        _n_detect = 0
    if _n_detect:
        try:
            await asyncio.to_thread(_load_models)
        except Exception as e:
            logger.exception("Premier chargement des modèles IA a échoué — la boucle continue")
            _ai_health["last_cycle_error"] = f"initial _load_models: {type(e).__name__}: {str(e)[:200]}"
    else:
        logger.info("IA · aucune caméra detect_enabled — chargement des modèles différé (lazy)")
    await load_runtime_config()
    logger.info(
        "Moteur IA démarré (device=%s · intervalle=%.1fs · yolo=%s · alpr=%s · pipeline=v2)",
        _detected_device(), _cfg("interval_seconds", AI_INTERVAL),
        "ok" if _ai_health["yolo_loaded"] else f"KO ({_ai_health['yolo_error']})",
        "ok" if _ai_health["alpr_loaded"] else f"KO ({_ai_health['alpr_error']})",
    )
    while True:
        _ai_health["cycles_total"] += 1
        _hot_reload_metrics["cycles_since_boot"] += 1
        _ai_health["last_cycle_ts"] = datetime.now(timezone.utc).isoformat()
        try:
            # v0.7.e · Wave A · Hot Reload chirurgical.
            # Les reloads Mongo ne se font PLUS chaque cycle. On respecte :
            #   1. Le signal explicite posé par les routes API (dirty flag).
            #   2. Un TTL de sûreté (défense en profondeur) pour rattraper
            #      un changement DB qui aurait échappé au signal.
            _now = time.time()
            if _camera_config_dirty or (_now - _last_camera_config_reload_ts > _HOT_RELOAD_TTL_SEC):
                await refresh_per_camera_configs()
            if _config_dirty or (_now - _last_config_reload_ts > _HOT_RELOAD_TTL_SEC):
                await load_runtime_config()

            cams = await db.cameras.find({"detect_enabled": True, "status": "online"}, {"_id": 0}).to_list(200)

            # P0-2 (v0.7.c) : retry de chargement UNIQUEMENT si des caméras l'exigent
            if cams and (not _ai_health["yolo_loaded"] or not _ai_health["alpr_loaded"]):
                try:
                    await asyncio.to_thread(_load_models)
                except Exception as reload_err:
                    logger.debug("Retry _load_models: %s", reload_err)

            # v0.7.e · sync workers : signal OU TTL (30s, 2× le TTL config)
            # ou changement effectif de l'ensemble des cam_ids actifs.
            global _last_topology_sync_ts, _cameras_topology_dirty
            need_full_sync = (_now - _last_topology_sync_ts) > (_HOT_RELOAD_TTL_SEC * 3)
            if _cameras_topology_dirty and _camera_dirty_set:
                # Signal ciblé — sync PARTIEL des seules caméras impactées.
                targeted = set(_camera_dirty_set)
                _camera_dirty_set.clear()
                _cameras_topology_dirty = False
                await _sync_frame_source_workers(cams, only=targeted)
                _last_topology_sync_ts = _now
            elif _cameras_topology_dirty or need_full_sync:
                _cameras_topology_dirty = False
                await _sync_frame_source_workers(cams)
                _last_topology_sync_ts = _now

            # v3.14 · Le superviseur ne bloque plus sur l'analyse : il se
            # contente d'aligner les tâches par caméra, qui tournent chacune
            # à leur propre rythme entre deux passages ici.
            _reconcile_camera_tasks(cams)
        except Exception as e:
            _ai_health["last_cycle_error"] = f"{type(e).__name__}: {str(e)[:200]}"
            logger.exception("ai_loop : erreur, reprise")
        # Cadence du SUPERVISEUR uniquement (relecture config / topologie).
        # `interval_seconds` ne cadence plus l'analyse — chaque caméra suit
        # désormais son propre flux d'images.
        await asyncio.sleep(_SUPERVISOR_PERIOD_S)
