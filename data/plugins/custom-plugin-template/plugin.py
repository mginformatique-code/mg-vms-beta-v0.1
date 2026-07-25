"""Plugin ANPR personnalisé — TEMPLATE.

Ce fichier est un modèle. Éditez `recognize()` pour brancher votre propre
moteur ANPR (REST interne, ONNX custom, TensorFlow, appel gRPC, etc.).

Contrat :
  1. Toujours retourner une `list[PlateResult]` (vide si aucune plaque).
  2. Le core ne connaît JAMAIS votre moteur — respectez le format normalisé.
  3. Le format `PlateResult` est immuable (ADR-16). N'ajoutez pas de champs.
"""
from __future__ import annotations

from typing import Optional

from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult


class CustomAnprPlugin(PlateRecognizer):
    """Plugin ANPR personnalisé — template à adapter."""

    name = "custom-plugin-template"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        if not cfg.get("enabled_for_demo"):
            ctx.set_state("not_configured",
                          "Éditez plugin.py pour brancher votre moteur, ou activez la démo dans la config")
        else:
            ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        if not (new_config or {}).get("enabled_for_demo"):
            self._ctx.set_state("not_configured", "Démo désactivée")
        else:
            self._ctx.set_state("ready")

    async def recognize(self, frame: Frame, vehicle_bbox: Optional[tuple] = None) -> list:
        # ─────────────────────────────────────────────────────────────
        # ⚙  BRANCHEZ VOTRE MOTEUR ICI  ⚙
        #
        # Exemple pattern REST :
        #   async with httpx.AsyncClient() as client:
        #       r = await client.post("http://mon-serveur/anpr", ...)
        #       ...
        #
        # Exemple pattern ONNX :
        #   session = onnxruntime.InferenceSession("model.onnx")
        #   outputs = session.run(None, {"input": frame.numpy_bgr})
        #
        # Exemple pattern GRPC / Kafka / autre :
        #   ... votre code ici ...
        # ─────────────────────────────────────────────────────────────
        cfg = self._ctx.config or {}
        if not cfg.get("enabled_for_demo"):
            return []
        return [PlateResult(
            text=str(cfg.get("demo_plate", "CUSTOM-99")).upper(),
            confidence=float(cfg.get("demo_confidence", 0.5)),
            engine="custom-plugin-template",
            processing_ms=1,
            country_hint="demo",
            bbox_plate=(0, 0, 100, 40),
        )]

    async def on_unload(self) -> None:
        pass
