"""Plugin ANPR — Fast-ALPR (ONNX local, wrapper bundle v2.30)."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult


class FastAlprPlugin(PlateRecognizer):
    name = "fast-alpr"
    version = "1.0.0-preview"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        try:
            import ai_engine
        except Exception as e:
            self._ctx.set_state("missing_dependency", f"ai_engine indisponible: {e}")
            return
        health = getattr(ai_engine, "_ai_health", {}) or {}
        if health.get("alpr_loaded"):
            self._ctx.set_state("ready")
        else:
            err = health.get("alpr_error") or "modèle non chargé (voir /api/diagnostics/ai-health)"
            self._ctx.set_state("error", err)

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    def refresh_state_lazy(self):
        """v1.0-rc4 · P0-3 : ré-évaluation à la lecture du bus (le modèle ALPR
        charge APRÈS le bootstrap — l'état doit suivre la réalité)."""
        self._evaluate_state()

    async def recognize(self, frame: Frame, vehicle_bbox: Optional[tuple] = None) -> list:
        """v3.1.9 · Root cause d'un faux "aucune plaque détectée" permanent :
        cette méthode appelait `ai_engine._analyze_frame_alpr` /
        `analyze_frame_alpr` — deux noms qui n'ont JAMAIS existé dans
        `ai_engine.py` (confirmé par grep sur le code déployé). `fn` valait
        donc toujours `None` et la fonction retournait `[]` immédiatement,
        quelle que soit l'image — fast-alpr n'a jamais lu une seule plaque
        via le plugin bus (donc jamais via `_prerun_multi_anpr` ni via
        l'endpoint `/events/{id}/reanalyze`), même une fois son état de bus
        débloqué (voir commit précédent). Le VRAI mécanisme qui marche existe
        déjà dans `pipeline_v2/plate_recognizer.py::FastAlprRecognizer` (le
        chemin interne utilisé par `_stage_anpr` en direct) : appeler
        directement `ai_engine._alpr.predict(...)`. On reproduit ce même
        appel ici, offload dans un thread (c'est un appel bloquant ONNX/GPU,
        ~2-3s) pour ne pas geler la boucle asyncio, protégé par le même
        `ALPR_INFERENCE_LOCK` que le chemin interne.
        """
        try:
            import ai_engine
        except Exception:
            return []
        health = getattr(ai_engine, "_ai_health", {})
        if not health.get("alpr_loaded") or ai_engine._alpr is None:
            return []

        img = frame.numpy_bgr
        if vehicle_bbox:
            x1, y1, x2, y2 = [int(v) for v in vehicle_bbox]
            c = img[max(0, y1):y2, max(0, x1):x2]
            if c.size > 0:
                img = c
        if img is None or getattr(img, "size", 0) == 0:
            return []

        def _predict():
            with ai_engine.ALPR_INFERENCE_LOCK:
                return list(ai_engine._alpr.predict(img))

        t0 = time.perf_counter()
        try:
            raw = await asyncio.to_thread(_predict)
        except Exception as e:
            self._ctx.log.warning(f"fast-alpr error: {e}")
            return []
        dt_ms = int((time.perf_counter() - t0) * 1000)

        min_conf = float((self._ctx.config or {}).get("min_confidence", 0.4))
        out = []
        for r in raw:
            if not getattr(r, "ocr", None) or not r.ocr.text:
                continue
            conf = float(r.ocr.confidence)
            if conf < min_conf:
                continue
            bb = r.detection.bounding_box
            out.append(PlateResult(
                text=str(r.ocr.text).upper().strip(), confidence=conf,
                bbox_plate=(float(bb.x1), float(bb.y1), float(bb.x2), float(bb.y2)),
                engine="fast-alpr", processing_ms=dt_ms,
            ))
        out.sort(key=lambda p: p.confidence, reverse=True)
        return out

    async def on_unload(self) -> None:
        pass
