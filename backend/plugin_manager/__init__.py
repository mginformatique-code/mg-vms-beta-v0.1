"""MG-VMS Plugin Manager — PoC v0.1 (Preview NG · roadmap v2.30 · chantier A).

Ce module pose les fondations du Plugin Manager décrit dans le chapitre 11 du
cahier des charges. En v2.30 il s'agit d'un PoC démonstratif qui :

  1. Définit les interfaces standardisées (FrameAnalyzer, PlateRecognizer,
     EventConsumer) — contrat public que les plugins implémenteront.
  2. Fournit un `PluginContext` que le core injecte à chaque plugin.
  3. Enregistre les plugins « officiels bundle » comme wrappers autour du code
     existant (`yolo-detection` wrappe `ai_engine._analyze_frame` YOLO).
  4. Expose `GET /api/plugins` qui liste l'état de chaque plugin.

En v3.0 : refonte complète avec chargement dynamique depuis /data/plugins/,
manifest YAML, sandbox sub-process/container, Marketplace.
"""

from .interfaces import (
    Plugin,
    FrameAnalyzer,
    PlateRecognizer,
    EventConsumer,
    Frame,
    AnalysisResult,
    Detection,
    PlateResult,
    MGVMSEvent,
    ConsumerResult,
)
from .context import PluginContext
from .registry import registry, PluginInfo

__all__ = [
    "Plugin",
    "FrameAnalyzer",
    "PlateRecognizer",
    "EventConsumer",
    "Frame",
    "AnalysisResult",
    "Detection",
    "PlateResult",
    "MGVMSEvent",
    "ConsumerResult",
    "PluginContext",
    "registry",
    "PluginInfo",
]
