"""Bird Detection — écoute les détections upstream avec label "bird"
(protection vignobles, aéroports, ornithologie).

"bird" fait déjà partie du jeu COCO standard du modèle YOLO principal —
pas besoin d'un second modèle dédié : on filtre les détections déjà
produites par le pipeline partagé, comme fire/smoke/weapon-detection.
"""
from __future__ import annotations
from plugin_manager.interfaces import PipelineConsumer, Frame, PipelineResult


class BirdDetectionPlugin(PipelineConsumer):
    name = "bird-detection"
    version = "2.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        self._min_conf = float(cfg.get("min_confidence", 0.5))
        self._alert_count = int(cfg.get("alert_count", 1))
        self._cooldown_s = float(cfg.get("cooldown_seconds", 30))
        self._last_alert = 0.0
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        cfg = new_config or {}
        self._min_conf = float(cfg.get("min_confidence", 0.5))
        self._alert_count = int(cfg.get("alert_count", 1))
        self._cooldown_s = float(cfg.get("cooldown_seconds", 30))
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        import time as _t
        birds = [d for d in pipeline.detections
                 if d.label.lower() == "bird" and d.confidence >= self._min_conf]
        if len(birds) < self._alert_count:
            return []
        now = _t.time()
        if now - self._last_alert < self._cooldown_s:
            return []
        self._last_alert = now
        return [{
            "type": "bird.detected",
            "severity": "info",
            "message": f"{len(birds)} oiseau(x) détecté(s) (conf max {max(d.confidence for d in birds):.0%})",
            "data": {
                "count": len(birds),
                "max_confidence": max(d.confidence for d in birds),
                "boxes": [list(d.bbox) for d in birds],
                "camera_id": frame.camera_id,
            },
        }]

    async def on_unload(self) -> None:
        pass
