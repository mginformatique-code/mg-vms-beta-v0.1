"""Tests — Phase B · Pipeline Hardening v0.5.6.

Vérifie que la migration hot-path YOLO → Detector abstraction est
opérationnelle :

  1. Le registry contient au moins ``yolov11`` (register auto au import).
  2. Un détecteur alternatif peut être enregistré via
     ``registry.register("mock", MockDetector)`` sans toucher au code du
     pipeline (contrat plugin-friendly).
  3. ``registry.get_active()`` retourne toujours (Detector, str, warning|None).
  4. ``_stage_detection`` utilise bien le registry :
       - Trace d'un import ``from .detector import registry`` dans le source.
       - Métadonnées ``ctx.metadata["detector"] = {name, warning}`` renseignées.
  5. ``DetectorRegistry`` gère la substitution : si le default n'existe
     pas, retourne ``_NULL_DETECTOR`` avec warning (jamais crash).
"""
import os
import sys
from pathlib import Path

_env_file = Path("/app/backend/.env")
for line in _env_file.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
sys.path.insert(0, "/app/backend")
os.environ.setdefault("TESTING", "1")


# ═══════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════
def test_registry_has_yolov11_by_default():
    from pipeline_v2.detector import registry
    assert "yolov11" in registry.known(), \
        "YOLOv11 doit être enregistré par défaut"


def test_registry_get_returns_singleton():
    from pipeline_v2.detector import registry
    d1 = registry.get("yolov11")
    d2 = registry.get("yolov11")
    assert d1 is d2, "get() doit renvoyer une instance singleton par nom"


def test_registry_get_unknown_returns_none():
    from pipeline_v2.detector import registry
    assert registry.get("does-not-exist") is None


def test_registry_can_register_third_party_detector():
    """Un détecteur tiers (Protocol-compatible) doit pouvoir être ajouté
    sans modifier une seule ligne du pipeline."""
    from pipeline_v2.detector import (
        Detector, DetectionObject, registry,
    )

    class MockDetector:
        name = "mock-detector"
        def detect(self, frame_bgr):
            return [DetectionObject(
                bbox=(0, 0, 10, 10), label="car", confidence=0.99, class_id=2,
            )]

    registry.register("mock-detector", MockDetector)
    assert "mock-detector" in registry.known()
    inst = registry.get("mock-detector")
    assert inst is not None
    assert isinstance(inst, Detector)  # Protocol runtime-checkable
    dets = inst.detect(None)
    assert len(dets) == 1 and dets[0].label == "car"


def test_registry_get_active_returns_triple():
    from pipeline_v2.detector import registry
    det, name, warning = registry.get_active(None)
    assert det is not None
    assert name == "yolov11"  # défaut Phase B
    # Warning peut être None (yolov11 ok) OU non-None si le YOLO n'est pas
    # chargé (env de test sans .pt) — dans les 2 cas c'est explicite.


def test_null_detector_never_crashes():
    """Le _NullDetector doit répondre proprement même sans frame."""
    from pipeline_v2.detector import _NULL_DETECTOR
    assert _NULL_DETECTOR.detect(None) == []
    assert _NULL_DETECTOR.name == "null"


# ═══════════════════════════════════════════════════════════════════════
# Migration hot path
# ═══════════════════════════════════════════════════════════════════════
def test_camera_worker_uses_registry():
    """Le code de _stage_detection doit référencer le registry."""
    src = Path("/app/backend/pipeline_v2/camera_worker.py").read_text()
    assert "from .detector import registry" in src, \
        "camera_worker._stage_detection doit importer le registry"
    assert "_detector_registry.get_active" in src, \
        "camera_worker._stage_detection doit appeler registry.get_active()"


def test_camera_worker_no_direct_predict_call():
    """Le code de _stage_detection ne doit PLUS appeler _model.predict directement.

    Note : d'autres stages (_stage_anpr) continuent d'appeler _alpr.predict
    directement — c'est prévu (Phase B ne migre QUE la détection, l'OCR
    sera migré en Phase B suite).
    """
    src = Path("/app/backend/pipeline_v2/camera_worker.py").read_text()
    # On cible spécifiquement _stage_detection
    start = src.find("def _stage_detection")
    end = src.find("def _stage_tracking")
    assert start > 0 and end > start
    detection_block = src[start:end]
    assert "_ae._model.predict" not in detection_block, \
        "_stage_detection ne doit plus appeler _ae._model.predict directement"
    assert "detector.detect(ctx.image)" in detection_block, \
        "_stage_detection doit appeler detector.detect(ctx.image)"


def test_ctx_metadata_detector_key():
    """Le contexte de frame doit exposer le nom du détecteur pour l'Inspector."""
    src = Path("/app/backend/pipeline_v2/camera_worker.py").read_text()
    assert 'ctx.metadata["detector"]' in src, \
        "_stage_detection doit renseigner ctx.metadata['detector']"


# ═══════════════════════════════════════════════════════════════════════
# Non-régression — le format des détections consommé aval est inchangé
# ═══════════════════════════════════════════════════════════════════════
def test_detection_dict_format_preserved():
    """Le format des dicts dans ctx.detections doit rester le même
    qu'avant la migration (compat avec tracking / plugins downstream)."""
    src = Path("/app/backend/pipeline_v2/camera_worker.py").read_text()
    detection_block = src[src.find("def _stage_detection"):src.find("def _stage_tracking")]
    # Les clés critiques doivent toutes rester présentes.
    for required in ('"class"', '"label"', '"confidence"', '"thumbnail"',
                      '"_crop"', '"vehicle_color"', '"_bbox"'):
        assert required in detection_block, \
            f"Clé {required} manquante dans _stage_detection (compat aval)"
