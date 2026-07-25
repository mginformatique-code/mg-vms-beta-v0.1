"""Plugin ANPR — PaddleOCR (local Baidu)."""
from __future__ import annotations

import re
import time
from typing import Optional

from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult

PLATE_RX = re.compile(r"[A-Z0-9\-]{4,10}")


class PaddleOCRPlugin(PlateRecognizer):
    name = "paddle-ocr"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._ocr = None
        self._evaluate_state()

    def _evaluate_state(self):
        try:
            import paddleocr  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install paddleocr paddlepaddle")
            return
        try:
            from paddleocr import PaddleOCR
            cfg = self._ctx.config or {}
            self._ocr = PaddleOCR(
                use_angle_cls=True,
                lang=cfg.get("lang", "en"),
                use_gpu=bool(cfg.get("use_gpu", False)),
                show_log=False,
            )
            self._ctx.set_state("ready")
        except Exception as e:
            self._ctx.set_state("error", f"PaddleOCR init failed: {e}")

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    async def recognize(self, frame: Frame, vehicle_bbox: Optional[tuple] = None) -> list:
        if self._ocr is None:
            return []
        img = frame.numpy_bgr
        if vehicle_bbox:
            x1, y1, x2, y2 = [int(v) for v in vehicle_bbox]
            c = img[max(0, y1):y2, max(0, x1):x2]
            if c.size > 0:
                img = c

        min_conf = float((self._ctx.config or {}).get("min_confidence", 0.5))
        t0 = time.perf_counter()
        try:
            result = self._ocr.ocr(img, cls=True) or []
        except Exception as e:
            self._ctx.log.warning(f"paddle-ocr error: {e}")
            return []
        dt_ms = int((time.perf_counter() - t0) * 1000)

        out = []
        # PaddleOCR retourne [[[box, (text, score)], ...]] par page
        for page in (result or []):
            if page is None:
                continue
            for line in page:
                try:
                    box, (text, score) = line
                except Exception:
                    continue
                if score < min_conf:
                    continue
                cleaned = str(text).upper().replace(" ", "")
                m = PLATE_RX.search(cleaned)
                if not m:
                    continue
                plate = m.group(0)
                if not (any(c.isalpha() for c in plate) and any(c.isdigit() for c in plate)):
                    continue
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                out.append(PlateResult(
                    text=plate,
                    confidence=float(score),
                    bbox_plate=(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
                    engine="paddle-ocr",
                    processing_ms=dt_ms,
                ))
        return out

    async def on_unload(self) -> None:
        self._ocr = None
