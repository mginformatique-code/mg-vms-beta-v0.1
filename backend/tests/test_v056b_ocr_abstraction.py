"""Tests — Phase B suite · Abstraction PlateRecognizer (OCR core).

Vérifie que la migration hot-path fast-alpr → PlateRecognizer abstraction
est opérationnelle :

  1. `plate_registry` contient au moins ``fast-alpr`` (register auto).
  2. Un OCR alternatif peut être enregistré via
     ``plate_registry.register("mock-ocr", MockRecognizer)``.
  3. ``plate_registry.get_active()`` retourne (PlateRecognizer, str, warning|None).
  4. Le hot path `_stage_anpr` utilise le registry (imports + appel).
  5. Le pipeline n'appelle plus `_alpr.predict` directement dans
     `_stage_anpr` (le lock ALPR est acquis dans le recognizer).
  6. Format `ctx.plates` inchangé (compat aval downstream).
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
def test_plate_registry_has_fastalpr_by_default():
    from pipeline_v2.plate_recognizer import plate_registry
    assert "fast-alpr" in plate_registry.known()


def test_plate_registry_get_returns_singleton():
    from pipeline_v2.plate_recognizer import plate_registry
    r1 = plate_registry.get("fast-alpr")
    r2 = plate_registry.get("fast-alpr")
    assert r1 is r2


def test_plate_registry_get_unknown_returns_none():
    from pipeline_v2.plate_recognizer import plate_registry
    assert plate_registry.get("unknown-ocr") is None


def test_plate_registry_can_register_third_party_ocr():
    from pipeline_v2.plate_recognizer import (
        PlateRecognizer, PlateOcrResult, plate_registry,
    )

    class MockOcr:
        name = "mock-ocr"
        def recognize(self, vehicle_crop_bgr):
            return [PlateOcrResult(
                text="AB123CD", confidence=0.87,
                bbox_in_roi=(10, 20, 60, 40),
            )]

    plate_registry.register("mock-ocr", MockOcr)
    inst = plate_registry.get("mock-ocr")
    assert inst is not None
    assert isinstance(inst, PlateRecognizer)
    out = inst.recognize(None)
    assert len(out) == 1 and out[0].text == "AB123CD"


def test_plate_registry_get_active_returns_triple():
    from pipeline_v2.plate_recognizer import plate_registry
    rec, name, warning = plate_registry.get_active(None)
    assert rec is not None
    assert name == "fast-alpr"


def test_null_plate_recognizer_never_crashes():
    from pipeline_v2.plate_recognizer import _NULL_PLATE_RECOGNIZER
    assert _NULL_PLATE_RECOGNIZER.recognize(None) == []
    assert _NULL_PLATE_RECOGNIZER.name == "null"


# ═══════════════════════════════════════════════════════════════════════
# Hot path migration
# ═══════════════════════════════════════════════════════════════════════
def test_camera_worker_uses_plate_registry():
    src = Path("/app/backend/pipeline_v2/camera_worker.py").read_text()
    assert "from .plate_recognizer import plate_registry" in src, \
        "camera_worker doit importer plate_registry"
    assert "_plate_registry.get_active" in src, \
        "camera_worker doit appeler plate_registry.get_active()"


def test_camera_worker_no_direct_alpr_predict_call():
    """_stage_anpr ne doit PLUS appeler _ae._alpr.predict directement."""
    src = Path("/app/backend/pipeline_v2/camera_worker.py").read_text()
    start = src.find("def _stage_anpr")
    # Cherche la fin — début du stage suivant OU fin de la classe
    end = src.find("def _write_debug", start)
    if end < 0:
        end = len(src)
    anpr_block = src[start:end]
    assert "_ae._alpr.predict" not in anpr_block, \
        "_stage_anpr ne doit plus appeler _ae._alpr.predict directement"
    assert "_ocr.recognize(roi.crop)" in anpr_block, \
        "_stage_anpr doit appeler _ocr.recognize(roi.crop)"


def test_ctx_metadata_ocr_core_key():
    src = Path("/app/backend/pipeline_v2/camera_worker.py").read_text()
    assert 'ctx.metadata["ocr_core"]' in src, \
        "_stage_anpr doit renseigner ctx.metadata['ocr_core']"


def test_plates_dict_format_preserved():
    """Le format des dicts dans ctx.plates doit rester le même qu'avant."""
    src = Path("/app/backend/pipeline_v2/camera_worker.py").read_text()
    anpr_block = src[src.find("def _stage_anpr"):src.find("def _write_debug", src.find("def _stage_anpr"))]
    for required in ('"plate"', '"confidence"', '"plate_crop"', '"vehicle_crop"',
                      '"vehicle_type"', '"vehicle_color"', '"engine"',
                      '"track_id"', '"_owner_bbox"'):
        assert required in anpr_block, \
            f"Clé {required} manquante dans _stage_anpr (compat aval)"


# ═══════════════════════════════════════════════════════════════════════
# FastAlprRecognizer
# ═══════════════════════════════════════════════════════════════════════
def test_fastalpr_recognizer_returns_empty_without_alpr():
    """Sans _alpr chargé, recognize retourne [] sans crasher."""
    from pipeline_v2.plate_recognizer import FastAlprRecognizer
    import ai_engine as _ae
    saved = _ae._alpr
    _ae._alpr = None
    try:
        rec = FastAlprRecognizer()
        assert rec.recognize(None) == []
        assert rec.name == "fast-alpr"
    finally:
        _ae._alpr = saved


def test_plate_ocr_result_fields():
    from pipeline_v2.plate_recognizer import PlateOcrResult
    r = PlateOcrResult(text="ABC-123", confidence=0.9, bbox_in_roi=(1, 2, 3, 4))
    assert r.text == "ABC-123"
    assert r.confidence == 0.9
    assert r.bbox_in_roi == (1, 2, 3, 4)
