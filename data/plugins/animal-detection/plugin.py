"""Animal Detection — écoute les détections upstream avec label animal.

Les classes animales (bird/cat/dog/horse/sheep/cow/elephant/bear/zebra/
giraffe) font déjà partie du jeu COCO standard du modèle YOLO principal —
pas besoin d'un second modèle dédié : on filtre les détections déjà
produites par le pipeline partagé, comme fire/smoke/weapon-detection.
"""
from __future__ import annotations
from plugin_manager.interfaces import PipelineConsumer, Frame, PipelineResult

ANIMAL_LABELS = {"bird", "cat", "dog", "horse", "sheep", "cow",
                  "elephant", "bear", "zebra", "giraffe"}


class AnimalDetectionPlugin(PipelineConsumer):
    name = "animal-detection"
    version = "2.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        self._labels = set(cfg.get("target_labels") or ANIMAL_LABELS)
        self._min_conf = float(cfg.get("min_confidence", 0.5))
        self._cooldown_s = float(cfg.get("cooldown_seconds", 30))
        self._last_alert = 0.0
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        cfg = new_config or {}
        self._labels = set(cfg.get("target_labels") or ANIMAL_LABELS)
        self._min_conf = float(cfg.get("min_confidence", 0.5))
        self._cooldown_s = float(cfg.get("cooldown_seconds", 30))
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        import time as _t
        animals = [d for d in pipeline.detections
                   if d.label.lower() in self._labels and d.confidence >= self._min_conf]
        if not animals:
            return []
        now = _t.time()
        if now - self._last_alert < self._cooldown_s:
            return []
        self._last_alert = now
        by_label: dict[str, int] = {}
        for d in animals:
            by_label[d.label] = by_label.get(d.label, 0) + 1
        return [{
            "type": "animal.detected",
            "severity": "info",
            "message": f"Animal détecté : {', '.join(f'{v}× {k}' for k, v in by_label.items())}",
            "data": {
                "count": len(animals),
                "by_label": by_label,
                "max_confidence": max(d.confidence for d in animals),
                "boxes": [list(d.bbox) for d in animals],
                "camera_id": frame.camera_id,
            },
        }]

    async def on_unload(self) -> None:
        pass
