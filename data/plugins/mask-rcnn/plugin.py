"""Plugin Segmentation — Mask R-CNN."""
from __future__ import annotations
import time
from plugin_manager.interfaces import Segmenter, Frame, SegmentationResult


class MaskRcnnPlugin(Segmenter):
    name = "mask-rcnn"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        try:
            from torchvision.models.detection import maskrcnn_resnet50_fpn
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install torchvision")
            return
        self._ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    async def segment(self, frame: Frame, camera_config: dict) -> SegmentationResult:
        # PoC v2.30 : segmentation vide. Branchement modèle à faire post-install.
        return SegmentationResult(masks=[], timing_ms=0)

    async def on_unload(self) -> None:
        pass
