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

from realtime import broadcast_alert

from .inspector import inspector
from .scenarios import _evaluate_scenarios, _raise_blacklist_alert, cooldown_ok

logger = logging.getLogger("pipeline_v2.downstream")


def _apply_hierarchical_anpr_fusion(cam: dict, result: dict) -> None:
    """v0.5.6 P0-4 — Fusion hiérarchique des lectures multi-OCR (in-place).

    Regroupe les lectures dans ``result["plates"]`` par ``track_id`` puis
    par plaque normalisée (§Étape 1). Applique ensuite la fusion
    hiérarchique (§Étapes 2-5). Après fusion :

    * Au maximum 1 entrée à ``_emit=True`` par (track_id) — la plaque
      gagnante, éventuellement marquée ``_ambiguous=True``.
    * Les lectures brutes sont attachées à ce gagnant via
      ``anpr_evidence: [{engine, text, confidence, normalized}]``.
    * Les autres lectures sont marquées ``_emit=False`` (la boucle de
      persistance les ignore — cf. ligne "if not p.get('_emit', True)").

    Cette fonction est purement sync et n'introduit aucune latence
    supplémentaire mesurable (< 1ms pour 10 moteurs × 5 ROIs).
    """
    from plugin_manager.fusion import (
        MODE_HIERARCHICAL, apply_policy, normalize_plate,
    )
    from plugin_manager.interfaces import PlateResult

    plates = result.get("plates") or []
    if not plates:
        return

    # Priorité déclarée = ordre des plugins dans enabled_plugins de la caméra.
    enabled = list(cam.get("enabled_plugins") or [])
    priority_order = [p for p in enabled if p in {
        "fast-alpr", "paddle-ocr", "openalpr", "plate-recognizer",
        "easyocr", "tesseract", "anpr-eps",
    }]

    # Groupement par track_id. Les lectures sans track_id sont émises telles
    # quelles (impossible de les corréler entre moteurs sans identifiant).
    by_track: dict = {}
    orphans: list = []
    for p in plates:
        tid = p.get("track_id")
        if tid is None:
            orphans.append(p)
        else:
            by_track.setdefault(tid, []).append(p)

    for _tid, reads in by_track.items():
        if len(reads) <= 1:
            # Une seule lecture pour ce track → rien à fusionner.
            continue
        # Reconstruit les PlateResult pour la fusion (sans copier les crops).
        results_by_engine: list[tuple[str, list]] = []
        for r in reads:
            eng = r.get("engine", "unknown")
            pr = PlateResult(
                text=r.get("plate") or "",
                confidence=float(r.get("confidence") or 0.0),
                engine=eng,
                processing_ms=0,
            )
            results_by_engine.append((eng, [pr]))
        try:
            fused = apply_policy(
                MODE_HIERARCHICAL, results_by_engine,
            )
        except Exception:  # pragma: no cover
            logger.exception("Hierarchical fusion failed on track %s", _tid)
            continue
        final = fused.get("final")
        if final is None:
            continue
        # Trouve la lecture qui correspond au texte gagnant (normalisation),
        # ou par défaut la lecture avec la plus grosse confiance.
        winner_norm = normalize_plate(final.text)
        winner_read = None
        best_conf = -1.0
        for r in reads:
            r_norm = normalize_plate(r.get("plate") or "")
            if r_norm == winner_norm and r.get("confidence", 0) > best_conf:
                winner_read = r
                best_conf = r.get("confidence", 0.0)
        if winner_read is None:
            # Ambigu : le gagnant est marqué comme tel, on garde le meilleur.
            best_conf = -1.0
            for r in reads:
                if r.get("confidence", 0) > best_conf:
                    winner_read = r
                    best_conf = r.get("confidence", 0.0)

        # Marque les non-gagnants pour qu'ils soient ignorés à la persistance.
        for r in reads:
            if r is not winner_read:
                r["_emit"] = False

        # Attache l'evidence brute + le mode de fusion au gagnant.
        winner_read["plate"] = final.text  # utilise le texte fusionné.
        winner_read["confidence"] = round(float(final.confidence), 2)
        winner_read["engine"] = final.engine or "fusion"
        winner_read["_ambiguous"] = (
            "ambiguous" in (final.engine or "").lower()
        )
        winner_read["anpr_evidence"] = [
            {
                "engine": r.get("engine"),
                "text": r.get("plate"),
                "confidence": r.get("confidence"),
                "normalized": normalize_plate(r.get("plate") or ""),
            }
            for r in reads
        ]
    _ = orphans  # traités inchangés par la boucle de persistance


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
    # v3.1.2 · voir commentaire ai_engine.py::_ensure_frame_thumb (même fix)
    det["thumbnail"] = encode_jpeg_data_uri(crop, max_width=1920)
    return det["thumbnail"]


