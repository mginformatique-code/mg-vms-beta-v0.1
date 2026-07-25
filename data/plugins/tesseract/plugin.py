"""Plugin ANPR — Tesseract OCR via pytesseract."""
from __future__ import annotations

import re
import shutil
import time
from typing import Optional

from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult

PLATE_RX = re.compile(r"[A-Z0-9\-]{4,10}")


class TesseractPlugin(PlateRecognizer):
    name = "tesseract"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        try:
            import pytesseract  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install pytesseract + apt install tesseract-ocr")
            return
        if not shutil.which("tesseract"):
            self._ctx.set_state("missing_dependency", "binaire tesseract absent (apt install tesseract-ocr)")
            return
        self._ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    async def recognize(self, frame: Frame, vehicle_bbox: Optional[tuple] = None) -> list:
        try:
            import pytesseract
            import cv2
        except Exception:
            return []
        cfg = self._ctx.config or {}
        img = frame.numpy_bgr
        if vehicle_bbox:
            x1, y1, x2, y2 = [int(v) for v in vehicle_bbox]
            c = img[max(0, y1):y2, max(0, x1):x2]
            if c.size > 0:
                img = c

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        config = f"--psm {int(cfg.get('psm', 7))} -c tessedit_char_whitelist={cfg.get('whitelist', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-')}"

        t0 = time.perf_counter()
        try:
            data = pytesseract.image_to_data(
                gray, lang=cfg.get("lang", "eng"),
                config=config, output_type=pytesseract.Output.DICT,
            )
        except Exception as e:
            self._ctx.log.warning(f"tesseract error: {e}")
            return []
        dt_ms = int((time.perf_counter() - t0) * 1000)

        out = []
        n = len(data.get("text", []))
        for i in range(n):
            text = str(data["text"][i] or "").upper().replace(" ", "")
            conf_str = str(data["conf"][i] or "0")
            try:
                conf = max(0.0, float(conf_str) / 100.0)
            except Exception:
                conf = 0.0
            if not text or conf < 0.3:
                continue
            m = PLATE_RX.search(text)
            if not m:
                continue
            plate = m.group(0)
            if not (any(c.isalpha() for c in plate) and any(c.isdigit() for c in plate)):
                continue
            x, y, w, h = int(data["left"][i]), int(data["top"][i]), int(data["width"][i]), int(data["height"][i])
            out.append(PlateResult(
                text=plate, confidence=conf,
                bbox_plate=(x, y, x + w, y + h),
                engine="tesseract", processing_ms=dt_ms,
            ))
        return out

    async def on_unload(self) -> None:
        pass
