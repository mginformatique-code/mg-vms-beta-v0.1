"""Plugin Tracking — OC-SORT."""
from __future__ import annotations
import time
from plugin_manager.interfaces import Tracker, Frame, TrackingResult, Track


class OcSortPlugin(Tracker):
    name = "ocsort"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        try:
            import ocsort
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install ocsort")
            return
        self._ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    async def track(self, frame: Frame, detections: list) -> TrackingResult:
        t0 = time.perf_counter()
        # PoC v2.30 : passe-plat qui recycle les detections comme tracks
        # avec ID synthétique. À remplacer par l'algo réel selon deps installées.
        tracks = []
        for i, det in enumerate(detections or []):
            tracks.append(Track(
                track_id=f"{det.label}#{i}",
                label=det.label,
                confidence=det.confidence,
                bbox=det.bbox,
                age=1,
            ))
        return TrackingResult(tracks=tracks, timing_ms=int((time.perf_counter() - t0) * 1000))

    async def on_unload(self) -> None:
        pass
