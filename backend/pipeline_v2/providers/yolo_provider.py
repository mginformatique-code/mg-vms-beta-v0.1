"""Pipeline v2 · YoloDetectionProvider natif.

Enveloppe le detector Ultralytics YOLOv11 (déjà utilisé par ``ai_engine.py``)
dans l'interface ``DetectionProvider`` v2. Aucune duplication de modèle : on
réutilise ``ai_engine._model`` qui est chargé au démarrage.

**Bénéfices** :
- Réel test d'inférence sur le nouveau pipeline
- Zéro chargement supplémentaire de modèle
- Format ``DetectionResult`` standardisé, alignable avec RT-DETR / YOLOv8 / TensorRT
- Skip auto si YOLO n'est pas chargé (fallback gracieux)
"""
from __future__ import annotations

import time
from typing import Optional

from ..interfaces import BBox, Detection, DetectionResult, Frame


class YoloDetectionProvider:
    """Provider natif basé sur ``ai_engine._model`` (Ultralytics YOLOv11).

    Args:
        confidence : seuil de confiance (0-1). None → utilise ``AI_CONFIDENCE``.
        model_name : identifiant informatif ("yolo11n", "yolo11s", etc.)
    """

    def __init__(self, confidence: Optional[float] = None,
                 model_name: str = "yolov11"):
        self.name = model_name
        self._confidence = confidence

    def detect(self, frame: Frame) -> DetectionResult:
        t0 = time.perf_counter()
        # Import local pour éviter les cycles + pouvoir démarrer sans YOLO
        try:
            import ai_engine as _ae
            model = _ae._model
        except Exception:
            model = None

        if model is None:
            return DetectionResult(detections=[], provider=self.name,
                                    processing_time_ms=0.0)

        # Seuil : fourni au ctor ou config runtime
        try:
            conf = self._confidence if self._confidence is not None else \
                   float(_ae._cfg("confidence", _ae.AI_CONFIDENCE))
        except Exception:
            conf = self._confidence or 0.45

        detections: list[Detection] = []
        try:
            # Ultralytics API : model(image, verbose=False)
            results = model(frame.image, verbose=False, conf=conf)
            r = results[0] if results else None
            if r is None or r.boxes is None:
                return DetectionResult(detections=[], provider=self.name,
                                        processing_time_ms=round(
                                            (time.perf_counter() - t0) * 1000, 2))
            names = getattr(model, "names", {}) or {}
            for box in r.boxes:
                try:
                    xyxy = box.xyxy[0].tolist()
                    cls_id = int(box.cls[0])
                    confv = float(box.conf[0])
                    label = names.get(cls_id, str(cls_id))
                    detections.append(Detection(
                        label=str(label),
                        confidence=round(confv, 3),
                        bbox=BBox(int(xyxy[0]), int(xyxy[1]),
                                   int(xyxy[2]), int(xyxy[3])),
                        class_id=cls_id,
                    ))
                except Exception:
                    continue
        except Exception:
            pass  # inférence a planté — provider retourne 0 détection

        return DetectionResult(
            detections=detections,
            provider=self.name,
            processing_time_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
