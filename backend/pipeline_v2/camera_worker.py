"""Pipeline v2 · CameraWorker — pipeline d'exécution PAR CAMÉRA.

Architecture cible (v0.4.2) :

    PipelineRuntime → CameraWorker → FrameContext → Stages → PluginBus

Chaque caméra possède son propre worker avec son propre état (motion,
tracker unique, cache plaques). Les stages s'exécutent dans l'ordre :

    decode → motion → yolo (UNE inférence) → tracking (UN tracker)
    → roi (UN crop/véhicule) → anpr (fast-alpr sur crops partagés)

Aucun plugin ne relance de détection ni de tracking : ils consomment
les Detection / TrackID / VehicleROI déjà présents dans le FrameContext.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from .frame_context import (FrameContext, VehicleROI, dominant_color_fr,
                            encode_jpeg_data_uri, point_in_polygon)
from .inspector import inspector
from .tracking import tracker_pool

logger = logging.getLogger("pipeline_v2.worker")

# Snapshot debug par caméra (mode #4) — consommé par /api/ai/debug
_last_debug: dict[str, dict] = {}


def get_debug_snapshot(camera_id: str) -> dict:
    return _last_debug.get(camera_id, {})


# v3.1.2 · Grab HD à la demande pour les crops (voir _stage_roi ci-dessous).
# Le scan continu (YOLO/motion) tourne en résolution fixe et légère
# (ai_engine._CONTINUOUS_SCAN_RES) — jamais de flux 4K en continu, ça a
# saturé le CPU du backend et affamé le live (mesuré en prod : 629% CPU).
# Quand un véhicule est détecté ET que la caméra demande mieux que 720p
# (``ai_resolution``), UNE frame native est récupérée via go2rtc
# (frame.jpeg, même mécanisme déjà utilisé par /api/stream/{id}/frame.jpeg)
# — coût payé une fois par cycle avec détection, pas 20x/s pour rien.
def _fetch_hd_crop_source(camera_id: str):
    """Frame BGR (numpy) en résolution native via go2rtc, ou None si échec.

    Synchrone : CameraWorker.analyze() tourne déjà hors boucle asyncio
    (ai_engine.py l'appelle via asyncio.to_thread), donc un appel HTTP
    bloquant ici ne gèle rien d'autre.
    """
    try:
        import cv2
        import numpy as np
        import httpx
        from streaming import GO2RTC_URL, _stream_name
    except Exception:
        return None
    name = _stream_name(camera_id)
    for src in (name, f"{name}_hd"):
        try:
            with httpx.Client(timeout=4.0) as client:
                r = client.get(f"{GO2RTC_URL}/api/frame.jpeg", params={"src": src})
            if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
                arr = np.frombuffer(r.content, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None and img.size > 0:
                    return img
        except Exception:
            continue
    return None


class CameraWorker:
    """Pipeline d'analyse d'UNE caméra — état strictement isolé."""

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self._prev_gray = None
        self._plate_cache: dict[str, datetime] = {}
        # v0.7.e · Wave C · Cache OCR par (track_id, crop_hash) — évite
        # de relancer les moteurs sur un crop quasi-identique du même
        # véhicule tracké (typique d'un véhicule stationné).
        self._crop_cache: dict[tuple, datetime] = {}
        self._last_ts: float = 0.0

    # ── Stages ───────────────────────────────────────────────────────

    def _stage_decode(self, ctx: FrameContext, frame_input) -> bool:
        """Charge ``ctx.image`` depuis un ndarray (zéro copie) ou depuis
        des bytes JPEG (imdecode). v0.4.3 · plus aucun ré-encodage inutile
        avant le worker : le RTSP direct passe directement en ndarray."""
        import cv2
        import numpy as np
        t0 = time.monotonic()
        if frame_input is None:
            ctx.image = None
        elif hasattr(frame_input, "shape"):
            # Déjà un ndarray BGR — utilisé tel quel (référence partagée)
            ctx.image = frame_input
        else:
            ctx.image = cv2.imdecode(
                np.frombuffer(frame_input, np.uint8), cv2.IMREAD_COLOR
            )
        ms = (time.monotonic() - t0) * 1000
        ctx.timings["decode_ms"] = round(ms, 1)
        inspector.record(self.camera_id, "decode", ms, error=ctx.image is None)
        return ctx.image is not None

    def _stage_motion(self, ctx: FrameContext) -> None:
        import cv2
        t0 = time.monotonic()
        gray = cv2.cvtColor(ctx.image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        prev = self._prev_gray
        self._prev_gray = gray
        if prev is not None and prev.shape == gray.shape:
            diff = cv2.absdiff(prev, gray)
            ctx.motion_pct = round((diff > 25).sum() * 100.0 / diff.size, 2)
        ms = (time.monotonic() - t0) * 1000
        ctx.timings["motion_ms"] = round(ms, 1)
        inspector.record(self.camera_id, "motion", ms)

    def _stage_detection(self, ctx: FrameContext, camera: Optional[dict] = None) -> None:
        """Detection — exécutée exactement UNE fois par frame via le
        registry d'abstraction (`pipeline_v2.detector.registry`).

        v0.5.6 Phase B · Le pipeline n'appelle plus jamais YOLO
        directement — il demande un ``Detector`` au registry et consomme
        des ``DetectionObject`` (indépendants du moteur). Aucun plugin
        aval ne relance d'inférence.

        Le comportement fonctionnel reste **identique** à v0.5.5 : la
        seule implémentation active est ``YoloDetector`` (qui utilise
        ``ai_engine._model`` avec le lock P0-1). Ajouter RT-DETR /
        TensorRT / ONNX se fait désormais par :

            registry.register("rt-detr", RTDetrDetector)

        sans toucher au pipeline. La sélection par caméra sera branchée
        en Phase C via ``cam_config['pipeline_config']['detector']``.
        """
        import ai_engine as _ae
        from .detector import registry as _detector_registry
        t0 = time.monotonic()

        detector, det_name, det_warning = _detector_registry.get_active(camera)
        objects = []
        detect_error = False
        if ctx.image is not None:
            try:
                objects = detector.detect(ctx.image)
            except Exception as e:  # pragma: no cover
                detect_error = True
                _ae._ai_health["last_cycle_error"] = \
                    f"detector.detect: {type(e).__name__}: {str(e)[:200]}"
                logger.exception("Detector %s a échoué sur %s", det_name, self.camera_id)
        else:
            # Aucune image dans le contexte : rien à détecter (early return).
            objects = []
        ms = (time.monotonic() - t0) * 1000
        ctx.timings["yolo_ms"] = round(ms, 1)  # clé historique — conservée pour l'UI
        ctx.timings["detector_ms"] = ctx.timings["yolo_ms"]
        ctx.metadata["detector"] = {"name": det_name, "warning": det_warning}
        inspector.record(self.camera_id, "yolo", ms, error=detect_error)
        inspector.set_meta(self.camera_id, detector=det_name)
        if not objects:
            return

        # Filtre par vocabulaire produit (CLASS_FR) + enrichissement crop +
        # couleur véhicule. Le pipeline downstream attend le format dict
        # historique — la conversion est faite ici en un seul endroit.
        img = ctx.image
        for obj in objects:
            cls_name = obj.label
            if cls_name not in _ae.CLASS_FR:
                continue
            x1, y1, x2, y2 = (max(0, int(v)) for v in obj.bbox)
            crop = img[y1:y2, x1:x2]
            is_vehicle = cls_name in _ae.VEHICLE_CLASSES
            ctx.detections.append({
                "class": cls_name, "label": _ae.CLASS_FR[cls_name],
                "confidence": round(float(obj.confidence), 2),
                # Encodage LAZY : le crop est encodé uniquement si un événement
                # est réellement inséré (downstream) — zéro JPEG inutile.
                "thumbnail": None,
                "_crop": crop,
                "vehicle_color": dominant_color_fr(crop) if is_vehicle else None,
                "_bbox": (x1, y1, x2, y2),
                "_detector": det_name,
            })

    def _stage_tracking(self, ctx: FrameContext, enabled_plugins: Optional[list],
                         camera: Optional[dict] = None) -> None:
        """Tracking UNIQUE — un seul tracker par caméra (TrackerPool).
        Les plugins tracker sont convertis en choix d'algorithme du stage."""
        import ai_engine as _ae
        from .tracking import resolve_algo
        t0 = time.monotonic()
        _req, _eff, _warn = resolve_algo(enabled_plugins, camera)
        meta = {"algo_requested": _req, "algo_effective": _eff, "tracked": 0}
        if _warn:
            meta["warning"] = _warn
        if _ae._bytetrack_cfg.get("enabled", True) and ctx.detections:
            meta = tracker_pool.update(self.camera_id, ctx, _ae._bytetrack_cfg,
                                       enabled_plugins=enabled_plugins)
        ms = (time.monotonic() - t0) * 1000
        ctx.timings["tracking_ms"] = round(ms, 1)
        ctx.metadata["tracking"] = meta
        inspector.record(self.camera_id, "tracking", ms)
        inspector.set_meta(self.camera_id, tracker=meta.get("algo_effective"))

    def _stage_roi(self, ctx: FrameContext, camera: Optional[dict] = None) -> None:
        """Extraction ROI véhicules — UN SEUL crop par véhicule, partagé
        ensuite par fast-alpr ET tous les moteurs ANPR cloud.

        v3.1.2 · Si la caméra demande mieux que 720p (``ai_resolution``) ET
        qu'au moins un véhicule est détecté, une frame HD est récupérée à la
        demande (voir _fetch_hd_crop_source) et les crops sont découpés
        dedans (bbox mise à l'échelle) au lieu de la frame basse résolution
        du scan continu. Échec du grab HD → repli silencieux sur le crop
        basse résolution, jamais bloquant pour le pipeline.
        """
        import ai_engine as _ae
        t0 = time.monotonic()
        h, w = ctx.height, ctx.width
        vehicle_dets = [d for d in ctx.detections if d["class"] in _ae.VEHICLE_CLASSES]
        if not vehicle_dets:
            ctx.timings["roi_ms"] = round((time.monotonic() - t0) * 1000, 1)
            return

        hd_img, hd_scale = None, None
        ai_res = ((camera or {}).get("ai_resolution") or "720p").lower()
        if ai_res != "720p":
            hd_img = _fetch_hd_crop_source(self.camera_id)
            if hd_img is not None and w > 0 and h > 0:
                hd_h, hd_w = hd_img.shape[:2]
                hd_scale = (hd_w / w, hd_h / h)
            else:
                hd_img = None

        for d in vehicle_dets:
            vx1, vy1, vx2, vy2 = d["_bbox"]
            pad_x = int((vx2 - vx1) * 0.08)
            pad_y = int((vy2 - vy1) * 0.08)
            cx1, cy1 = max(0, vx1 - pad_x), max(0, vy1 - pad_y)
            cx2, cy2 = min(w, vx2 + pad_x), min(h, vy2 + pad_y)
            if cx2 - cx1 < 40 or cy2 - cy1 < 40:
                continue
            crop_source, rx1, ry1, rx2, ry2 = ctx.image, cx1, cy1, cx2, cy2
            if hd_img is not None:
                sx, sy = hd_scale
                rx1, ry1 = int(cx1 * sx), int(cy1 * sy)
                rx2, ry2 = int(cx2 * sx), int(cy2 * sy)
                rx2 = max(rx1 + 1, min(hd_img.shape[1], rx2))
                ry2 = max(ry1 + 1, min(hd_img.shape[0], ry2))
                crop_source = hd_img
            ctx.vehicle_rois.append(VehicleROI(
                owner=d, bbox=(cx1, cy1, cx2, cy2),
                crop=crop_source[ry1:ry2, rx1:rx2],
                track_id=d.get("track_id"),
            ))
        ms = (time.monotonic() - t0) * 1000
        ctx.timings["roi_ms"] = round(ms, 1)
        inspector.record(self.camera_id, "roi", ms)

    def _stage_anpr(self, ctx: FrameContext, enabled_plugins: Optional[list],
                    camera: Optional[dict]) -> None:
        """fast-alpr local sur les crops partagés + gate qualité v0.4.2."""
        import ai_engine as _ae
        plate_debug: list = []
        ctx.timings["alpr_ms"] = 0.0
        anpr_cfg = _ae._camera_anpr_cfg.get(self.camera_id, {}) or {}
        roi_poly = anpr_cfg.get("roi_polygon") or []

        # v0.4.3 · Fermeture stricte (fail-safe) — le CameraWorker est
        # l'unique autorité qui décide des plugins. ``enabled_plugins``
        # null / vide / absent ⇒ aucun plugin dispatché, jamais.
        active = list(enabled_plugins) if enabled_plugins else []
        skipped = "fast-alpr" not in active
        if skipped:
            logger.debug("ANPR skip %s : fast-alpr not in enabled_plugins (strict)",
                         self.camera_id)

        # Auto-suspension qualité + caméras spécialisées (v0.4.2 — préservé)
        if ctx.vehicle_rois and _ae._alpr and not skipped:
            try:
                from .anpr_quality import anpr_quality
                should_run, state, score = anpr_quality.should_run_anpr(
                    self.camera_id, ctx.image, camera=camera)
                ctx.anpr_state = state.to_dict() if state else None
                ctx.anpr_quality = score.to_dict() if score else None
                if not should_run:
                    skipped = True
                    logger.info("ANPR skip %s : qualité insuffisante (score=%.2f · %s)",
                                self.camera_id, score.score, state.last_reason)
            except Exception:
                logger.exception("anpr_quality.should_run_anpr error — legacy path")

        if not (ctx.vehicle_rois and _ae._alpr and not skipped):
            self._write_debug(ctx, plate_debug)
            return

        now = datetime.now(timezone.utc)
        for k, exp in list(self._plate_cache.items()):
            if exp <= now:
                self._plate_cache.pop(k, None)
        cache_ttl = int(_ae._cfg("plate_cache_seconds", _ae.AI_PLATE_CACHE_SECONDS))
        min_side = int(_ae._cfg("min_plate_px", _ae.AI_MIN_PLATE_PX))
        min_conf = float(anpr_cfg.get("min_confidence", 0.0) or 0.0)
        w, h = ctx.width, ctx.height

        # v0.5.6 Phase B suite · L'OCR core est demandé au registry —
        # le pipeline ne connaît plus fast-alpr directement.
        from .plate_recognizer import plate_registry as _plate_registry
        _ocr, _ocr_name, _ocr_warning = _plate_registry.get_active(camera)
        ctx.metadata["ocr_core"] = {"name": _ocr_name, "warning": _ocr_warning}
        inspector.set_meta(self.camera_id, ocr_core=_ocr_name)

        t0 = time.monotonic()
        try:
            for roi in ctx.vehicle_rois:
                cx1, cy1, cx2, cy2 = roi.bbox
                try:
                    # Le lock ALPR est appliqué en interne par le recognizer
                    # (v0.5.6 P0-1). Le pipeline ne connaît plus le lock.
                    ocr_results = _ocr.recognize(roi.crop)
                except Exception:
                    logger.exception("OCR core '%s' recognize sur crop véhicule", _ocr_name)
                    continue
                for r in ocr_results:
                    bx1, by1, bx2, by2 = r.bbox_in_roi
                    abs_x1, abs_y1 = cx1 + bx1, cy1 + by1
                    abs_x2, abs_y2 = cx1 + bx2, cy1 + by2
                    pw, ph = abs_x2 - abs_x1, abs_y2 - abs_y1
                    plate_text = (r.text or "").upper().strip()
                    if pw < min_side or ph < min_side:
                        plate_debug.append({"plate": plate_text, "skipped": "trop petit",
                                             "size": f"{pw}x{ph}"})
                        continue
                    cx_n, cy_n = ((abs_x1 + abs_x2) / 2) / w, ((abs_y1 + abs_y2) / 2) / h
                    if roi_poly and not point_in_polygon(cx_n, cy_n, roi_poly):
                        plate_debug.append({"plate": plate_text, "skipped": "hors ROI",
                                             "size": f"{pw}x{ph}"})
                        continue
                    if float(r.confidence) < min_conf:
                        plate_debug.append({"plate": plate_text, "skipped": "conf<seuil",
                                             "size": f"{pw}x{ph}",
                                             "conf": round(float(r.confidence), 2)})
                        continue
                    if not plate_text:
                        continue
                    if plate_text in self._plate_cache:
                        plate_debug.append({
                            "plate": plate_text, "skipped": "cache",
                            "expires_in": int((self._plate_cache[plate_text] - now).total_seconds())})
                        continue
                    self._plate_cache[plate_text] = now + timedelta(seconds=max(cache_ttl, 1))
                    # v0.7.e · Wave C · extraction du crop plaque HD sur
                    # ``ctx.image`` (HD, jamais preview MJPEG) + gate qualité
                    # + amélioration (deskew/CLAHE/sharpen) si utile + cache
                    # (track_id, hash). Le résultat est stocké tel quel dans
                    # `plate_crop` (crop optimal utilisé pour l'affichage et
                    # partagé par les moteurs OCR additionnels).
                    from .plate_quality import (assess_crop_quality, enhance_plate_crop,
                                                 crop_hash, save_debug_bundle)
                    raw_plate_crop = ctx.image[max(0, int(abs_y1)):int(abs_y2),
                                                max(0, int(abs_x1)):int(abs_x2)]
                    q = assess_crop_quality(raw_plate_crop)
                    enhanced_crop = raw_plate_crop
                    crop_premium_meta = None  # v0.8-rc5 · trace CropPremium si escalade
                    if q.should_enhance and not q.skip:
                        enhanced_crop = enhance_plate_crop(raw_plate_crop, q)
                    # v0.8-rc5 · Crop Premium v2 · Sprint stabilisation P0 #2
                    # Si le crop reste sous 60/100 malgré l'enhance basique, on
                    # tente une cascade multi-marges + prétraitements et on
                    # sélectionne le meilleur crop pour l'OCR aval.
                    # Correction MINIMALE : additive, aucun impact si score >= 60.
                    try:
                        current_score_100 = int(round((q.score or 0) * 100))
                    except Exception:
                        current_score_100 = 0
                    if not q.skip and current_score_100 < 60:
                        try:
                            from .crop_premium import run_crop_premium
                            cp = run_crop_premium(
                                image_hd=ctx.image,
                                bbox=(int(abs_x1), int(abs_y1), int(abs_x2), int(abs_y2)),
                                min_score=60,
                            )
                            # On garde le résultat uniquement s'il est
                            # meilleur que ce qu'on avait produit.
                            if cp.best_quality.score_100 > current_score_100:
                                enhanced_crop = cp.best_crop
                                q = cp.best_quality
                                crop_premium_meta = cp.to_dict()
                        except Exception:
                            logger.exception("crop_premium a échoué (non bloquant)")
                    plate_crop = enhanced_crop
                    # Cache (track_id, hash) — évite le re-OCR de crops
                    # quasi-identiques (véhicule stationné, faible mouvement).
                    ch = crop_hash(enhanced_crop)
                    cache_key = (roi.track_id, ch) if roi.track_id is not None else (None, ch)
                    if cache_key in self._crop_cache and self._crop_cache[cache_key] > now:
                        plate_debug.append({
                            "plate": plate_text, "skipped": "cache_crop_hash",
                            "hash": ch})
                        continue
                    self._crop_cache[cache_key] = now + timedelta(seconds=max(cache_ttl, 1))
                    # Debug bundle (activable via env MGVMS_DEBUG_OCR=1 ou API)
                    save_debug_bundle(
                        self.camera_id, roi.track_id,
                        original_frame=ctx.image,
                        vehicle_crop=roi.crop,
                        raw_plate_crop=raw_plate_crop,
                        enhanced_plate_crop=enhanced_crop if q.should_enhance else None,
                        quality=q,
                        ocr_results_by_engine={_ocr_name: {
                            "plate": plate_text,
                            "confidence": round(float(r.confidence), 2),
                        }},
                        final_decision={"plate": plate_text,
                                         "confidence": round(float(r.confidence), 2),
                                         "engine": _ocr_name},
                    )
                    ctx.plates.append({
                        "plate": plate_text,
                        "confidence": round(float(r.confidence), 2),
                        # v3.1.2 · 240→480 (plate_crop) et défaut→1920
                        # (vehicle_crop) : voir commentaire
                        # ai_engine.py::_ensure_frame_thumb, même fix —
                        # 240px était bien trop serré pour zoomer sur une
                        # plaque, surtout maintenant que la source peut être
                        # captée en natif (ai_resolution="native").
                        "plate_crop": encode_jpeg_data_uri(plate_crop, max_width=480),
                        # Crop véhicule PARTAGÉ (memoizé) — encodé une seule fois
                        "vehicle_crop": roi.jpeg_data_uri(max_width=1920),
                        "vehicle_type": roi.owner["label"],
                        "vehicle_color": roi.owner["vehicle_color"],
                        "engine": _ocr_name,  # v0.5.6 : nom depuis le registry
                        "track_id": roi.track_id,
                        "_owner_bbox": tuple(roi.owner["_bbox"]),
                        "_plate_crop_np": enhanced_crop,   # Wave C · partagé pour multi-OCR aval
                        "_plate_quality": q.to_dict(),
                        "_crop_hash": ch,
                        "_crop_premium": crop_premium_meta,  # v0.8-rc5 · trace escalade
                    })
                    plate_debug.append({"plate": plate_text,
                                         "confidence": round(float(r.confidence), 2),
                                         "size": f"{pw}x{ph}", "kept": True,
                                         "quality": q.to_dict()})
        except Exception:
            logger.exception("Erreur LAPI (crop véhicule)")
        ms = (time.monotonic() - t0) * 1000
        ctx.timings["alpr_ms"] = round(ms, 1)
        inspector.record(self.camera_id, "anpr", ms)

        # Accumulateur ANPR par track (anti-doublons / consensus) — préservé
        try:
            from anpr_tracker import anpr_tracker, PlateReading
            for p in ctx.plates:
                reading = PlateReading(
                    plate=p["plate"], confidence=float(p["confidence"]),
                    ts=time.time(), plate_crop=p.get("plate_crop") or "",
                    vehicle_crop=p.get("vehicle_crop") or "",
                    vehicle_type=p.get("vehicle_type") or "",
                    vehicle_color=p.get("vehicle_color") or "",
                    engine=p.get("engine") or "fast-alpr",
                )
                p["_emit"] = anpr_tracker.record_reading(self.camera_id, p.get("track_id"), reading)
            seen = {d.get("track_id") for d in ctx.detections if d.get("track_id") is not None}
            anpr_tracker.tick_missing(self.camera_id, seen)
        except Exception:
            logger.exception("anpr_tracker: erreur")

        self._write_debug(ctx, plate_debug)

    def _write_debug(self, ctx: FrameContext, plate_debug: list) -> None:
        import ai_engine as _ae
        _last_debug[self.camera_id] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "resolution": f"{ctx.width}x{ctx.height}",
            "device": _ae._detected_device(),
            "timings": ctx.timings,
            "vehicles": [{"label": r.owner["label"], "confidence": r.owner["confidence"],
                          "bbox": r.owner["_bbox"], "vehicle_color": r.owner.get("vehicle_color")}
                         for r in ctx.vehicle_rois],
            "plate_attempts": plate_debug,
            "plates_ocr": [{"plate": p["plate"], "confidence": p["confidence"]}
                           for p in ctx.plates],
            "motion_pct": ctx.motion_pct,
            "frame_preview": ctx.jpeg_data_uri(640, 60),
        }

    # ── Entrée principale (sync, appelée via asyncio.to_thread) ─────

    def analyze(self, frame_input, enabled_plugins: Optional[list] = None,
                camera: Optional[dict] = None) -> dict:
        """Exécute tous les stages sur une frame et retourne le résultat legacy.

        v0.4.3 · ``frame_input`` accepte :
          - ``numpy.ndarray`` BGR (chemin RTSP direct — zéro encode)
          - ``bytes`` JPEG (fallback go2rtc, upload manuel, tests)
        """
        import ai_engine as _ae
        _ae._load_models()
        t_total = time.monotonic()
        now_ts = time.time()
        ctx = FrameContext(camera_id=self.camera_id, timestamp=now_ts)
        if self._last_ts:
            dt = now_ts - self._last_ts
            ctx.fps = round(1.0 / dt, 2) if dt > 0 else 0.0
        self._last_ts = now_ts

        # v0.8-rc6 · Pipeline Trace End-to-End · sampling léger (1/N frames)
        # Zéro coût quand collector.should_sample() renvoie False (>99% des frames).
        from .trace import collector as _trace_collector, stage as _trace_stage
        _trc = _trace_collector.start_trace(self.camera_id) \
            if _trace_collector.should_sample(self.camera_id) else None

        with _trace_stage(_trc, "decode"):
            if not self._stage_decode(ctx, frame_input):
                _trace_collector.finish_trace(_trc, {"error": "decode_failed"})
                return {"detections": [], "plates": [], "motion_pct": 0.0}
        with _trace_stage(_trc, "motion"):
            self._stage_motion(ctx)
        with _trace_stage(_trc, "yolo"):
            self._stage_detection(ctx, camera)
        with _trace_stage(_trc, "tracking"):
            self._stage_tracking(ctx, enabled_plugins, camera)
        with _trace_stage(_trc, "roi"):
            self._stage_roi(ctx, camera)
        with _trace_stage(_trc, "anpr"):
            self._stage_anpr(ctx, enabled_plugins, camera)

        # Overlay LIVE : bboxes normalisées + track_id
        w, h = ctx.width, ctx.height
        for d in ctx.detections:
            x1, y1, x2, y2 = d["_bbox"]
            ctx.overlay_boxes.append({
                "cls": d["class"], "label": d["label"], "confidence": d["confidence"],
                "vehicle_color": d.get("vehicle_color"),
                "track_id": d.get("track_id"),
                "bbox_norm": [round(x1 / w, 4), round(y1 / h, 4),
                              round(x2 / w, 4), round(y2 / h, 4)],
            })
            ctx.counts[d["label"]] = ctx.counts.get(d["label"], 0) + 1

        ctx.timings["total_ms"] = round((time.monotonic() - t_total) * 1000, 1)
        # v0.8-rc6 · Trace terminé : outcome = résumé de la détection
        _trace_collector.finish_trace(_trc, {
            "detections_count": len(ctx.detections),
            "plates_count": len(ctx.plates),
            "plates": [p.get("plate") for p in ctx.plates if p.get("plate")],
            "motion_pct": ctx.motion_pct,
        })
        return ctx.to_legacy_result()


class PipelineRuntime:
    """Fabrique et registre des CameraWorker — un worker par caméra, jamais partagé."""

    def __init__(self):
        self._workers: dict[str, CameraWorker] = {}

    def worker(self, camera_id: str) -> CameraWorker:
        w = self._workers.get(camera_id)
        if w is None:
            w = CameraWorker(camera_id)
            self._workers[camera_id] = w
            logger.info("pipeline_v2: CameraWorker créé pour %s", camera_id)
        return w

    def remove(self, camera_id: str) -> None:
        self._workers.pop(camera_id, None)
        tracker_pool.reset(camera_id)

    def describe(self) -> dict:
        return {
            "workers": list(self._workers.keys()),
            "trackers": tracker_pool.describe(),
        }


runtime = PipelineRuntime()
