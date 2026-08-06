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


class CameraWorker:
    """Pipeline d'analyse d'UNE caméra — état strictement isolé."""

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self._prev_gray = None
        self._plate_cache: dict[str, datetime] = {}
        self._last_ts: float = 0.0

    # ── Stages ───────────────────────────────────────────────────────

    def _stage_decode(self, ctx: FrameContext, frame_bytes: bytes) -> bool:
        import cv2
        import numpy as np
        t0 = time.monotonic()
        ctx.image = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
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

    def _stage_detection(self, ctx: FrameContext) -> None:
        """YOLO — exécuté exactement UNE fois par frame. Aucun plugin ne
        relance d'inférence : tous consomment ces Detection."""
        import ai_engine as _ae
        t0 = time.monotonic()
        results = None
        if _ae._model is not None:
            try:
                results = _ae._model.predict(
                    ctx.image, conf=_ae._cfg("confidence", _ae.AI_CONFIDENCE),
                    device=_ae._detected_device(), verbose=False)[0]
            except Exception as e:
                _ae._ai_health["last_cycle_error"] = \
                    f"yolo.predict: {type(e).__name__}: {str(e)[:200]}"
                logger.exception("YOLO.predict a échoué sur %s", self.camera_id)
        ms = (time.monotonic() - t0) * 1000
        ctx.timings["yolo_ms"] = round(ms, 1)
        inspector.record(self.camera_id, "yolo", ms, error=(results is None and _ae._model is not None))
        if results is None:
            return
        for box in results.boxes:
            cls_name = _ae._model.names[int(box.cls)]
            if cls_name not in _ae.CLASS_FR:
                continue
            x1, y1, x2, y2 = (max(0, int(v)) for v in box.xyxy[0])
            crop = ctx.image[y1:y2, x1:x2]
            is_vehicle = cls_name in _ae.VEHICLE_CLASSES
            ctx.detections.append({
                "class": cls_name, "label": _ae.CLASS_FR[cls_name],
                "confidence": round(float(box.conf), 2),
                # Encodage LAZY : le crop est encodé uniquement si un événement
                # est réellement inséré (downstream) — zéro JPEG inutile.
                "thumbnail": None,
                "_crop": crop,
                "vehicle_color": dominant_color_fr(crop) if is_vehicle else None,
                "_bbox": (x1, y1, x2, y2),
            })

    def _stage_tracking(self, ctx: FrameContext, enabled_plugins: Optional[list]) -> None:
        """Tracking UNIQUE — un seul tracker par caméra (TrackerPool).
        Les plugins tracker sont convertis en choix d'algorithme du stage."""
        import ai_engine as _ae
        t0 = time.monotonic()
        meta = {"algo_effective": None}
        if _ae._bytetrack_cfg.get("enabled", True) and ctx.detections:
            meta = tracker_pool.update(self.camera_id, ctx, _ae._bytetrack_cfg,
                                       enabled_plugins=enabled_plugins)
        ms = (time.monotonic() - t0) * 1000
        ctx.timings["tracking_ms"] = round(ms, 1)
        ctx.metadata["tracking"] = meta
        inspector.record(self.camera_id, "tracking", ms)
        inspector.set_meta(self.camera_id, tracker=meta.get("algo_effective"))

    def _stage_roi(self, ctx: FrameContext) -> None:
        """Extraction ROI véhicules — UN SEUL crop par véhicule, partagé
        ensuite par fast-alpr ET tous les moteurs ANPR cloud."""
        import ai_engine as _ae
        t0 = time.monotonic()
        h, w = ctx.height, ctx.width
        for d in ctx.detections:
            if d["class"] not in _ae.VEHICLE_CLASSES:
                continue
            vx1, vy1, vx2, vy2 = d["_bbox"]
            pad_x = int((vx2 - vx1) * 0.08)
            pad_y = int((vy2 - vy1) * 0.08)
            cx1, cy1 = max(0, vx1 - pad_x), max(0, vy1 - pad_y)
            cx2, cy2 = min(w, vx2 + pad_x), min(h, vy2 + pad_y)
            if cx2 - cx1 < 40 or cy2 - cy1 < 40:
                continue
            ctx.vehicle_rois.append(VehicleROI(
                owner=d, bbox=(cx1, cy1, cx2, cy2),
                crop=ctx.image[cy1:cy2, cx1:cx2],
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

        # Whitelist per-camera (fix critique v0.4.1 — préservé)
        skipped = bool(enabled_plugins) and "fast-alpr" not in enabled_plugins
        if skipped:
            logger.debug("ANPR skip %s : fast-alpr not in enabled_plugins", self.camera_id)

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

        t0 = time.monotonic()
        try:
            for roi in ctx.vehicle_rois:
                cx1, cy1, cx2, cy2 = roi.bbox
                try:
                    alpr_results = list(_ae._alpr.predict(roi.crop))
                except Exception:
                    logger.exception("fast-alpr predict sur crop véhicule")
                    continue
                for r in alpr_results:
                    if not r.ocr or not r.ocr.text:
                        continue
                    bb = r.detection.bounding_box
                    abs_x1, abs_y1 = cx1 + bb.x1, cy1 + bb.y1
                    abs_x2, abs_y2 = cx1 + bb.x2, cy1 + bb.y2
                    pw, ph = abs_x2 - abs_x1, abs_y2 - abs_y1
                    plate_text = r.ocr.text.upper().strip()
                    if pw < min_side or ph < min_side:
                        plate_debug.append({"plate": plate_text, "skipped": "trop petit",
                                             "size": f"{pw}x{ph}"})
                        continue
                    cx_n, cy_n = ((abs_x1 + abs_x2) / 2) / w, ((abs_y1 + abs_y2) / 2) / h
                    if roi_poly and not point_in_polygon(cx_n, cy_n, roi_poly):
                        plate_debug.append({"plate": plate_text, "skipped": "hors ROI",
                                             "size": f"{pw}x{ph}"})
                        continue
                    if float(r.ocr.confidence) < min_conf:
                        plate_debug.append({"plate": plate_text, "skipped": "conf<seuil",
                                             "size": f"{pw}x{ph}",
                                             "conf": round(float(r.ocr.confidence), 2)})
                        continue
                    if not plate_text:
                        continue
                    if plate_text in self._plate_cache:
                        plate_debug.append({
                            "plate": plate_text, "skipped": "cache",
                            "expires_in": int((self._plate_cache[plate_text] - now).total_seconds())})
                        continue
                    self._plate_cache[plate_text] = now + timedelta(seconds=min(cache_ttl, 1))
                    plate_crop = ctx.image[max(0, abs_y1):abs_y2, max(0, abs_x1):abs_x2]
                    ctx.plates.append({
                        "plate": plate_text,
                        "confidence": round(float(r.ocr.confidence), 2),
                        "plate_crop": encode_jpeg_data_uri(plate_crop, 240),
                        # Crop véhicule PARTAGÉ (memoizé) — encodé une seule fois
                        "vehicle_crop": roi.jpeg_data_uri(),
                        "vehicle_type": roi.owner["label"],
                        "vehicle_color": roi.owner["vehicle_color"],
                        "engine": "fast-alpr",
                        "track_id": roi.track_id,
                        "_owner_bbox": tuple(roi.owner["_bbox"]),
                    })
                    plate_debug.append({"plate": plate_text,
                                         "confidence": round(float(r.ocr.confidence), 2),
                                         "size": f"{pw}x{ph}", "kept": True})
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

    def analyze(self, frame_bytes: bytes, enabled_plugins: Optional[list] = None,
                camera: Optional[dict] = None) -> dict:
        """Exécute tous les stages sur une frame et retourne le résultat legacy."""
        import ai_engine as _ae
        _ae._load_models()
        t_total = time.monotonic()
        now_ts = time.time()
        ctx = FrameContext(camera_id=self.camera_id, timestamp=now_ts)
        if self._last_ts:
            dt = now_ts - self._last_ts
            ctx.fps = round(1.0 / dt, 2) if dt > 0 else 0.0
        self._last_ts = now_ts

        if not self._stage_decode(ctx, frame_bytes):
            return {"detections": [], "plates": [], "motion_pct": 0.0}
        self._stage_motion(ctx)
        self._stage_detection(ctx)
        self._stage_tracking(ctx, enabled_plugins)
        self._stage_roi(ctx)
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
