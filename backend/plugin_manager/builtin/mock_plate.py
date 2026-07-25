"""Mock plugin PlateRecognizer — utile pour tests unitaires et démo multi-ANPR.

Retourne toujours une plaque configurable. Permet de tester le bus/fusion
sans charger de vrai modèle IA.
"""
from __future__ import annotations

from typing import Optional

from ..interfaces import PlateRecognizer, Frame, PlateResult

MOCK_PLATE_TEXT = "AB-123-CD"


class MockPlatePlugin(PlateRecognizer):
    """Plugin ANPR factice — retourne une plaque prédéfinie."""

    def __init__(self, engine_name: str = "mock", text: str = MOCK_PLATE_TEXT,
                 confidence: float = 0.9, processing_ms: int = 5):
        self.engine_name = engine_name
        self.text = text
        self.confidence = confidence
        self.processing_ms = processing_ms

    async def on_load(self, ctx) -> None:
        self._ctx = ctx

    async def recognize(self, frame: Frame, vehicle_bbox: Optional[tuple] = None) -> list:
        return [PlateResult(
            text=self.text,
            confidence=self.confidence,
            country_hint="fr",
            bbox_plate=(10, 10, 100, 40),
            engine=self.engine_name,
            processing_ms=self.processing_ms,
        )]

    async def on_unload(self) -> None:
        pass
