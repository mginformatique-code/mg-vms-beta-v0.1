"""Plugin ANPR — CodeProject.AI Server (self-hosted, gratuit)."""
from __future__ import annotations

import io
import time
from typing import Optional

from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult


class CodeProjectAIPlugin(PlateRecognizer):
    name = "codeproject-ai"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        cfg = self._ctx.config or {}
        if not cfg.get("endpoint"):
            self._ctx.set_state("not_configured", "endpoint CodeProject.AI manquant")
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
        route = cfg.get("route", "/v1/vision/alpr")
        min_conf = float(cfg.get("min_confidence", 0.4))

        img = frame.numpy_bgr
        if vehicle_bbox:
            x1, y1, x2, y2 = [int(v) for v in vehicle_bbox]
            c = img[max(0, y1):y2, max(0, x1):x2]
            if c.size > 0:
                img = c
            ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            buf = enc.tobytes() if ok else None
        else:
            # v0.4.2 · JPEG PARTAGÉ : encodé une seule fois pour tous les moteurs
            buf = frame.jpeg(85)
        if buf is None:
            return []

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=float(cfg.get("timeout_s") or 8.0)) as client:
                r = await client.post(
                    f"{base}{route}",
                    files={"image": ("frame.jpg", io.BytesIO(bytes(buf)), "image/jpeg")},
                    data={"min_confidence": min_conf},
                )
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            self._ctx.log.warning(f"codeproject-ai error: {e}")
            return []

        dt_ms = int((time.perf_counter() - t0) * 1000)
        out = []
        for pred in (data.get("predictions") or []):
            plate = str(pred.get("plate", "") or pred.get("label", "")).upper().strip()
            if not plate:
                continue
            out.append(PlateResult(
                text=plate,
                confidence=float(pred.get("confidence", 0.0)),
                bbox_plate=(int(pred.get("x_min", 0)), int(pred.get("y_min", 0)),
                            int(pred.get("x_max", 0)), int(pred.get("y_max", 0))),
                engine="codeproject-ai",
                processing_ms=dt_ms,
            ))
        return out

    async def on_unload(self) -> None:
        pass
