"""Plugin ANPR — OpenALPR (cloud api.openalpr.com)."""
from __future__ import annotations

import base64
import time
from typing import Optional

from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult


class OpenALPRPlugin(PlateRecognizer):
    name = "openalpr"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        cfg = self._ctx.config or {}
        if not cfg.get("secret_key"):
            self._ctx.set_state("not_configured", "secret_key OpenALPR manquant")
            return
        try:
            import httpx  # noqa: F401
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
        endpoint = cfg.get("endpoint", "https://api.openalpr.com/v3/recognize_bytes")

        img = frame.numpy_bgr
        if vehicle_bbox:
            x1, y1, x2, y2 = [int(v) for v in vehicle_bbox]
            crop = img[max(0, y1):y2, max(0, x1):x2]
            if crop.size > 0:
                img = crop
            ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            buf = enc.tobytes() if ok else None
        else:
            # v0.4.2 · JPEG PARTAGÉ : encodé une seule fois pour tous les moteurs
            buf = frame.jpeg(85)
        if buf is None:
            return []
        b64 = base64.b64encode(bytes(buf)).decode()

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=float(cfg.get("timeout_s") or 5.0)) as client:
                r = await client.post(endpoint, params={
                    "secret_key": cfg["secret_key"],
                    "country": cfg.get("country", "eu"),
                    "recognize_vehicle": int(bool(cfg.get("recognize_vehicle"))),
                    "return_image": 0,
                    "topn": 10,
                }, content=b64)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            self._ctx.log.warning(f"openalpr error: {e}")
            return []

        dt_ms = int((time.perf_counter() - t0) * 1000)
        out = []
        for res in (data.get("results") or []):
            plate = str(res.get("plate", "")).upper()
            if not plate:
                continue
            coords = res.get("coordinates") or []
            xs = [c["x"] for c in coords] if coords else [0]
            ys = [c["y"] for c in coords] if coords else [0]
            out.append(PlateResult(
                text=plate,
                confidence=float(res.get("confidence", 0.0)) / 100.0,
                country_hint=res.get("region"),
                bbox_plate=(min(xs), min(ys), max(xs), max(ys)),
                engine="openalpr",
                processing_ms=dt_ms,
            ))
        return out

    async def on_unload(self) -> None:
        pass
