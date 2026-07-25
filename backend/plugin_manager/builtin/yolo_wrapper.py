"""Wrapper YOLO — expose `ai_engine`'s YOLO en tant que `FrameAnalyzer` plugin."""
from __future__ import annotations

import time
from typing import Optional

from ..interfaces import FrameAnalyzer, Frame, AnalysisResult, Detection


class YoloDetectionPlugin(FrameAnalyzer):
    """Plugin bundle officiel `yolo-detection` (v2.30 PoC)."""

    name = "yolo-detection"
    version = "1.0.0-preview"

    async def on_load(self, ctx) -> None:
        # Le vrai chargement YOLO reste géré par ai_engine._ai_health (resilient loop).
        # Ce wrapper ne fait qu'aiguiller les appels — pas de double init du modèle.
        self._ctx = ctx

    async def analyze(self, frame: Frame, camera_config: dict) -> AnalysisResult:
        """Délègue à `ai_engine._analyze_frame_yolo` s'il est disponible."""
        try:
            import ai_engine  # import différé pour éviter cycles
        except Exception:  # pragma: no cover
            return AnalysisResult(detections=[], timing_ms=0, device_used="unavailable")

        t0 = time.perf_counter()
        # ai_engine expose déjà une fonction bas-niveau pour analyser un ndarray
        raw_detections = []
        analyze_fn = getattr(ai_engine, "_analyze_frame_yolo", None) or getattr(ai_engine, "analyze_frame_yolo", None)
        if analyze_fn is None or not getattr(ai_engine, "_ai_health", {}).get("yolo_loaded", False):
            return AnalysisResult(detections=[], timing_ms=0, device_used="unavailable")

        try:
            raw_detections = analyze_fn(frame.numpy_bgr, camera_config or {}) or []
        except Exception:  # pragma: no cover — le bus attrape déjà
            return AnalysisResult(detections=[], timing_ms=int((time.perf_counter() - t0) * 1000), device_used="cpu")

        detections = []
        for d in raw_detections:
            if isinstance(d, dict):
                detections.append(Detection(
                    label=d.get("label", "?"),
                    label_fr=d.get("label_fr"),
                    confidence=float(d.get("confidence", 0.0)),
                    bbox=tuple(d.get("bbox", (0, 0, 0, 0))),
                    track_id=d.get("track_id"),
                    extra={k: v for k, v in d.items() if k not in ("label", "label_fr", "confidence", "bbox", "track_id")},
                ))
        return AnalysisResult(
            detections=detections,
            timing_ms=int((time.perf_counter() - t0) * 1000),
            device_used=str(getattr(ai_engine, "_yolo_device", "cpu")),
        )

    async def on_unload(self) -> None:
        pass
