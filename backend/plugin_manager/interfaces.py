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
    """Une frame vidéo transmise à un plugin FrameAnalyzer.

    v0.4.2 : ``jpeg()`` fournit un encodage JPEG **partagé et memoizé** —
    tous les plugins consommant la même Frame réutilisent le même buffer
    (un seul ``cv2.imencode`` quel que soit le nombre de moteurs).
    """
    camera_id: str
    timestamp: str  # ISO 8601 UTC
    numpy_bgr: object  # numpy.ndarray, opaque au niveau interface
    width: int
    height: int
    _jpeg_cache: dict = field(default_factory=dict, repr=False)

    def jpeg(self, quality: int = 85):
        """JPEG bytes de la frame — encodé UNE seule fois par qualité."""
        q = int(quality)
        if q not in self._jpeg_cache:
            img = self.numpy_bgr
            if img is None or getattr(img, "size", 0) == 0:
                self._jpeg_cache[q] = None
            else:
                import cv2
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
                self._jpeg_cache[q] = buf.tobytes() if ok else None
        return self._jpeg_cache[q]


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


# ── Interfaces additionnelles (session 4 · Tracking + Segmentation) ───────

@dataclass
class Track:
    """Un track produit par un plugin `Tracker`."""
    track_id: str
    label: str
    confidence: float = 0.0
    bbox: tuple = (0, 0, 0, 0)  # x1, y1, x2, y2
    age: int = 0                # nb frames depuis la 1ère détection
    velocity: tuple = (0.0, 0.0)  # (vx, vy) px/frame
    extra: dict = field(default_factory=dict)


@dataclass
class TrackingResult:
    tracks: list = field(default_factory=list)
    timing_ms: int = 0


class Tracker(Plugin):
    """Plugin qui maintient l'identité d'objets à travers les frames.
    Exemples : ByteTrack, BoTSORT, DeepSORT, StrongSORT, OCSORT.
    """
    @abstractmethod
    async def track(self, frame: Frame, detections: list) -> TrackingResult:
        """Reçoit les détections courantes (Detection[]) et retourne les tracks."""


@dataclass
class SegmentMask:
    """Un masque de segmentation produit par un plugin `Segmenter`."""
    label: str
    confidence: float = 0.0
    bbox: tuple = (0, 0, 0, 0)
    mask_rle: Optional[str] = None  # RLE encodé pour compact JSON
    area_px: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class SegmentationResult:
    masks: list = field(default_factory=list)
    timing_ms: int = 0


class Segmenter(Plugin):
    """Plugin qui segmente les objets/zones dans une frame.
    Exemples : SAM2, Detectron2, Mask R-CNN.
    """
    @abstractmethod
    async def segment(self, frame: Frame, camera_config: dict) -> SegmentationResult:
        ...


# ── Pipeline result (session 5) ────────────────────────────────────

@dataclass
class PipelineResult:
    """Résultat d'un cycle pipeline complet Detector→Tracker→Segmenter→Business."""
    camera_id: Optional[str] = None
    timestamp: Optional[str] = None
    detections: list = field(default_factory=list)           # list[Detection]
    tracks: list = field(default_factory=list)               # list[Track]
    masks: list = field(default_factory=list)                # list[SegmentMask]
    business_events: list = field(default_factory=list)      # list[dict]
    timing_ms: dict = field(default_factory=dict)            # {"detection": 12, "tracking": 3, "segmentation": 50}
    plugins_used: dict = field(default_factory=dict)         # {"detectors": [...], "trackers": [...], ...}


class PipelineConsumer(Plugin):
    """Plugin métier qui consomme le résultat complet d'un pipeline.

    Exemples : person-counting, vehicle-counting, occupancy, fire-detection.
    Reçoit le PipelineResult déjà rempli avec detections + tracks + masks, et
    retourne 0..N événements métier (dict JSON-sérialisable).
    """
    @abstractmethod
    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        """Retourne une liste d'événements métier `{type, severity, message, data}`."""
