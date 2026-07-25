"""Plugin ANPR — Azure Computer Vision (Read API v3.2 OCR)."""
from __future__ import annotations

import asyncio
import io
import re
import time
from typing import Optional

from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult

# Regex simple : suite de 4-10 caractères alphanumériques avec au moins 1 lettre et 1 chiffre
PLATE_RX = re.compile(r"[A-Z0-9\-]{4,10}")


class AzureVisionPlugin(PlateRecognizer):
    name = "azure-vision"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        cfg = self._ctx.config or {}
        if not cfg.get("endpoint") or not cfg.get("subscription_key"):
            self._ctx.set_state("not_configured", "endpoint et/ou subscription_key Azure manquants")
            return
        try:
            import httpx  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install httpx")
            return
        self._ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    async def recognize(self, frame: Frame, vehicle_bbox: Optional[tuple] = None) -> list:
        import httpx
        import cv2
        cfg = self._ctx.config or {}
        base = str(cfg["endpoint"]).rstrip("/")
        key = cfg["subscription_key"]
        lang = cfg.get("language", "en")
        min_conf = float(cfg.get("min_confidence", 0.5))

        img = frame.numpy_bgr
        if vehicle_bbox:
            x1, y1, x2, y2 = [int(v) for v in vehicle_bbox]
            c = img[max(0, y1):y2, max(0, x1):x2]
            if c.size > 0:
                img = c
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return []

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{base}/vision/v3.2/read/analyze",
                    params={"language": lang},
                    headers={"Ocp-Apim-Subscription-Key": key,
                             "Content-Type": "application/octet-stream"},
                    content=bytes(buf),
                )
                r.raise_for_status()
                op_url = r.headers.get("Operation-Location")
                if not op_url:
                    return []
                # Poll (max 8 * 400ms = 3.2s)
                data = None
                for _ in range(8):
                    await asyncio.sleep(0.4)
                    rr = await client.get(op_url, headers={"Ocp-Apim-Subscription-Key": key})
                    d = rr.json()
                    if d.get("status") == "succeeded":
                        data = d
                        break
                if not data:
                    return []
        except Exception as e:
            self._ctx.log.warning(f"azure-vision error: {e}")
            return []

        dt_ms = int((time.perf_counter() - t0) * 1000)
        out = []
        for page in (data.get("analyzeResult", {}).get("readResults") or []):
            for line in page.get("lines", []):
                text = str(line.get("text", "")).upper().replace(" ", "")
                if not text:
                    continue
                m = PLATE_RX.search(text)
                if not m:
                    continue
                plate = m.group(0)
                if not (any(c.isalpha() for c in plate) and any(c.isdigit() for c in plate)):
                    continue
                bb = line.get("boundingBox") or [0] * 8
                xs = bb[0::2] if len(bb) >= 8 else [0]
                ys = bb[1::2] if len(bb) >= 8 else [0]
                confs = [w.get("confidence", 0.0) for w in line.get("words", []) if w.get("confidence") is not None]
                conf = sum(confs) / len(confs) if confs else 0.0
                if conf < min_conf:
                    continue
                out.append(PlateResult(
                    text=plate,
                    confidence=conf,
                    bbox_plate=(min(xs), min(ys), max(xs), max(ys)),
                    engine="azure-vision",
                    processing_ms=dt_ms,
                ))
        return out

    async def on_unload(self) -> None:
        pass
