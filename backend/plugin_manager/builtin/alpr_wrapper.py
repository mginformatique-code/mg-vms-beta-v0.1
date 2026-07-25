"""Wrapper Fast-ALPR — expose `ai_engine`'s ALPR en tant que `PlateRecognizer`."""
from __future__ import annotations

import time
from typing import Optional

from ..interfaces import PlateRecognizer, Frame, PlateResult


class FastAlprPlugin(PlateRecognizer):
    """Plugin bundle officiel `fast-alpr` (v2.30 PoC)."""

    name = "fast-alpr"
    version = "1.0.0-preview"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx

    async def recognize(self, frame: Frame, vehicle_bbox: Optional[tuple] = None) -> list:
        try:
            import ai_engine
        except Exception:  # pragma: no cover
            return []

        health = getattr(ai_engine, "_ai_health", {})
        if not health.get("alpr_loaded", False):
            return []

        # ai_engine expose déjà une fonction bas-niveau ALPR (retourne list[dict])
        alpr_fn = (
            getattr(ai_engine, "_analyze_frame_alpr", None)
            or getattr(ai_engine, "analyze_frame_alpr", None)
        )
        if alpr_fn is None:
            return []

        t0 = time.perf_counter()
        try:
            raw = alpr_fn(frame.numpy_bgr, vehicle_bbox) or []
        except Exception:  # pragma: no cover
            return []
        dt_ms = int((time.perf_counter() - t0) * 1000)

        out: list[PlateResult] = []
        for r in raw:
            if not isinstance(r, dict):
                continue
            out.append(PlateResult(
                text=str(r.get("text") or r.get("plate") or "").upper().strip(),
                confidence=float(r.get("confidence") or r.get("conf") or 0.0),
                country_hint=r.get("country_hint") or r.get("country"),
                region_hint=r.get("region_hint") or r.get("region"),
                bbox_plate=tuple(r.get("bbox_plate") or r.get("bbox") or (0, 0, 0, 0)),
                engine="fast-alpr",
                processing_ms=dt_ms,
            ))
        return out

    async def on_unload(self) -> None:
        pass
