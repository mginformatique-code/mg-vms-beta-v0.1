"""Pipeline v2 · Interfaces stables + résultats standardisés.

Toutes les implémentations (YOLO, ByteTrack, FastALPR, PaddleOCR…) doivent
respecter ces interfaces et retourner ces dataclasses. **Aucun format
propriétaire n'est autorisé** — le pipeline appelle uniquement les méthodes
du Protocol et ne connaît jamais le moteur sous-jacent.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

import numpy as np


# ═══════════════════════════════════════════════════════════════════
# Résultats standardisés — même structure quel que soit le provider
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Frame:
    """Frame vidéo décodée UNE seule fois. Passée par référence à toutes
    les étapes du pipeline pour éviter les copies GPU inutiles."""
    camera_id: str
    image: np.ndarray           # BGR HxWx3
    timestamp: float            # epoch seconds
    frame_id: int = 0           # incrémenté par le scheduler
    site_id: str = ""


@dataclass
class BBox:
    """Coordonnées entières (pixels image). x2>x1, y2>y1."""
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def area(self) -> int:
        return max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)


@dataclass
class Detection:
    """Détection normalisée d'un objet dans une frame."""
    label: str                  # ex : "car", "person", "truck"
    confidence: float           # 0.0 - 1.0
    bbox: BBox
    class_id: int = -1
    attrs: dict = field(default_factory=dict)  # couleur, orientation, embedding…
    track_id: Optional[int] = None             # rempli par le tracking stage


@dataclass
class Track:
    """État de tracking (association temporelle des détections)."""
    track_id: int
    label: str
    bbox: BBox
    confidence: float
    age_frames: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0


@dataclass
class PlateResult:
    """**Format standard obligatoire** pour TOUTES les implémentations ANPR."""
    plate: str
    confidence: float
    bbox: Optional[BBox] = None
    country: str = ""
    processing_time_ms: float = 0.0
    provider: str = ""              # "fast-alpr" / "google-vision" / "openalpr"…
    raw_text: str = ""              # texte non-normalisé (debug)
    vehicle_type: str = ""
    vehicle_color: str = ""
    track_id: Optional[int] = None
    extras: dict = field(default_factory=dict)


@dataclass
class DetectionResult:
    detections: list[Detection] = field(default_factory=list)
    processing_time_ms: float = 0.0
    provider: str = ""


@dataclass
class TrackingResult:
    tracks: list[Track] = field(default_factory=list)
    processing_time_ms: float = 0.0
    provider: str = ""


# ═══════════════════════════════════════════════════════════════════
# Providers (interfaces stables) — Protocols runtime-checkable
# ═══════════════════════════════════════════════════════════════════

@runtime_checkable
class DetectionProvider(Protocol):
    """YOLOv11 / YOLOv8 / TensorRT / RT-DETR / OpenVINO / ONNX / …

    Le pipeline appelle uniquement ``detect(frame) → DetectionResult``.
    Aucun plugin ne connaît le tracking, la BD, les events, etc.
    """
    name: str

    def detect(self, frame: Frame) -> DetectionResult: ...


@runtime_checkable
class TrackingProvider(Protocol):
    """ByteTrack / BoTSORT / OCSORT / StrongSORT / DeepSORT / …

    Reçoit les détections d'un frame et retourne les tracks avec IDs stables.
    Le tracking est **centralisé** — un seul tracker par caméra, partagé.
    """
    name: str

    def update(self, frame: Frame, detections: list[Detection]) -> TrackingResult: ...


@runtime_checkable
class PlateRecognitionProvider(Protocol):
    """FastALPR / PlateRecognizer / OpenALPR / PaddleOCR / EasyOCR /
    Tesseract / Google Vision / Azure Vision / CodeProject AI / …

    Reçoit une ROI image (crop véhicule) et retourne 0..N PlateResult
    tous au **format standard obligatoire**.
    """
    name: str

    def recognize(self, roi: np.ndarray) -> list[PlateResult]: ...


@runtime_checkable
class PipelineConsumer(Protocol):
    """Business logic : EPS ANPR, comptage, Smart Zones, workflows, notifiers…

    Reçoit le contexte complet (frame + detections + tracks + plates) et
    produit des business events. Peut être totalement asynchrone.
    """
    name: str

    async def consume(self, context: "PipelineContext") -> list[dict]: ...


# ═══════════════════════════════════════════════════════════════════
# Contexte pipeline — passe entre les stages, garde la trace complète
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PipelineContext:
    frame: Frame
    detections: list[Detection] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    plates: list[PlateResult] = field(default_factory=list)
    business_events: list[dict] = field(default_factory=list)
    # Traçabilité pour le monitoring (voir /diagnostics/pipeline-metrics)
    providers_used: dict = field(default_factory=lambda: {
        "detectors": [], "trackers": [], "recognizers": [], "consumers": [],
    })
    timings_ms: dict = field(default_factory=dict)
    # Config caméra (enabled_plugins whitelist, fusion strategy, …)
    camera_config: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.perf_counter)
