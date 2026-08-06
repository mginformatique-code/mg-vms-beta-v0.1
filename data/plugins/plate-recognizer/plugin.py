"""Plugin ANPR — Plate Recognizer (cloud API platerecognizer.com)."""
from __future__ import annotations

import io
import time
from typing import Optional

from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult


class PlateRecognizerPlugin(PlateRecognizer):
    name = "plate-recognizer"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        cfg = self._ctx.config or {}
        token = cfg.get("api_token")
        if not token:
            self._ctx.set_state("not_configured", "api_token manquant — configurez-le dans l'UI")
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
        token = cfg.get("api_token")
        endpoint = cfg.get("endpoint", "https://api.platerecognizer.com/v1/plate-reader/")
        regions = cfg.get("regions") or ["fr"]
        timeout_s = float(cfg.get("timeout_s") or 5.0)

        # Recadrage optionnel sur bbox véhicule
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

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                r = await client.post(
                    endpoint,
                    headers={"Authorization": f"Token {token}"},
                    files={"upload": ("frame.jpg", io.BytesIO(bytes(buf)), "image/jpeg")},
                    data={"regions": ",".join(regions)},
                )
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            self._ctx.log.warning(f"plate-recognizer error: {e}")
            return []

        dt_ms = int((time.perf_counter() - t0) * 1000)
        out = []
        for res in (data.get("results") or []):
            plate = str(res.get("plate", "")).upper()
            if not plate:
                continue
            box = res.get("box") or {}
            out.append(PlateResult(
                text=plate,
                confidence=float(res.get("score", 0.0)),
                country_hint=(res.get("region") or {}).get("code") if isinstance(res.get("region"), dict) else None,
                region_hint=(res.get("region") or {}).get("code") if isinstance(res.get("region"), dict) else None,
                bbox_plate=(box.get("xmin", 0), box.get("ymin", 0), box.get("xmax", 0), box.get("ymax", 0)),
                engine="plate-recognizer",
                processing_ms=dt_ms,
            ))
        return out

    async def on_unload(self) -> None:
        pass
