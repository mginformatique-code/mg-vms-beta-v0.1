"""Pipeline v2 · Engine — orchestrateur central.

Enchaîne les stages en séquence, mesure les latences, gère les branches
parallèles, expose la config par caméra.

Usage type :
    engine = PipelineEngine.build_default(
        detectors=[YoloProvider(...)],
        tracker=ByteTrackProvider(...),
        recognizers=[FastAlprProvider(...), GoogleVisionProvider(...)],
        consumers=[AnprEpsConsumer(...), SmartZonesConsumer(...)],
        fusion=FusionEngine(strategy="weighted_vote"),
    )
    context = await engine.process(frame, camera_config={...})
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from .fusion import FusionEngine
from .interfaces import (DetectionProvider, Frame, PipelineConsumer,
                         PipelineContext, PlateRecognitionProvider, TrackingProvider)
from .stages import (BusinessStage, DetectionStage, PipelineStage,
                     RecognitionStage, ROIExtractionStage, TrackingStage)


class PipelineEngine:
    """Orchestrateur inversé : c'est le pipeline qui pilote les plugins.

    Aucun plugin ne fait de tracking, cache, événements, BD, notifications.
    Tout est centralisé dans les stages.
    """

    def __init__(self, stages: list[PipelineStage]):
        self.stages = stages
        # Traçabilité : stats runtime par caméra
        self._stats: dict[str, dict] = {}

    @classmethod
    def build_default(cls,
                      detectors: Optional[list[DetectionProvider]] = None,
                      tracker: Optional[TrackingProvider] = None,
                      recognizers: Optional[list[PlateRecognitionProvider]] = None,
                      consumers: Optional[list[PipelineConsumer]] = None,
                      fusion: Optional[FusionEngine] = None) -> "PipelineEngine":
        """Construit le pipeline canonique v2 avec ordre fixe :

            Detection → Tracking → ROI Extraction → Recognition → Business
        """
        fusion = fusion or FusionEngine("highest_confidence")
        stages: list[PipelineStage] = []
        if detectors:
            stages.append(DetectionStage(detectors))
        if tracker is not None:
            stages.append(TrackingStage(tracker))
        if recognizers:
            stages.append(ROIExtractionStage())
            stages.append(RecognitionStage(recognizers, fusion))
        if consumers:
            stages.append(BusinessStage(consumers))
        return cls(stages)

    async def process(self, frame: Frame,
                      camera_config: Optional[dict] = None) -> PipelineContext:
        """Exécute le pipeline complet sur une frame et retourne le contexte."""
        ctx = PipelineContext(frame=frame, camera_config=camera_config or {})
        t0 = time.perf_counter()
        for stage in self.stages:
            await stage._timed(ctx)
        ctx.timings_ms["total_ms"] = round(
            (time.perf_counter() - t0) * 1000, 2)

        # Stats runtime par caméra (pour le monitoring)
        s = self._stats.setdefault(frame.camera_id, {
            "processed": 0, "total_ms_sum": 0.0, "last_providers": {},
        })
        s["processed"] += 1
        s["total_ms_sum"] += ctx.timings_ms["total_ms"]
        s["last_providers"] = dict(ctx.providers_used)
        return ctx

    def stats(self) -> dict:
        """Retourne les stats agrégées par caméra (usage monitoring)."""
        out = {}
        for cid, s in self._stats.items():
            n = s["processed"] or 1
            out[cid] = {
                "processed": s["processed"],
                "avg_total_ms": round(s["total_ms_sum"] / n, 2),
                "last_providers": s["last_providers"],
            }
        return out

    def describe(self) -> dict:
        """Introspection : ordre des stages + config providers pour l'UI Pipeline Designer."""
        return {
            "stages": [
                {
                    "name": s.name,
                    "timeout_ms": s.timeout_ms,
                    "parallel_safe": s.parallel_safe,
                    "class": s.__class__.__name__,
                }
                for s in self.stages
            ],
        }
