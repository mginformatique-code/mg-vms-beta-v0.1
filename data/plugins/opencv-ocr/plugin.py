"""Plugin ANPR — OpenCV OCR (contrib text module).

Utilise `cv2.text.OCRTesseract_create()` du package `opencv-contrib-python`.
En fallback léger : chaîne EAST text detector + pytesseract.
"""
from __future__ import annotations

import re
import time
from typing import Optional

from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult

PLATE_RX = re.compile(r"[A-Z0-9\-]{4,10}")


class OpenCVOCRPlugin(PlateRecognizer):
    name = "opencv-ocr"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._tess = None
        self._evaluate_state()

    def _evaluate_state(self):
        try:
            import cv2
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install opencv-python")
            return
        # Le module cv2.text n'existe que dans opencv-contrib-python
        text_mod = getattr(cv2, "text", None)
        if text_mod is None or not hasattr(text_mod, "OCRTesseract_create"):
            self._ctx.set_state("missing_dependency",
                                "pip install opencv-contrib-python (module cv2.text absent)")
            return
        try:
            self._tess = text_mod.OCRTesseract_create()
            self._ctx.set_state("ready")
        except Exception as e:
            self._ctx.set_state("error", f"OpenCV text init failed: {e}")

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    async def recognize(self, frame: Frame, vehicle_bbox: Optional[tuple] = None) -> list:
        if self._tess is None:
            return []
        import cv2
        cfg = self._ctx.config or {}
        min_conf = float(cfg.get("min_confidence", 0.4))
        pp = cfg.get("preprocess", "adaptive")

        img = frame.numpy_bgr
        if vehicle_bbox:
            x1, y1, x2, y2 = [int(v) for v in vehicle_bbox]
            c = img[max(0, y1):y2, max(0, x1):x2]
            if c.size > 0:
                img = c

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if pp == "adaptive":
            gray = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                         cv2.THRESH_BINARY, 11, 2)
        elif pp == "otsu":
            _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        t0 = time.perf_counter()
        try:
            out_text = self._tess.run(gray, 0)
        except Exception as e:
            self._ctx.log.warning(f"opencv-ocr error: {e}")
            return []
        dt_ms = int((time.perf_counter() - t0) * 1000)

        text = str(out_text or "").upper().replace(" ", "")
        m = PLATE_RX.search(text)
        if not m:
            return []
        plate = m.group(0)
        if not (any(c.isalpha() for c in plate) and any(c.isdigit() for c in plate)):
            return []
        conf = 0.6  # OpenCV OCR ne fournit pas de score fiable
        if conf < min_conf:
            return []
        h, w = gray.shape[:2]
        return [PlateResult(
            text=plate, confidence=conf,
            bbox_plate=(0, 0, w, h),
            engine="opencv-ocr", processing_ms=dt_ms,
        )]

    async def on_unload(self) -> None:
        self._tess = None
