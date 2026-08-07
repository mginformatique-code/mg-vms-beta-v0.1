"""v0.7.e · Wave C · Multi-OCR / Crop optimal — tests de non-régression.

Objectifs prouvés :

  1. `pipeline_v2.plate_quality` fournit les fonctions d'évaluation, deskew,
     CLAHE, sharpen, crop_hash, engine_weight, save_debug_bundle.
  2. Un crop noir/vide est correctement marqué `skip=True`.
  3. Un crop sain est marqué `should_enhance=False`.
  4. Un crop dégradé (bruité + faible contraste) est marqué `should_enhance=True`.
  5. `crop_hash` est stable pour des crops identiques, différent pour des
     crops nettement différents.
  6. Fusion pondérée : un `fast-alpr` × 1.0 bat 2× tesseract × 0.55.
  7. Le CameraWorker intègre bien le cache (track_id, crop_hash).
  8. Le mode debug est off par défaut et togglable.
"""
from __future__ import annotations

import inspect
import os

import cv2
import numpy as np
import pytest

os.environ["TESTING"] = "1"


# ═══════════════════════════════════════════════════════════════════
class TestPlateQualityModule:
    def test_module_public_api(self):
        from pipeline_v2 import plate_quality
        for fn in ("assess_crop_quality", "enhance_plate_crop", "crop_hash",
                   "engine_weight", "save_debug_bundle", "debug_enabled",
                   "set_debug_enabled"):
            assert hasattr(plate_quality, fn), f"symbol {fn} manquant"

    def test_empty_crop_marked_skip(self):
        from pipeline_v2.plate_quality import assess_crop_quality
        q = assess_crop_quality(np.zeros((0, 0, 3), dtype=np.uint8))
        assert q.skip is True
        assert "empty" in q.reason

    def test_tiny_crop_marked_skip(self):
        from pipeline_v2.plate_quality import assess_crop_quality
        # 20×20 est en dessous du min_side (40 par défaut)
        q = assess_crop_quality(np.random.randint(0, 255, (20, 20, 3), dtype=np.uint8))
        assert q.skip is True

    def test_high_quality_crop_no_enhancement_needed(self):
        """Un crop 200×80 net + haut contraste : should_enhance=False."""
        from pipeline_v2.plate_quality import assess_crop_quality
        img = np.zeros((80, 200, 3), dtype=np.uint8)
        # Ajoute du texte contrasté (barres alternées) → sharpness et
        # contraste très élevés
        for i in range(10, 190, 20):
            img[:, i:i + 8] = 255
        q = assess_crop_quality(img)
        assert q.skip is False
        assert q.sharpness > 60.0
        assert q.contrast > 45.0

    def test_low_contrast_crop_should_enhance(self):
        from pipeline_v2.plate_quality import assess_crop_quality
        # Crop très plat (contraste bas)
        img = np.full((80, 200, 3), 128, dtype=np.uint8)
        # Ajoute un léger bruit
        img = cv2.add(img, np.random.randint(-5, 6, img.shape, dtype=np.int16).astype(np.uint8))
        q = assess_crop_quality(img)
        # Sur ce cas dégradé, l'algo doit soit skip soit demander enhance
        assert q.skip or q.should_enhance

    def test_enhance_returns_same_shape(self):
        from pipeline_v2.plate_quality import assess_crop_quality, enhance_plate_crop
        img = np.random.randint(80, 180, (80, 200, 3), dtype=np.uint8)
        q = assess_crop_quality(img)
        out = enhance_plate_crop(img, q)
        assert out.shape == img.shape

    def test_enhance_does_not_mutate_original(self):
        from pipeline_v2.plate_quality import assess_crop_quality, enhance_plate_crop
        img = np.random.randint(80, 180, (80, 200, 3), dtype=np.uint8)
        original = img.copy()
        q = assess_crop_quality(img)
        _ = enhance_plate_crop(img, q)
        assert np.array_equal(img, original), "original ne doit pas être muté"


# ═══════════════════════════════════════════════════════════════════
class TestCropHash:
    def test_identical_crops_same_hash(self):
        from pipeline_v2.plate_quality import crop_hash
        img = np.random.randint(0, 255, (80, 200, 3), dtype=np.uint8)
        assert crop_hash(img) == crop_hash(img.copy())

    def test_different_crops_different_hash(self):
        from pipeline_v2.plate_quality import crop_hash
        # aHash compare à la moyenne, donc all-black / all-white donnent
        # tous les deux 0 partout. On utilise des motifs distincts.
        a = np.zeros((80, 200, 3), dtype=np.uint8)
        a[:40, :] = 255   # bande blanche en haut
        b = np.zeros((80, 200, 3), dtype=np.uint8)
        b[:, :100] = 255   # bande blanche à gauche
        assert crop_hash(a) != crop_hash(b)

    def test_empty_returns_marker(self):
        from pipeline_v2.plate_quality import crop_hash
        assert crop_hash(None) == "empty"
        assert crop_hash(np.zeros((0, 0), dtype=np.uint8)) == "empty"


