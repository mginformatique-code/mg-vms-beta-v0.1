"""Tests — Phase A · Pipeline Hardening v0.5.6 (P0).

Couvre les 5 P0 identifiés par l'audit v0.5.5 :

  P0-1 : Race condition YOLO/ALPR — vérifie l'existence des locks globaux
         (``ai_engine.YOLO_INFERENCE_LOCK``, ``ALPR_INFERENCE_LOCK``) et
         qu'ils sont bien acquis avant les appels ``predict``.
  P0-2 : Abstraction Detector — vérifie que ``pipeline_v2.detector``
         expose ``Detector`` (Protocol) et ``YoloDetector`` implémentant
         l'interface, sans dépendre directement d'Ultralytics.
  P0-3 : Tracker fallback — vérifie que ``resolve_algo`` retourne
         désormais un tuple à 3 éléments (requested, effective, warning)
         et surface un warning explicite pour deepsort/ocsort/strongsort.
  P0-4 : Fusion hiérarchique — vérifie normalisation, majorité, tie-break
         par confidence, priorité déclarée, marqueur ambigu.
  P0-5 : Cache plaque — vérifie que le TTL est bien ``max(cache_ttl, 1)``
         (au moins 1 seconde, mais jamais plafonné à 1s).

Ces tests sont volontairement offline (pas d'appel API HTTP) pour rester
rapides et reproductibles ; ils inspectent le code et importent les
modules pour valider les contrats.
"""
import os
import sys
from pathlib import Path

# Charge env pour les modules backend
_env_file = Path("/app/backend/.env")
for line in _env_file.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
sys.path.insert(0, "/app/backend")
os.environ.setdefault("TESTING", "1")


# ═══════════════════════════════════════════════════════════════════════
# P0-1 · Race condition YOLO/ALPR
# ═══════════════════════════════════════════════════════════════════════
def test_p0_1_yolo_inference_lock_exists():
    """`ai_engine.YOLO_INFERENCE_LOCK` doit être un lock threading."""
    import threading
    import ai_engine
    assert hasattr(ai_engine, "YOLO_INFERENCE_LOCK"), \
        "YOLO_INFERENCE_LOCK doit exister (v0.5.6 P0-1)"
    lock_type = type(threading.Lock())
    assert isinstance(ai_engine.YOLO_INFERENCE_LOCK, lock_type), \
        f"Le lock doit être un threading.Lock (trouvé {type(ai_engine.YOLO_INFERENCE_LOCK)})"


def test_p0_1_alpr_inference_lock_exists():
    """`ai_engine.ALPR_INFERENCE_LOCK` doit être un lock threading."""
    import threading
    import ai_engine
    assert hasattr(ai_engine, "ALPR_INFERENCE_LOCK"), \
        "ALPR_INFERENCE_LOCK doit exister (v0.5.6 P0-1)"
    lock_type = type(threading.Lock())
    assert isinstance(ai_engine.ALPR_INFERENCE_LOCK, lock_type)


def test_p0_1_locks_are_used_in_camera_worker():
    """YOLO_INFERENCE_LOCK acquis avant _model.predict, ALPR_INFERENCE_LOCK
    avant _alpr.predict — quel que soit le module où ils vivent (Phase B a
    migré YOLO dans detector.py, Phase B suite a migré ALPR dans
    plate_recognizer.py).
    """
    files = [
        "/app/backend/pipeline_v2/camera_worker.py",
        "/app/backend/pipeline_v2/detector.py",
        "/app/backend/pipeline_v2/plate_recognizer.py",
    ]
    combined = "\n".join(Path(f).read_text() for f in files)
    assert "with _ae.YOLO_INFERENCE_LOCK" in combined, \
        "YOLO_INFERENCE_LOCK doit être acquis autour de _model.predict"
    assert "with _ae.ALPR_INFERENCE_LOCK" in combined, \
        "ALPR_INFERENCE_LOCK doit être acquis autour de _alpr.predict"


# ═══════════════════════════════════════════════════════════════════════
# P0-2 · Abstraction Detector
# ═══════════════════════════════════════════════════════════════════════
def test_p0_2_detector_protocol_defined():
    """L'interface ``Detector`` doit être exposée dans pipeline_v2.detector."""
    from pipeline_v2 import detector
    assert hasattr(detector, "Detector"), "Detector Protocol manquant"
    assert hasattr(detector, "DetectionObject"), "DetectionObject dataclass manquant"
    assert hasattr(detector, "YoloDetector"), "YoloDetector implementation manquante"