# ═══════════════════════════════════════════════════════════════════
# v0.5.1.c · Multi-plugin tracking (events + plates)
# ═══════════════════════════════════════════════════════════════════
# Plugins CORE toujours actifs quand le pipeline tourne (ne dépendent pas de
# la whitelist caméra). yolov11 = détection, bytetrack = tracking.
# v3.1.4 · fast-alpr RETIRÉ d'ici : contrairement à yolov11/bytetrack, l'ANPR
# N'est PAS inconditionnel — camera_worker.py::_stage_anpr applique une
# fermeture stricte (enabled_plugins vide/absent ⇒ jamais dispatché). Le
# lister ici affichait "fast-alpr actif" même sur des caméras où l'ANPR était
# désactivé, alors qu'aucune plaque n'était réellement lue. Il redescend
# maintenant par la whitelist ci-dessous, comme n'importe quel autre plugin.
_CORE_PLUGINS_ALWAYS_ON = ["yolov11", "bytetrack"]


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
                        # v3.1.2 · voir commentaire ai_engine.py::_ensure_frame_thumb
                        "vehicle_crop": _roi.jpeg_data_uri(max_width=1920),
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
            "thumbnail": _ae._ensure_frame_thumb(result),
            "thumbnail_sm": _ae._ensure_frame_thumb_sm(result), "vehicle_color": None,
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
                        "thumbnail_sm": _ae._ensure_frame_thumb_sm(result),
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
                            "thumbnail_sm": _ae._ensure_frame_thumb_sm(result),
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
            "thumbnail_sm": _ae._ensure_frame_thumb_sm(result) or _det_thumb(det),
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
                        "thumbnail_sm": _ae._ensure_frame_thumb_sm(result),
                        "data": be.get("data"),
                    })

                # Promotion en alerte temps réel (db.alerts + websocket) pour
                # tout business_event de sévérité warning/critical. Contrairement
                # au cooldown ci-dessus (générique "camera_id:type", partagé par
                # toutes les personnes/tracks sur cette caméra), le cooldown ici
                # inclut le track_id : deux personnes distinctes déclenchant le
                # même type d'event à quelques secondes d'intervalle sont donc
                # bien alertées toutes les deux, pas seulement la première.
                # Générique à tous les PipelineConsumer (occupancy.alert compris)
                # — voir plan "Plugin IA anti-vol", Phase 1.
                for be in _pr.business_events:
                    severity = be.get("severity", "info")
                    if severity not in ("warning", "critical"):
                        continue
                    track_id = (be.get("data") or {}).get("track_id", "")
                    alert_key = f"{cam['id']}:{be.get('type')}:{track_id}"
                    if not cooldown_ok(alert_key, _ae.EVENT_COOLDOWN, now):
                        continue
                    alert = {
                        "id": str(uuid.uuid4()), "type": be.get("type", "plugin.event"),
                        "severity": severity,
                        "message": be.get("message"),
                        "camera_id": cam["id"], "camera_name": cam["name"],
                        "site_id": cam.get("site_id", ""), "site_name": cam.get("site_name", ""),
                        "plugin": be.get("source"),
                        "thumbnail": _ae._ensure_frame_thumb(result),
                        "acknowledged": False, "timestamp": now_iso,
                        "data": be.get("data"),
                    }
                    await db.alerts.insert_one(dict(alert))
                    alert.pop("_id", None)
                    await broadcast_alert(alert)
                    if severity == "critical":
                        try:
                            from notifications import send_notification
                            await send_notification(
                                f"ALERTE IA — {be.get('message', be.get('type'))}",
                                f"Caméra {cam['name']} ({cam.get('site_name', '')})",
                            )
                        except Exception:
                            logger.exception("send_notification error (plugin alert)")

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

    # ── v0.5.6 P0-4 · Fusion hiérarchique multi-OCR ─────────────────
    # Regroupe les lectures par (track_id, plate_normalisée) puis applique
    # la fusion hiérarchique (majorité → confiance → priorité → ambigu).
    # Résultat : au maximum 1 doc `plates` en DB par (track_id, gagnant).
    # Les autres lectures sont conservées en `evidence` pour audit.
    _apply_hierarchical_anpr_fusion(cam, result)

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
            "anpr_evidence": p.get("anpr_evidence"),        # v0.5.6 P0-4
            "ambiguous": bool(p.get("_ambiguous", False)),  # v0.5.6 P0-4
            "track_id": _tid,
        }
        await db.plates.insert_one(dict(doc))
        doc.pop("_id", None)
        # v0.7.e · Wave C · nettoyage des champs internes (ndarray non
        # sérialisables, dict quality volumineux) — jamais persistés en Mongo
        # (le doc est construit champ par champ ci-dessus), on les retire
        # aussi de p pour libérer la mémoire du result dict.
        for k in ("_emit", "_owner_bbox", "_plate_crop_np",
                  "_plate_quality", "_crop_hash", "_crop_premium"):
            p.pop(k, None)
        if list_status == "black":
            await _raise_blacklist_alert(cam, doc, (wl or {}).get("reason", ""))
    inspector.record(cam["id"], "persist", (time.perf_counter() - t_persist) * 1000)
