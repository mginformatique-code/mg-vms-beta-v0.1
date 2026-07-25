"""Interfaces standardisées des plugins MG-VMS (chapitre 11 §11.3).

Ces classes sont le CONTRAT public. Un plugin conforme implémente exactement
une de ces interfaces. Le core ne connaît jamais l'implémentation d'un plugin,
uniquement son interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ── Types de données transportés ────────────────────────────────────────────

@dataclass
class Frame:
    """Une frame vidéo transmise à un plugin FrameAnalyzer."""
    camera_id: str
    timestamp: str  # ISO 8601 UTC
    numpy_bgr: object  # numpy.ndarray, opaque au niveau interface
    width: int
    height: int


@dataclass
class Detection:
    """Une détection produite par un FrameAnalyzer."""
    label: str
    label_fr: Optional[str] = None
    confidence: float = 0.0
    bbox: tuple = (0, 0, 0, 0)  # x1, y1, x2, y2
    track_id: Optional[str] = None
    extra: dict = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Résultat d'un cycle d'analyse."""
    detections: list = field(default_factory=list)
    timing_ms: int = 0
    device_used: str = "cpu"


@dataclass
class PlateResult:
    """Résultat normalisé d'un plugin PlateRecognizer (ADR-16).

    TOUS les moteurs ANPR retournent cette structure. Le core ne connaît jamais
    le moteur sous-jacent.
    """
    text: str
    confidence: float
    country_hint: Optional[str] = None
    region_hint: Optional[str] = None
    bbox_plate: tuple = (0, 0, 0, 0)
    engine: str = ""
    processing_ms: int = 0


@dataclass
class MGVMSEvent:
    """Événement du bus interne consommé par les EventConsumer."""
    type: str  # ex. "event.detected", "plate.blacklist", "alert.critical"
    camera_id: Optional[str]
    data: dict
    timestamp: str


@dataclass
class ConsumerResult:
    """Résultat d'un traitement EventConsumer."""
    handled: bool = True
    error: Optional[str] = None


# ── Interfaces plugin ───────────────────────────────────────────────────────

class Plugin(ABC):
    """Classe base commune à tous les plugins."""

    async def on_load(self, ctx) -> None:  # pragma: no cover — implémentation par sous-classe
        """Chargement initial. Peut échouer sans crasher le core."""

    async def on_config_change(self, new_config: dict) -> None:  # pragma: no cover
        """Notification que la config utilisateur a changé."""

    async def on_unload(self) -> None:  # pragma: no cover
        """Nettoyage avant arrêt ou désinstallation."""


class FrameAnalyzer(Plugin):
    """Plugin qui analyse chaque frame vidéo (YOLO, Face, Smoke, Fire, PPE…)."""

    @abstractmethod
    async def analyze(self, frame: Frame, camera_config: dict) -> AnalysisResult:
        ...


class PlateRecognizer(Plugin):
    """Plugin qui lit les plaques d'immatriculation (ADR-16 : format normalisé)."""

    @abstractmethod
    async def recognize(self, frame: Frame, vehicle_bbox: Optional[tuple] = None) -> list:
        """Retourne list[PlateResult]. Vide si rien détecté."""


class EventConsumer(Plugin):
    """Plugin qui consomme des événements (notifications, MQTT, webhooks…)."""

    @abstractmethod
    async def on_event(self, event: MGVMSEvent) -> ConsumerResult:
        ...
