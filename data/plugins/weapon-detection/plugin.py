"""Weapon Detection — écoute les détections upstream avec label ∈ WEAPON_LABELS."""
from __future__ import annotations
from plugin_manager.interfaces import PipelineConsumer, Frame, PipelineResult

WEAPON_LABELS = {"knife", "gun", "pistol", "rifle", "weapon", "firearm"}


class WeaponDetectionPlugin(PipelineConsumer):
    name = "weapon-detection"
    version = "2.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        self._min_conf = float(cfg.get("min_confidence", 0.7))
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        self._min_conf = float((new_config or {}).get("min_confidence", 0.7))
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        weapons = [d for d in pipeline.detections
                   if d.label.lower() in WEAPON_LABELS and d.confidence >= self._min_conf]
        if not weapons:
            return []
        return [{
            "type": "alert.critical",
            "severity": "critical",
            "message": f"🚨 ARME DÉTECTÉE ({len(weapons)}) — Alerte immédiate",
            "data": {
                "count": len(weapons),
                "types": list(set(d.label for d in weapons)),
                "max_confidence": max(d.confidence for d in weapons),
                "camera_id": frame.camera_id,
            },
        }]

    async def on_unload(self) -> None:
        pass