def test_p0_2_yolo_detector_implements_protocol():
    """YoloDetector doit satisfaire structurellement le protocole Detector."""
    from pipeline_v2.detector import Detector, YoloDetector
    d = YoloDetector()
    assert d.name == "yolov11"
    assert isinstance(d, Detector)  # runtime_checkable Protocol


def test_p0_2_detection_object_fields():
    """DetectionObject doit avoir les champs sémantiques indépendants du moteur."""
    from pipeline_v2.detector import DetectionObject
    obj = DetectionObject(bbox=(10, 20, 30, 40), label="person", confidence=0.95, class_id=0)
    assert obj.label == "person"
    assert obj.bbox == (10, 20, 30, 40)
    assert obj.track_id is None
    assert isinstance(obj.metadata, dict)


# ═══════════════════════════════════════════════════════════════════════
# P0-3 · Tracker fallback explicite (plus de silence)
# ═══════════════════════════════════════════════════════════════════════
def test_p0_3_resolve_algo_returns_triple():
    """`resolve_algo` doit retourner (requested, effective, warning|None)."""
    from pipeline_v2.tracking import resolve_algo
    r, e, w = resolve_algo([])
    assert r == "bytetrack" and e == "bytetrack" and w is None


def test_p0_3_supported_tracker_no_warning():
    from pipeline_v2.tracking import resolve_algo
    r, e, w = resolve_algo(["botsort"])
    assert r == "botsort" and e == "botsort" and w is None


def test_p0_3_unsupported_tracker_emits_warning():
    """DeepSORT/OCSORT/StrongSORT → fallback bytetrack + warning explicite."""
    from pipeline_v2.tracking import resolve_algo
    for algo in ("deepsort", "ocsort", "strongsort"):
        r, e, w = resolve_algo([algo])
        assert r == algo, f"requested doit être {algo}"
        assert e == "bytetrack", "effective fallback = bytetrack"
        assert w is not None, f"warning doit être présent pour {algo}"
        assert algo in w and "non implémenté" in w.lower(), \
            f"warning doit expliquer clairement le fallback (got: {w})"


# ═══════════════════════════════════════════════════════════════════════
# P0-4 · Fusion hiérarchique
# ═══════════════════════════════════════════════════════════════════════
def test_p0_4_normalize_plate():
    from plugin_manager.fusion import normalize_plate
    assert normalize_plate("AB-123-CD") == "AB123CD"
    assert normalize_plate("  ab 123 cd  ") == "AB123CD"
    assert normalize_plate("") == ""


def test_p0_4_majority_wins_immediately():
    """Étape 2 : si ≥ 2 moteurs proposent la même plaque, elle gagne."""
    from plugin_manager.fusion import (
        MODE_HIERARCHICAL, apply_policy, PlateResult,
    )
    results = [
        ("fast-alpr", [PlateResult(text="AB-123-CD", confidence=0.85, engine="fast-alpr", processing_ms=10)]),
        ("paddle-ocr", [PlateResult(text="AB123CD", confidence=0.90, engine="paddle-ocr", processing_ms=15)]),
        ("openalpr", [PlateResult(text="XY999ZZ", confidence=0.70, engine="openalpr", processing_ms=20)]),
    ]
    fused = apply_policy(MODE_HIERARCHICAL, results)
    assert fused["final"] is not None
    # AB123CD gagne (2 votes) même si "AB-123-CD" a été proposé différemment
    from plugin_manager.fusion import normalize_plate
    assert normalize_plate(fused["final"].text) == "AB123CD"
    assert "majority" in fused["final"].engine


def test_p0_4_priority_used_when_no_consensus():
    """Étape 4 : chaque moteur propose un texte différent → priorité."""
    from plugin_manager.fusion import (
        MODE_HIERARCHICAL, hierarchical_fusion, PlateResult,
    )
    results = [
        ("fast-alpr", [PlateResult(text="AAA111", confidence=0.60, engine="fast-alpr", processing_ms=10)]),
        ("paddle-ocr", [PlateResult(text="BBB222", confidence=0.65, engine="paddle-ocr", processing_ms=15)]),
        ("openalpr", [PlateResult(text="CCC333", confidence=0.70, engine="openalpr", processing_ms=20)]),
    ]
    final, ambiguous = hierarchical_fusion(results, priority_order=["paddle-ocr", "fast-alpr"])
    assert final is not None
    assert final.text == "BBB222"  # paddle-ocr a priorité
    assert "priority:paddle-ocr" in final.engine
    assert ambiguous is False


