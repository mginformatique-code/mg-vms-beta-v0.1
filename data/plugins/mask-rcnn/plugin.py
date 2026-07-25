"""Plugin Segmentation — Mask R-CNN (torchvision, ResNet50 FPN)."""
from __future__ import annotations
import time
import numpy as np
from plugin_manager.interfaces import Segmenter, Frame, SegmentationResult, SegmentMask

# Labels COCO abrégés (index → label)
COCO_LABELS = [
    "__background__", "person", "bicycle", "car", "motorcycle", "airplane", "bus",
    "train", "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
]


class MaskRcnnPlugin(Segmenter):
    name = "mask-rcnn"
    version = "1.0.0"

    def __init__(self):
        self._model = None
        self._device = "cpu"
        self._transform = None

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        cfg = self._ctx.config or {}
        try:
            import torch  # noqa
            import torchvision  # noqa
            from torchvision.models.detection import maskrcnn_resnet50_fpn  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install torchvision")
            return
        # Modèle initialisé paresseusement — le download des poids est coûteux
        self._device = cfg.get("device", "cpu")
        self._ctx.set_state("ready")

    def _lazy_load_model(self):
        if self._model is not None:
            return True
        try:
            import torch
            from torchvision.models.detection import maskrcnn_resnet50_fpn
            from torchvision.transforms import functional as F
            self._model = maskrcnn_resnet50_fpn(weights="DEFAULT", progress=False)
            self._model.eval()
            self._model.to(self._device)
            self._F = F
            self._torch = torch
            return True
        except Exception as e:
            self._ctx.log.warning(f"mask-rcnn model load failed: {e}")
            self._ctx.set_state("error", f"model load: {e}")
            return False

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    async def segment(self, frame: Frame, camera_config: dict) -> SegmentationResult:
        if not self._lazy_load_model():
            return SegmentationResult(masks=[], timing_ms=0)

        t0 = time.perf_counter()
        cfg = self._ctx.config or {}
        min_conf = float(cfg.get("confidence", 0.5))

        try:
            import cv2
            # BGR → RGB
            rgb = cv2.cvtColor(frame.numpy_bgr, cv2.COLOR_BGR2RGB)
            tensor = self._F.to_tensor(rgb).to(self._device)
            with self._torch.no_grad():
                pred = self._model([tensor])[0]
        except Exception as e:
            self._ctx.log.warning(f"mask-rcnn inference failed: {e}")
            return SegmentationResult(masks=[], timing_ms=int((time.perf_counter() - t0) * 1000))

        dt_ms = int((time.perf_counter() - t0) * 1000)
        out = []
        boxes = pred["boxes"].cpu().numpy() if len(pred["boxes"]) else np.array([])
        scores = pred["scores"].cpu().numpy() if len(pred["scores"]) else np.array([])
        labels = pred["labels"].cpu().numpy() if len(pred["labels"]) else np.array([])
        masks = pred["masks"].cpu().numpy() if len(pred["masks"]) else np.array([])

        for i in range(len(scores)):
            if scores[i] < min_conf:
                continue
            lbl_idx = int(labels[i])
            label = COCO_LABELS[lbl_idx] if 0 <= lbl_idx < len(COCO_LABELS) else f"cls{lbl_idx}"
            x1, y1, x2, y2 = boxes[i].tolist()
            mask_bin = (masks[i][0] > 0.5).astype(np.uint8) if i < len(masks) else None
            area = int(mask_bin.sum()) if mask_bin is not None else 0
            out.append(SegmentMask(
                label=label,
                confidence=float(scores[i]),
                bbox=(x1, y1, x2, y2),
                area_px=area,
            ))
        return SegmentationResult(masks=out, timing_ms=dt_ms)

    async def on_unload(self) -> None:
        self._model = None
