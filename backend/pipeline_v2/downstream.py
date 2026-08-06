"""Pipeline v2 · Downstream — travail métier hors chemin critique vidéo.

Consomme le FrameContext produit par CameraWorker :
  - Persistance événements Mouvement / YOLO / Visages
  - Dispatch PluginBus per-camera (graph registry) avec tracks PRÉ-CALCULÉS
    (les plugins Tracker ne sont plus jamais dispatchés — tracking unique)
  - Smart Zones + Workflow Engine + Scénarios IA
  - Multi-moteurs ANPR sur les VehicleROI PARTAGÉS (un crop, un JPEG,
    tous les moteurs lisent les mêmes pixels)
  - Persistance plaques + alertes liste noire
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from database import db
from pipeline_metrics import pipeline_metrics

from .inspector import inspector
from .scenarios import _evaluate_scenarios, _raise_blacklist_alert, cooldown_ok

logger = logging.getLogger("pipeline_v2.downstream")


async def _get_global_anpr_country():
    doc = await db.settings.find_one({"key": "anpr_config"}, {"_id": 0})
    return ((doc or {}).get("value", {}) or {}).get("country")


def _det_thumb(det: dict):
    """Encode le crop de la détection à la demande (lazy, memoizé)."""
    if det.get("thumbnail"):
        return det["thumbnail"]
    crop = det.get("_crop")
    if crop is None:
        return None
    from .frame_context import encode_jpeg_data_uri
    det["thumbnail"] = encode_jpeg_data_uri(crop)
    return det["thumbnail"]


# ═══════════════════════════════════════════════════════════════════
# v0.5.1.c · Multi-plugin tracking (events + plates)
# ═══════════════════════════════════════════════════════════════════
# Plugins CORE toujours actifs quand le pipeline tourne (ne dépendent pas de
# la whitelist caméra). yolov11 = détection, bytetrack = tracking, fast-alpr =
# OCR embarqué toujours dispatché sur les véhicules.
_CORE_PLUGINS_ALWAYS_ON = ["yolov11", "bytetrack", "fast-alpr"]


def _compute_plugins_used(cam: dict) -> list[str]:
    """Retourne la liste UNIQUE et ordonnée des plugins actifs pour cette caméra.

    - Plugins CORE (`yolov11`, `bytetrack`, `fast-alpr`) toujours listés.
    - Plugins additionnels : la whitelist `enabled_plugins` de la caméra.

    Cette liste est stockée dans chaque événement et chaque plaque, permettant
    au frontend d'afficher des badges "multi-plugins" au lieu d'un seul champ
    ``engine`` hardcodé sur ``fast-alpr``.
    """
    wl = cam.get("enabled_plugins") or []
    out = list(_CORE_PLUGINS_ALWAYS_ON)
    for name in wl:
        if name and name not in out:
            out.append(name)
    return out


async def _prerun_multi_anpr(cam: dict, ctx, result: dict, now_iso: str) -> None:
    """Dispatch multi-moteurs ANPR AVANT l'écriture des events YOLO.

    Alimente ``result["plates"]`` avec les lectures de tous les moteurs
    additionnels de la whitelist (openalpr, google-vision, azure, plate-
    recognizer, codeproject…). Chaque moteur reçoit le MÊME objet Frame par
    ROI véhicule (mêmes pixels, un seul encodage JPEG memoizé).

    Fermeture stricte : whitelist vide/absente ⇒ aucun moteur dispatché.
    """
    try:
        from plugin_manager.bus import bus as _plugin_bus_multi
        from plugin_manager.interfaces import Frame as _MFrame
        _cam_whitelist = set(cam.get("enabled_plugins") or [])
        if not _cam_whitelist:
            return
        _anpr_entries = [e for e in _plugin_bus_multi.active("PlateRecognizer")
                         if e.name != "fast-alpr" and e.name in _cam_whitelist]
        _rois = (ctx.vehicle_rois if ctx else []) or []
        if not _anpr_entries or not _rois:
            return
        _only = {e.name for e in _anpr_entries}
        for _roi in _rois:
            _mf = _MFrame(
                camera_id=cam["id"], timestamp=now_iso,
                numpy_bgr=_roi.crop,
                width=int(_roi.crop.shape[1]), height=int(_roi.crop.shape[0]),
            )
            _multi_results = await _plugin_bus_multi.dispatch_plate(
                _mf, vehicle_bbox=None, timeout_s=8.0, only=_only,
            )
            for engine_name, plate_results in _multi_results:
                for pr in plate_results or []:
                    result["plates"].append({
                        "plate": (pr.text or "").upper().strip(),
                        "confidence": round(float(getattr(pr, "confidence", 0.0)), 2),
                        "plate_crop": None,
                        "vehicle_crop": _roi.jpeg_data_uri(),
                        "vehicle_type": _roi.owner.get("label"),
                        "vehicle_color": _roi.owner.get("vehicle_color"),
                        "track_id": _roi.track_id,
                        "engine": engine_name,
                    })
    except Exception:
        logger.exception("_prerun_multi_anpr dispatch error")


async def run_downstream(cam: dict, frame, result: dict) -> None:
    """Corps du worker downstream (ex ``ai_engine._do_downstream_work``)."""
    import ai_engine as _ae

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    ctx = result.get("_ctx")
    base = {
        "camera_id": cam["id"], "camera_name": cam["name"],
        "site_id": cam.get("site_id", ""), "site_name": cam.get("site_name", ""),
        "timestamp": now_iso,
    }
    # Image partagée : FrameContext prioritaire, sinon legacy (ndarray ou None)
    img = ctx.image if ctx is not None else (frame if hasattr(frame, "shape") else None)

    # ── v0.5.1.c · Multi-plugin tracking : plugins actifs pour cette caméra ──
    # Liste UNIQUE de tous les plugins qui participent au pipeline (utilisée
    # dans les events + plates pour l'affichage frontend "multi-plugins").
    plugins_used = _compute_plugins_used(cam)
    # Index track_id → lectures ANPR multi-moteurs (rempli en fin de fonction).
    result.setdefault("_anpr_by_track", {})

    # ── Mouvement réel ───────────────────────────────────────────────
    if result["motion_pct"] >= _ae.MOTION_THRESHOLD_PCT and \
            cooldown_ok(f"{cam['id']}:motion", _ae.MOTION_COOLDOWN, now):
        await db.events.insert_one({
            "id": str(uuid.uuid4()), "type": "Mouvement", **base,
            "confidence": None, "motion_pct": result["motion_pct"],
            "thumbnail": _ae._ensure_frame_thumb(result), "vehicle_color": None,
            "plugins_used": plugins_used,
        })

    # ── Reconnaissance faciale ───────────────────────────────────────
    face_cfg = await db.settings.find_one({"key": "face_recognition_config"}, {"_id": 0})
    if (face_cfg or {}).get("value", {}).get("enabled"):
        known = await db.faces.find({"encoding": {"$ne": None, "$exists": True}},
                                     {"_id": 0, "id": 1, "name": 1, "watchlist": 1, "encoding": 1}).to_list(2000)
        if known:
            try:
                from face_recognition_engine import analyze_frame as face_analyze
                threshold = float(face_cfg["value"].get("distance_threshold", 0.55))
                matches = face_analyze(frame, [{"id": k["id"], "name": k["name"],
                                                  "watchlist": k.get("watchlist", False),
                                                  "embedding": k["encoding"]} for k in known],
                                        threshold=threshold)
                for m in matches:
                    key = f"{cam['id']}:face:{m.get('face_id') or 'unknown'}"
                    if not cooldown_ok(key, _ae.EVENT_COOLDOWN, now):
                        continue
                    is_watch = m.get("watchlist")
                    is_unknown = m.get("face_id") is None
                    should_alert = (is_watch and face_cfg["value"].get("alert_on_watchlist", True)) or \
                                    (is_unknown and face_cfg["value"].get("alert_on_unknown", False))
                    if is_unknown and not face_cfg["value"].get("alert_on_unknown"):
                        continue
                    await db.events.insert_one({
                        "id": str(uuid.uuid4()),
                        "type": f"Visage · {m.get('name')}",
                        "plugin": "face_recognition",
                        **base,
                        "confidence": m.get("similarity"),
                        "thumbnail": _ae._ensure_frame_thumb(result),
                        "vehicle_color": None,
                        "face_id": m.get("face_id"),
                        "face_name": m.get("name"),
                        "watchlist": is_watch,
                        "plugins_used": plugins_used,
                    })
                    if should_alert and is_watch:
                        await db.alerts.insert_one({
                            "id": str(uuid.uuid4()),
                            "type": "face_watchlist", **base,
                            "severity": "critical",
                            "message": f"Visage sur liste de surveillance : {m.get('name')}",
                            "thumbnail": _ae._ensure_frame_thumb(result),
                            "acknowledged": False,
                            "plugin": "face_recognition",
                        })
            except Exception:
                logger.exception("Face recognition : erreur d'analyse")

    # ── v0.5.1.c · Multi-ANPR pré-collecté avant les events YOLO ─────
    # On lance le dispatch multi-moteurs sur les VehicleROI IMMÉDIATEMENT
    # après YOLO/tracking, avant d'écrire les événements de détection,
    # afin que chaque événement puisse embarquer directement la lecture de
    # plaque consensuelle et la liste des moteurs qui ont contribué.
    await _prerun_multi_anpr(cam, ctx, result, now_iso)
    # Consolidation fast-alpr (déjà présent dans result["plates"]) + multi
    # dans un index track_id → readings (pour attacher aux events YOLO).
    for p in result.get("plates", []):
        tid = p.get("track_id")
        if tid is None:
            continue
        entry = {
            "engine": p.get("engine") or "fast-alpr",
            "plate": p.get("plate"),
            "confidence": p.get("confidence", 0.0),
            "plate_crop": p.get("plate_crop"),
        }
        result["_anpr_by_track"].setdefault(tid, []).append(entry)

    # ── Détections YOLO → événements ─────────────────────────────────
    for det in result["detections"]:
        if not cooldown_ok(f"{cam['id']}:{det['class']}", _ae.EVENT_COOLDOWN, now):
            continue
        tid = det.get("track_id")
        anpr_readings = result["_anpr_by_track"].get(tid, []) if tid is not None else []
        # Consensus plaque : la plus confiante parmi les lectures multi-moteurs
        best_reading = max(anpr_readings, key=lambda r: r.get("confidence", 0), default=None)
        await db.events.insert_one({
            "id": str(uuid.uuid4()), "type": det["label"], **base,
            "confidence": det["confidence"],
            "thumbnail": _ae._ensure_frame_thumb(result) or _det_thumb(det),
            "crop_thumbnail": _det_thumb(det),
            "vehicle_color": det.get("vehicle_color"),
            "track_id": tid,
            "plugins_used": plugins_used,
            "plate": best_reading["plate"] if best_reading else None,
            "plate_confidence": best_reading["confidence"] if best_reading else None,
            "anpr_readings": anpr_readings,
        })

    # ── PluginBus per-camera (graph registry) — TRACKS PRÉ-CALCULÉS ──
    t_dispatch = time.perf_counter()
    try:
        pipeline_cfg = await db.settings.find_one(
            {"key": "plugin_manager_pipeline"}, {"_id": 0}
        )
        if (pipeline_cfg or {}).get("value", {}).get("enabled", True):
            from plugin_manager import bus as _plugin_bus, Frame as _Frame
            from plugin_manager.interfaces import Detection as _Detection, Track as _Track
            from pipeline_v2.registry import registry as _graph_registry

            _graph = _graph_registry.get(
                cam["id"],
                enabled_plugins=cam.get("enabled_plugins") or [],
                bus=_plugin_bus,
            )
            # v0.4.2 · Le tracking est CORE (TrackerPool) — le bus n'a plus
            # besoin de dispatcher les plugins Tracker. Seuls segmentation et
            # business justifient un dispatch.
            _pipeline_plugins_active = (
                _graph.needs_segmentation or _graph.needs_business
            )
            _pr = None
            _pipeline_ok = True
            if _pipeline_plugins_active:
                det_objs = []
                for d in result["detections"]:
                    bb = d.get("_bbox") or d.get("bbox") or (0, 0, 0, 0)
                    det_objs.append(_Detection(
                        label=d.get("label", "?"),
                        label_fr=d.get("label_fr"),
                        confidence=float(d.get("confidence", 0.0)),
                        bbox=tuple(bb),
                        track_id=d.get("track_id"),
                    ))
                # Tracks UNIQUES venant du TrackerPool core — les plugins
                # Tracker ne tournent JAMAIS (zéro double tracking).
                track_objs = [
                    _Track(track_id=str(t["track_id"]), label=t.get("label") or "?",
                           confidence=float(t.get("confidence") or 0.0),
                           bbox=tuple(t.get("bbox") or (0, 0, 0, 0)), age=1)
                    for t in ((ctx.tracks if ctx else []) or [])
                ]
                _frame = _Frame(
                    camera_id=cam["id"],
                    timestamp=now_iso,
                    numpy_bgr=img,
                    width=int(img.shape[1]) if img is not None else 0,
                    height=int(img.shape[0]) if img is not None else 0,
                )
                _pipeline_t0 = time.perf_counter()
                try:
                    _pr = await _plugin_bus.dispatch_pipeline(
                        _frame,
                        camera_config={
                            "camera_id": cam["id"],
                            "site_id": cam.get("site_id"),
                            "enabled_plugins": cam.get("enabled_plugins") or [],
                        },
                        precomputed_detections=det_objs,
                        precomputed_tracks=track_objs,
                        run_business=_graph.needs_business,
                        run_segmentation=_graph.needs_segmentation,
                        emit_events=True,
                        timeout_s=2.0,
                    )
                    _pipeline_ms = (time.perf_counter() - _pipeline_t0) * 1000
                    pipeline_metrics.record(cam["id"], _pipeline_ms,
                                             plugins_used=_pr.plugins_used or {})
                except Exception:
                    _pipeline_ms = (time.perf_counter() - _pipeline_t0) * 1000
                    pipeline_metrics.record_error(cam["id"], _pipeline_ms)
                    logger.exception("dispatch_pipeline error — skip plugin block")
                    _pipeline_ok = False
                    _pr = None

            if _pipeline_ok and _pr:
                for be in _pr.business_events:
                    if not cooldown_ok(f"{cam['id']}:{be.get('type', 'plugin')}", _ae.EVENT_COOLDOWN, now):
                        continue
                    await db.events.insert_one({
                        "id": str(uuid.uuid4()), "type": be.get("type", "plugin.event"),
                        **base,
                        "confidence": (be.get("data") or {}).get("max_confidence"),
                        "message": be.get("message"),
                        "severity": be.get("severity", "info"),
                        "plugin": be.get("source"),
                        "detectors": (_pr.plugins_used or {}).get("detectors", []),
                        "trackers": (_pr.plugins_used or {}).get("trackers", []),
                        "segmenters": (_pr.plugins_used or {}).get("segmenters", []),
                        "thumbnail": _ae._ensure_frame_thumb(result),
                        "data": be.get("data"),
                    })

                # Smart Zones + Workflow Engine
                try:
                    from smart_zones.engine import engine as _sz_engine
                    _dets = [
                        {"class": d.label, "confidence": d.confidence,
                         "bbox": tuple(d.bbox) if hasattr(d, "bbox") else (0, 0, 0, 0)}
                        for d in (_pr.detections or [])
                    ]
                    _tracks = [
                        {"track_id": getattr(t, "track_id", None),
                         "class": getattr(t, "label", None),
                         "confidence": getattr(t, "confidence", None),
                         "bbox": tuple(getattr(t, "bbox", (0, 0, 0, 0)))}
                        for t in (_pr.tracks or [])
                    ]
                    _plates = [
                        (be.get("data") or {})
                        for be in _pr.business_events
                        if be.get("type") == "plate_recognized"
                    ]
                    _sz_events = await _sz_engine.evaluate(cam["id"], _dets, _tracks, _plates)
                    for zev in _sz_events:
                        await db.events.insert_one({
                            "id": str(uuid.uuid4()),
                            "type": zev["type"], "message": zev["message"],
                            "severity": zev.get("severity", "info"),
                            **base,
                            "plugin": "smart-zone",
                            "data": zev.get("data"),
                        })
                        try:
                            from workflow_engine import engine as _wf_engine
                            await _wf_engine.on_event({
                                "type": zev["type"], "camera_id": cam["id"],
                                "timestamp": now.isoformat(), "data": zev.get("data"),
                            })
                        except Exception:
                            logger.exception("workflow_engine dispatch error")
                except Exception:
                    logger.exception("smart_zones eval error")
    except Exception:
        logger.exception("plugin_manager pipeline error")
    inspector.record(cam["id"], "dispatch", (time.perf_counter() - t_dispatch) * 1000)

    # ── Scénarios IA ─────────────────────────────────────────────────
    t_scen = time.perf_counter()
    await _evaluate_scenarios(cam, result, now)
    inspector.record(cam["id"], "scenarios", (time.perf_counter() - t_scen) * 1000)

    # ── Multi-moteurs ANPR : DÉJÀ RUN plus haut (`_prerun_multi_anpr`) ──
    # Bloc conservé désactivé pour clarté. Toutes les lectures multi-moteurs
    # figurent maintenant dans `result["plates"]` avant même l'écriture des
    # events YOLO. Voir _prerun_multi_anpr() en début de fonction.
    inspector.record(cam["id"], "multi_anpr", 0.0)

    # ── Persistance plaques + alertes liste noire ────────────────────
    # ── Persistance plaques + alertes liste noire ────────────────────
    # Charge la config ANPR caméra (whitelist/blacklist locales, override
    # pays) juste avant la boucle de persistance.
    anpr_cfg_cam = _ae._camera_anpr_cfg.get(cam["id"], {}) or {}
    wl_local = set(anpr_cfg_cam.get("whitelist_local", []) or [])
    bl_local = set(anpr_cfg_cam.get("blacklist_local", []) or [])

    t_persist = time.perf_counter()
    for p in result["plates"]:
        if "_emit" in p and not p["_emit"]:
            continue
        recent = await db.plates.find_one({
            "plate": p["plate"], "camera_id": cam["id"],
            "engine": p.get("engine", "fast-alpr"),
            "timestamp": {"$gte": (now - timedelta(seconds=_ae.EVENT_COOLDOWN)).isoformat()},
        })
        if recent:
            continue
        if p["plate"] in bl_local:
            list_status = "black"; wl = {"reason": "Liste noire locale caméra"}
        elif p["plate"] in wl_local:
            list_status = "white"; wl = None
        else:
            wl = await db.watchlist.find_one({"plate": p["plate"]}, {"_id": 0})
            list_status = wl["list_type"] if wl else "none"
        # Toutes les lectures multi-moteurs pour ce track_id (permet à
        # l'UI Recherche véhicule d'afficher tous les moteurs qui ont
        # contribué à cette plaque).
        _tid = p.get("track_id")
        all_readings = result["_anpr_by_track"].get(_tid, []) if _tid is not None else []
        doc = {
            "id": str(uuid.uuid4()), "plate": p["plate"], **base,
            "confidence": p["confidence"],
            "vehicle_color": p.get("vehicle_color"), "vehicle_make": None, "vehicle_model": None,
            "vehicle_type": p.get("vehicle_type"),
            "country": (anpr_cfg_cam.get("country_override")
                         or (await _get_global_anpr_country())),
            "direction": None,
            "lat": cam.get("lat"), "lng": cam.get("lng"),
            "list_status": list_status,
            "vehicle_crop": p.get("vehicle_crop"), "plate_crop": p.get("plate_crop"),
            "frame_thumb": _ae._ensure_frame_thumb(result),
            "engine": p.get("engine", "fast-alpr"),
            "plugins_used": plugins_used,
            "anpr_readings": all_readings,
            "track_id": _tid,
        }
        await db.plates.insert_one(dict(doc))
        doc.pop("_id", None)
        for k in ("_emit", "_owner_bbox"):
            p.pop(k, None)
        if list_status == "black":
            await _raise_blacklist_alert(cam, doc, (wl or {}).get("reason", ""))
    inspector.record(cam["id"], "persist", (time.perf_counter() - t_persist) * 1000)
