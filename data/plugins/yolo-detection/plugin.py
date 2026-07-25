"""Plugin YOLO Object Detection — v1.0.0-preview.

Plugin isolé du bundle officiel. En v2.30 (PoC dynamic loading) : délègue le
travail réel à `ai_engine._analyze_frame_yolo` pour garder une seule source
de vérité côté modèle. En v3.0 : embarque son propre modèle et process
sub-process.

Interface : `FrameAnalyzer` (chapitre 11 §11.3.1).
"""
from __future__ import annotations

import time
from typing import Optional

# Import via chemin absolu — le loader ajoute /app/backend au sys.path
from plugin_manager.interfaces import FrameAnalyzer, Frame, AnalysisResult, Detection


class YoloDetectionPlugin(FrameAnalyzer):
    """Détection YOLOv11 — délégation à ai_engine (bundle v2.30)."""

    name = "yolo-detection"
    version = "1.0.0-preview"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        try:
            ctx.log.info("[yolo-detection] plugin loaded via dynamic manifest loader")
        except Exception:
            pass

    async def analyze(self, frame: Frame, camera_config: dict) -> AnalysisResult:
        try:
            import ai_engine
        except Exception:
            return AnalysisResult(detections=[], timing_ms=0, device_used="unavailable")

        health = getattr(ai_engine, "_ai_health", {}) or {}
        analyze_fn = (
            getattr(ai_engine, "_analyze_frame_yolo", None)
            or getattr(ai_engine, "analyze_frame_yolo", None)
        )
        if not health.get("yolo_loaded") or analyze_fn is None:
            return AnalysisResult(detections=[], timing_ms=0, device_used="unavailable")

        t0 = time.perf_counter()
        try:
            raw = analyze_fn(frame.numpy_bgr, camera_config or {}) or []
        except Exception:
            return AnalysisResult(detections=[], timing_ms=int((time.perf_counter() - t0) * 1000))

        detections = []
        for d in raw:
            if not isinstance(d, dict):
                continue
            detections.append(Detection(
                label=d.get("label", "?"),
                label_fr=d.get("label_fr"),
                confidence=float(d.get("confidence", 0.0)),
                bbox=tuple(d.get("bbox", (0, 0, 0, 0))),
                track_id=d.get("track_id"),
                extra={k: v for k, v in d.items()
                       if k not in ("label", "label_fr", "confidence", "bbox", "track_id")},
            ))
        return AnalysisResult(
            detections=detections,
            timing_ms=int((time.perf_counter() - t0) * 1000),
            device_used=str(getattr(ai_engine, "_yolo_device", "cpu")),
        )

    async def on_config_change(self, new_config: dict) -> None:
        # Reload YOLO if model changes — v3.0 embarquera le modèle localement
        pass

    async def on_unload(self) -> None:
        pass
