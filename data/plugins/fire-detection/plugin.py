"""Fire Detection — écoute les détections upstream avec label ∈ FIRE_LABELS."""
from __future__ import annotations
from plugin_manager.interfaces import PipelineConsumer, Frame, PipelineResult

# Labels usuels pour la détection de flammes selon les modèles YOLO custom
FIRE_LABELS = {"fire", "flame", "flames"}


class FireDetectionPlugin(PipelineConsumer):
    name = "fire-detection"
    version = "2.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        self._min_conf = float(cfg.get("min_confidence", 0.6))
        self._cooldown_s = float(cfg.get("cooldown_seconds", 30))
        self._last_alert = 0.0
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        cfg = new_config or {}
        self._min_conf = float(cfg.get("min_confidence", 0.6))
        self._cooldown_s = float(cfg.get("cooldown_seconds", 30))
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        import time as _t
        fires = [d for d in pipeline.detections
                 if d.label.lower() in FIRE_LABELS and d.confidence >= self._min_conf]
        if not fires:
            return []
        now = _t.time()
        if now - self._last_alert < self._cooldown_s:
            return []
        self._last_alert = now
        return [{
            "type": "alert.critical",
            "severity": "critical",
            "message": f"🔥 FEU DÉTECTÉ ({len(fires)} zone(s), max conf {max(d.confidence for d in fires):.0%})",
            "data": {
                "count": len(fires),
                "max_confidence": max(d.confidence for d in fires),
                "boxes": [list(d.bbox) for d in fires],
                "camera_id": frame.camera_id,
            },
        }]

    async def on_unload(self) -> None:
        pass
