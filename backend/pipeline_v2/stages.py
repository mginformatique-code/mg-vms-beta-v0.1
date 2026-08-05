"""Pipeline v2 · Étapes (stages) du pipeline.

Chaque stage est **indépendant**, avec une interface simple :
    async def run(context: PipelineContext) -> None

Les stages modifient ``context`` en place. Le PipelineEngine les enchaîne.
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Optional

from .interfaces import (BBox, Detection, DetectionProvider, Frame,
                         PipelineConsumer, PipelineContext, PlateRecognitionProvider,
                         Track, TrackingProvider)
from .fusion import FusionEngine


class PipelineStage(ABC):
    """Interface stable pour tous les stages du pipeline."""

    name: str = "stage"
    timeout_ms: Optional[float] = None  # None = pas de timeout
    parallel_safe: bool = True

    @abstractmethod
    async def run(self, ctx: PipelineContext) -> None: ...

    async def _timed(self, ctx: PipelineContext) -> None:
        t0 = time.perf_counter()
        try:
            if self.timeout_ms:
                await asyncio.wait_for(self.run(ctx), self.timeout_ms / 1000.0)
            else:
                await self.run(ctx)
        finally:
            ctx.timings_ms[self.name] = round(
                (time.perf_counter() - t0) * 1000, 2)


class DetectionStage(PipelineStage):
    """Étape détection : appelle 1..N DetectionProviders en parallèle."""

    name = "detection"

    def __init__(self, providers: list[DetectionProvider], timeout_ms: float = 2000):
        self.providers = providers
        self.timeout_ms = timeout_ms

    async def run(self, ctx: PipelineContext) -> None:
        if not self.providers:
            return

        async def _call(p: DetectionProvider):
            try:
                # Providers sont sync par nature (GPU) → délègue au thread pool
                return await asyncio.to_thread(p.detect, ctx.frame)
            except Exception:
                return None

        results = await asyncio.gather(*(_call(p) for p in self.providers),
                                       return_exceptions=False)
        for provider, res in zip(self.providers, results):
            if res is None:
                continue
            ctx.detections.extend(res.detections)
            ctx.providers_used["detectors"].append(provider.name)


class TrackingStage(PipelineStage):
    """Étape tracking centralisée — UN seul tracker par pipeline.

    Le tracking n'est plus jamais dans les plugins ; c'est le pipeline qui
    l'exécute. Les IDs sont propagés à toutes les étapes suivantes.
    """

    name = "tracking"

    def __init__(self, provider: Optional[TrackingProvider], timeout_ms: float = 200):
        self.provider = provider
        self.timeout_ms = timeout_ms

    async def run(self, ctx: PipelineContext) -> None:
        if not self.provider or not ctx.detections:
            return
        res = await asyncio.to_thread(self.provider.update, ctx.frame, ctx.detections)
        ctx.tracks = res.tracks
        ctx.providers_used["trackers"].append(self.provider.name)

        # Propage les track_id sur les detections (association simple par bbox center)
        by_center = {(int(t.bbox.center[0]), int(t.bbox.center[1])): t.track_id
                     for t in ctx.tracks}
        for d in ctx.detections:
            cx, cy = int(d.bbox.center[0]), int(d.bbox.center[1])
            # Cherche le track dont le centre est le plus proche (< 30 px)
            best_tid, best_d = None, 30
            for (tx, ty), tid in by_center.items():
                dd = abs(tx - cx) + abs(ty - cy)
                if dd < best_d:
                    best_d, best_tid = dd, tid
            d.track_id = best_tid


class ROIExtractionStage(PipelineStage):
    """Étape ROI : extrait les crops véhicules pour l'ANPR (partagés).

    Un seul crop par véhicule tracké, réutilisé par TOUS les providers ANPR
    (pas de duplication mémoire).
    """

    name = "roi_extraction"
    parallel_safe = False  # utilise ctx.frame.image, modifie state

    VEHICLE_LABELS = {"car", "truck", "bus", "motorcycle", "motorbike", "vehicle"}

    async def run(self, ctx: PipelineContext) -> None:
        rois: list[tuple[Optional[int], BBox, "np.ndarray"]] = []
        img = ctx.frame.image
        h, w = img.shape[:2]
        for d in ctx.detections:
            if d.label.lower() not in self.VEHICLE_LABELS:
                continue
            # marge +8% (les plaques dépassent souvent les bbox strictes)
            pad_x = int((d.bbox.x2 - d.bbox.x1) * 0.08)
            pad_y = int((d.bbox.y2 - d.bbox.y1) * 0.08)
            cx1 = max(0, d.bbox.x1 - pad_x)
            cy1 = max(0, d.bbox.y1 - pad_y)
            cx2 = min(w, d.bbox.x2 + pad_x)
            cy2 = min(h, d.bbox.y2 + pad_y)
            if cx2 - cx1 < 40 or cy2 - cy1 < 40:
                continue
            rois.append((d.track_id, BBox(cx1, cy1, cx2, cy2), img[cy1:cy2, cx1:cx2]))
        ctx.frame.image  # référence stockée
        ctx.timings_ms["roi_extraction_count"] = len(rois)
        # Stocke temporairement dans un attribut du context (via dict extras)
        ctx.camera_config.setdefault("_rois", []).extend(rois)  # transitoire


class RecognitionStage(PipelineStage):
    """Étape ANPR : appelle 1..N PlateRecognitionProviders en parallèle,
    puis fusionne les résultats via le FusionEngine."""

    name = "recognition"

    def __init__(self, providers: list[PlateRecognitionProvider],
                 fusion: FusionEngine, timeout_ms: float = 3000):
        self.providers = providers
        self.fusion = fusion
        self.timeout_ms = timeout_ms

    async def run(self, ctx: PipelineContext) -> None:
        if not self.providers:
            return
        rois = ctx.camera_config.pop("_rois", [])
        if not rois:
            return

        async def _call_provider_roi(p, tid, bbox, crop):
            try:
                results = await asyncio.to_thread(p.recognize, crop)
                for r in results:
                    r.track_id = tid
                    r.provider = r.provider or p.name
                return results
            except Exception:
                return []

        # Dispatch (roi × provider) en parallèle
        tasks = []
        for tid, bbox, crop in rois:
            for p in self.providers:
                tasks.append(_call_provider_roi(p, tid, bbox, crop))
        all_results = await asyncio.gather(*tasks, return_exceptions=False)

        # Regroupe par track_id, fusionne par groupe
        by_track: dict = {}
        for res_list in all_results:
            for r in res_list:
                by_track.setdefault(r.track_id, []).append(r)
        for tid, readings in by_track.items():
            fused = self.fusion.fuse(readings)
            if fused:
                ctx.plates.append(fused)

        ctx.providers_used["recognizers"].extend(p.name for p in self.providers)


class BusinessStage(PipelineStage):
    """Étape business : exécute les consumers (EPS ANPR, comptage, workflows…)

    Les consumers sont **fire-and-forget** avec timeout individuel.
    """

    name = "business"

    def __init__(self, consumers: list[PipelineConsumer], timeout_ms: float = 5000):
        self.consumers = consumers
        self.timeout_ms = timeout_ms

    async def run(self, ctx: PipelineContext) -> None:
        if not self.consumers:
            return

        async def _run_one(c: PipelineConsumer):
            try:
                events = await asyncio.wait_for(c.consume(ctx),
                                                 self.timeout_ms / 1000.0)
                return c.name, events or []
            except Exception:
                return c.name, []

        results = await asyncio.gather(*(_run_one(c) for c in self.consumers),
                                       return_exceptions=False)
        for name, events in results:
            ctx.providers_used["consumers"].append(name)
            ctx.business_events.extend(events)
