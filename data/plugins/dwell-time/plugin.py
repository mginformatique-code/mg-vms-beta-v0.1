"""Plugin métier — Temps passé (dwell time).

Consomme les frames + détections upstream (via bus) et retourne des
événements/analyses métier. En v2.30 : squelette. Enable la démo dans
la config pour tester le pipeline.
"""
from __future__ import annotations
import time
from plugin_manager.interfaces import FrameAnalyzer, Frame, AnalysisResult, Detection


class DwellTimePlugin(FrameAnalyzer):
    name = "dwell-time"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        if not cfg.get("enabled_for_demo"):
            ctx.set_state("not_configured", "Activer la démo dans la config ou brancher un modèle propriétaire")
        else:
            ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        if not (new_config or {}).get("enabled_for_demo"):
            self._ctx.set_state("not_configured", "Démo désactivée")
        else:
            self._ctx.set_state("ready")

    async def analyze(self, frame: Frame, camera_config: dict) -> AnalysisResult:
        cfg = self._ctx.config or {}
        if not cfg.get("enabled_for_demo"):
            return AnalysisResult(detections=[], timing_ms=0)
        # Démo : retourne une détection fictive pour valider le pipeline
        return AnalysisResult(
            detections=[Detection(
                label="dwell",
                label_fr="Temps passé",
                confidence=0.75,
                bbox=(100, 100, 300, 300),
            )],
            timing_ms=1,
        )

    async def on_unload(self) -> None:
        pass
