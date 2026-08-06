"""Plugin ANPR — Google Cloud Vision (OCR généraliste)."""
from __future__ import annotations

import os
import re
import time
from typing import Optional

from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult

PLATE_RX = re.compile(r"[A-Z0-9\-]{4,10}")


class GoogleVisionPlugin(PlateRecognizer):
    name = "google-vision"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._client = None
        self._evaluate_state()

    def _evaluate_state(self):
        cfg = self._ctx.config or {}
        cred_path = cfg.get("credentials_json_path")
        if not cred_path:
            self._ctx.set_state("not_configured", "credentials_json_path manquant")
            return
        if not os.path.exists(cred_path):
            self._ctx.set_state("not_configured", f"fichier credentials introuvable: {cred_path}")
            return
        try:
            from google.cloud import vision  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install google-cloud-vision")
            return
        try:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
            from google.cloud import vision
            self._client = vision.ImageAnnotatorClient()
            self._ctx.set_state("ready")
        except Exception as e:
            self._ctx.set_state("error", f"Google Vision init failed: {e}")

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    async def recognize(self, frame: Frame, vehicle_bbox: Optional[tuple] = None) -> list:
        if self._client is None:
            return []
        import cv2
        from google.cloud import vision

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

        min_conf = float((self._ctx.config or {}).get("min_confidence", 0.5))
        t0 = time.perf_counter()
        try:
            image = vision.Image(content=bytes(buf))
            response = self._client.text_detection(image=image)
        except Exception as e:
            self._ctx.log.warning(f"google-vision error: {e}")
            return []
        dt_ms = int((time.perf_counter() - t0) * 1000)

        out = []
        # Le premier text_annotations est le bloc global. On itère sur les suivants.
        for ann in (response.text_annotations or [])[1:]:
            text = str(ann.description or "").upper().replace(" ", "")
            m = PLATE_RX.search(text)
            if not m:
                continue
            plate = m.group(0)
            if not (any(c.isalpha() for c in plate) and any(c.isdigit() for c in plate)):
                continue
            verts = ann.bounding_poly.vertices if ann.bounding_poly else []
            xs = [v.x for v in verts] or [0]
            ys = [v.y for v in verts] or [0]
            conf = 0.9  # Google Vision ne remonte pas de score direct par annotation
            if conf < min_conf:
                continue
            out.append(PlateResult(
                text=plate, confidence=conf,
                bbox_plate=(min(xs), min(ys), max(xs), max(ys)),
                engine="google-vision", processing_ms=dt_ms,
            ))
        return out

    async def on_unload(self) -> None:
        self._client = None
