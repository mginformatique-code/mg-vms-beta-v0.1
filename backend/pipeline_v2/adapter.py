"""Pipeline v2 · Adapter — compat rétro avec les plugins Plugin Manager v1.

Wrap les plugins existants (chargés par ``plugin_manager.loader``) dans les
nouvelles interfaces ``DetectionProvider`` / ``TrackingProvider`` /
``PlateRecognitionProvider`` / ``PipelineConsumer`` afin que la migration
soit **progressive et sans casse**.

Aucun plugin actuel n'est modifié. L'adapter joue les traductions :
    - ``plugin.detect(...)`` v1  → ``DetectionResult`` v2
    - ``plugin.track(...)`` v1   → ``TrackingResult`` v2
    - ``plugin.on_plate(...)`` v1 (async) → ``list[PlateResult]`` v2
    - ``plugin.on_event(...)`` v1 async  → ``list[dict]`` business_events v2
"""
from __future__ import annotations

import time
from typing import Any

from .interfaces import (BBox, Detection, DetectionResult, PipelineContext,
                         PlateResult, Track, TrackingResult)


class V1DetectorAdapter:
    """Wrap un ``FrameAnalyzer`` v1 → ``DetectionProvider`` v2."""

    def __init__(self, entry: Any):
        self._entry = entry
        self.name = entry.name

    def detect(self, frame) -> DetectionResult:
        t0 = time.perf_counter()
        # Le plugin v1 attend (frame_bytes, camera_config) — adapte
        try:
            raw = self._entry.instance.analyze_frame(frame.image, frame.camera_id)
            detections = _to_v2_detections(raw)
        except Exception:
            detections = []
        return DetectionResult(
            detections=detections,
            processing_time_ms=round((time.perf_counter() - t0) * 1000, 2),
            provider=self.name,
        )


class V1TrackerAdapter:
    """Wrap un ``Tracker`` v1 (ByteTrack/BoTSORT) → ``TrackingProvider`` v2."""

    def __init__(self, entry: Any):
        self._entry = entry
        self.name = entry.name

    def update(self, frame, detections: list[Detection]) -> TrackingResult:
        t0 = time.perf_counter()
        try:
            raw = self._entry.instance.track(frame.image, [
                {"bbox": (d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2),
                 "confidence": d.confidence, "class": d.label}
                for d in detections
            ])
            tracks = _to_v2_tracks(raw)
        except Exception:
            tracks = []
        return TrackingResult(
            tracks=tracks,
            processing_time_ms=round((time.perf_counter() - t0) * 1000, 2),
            provider=self.name,
        )


class V1PlateRecognizerAdapter:
    """Wrap un ``PlateRecognizer`` v1 → ``PlateRecognitionProvider`` v2."""

    def __init__(self, entry: Any):
        self._entry = entry
        self.name = entry.name

    def recognize(self, roi) -> list[PlateResult]:
        t0 = time.perf_counter()
        try:
            raw = self._entry.instance.recognize(roi)
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return _to_v2_plates(raw, provider=self.name, elapsed_ms=elapsed)
        except Exception:
            return []


class V1ConsumerAdapter:
    """Wrap un ``PipelineConsumer`` v1 → v2 (interface async standard)."""

    def __init__(self, entry: Any):
        self._entry = entry
        self.name = entry.name

    async def consume(self, ctx: PipelineContext) -> list[dict]:
        try:
            result = await self._entry.instance.on_pipeline(ctx)
            if isinstance(result, list):
                return result
            if isinstance(result, dict) and "events" in result:
                return list(result["events"])
            return []
        except Exception:
            return []


# ─── Helpers de conversion v1 → v2 ────────────────────────────────────

def _to_v2_detections(raw: Any) -> list[Detection]:
    """Accepte formats hétérogènes ``[{bbox,label,confidence}, ...]`` ou
    ``AnalyzerResult(detections=[...])``."""
    if raw is None:
        return []
    if hasattr(raw, "detections"):
        raw = raw.detections
    out: list[Detection] = []
    for d in raw or []:
        try:
            if isinstance(d, dict):
                b = d.get("bbox") or (0, 0, 0, 0)
                out.append(Detection(
                    label=str(d.get("label") or d.get("class") or "object"),
                    confidence=float(d.get("confidence") or 0.0),
                    bbox=BBox(int(b[0]), int(b[1]), int(b[2]), int(b[3])),
                    class_id=int(d.get("class_id") or -1),
                    attrs=d.get("attrs", {}),
                ))
            else:
                b = getattr(d, "bbox", None) or (0, 0, 0, 0)
                out.append(Detection(
                    label=str(getattr(d, "label", "object")),
                    confidence=float(getattr(d, "confidence", 0.0)),
                    bbox=BBox(int(b[0]), int(b[1]), int(b[2]), int(b[3])),
                ))
        except Exception:
            continue
    return out


def _to_v2_tracks(raw: Any) -> list[Track]:
    if raw is None:
        return []
    if hasattr(raw, "tracks"):
        raw = raw.tracks
    out: list[Track] = []
    for t in raw or []:
        try:
            if isinstance(t, dict):
                b = t.get("bbox") or (0, 0, 0, 0)
                out.append(Track(
                    track_id=int(t.get("track_id") or 0),
                    label=str(t.get("label") or "object"),
                    bbox=BBox(int(b[0]), int(b[1]), int(b[2]), int(b[3])),
                    confidence=float(t.get("confidence") or 0.0),
                ))
            else:
                b = getattr(t, "bbox", None) or (0, 0, 0, 0)
                out.append(Track(
                    track_id=int(getattr(t, "track_id", 0)),
                    label=str(getattr(t, "label", "object")),
                    bbox=BBox(int(b[0]), int(b[1]), int(b[2]), int(b[3])),
                    confidence=float(getattr(t, "confidence", 0.0)),
                ))
        except Exception:
            continue
    return out


def _to_v2_plates(raw: Any, provider: str, elapsed_ms: float) -> list[PlateResult]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    out: list[PlateResult] = []
    for r in raw:
        try:
            if isinstance(r, dict):
                b = r.get("bbox")
                bbox = BBox(int(b[0]), int(b[1]), int(b[2]), int(b[3])) if b else None
                out.append(PlateResult(
                    plate=str(r.get("plate") or r.get("text") or "").upper().strip(),
                    confidence=float(r.get("confidence") or 0.0),
                    bbox=bbox,
                    country=str(r.get("country") or ""),
                    processing_time_ms=float(r.get("processing_time_ms") or elapsed_ms),
                    provider=str(r.get("provider") or provider),
                    raw_text=str(r.get("raw_text") or r.get("plate") or ""),
                    vehicle_type=str(r.get("vehicle_type") or ""),
                    vehicle_color=str(r.get("vehicle_color") or ""),
                ))
            else:
                out.append(PlateResult(
                    plate=str(getattr(r, "plate", "")).upper().strip(),
                    confidence=float(getattr(r, "confidence", 0.0)),
                    provider=provider, processing_time_ms=elapsed_ms,
                ))
        except Exception:
            continue
    return out
