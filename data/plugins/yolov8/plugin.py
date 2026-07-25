"""Plugin Object Detection — YOLOv8 (Ultralytics).

PoC v2.30 : ce plugin détecte les dépendances requises et déclare son état
en conséquence. L'implémentation réelle d'inférence sera branchée sur
`ai_engine.frame_source` en v3.0 (partage du framebuffer GPU/CPU).
"""
from __future__ import annotations

import time
from typing import Optional

from plugin_manager.interfaces import FrameAnalyzer, Frame, AnalysisResult


class YoloV8Plugin(FrameAnalyzer):
    name = "yolov8"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        cfg = self._ctx.config or {}
        # Détection deps
        try:
            from ultralytics import YOLO  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install ultralytics")
            return
        # Optionnel : le chemin modèle est requis pour ce provider
        model_path = cfg.get("model_path")
        if model_path is not None and model_path != "" and not self._is_model_ok(model_path):
            self._ctx.set_state("not_configured", f"model_path invalide : {model_path}")
            return
        self._ctx.set_state("ready")

    def _is_model_ok(self, path: str) -> bool:
        from pathlib import Path
        return Path(path).exists()

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    async def analyze(self, frame: Frame, camera_config: dict) -> AnalysisResult:
        # PoC v2.30 : retour vide. L'inférence réelle sera implémentée quand
        # les deps seront installées via l'UI "Installer les deps".
        # Chaque provider peut aussi être branché sur un modèle spécifique
        # via le champ model_path de sa config.
        t0 = time.perf_counter()
        return AnalysisResult(
            detections=[],
            timing_ms=int((time.perf_counter() - t0) * 1000),
            device_used=(self._ctx.config or {}).get("device", "cpu"),
        )

    async def on_unload(self) -> None:
        pass