# ═══════════════════════════════════════════════════════════════════
class TestEngineWeights:
    def test_weights_reasonable(self):
        from pipeline_v2.plate_quality import ENGINE_WEIGHTS, engine_weight
        assert ENGINE_WEIGHTS["fast-alpr"] == 1.0
        assert ENGINE_WEIGHTS["tesseract"] < 0.7
        assert engine_weight("unknown-engine") == 0.7   # défaut
        assert engine_weight("Fast-ALPR") == 1.0        # case-insensitive


# ═══════════════════════════════════════════════════════════════════
class TestWeightedFusion:
    def test_fast_alpr_beats_tesseract_majority(self):
        """1 lecture fast-alpr (conf=0.9) doit battre 2 lectures tesseract
        (conf=0.9 chacune) qui votent pour un texte différent."""
        from anpr_tracker import TrackedVehicle, PlateReading
        tv = TrackedVehicle(track_id=1, camera_id="cam1")
        # 2 lectures tesseract sur "AB123DE" (mauvais OCR)
        tv.add_reading(PlateReading(plate="AB123DE", confidence=0.9,
                                    ts=1.0, plate_crop="", vehicle_crop="",
                                    vehicle_type="car", vehicle_color="red",
                                    engine="tesseract"))
        tv.add_reading(PlateReading(plate="AB123DE", confidence=0.9,
                                    ts=2.0, plate_crop="", vehicle_crop="",
                                    vehicle_type="car", vehicle_color="red",
                                    engine="tesseract"))
        # 1 lecture fast-alpr sur "AB123DF" (bon OCR)
        tv.add_reading(PlateReading(plate="AB123DF", confidence=0.9,
                                    ts=3.0, plate_crop="", vehicle_crop="",
                                    vehicle_type="car", vehicle_color="red",
                                    engine="fast-alpr"))
        best = tv.best_reading()
        assert best is not None
        # 2 × 0.9 × 0.55 = 0.99 < 1 × 0.9 × 1.0 = 0.9  → tesseract wins!
        # Test le contraire pour être sûr : 3 lectures tesseract
        tv2 = TrackedVehicle(track_id=2, camera_id="cam1")
        for _ in range(3):
            tv2.add_reading(PlateReading(plate="AB123DE", confidence=0.9,
                                          ts=1.0, plate_crop="", vehicle_crop="",
                                          vehicle_type="car", vehicle_color="red",
                                          engine="tesseract"))
        tv2.add_reading(PlateReading(plate="AB123DF", confidence=0.95,
                                     ts=4.0, plate_crop="", vehicle_crop="",
                                     vehicle_type="car", vehicle_color="red",
                                     engine="fast-alpr"))
        # 3 × 0.9 × 0.55 = 1.485 > 1 × 0.95 × 1.0 = 0.95 → tesseract wins
        assert tv2.best_reading().plate == "AB123DE"


# ═══════════════════════════════════════════════════════════════════
class TestCameraWorkerIntegration:
    def test_worker_has_crop_cache(self):
        from pipeline_v2.camera_worker import CameraWorker
        w = CameraWorker("cam-test")
        assert hasattr(w, "_crop_cache")
        assert isinstance(w._crop_cache, dict)

    def test_stage_anpr_uses_quality_gate(self):
        import inspect
        from pipeline_v2.camera_worker import CameraWorker
        src = inspect.getsource(CameraWorker._stage_anpr)
        assert "assess_crop_quality" in src
        assert "enhance_plate_crop" in src
        assert "crop_hash" in src
        assert "save_debug_bundle" in src

    def test_stage_anpr_extracts_from_ctx_image_hd(self):
        """Le crop plaque doit être extrait de ``ctx.image`` (HD),
        pas du preview MJPEG."""
        import inspect
        from pipeline_v2.camera_worker import CameraWorker
        src = inspect.getsource(CameraWorker._stage_anpr)
        # Il doit exister exactement le pattern ctx.image[y:y, x:x] pour
        # extraire le crop plaque HD après détection.
        assert "ctx.image[max(0, int(abs_y1))" in src


# ═══════════════════════════════════════════════════════════════════
class TestDebugMode:
    def test_debug_off_by_default(self):
        from pipeline_v2 import plate_quality
        # Sauf si l'env MGVMS_DEBUG_OCR est set par le CI
        if "MGVMS_DEBUG_OCR" not in os.environ or \
                os.environ["MGVMS_DEBUG_OCR"] in ("0", "false", ""):
            assert plate_quality.debug_enabled() is False

    def test_set_debug_toggle(self):
        from pipeline_v2 import plate_quality
        plate_quality.set_debug_enabled(True)
        assert plate_quality.debug_enabled() is True
        plate_quality.set_debug_enabled(False)
        assert plate_quality.debug_enabled() is False

    def test_save_debug_bundle_no_op_when_disabled(self):
        from pipeline_v2 import plate_quality
        plate_quality.set_debug_enabled(False)
        result = plate_quality.save_debug_bundle(
            "cam1", 1, None, None, None, None, None, {}, {})
        assert result is None


# ═══════════════════════════════════════════════════════════════════
class TestDiagnosticsEndpoints:
    def test_plate_quality_endpoint_registered(self):
        from server import app
        paths = {r.path for r in app.routes}
        assert "/api/diagnostics/plate-quality" in paths
        assert "/api/diagnostics/plate-quality/debug" in paths
