"""Smoke Detection — écoute les détections upstream avec label ∈ SMOKE_LABELS."""
from __future__ import annotations
from plugin_manager.interfaces import PipelineConsumer, Frame, PipelineResult

SMOKE_LABELS = {"smoke", "fumée", "fumee"}


class SmokeDetectionPlugin(PipelineConsumer):
    name = "smoke-detection"
    version = "2.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        self._min_conf = float(cfg.get("min_confidence", 0.55))
        self._cooldown_s = float(cfg.get("cooldown_seconds", 60))
        self._last_alert = 0.0
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        cfg = new_config or {}
        self._min_conf = float(cfg.get("min_confidence", 0.55))
        self._cooldown_s = float(cfg.get("cooldown_seconds", 60))
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        import time as _t
        smokes = [d for d in pipeline.detections
                  if d.label.lower() in SMOKE_LABELS and d.confidence >= self._min_conf]
        if not smokes:
            return []
        now = _t.time()
        if now - self._last_alert < self._cooldown_s:
            return []
        self._last_alert = now
        return [{
            "type": "alert.warning",
            "severity": "warning",
            "message": f"💨 FUMÉE DÉTECTÉE ({len(smokes)} zone(s))",
            "data": {"count": len(smokes),
                     "max_confidence": max(d.confidence for d in smokes),
                     "camera_id": frame.camera_id},
        }]

    async def on_unload(self) -> None:
        pass
