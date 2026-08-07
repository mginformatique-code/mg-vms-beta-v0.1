"""Plugin ANPR — Fast-ALPR (ONNX local, wrapper bundle v2.30)."""
from __future__ import annotations

import time
from typing import Optional

from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult


class FastAlprPlugin(PlateRecognizer):
    name = "fast-alpr"
    version = "1.0.0-preview"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        try:
            import ai_engine
        except Exception as e:
            self._ctx.set_state("missing_dependency", f"ai_engine indisponible: {e}")
            return
        health = getattr(ai_engine, "_ai_health", {}) or {}
        if health.get("alpr_loaded"):
            self._ctx.set_state("ready")
        else:
            err = health.get("alpr_error") or "modèle non chargé (voir /api/diagnostics/ai-health)"
            self._ctx.set_state("error", err)

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    def refresh_state_lazy(self):
        """v1.0-rc4 · P0-3 : ré-évaluation à la lecture du bus (le modèle ALPR
        charge APRÈS le bootstrap — l'état doit suivre la réalité)."""
        self._evaluate_state()

    async def recognize(self, frame: Frame, vehicle_bbox: Optional[tuple] = None) -> list:
        try:
            import ai_engine
        except Exception:
            return []
        health = getattr(ai_engine, "_ai_health", {})
        if not health.get("alpr_loaded"):
            return []
        fn = getattr(ai_engine, "_analyze_frame_alpr", None) or getattr(ai_engine, "analyze_frame_alpr", None)
        if fn is None:
            return []

        t0 = time.perf_counter()
        try:
            raw = fn(frame.numpy_bgr, vehicle_bbox) or []
        except Exception as e:
            self._ctx.log.warning(f"fast-alpr error: {e}")
            return []
        dt_ms = int((time.perf_counter() - t0) * 1000)

        min_conf = float((self._ctx.config or {}).get("min_confidence", 0.4))
        out = []
        for r in raw:
            if not isinstance(r, dict):
                continue
            text = str(r.get("text") or r.get("plate") or "").upper().strip()
            if not text:
                continue
            conf = float(r.get("confidence") or r.get("conf") or 0.0)
            if conf < min_conf:
                continue
            out.append(PlateResult(
                text=text, confidence=conf,
                country_hint=r.get("country_hint") or r.get("country"),
                region_hint=r.get("region_hint") or r.get("region"),
                bbox_plate=tuple(r.get("bbox_plate") or r.get("bbox") or (0, 0, 0, 0)),
                engine="fast-alpr", processing_ms=dt_ms,
            ))
        return out

    async def on_unload(self) -> None:
        pass