def test_p0_4_ambiguous_when_no_priority_and_no_majority():
    from plugin_manager.fusion import hierarchical_fusion, PlateResult
    results = [
        ("fast-alpr", [PlateResult(text="AAA111", confidence=0.60, engine="fast-alpr", processing_ms=10)]),
        ("paddle-ocr", [PlateResult(text="BBB222", confidence=0.75, engine="paddle-ocr", processing_ms=15)]),
    ]
    final, ambiguous = hierarchical_fusion(results, priority_order=None)
    assert final is not None
    assert final.text == "BBB222"  # meilleur candidat brut conservé
    assert ambiguous is True
    assert "ambiguous" in final.engine


def test_p0_4_single_engine_no_fusion():
    """Un seul moteur → retourne sa lecture inchangée (pas de tag fusion)."""
    from plugin_manager.fusion import hierarchical_fusion, PlateResult
    results = [
        ("fast-alpr", [PlateResult(text="ABC123", confidence=0.85, engine="fast-alpr", processing_ms=10)]),
    ]
    final, ambiguous = hierarchical_fusion(results)
    assert final is not None
    assert final.text == "ABC123"
    assert ambiguous is False


def test_p0_4_hierarchical_mode_in_apply_policy():
    """apply_policy(MODE_HIERARCHICAL, ...) doit être valide."""
    from plugin_manager.fusion import (
        MODE_HIERARCHICAL, VALID_MODES, apply_policy, PlateResult,
    )
    assert MODE_HIERARCHICAL in VALID_MODES
    results = [
        ("e1", [PlateResult(text="AA111", confidence=0.9, engine="e1", processing_ms=5)]),
        ("e2", [PlateResult(text="AA111", confidence=0.8, engine="e2", processing_ms=8)]),
    ]
    out = apply_policy(MODE_HIERARCHICAL, results)
    assert out["mode"] == MODE_HIERARCHICAL
    assert out["final"] is not None
    assert out["final"].text == "AA111"


# ═══════════════════════════════════════════════════════════════════════
# P0-5 · Cache plaque min→max
# ═══════════════════════════════════════════════════════════════════════
def test_p0_5_plate_cache_uses_max():
    """La ligne 248 devait passer de min() à max() (bug typo v0.5.5)."""
    src = Path("/app/backend/pipeline_v2/camera_worker.py").read_text()
    # Ne doit plus contenir `min(cache_ttl, 1)`
    assert "min(cache_ttl, 1)" not in src, \
        "Le bug v0.5.5 doit être corrigé (min → max)"
    assert "max(cache_ttl, 1)" in src, \
        "Le cache TTL doit utiliser max(cache_ttl, 1) — v0.5.6 P0-5"


# ═══════════════════════════════════════════════════════════════════════
# Vérification globale — timing du pipeline reste ordonné (audit read-only)
# ═══════════════════════════════════════════════════════════════════════
def test_pipeline_ordering_capture_then_detect_then_track_then_roi():
    """Contrôle l'ordre des stages dans CameraWorker.run().

    Le contrat est : Capture → Decode → Detection → Tracking → ROI → Crop
    → OCR → Fusion → Plugins → Workflows → Persistance → Broadcast.
    On repère les positions relatives des appels dans le code source.
    """
    src = Path("/app/backend/pipeline_v2/camera_worker.py").read_text()
    positions = {
        "decode":    src.find("_stage_decode"),
        "motion":    src.find("_stage_motion"),
        "detect":    src.find("_stage_detection"),
        "track":     src.find("_stage_tracking"),
        "roi":       src.find("_stage_roi"),
        "anpr":      src.find("_stage_anpr"),
    }
    # Aucun ne doit être introuvable
    for k, v in positions.items():
        assert v > 0, f"Stage '{k}' introuvable dans camera_worker.py"
    # Ordre attendu: decode < motion < detect < track < roi < anpr
    assert positions["decode"] < positions["motion"] < positions["detect"]
    assert positions["detect"] < positions["track"], \
        "Detection doit précéder Tracking"
    assert positions["track"] < positions["roi"], \
        "Tracking doit précéder ROI build"
    assert positions["roi"] < positions["anpr"], \
        "ROI doit précéder ANPR (le crop est fait dans build_rois)"
