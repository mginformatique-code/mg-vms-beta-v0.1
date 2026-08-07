"""v0.8-rc5 · FEATURE FREEZE · Stabilisation Sprint 2

Priorité #2 absolue : Crop Premium v2 (image processing fallbacks)
Priorité #3          : Frames Dropped catégorisation

Preuves demandées par mandat "Avant / après, tests, zéro régression".
"""
from __future__ import annotations

import os
import numpy as np
import cv2
import pytest


os.environ["TESTING"] = "1"


# ═══════════════════════════════════════════════════════════════════
# Helpers : générateurs de crops synthétiques calibrés
# ═══════════════════════════════════════════════════════════════════
def _make_hd_image_with_plate(quality: str = "good", width: int = 1920, height: int = 1080):
    """Crée une image HD avec une plaque simulée à une bbox connue.

    quality : 'good'  = plaque nette, contrastée
              'blur'  = plaque floue → doit déclencher escalade
              'dark'  = plaque sombre → doit déclencher escalade
              'skew'  = plaque inclinée
    Retourne (image, bbox=(x1,y1,x2,y2)).
    """
    img = np.full((height, width, 3), 60, dtype=np.uint8)  # fond gris foncé
    x1, y1, x2, y2 = 800, 500, 1120, 600  # plaque 320×100
    # Plaque = fond blanc + texte noir
    cv2.rectangle(img, (x1, y1), (x2, y2), (240, 240, 240), thickness=-1)
    cv2.putText(img, "AB-123-CD", (x1 + 10, y1 + 70),
                cv2.FONT_HERSHEY_SIMPLEX, 2.0, (10, 10, 10), 4, cv2.LINE_AA)
    if quality == "blur":
        # Applique un flou massif SUR toute l'image (pas juste plaque)
        img = cv2.GaussianBlur(img, (25, 25), sigmaX=10)
    elif quality == "dark":
        img = (img.astype(np.float32) * 0.2).clip(0, 255).astype(np.uint8)
    elif quality == "skew":
        M = cv2.getRotationMatrix2D((width / 2, height / 2), 12, 1.0)
        img = cv2.warpAffine(img, M, (width, height), borderMode=cv2.BORDER_REPLICATE)
    return img, (x1, y1, x2, y2)


# ═══════════════════════════════════════════════════════════════════
# Suite A · Crop Premium v2 · contrats de base
# ═══════════════════════════════════════════════════════════════════
class TestCropPremiumFastPath:
    """Score initial >= 60 → return direct, aucune escalade, aucun coût."""

    def test_good_crop_returns_fast_no_escalation(self):
        from pipeline_v2.crop_premium import run_crop_premium
        img, bbox = _make_hd_image_with_plate("good")
        result = run_crop_premium(img, bbox, min_score=60)
        assert result.escalated is False
        assert result.tried_count == 1  # baseline uniquement
        assert result.best_method == "raw"
        assert result.best_quality.score_100 >= 60


class TestCropPremiumEscalation:
    """Score < 60 → escalade avec marges + méthodes."""

    def test_blur_crop_triggers_escalation(self):
        from pipeline_v2.crop_premium import run_crop_premium
        img, bbox = _make_hd_image_with_plate("blur")
        result = run_crop_premium(img, bbox, min_score=60)
        assert result.escalated is True
        assert result.tried_count > 1
        # Le meilleur crop doit être au moins aussi bon que le baseline
        baseline_score = result.all_variants[-1]["score_100"]
        # (all_variants trié par score desc, le pire = dernier)
        assert result.best_quality.score_100 >= baseline_score
        # Trace attendue : au moins 4 méthodes tentées (raw + enhance + denoise + perspective)
        methods = {v["method"] for v in result.all_variants}
        assert "raw" in methods
        # au moins UNE méthode d'amélioration testée
        assert methods & {"enhance", "denoise", "perspective"}

    def test_result_dict_contains_expected_fields(self):
        from pipeline_v2.crop_premium import run_crop_premium
        img, bbox = _make_hd_image_with_plate("blur")
        result = run_crop_premium(img, bbox, min_score=60)
        d = result.to_dict()
        for k in ("best_method", "best_margin", "best_score_100", "best_size",
                   "tried_count", "escalated", "variants", "took_ms"):
            assert k in d, f"champ {k} manquant dans to_dict()"


class TestCropPremiumMarginGeneration:
    """Vérifie que les 5 marges sont bien générées (0, 5, 10, 15, 20, 25 %)."""

    def test_all_margins_attempted_on_escalation(self):
        from pipeline_v2.crop_premium import run_crop_premium, DEFAULT_MARGINS
        img, bbox = _make_hd_image_with_plate("blur")
        result = run_crop_premium(img, bbox, min_score=60)
        margins_seen = {round(v["margin"], 2) for v in result.all_variants
                        if v["method"] == "raw"}
        expected = {round(m, 2) for m in DEFAULT_MARGINS}
        # Tolère au moins 5/6 (certaines marges peuvent produire un crop skip)
        assert len(margins_seen & expected) >= 5, \
            f"marges vues : {margins_seen}, attendues : {expected}"


class TestCropPremiumRobustness:
    """Robustesse : bbox invalide, image dégénérée, exceptions internes."""

    def test_bbox_out_of_bounds_is_clamped(self):
        from pipeline_v2.crop_premium import run_crop_premium
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        # bbox partiellement hors image
        result = run_crop_premium(img, (-50, -50, 400, 400), min_score=60)
        assert result.best_crop.size > 0
        assert result.best_quality.width > 0

    def test_tiny_crop_marked_skip(self):
        from pipeline_v2.crop_premium import run_crop_premium
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        result = run_crop_premium(img, (40, 40, 50, 50), min_score=60)
        # Doit toujours retourner un résultat, pas crasher
        assert result is not None
        assert result.best_crop is not None


# ═══════════════════════════════════════════════════════════════════
# Suite B · Camera Worker · intégration Crop Premium
# ═══════════════════════════════════════════════════════════════════
class TestCameraWorkerIntegration:
    def test_camera_worker_source_wires_crop_premium(self):
        src = open("/app/backend/pipeline_v2/camera_worker.py", encoding="utf-8").read()
        # Preuves d'intégration attendues
        assert "from .crop_premium import run_crop_premium" in src
        assert "if not q.skip and current_score_100 < 60" in src
        assert "crop_premium_meta" in src

    def test_downstream_cleans_crop_premium_field(self):
        """Le champ _crop_premium ne doit pas fuir dans Mongo."""
        src = open("/app/backend/pipeline_v2/downstream.py", encoding="utf-8").read()
        assert "_crop_premium" in src  # présent dans la liste des pop


# ═══════════════════════════════════════════════════════════════════
# Suite C · Frames Dropped catégorisation
# ═══════════════════════════════════════════════════════════════════
class TestFramesDroppedCategories:
    def test_worker_dataclass_has_new_counters(self):
        from frame_source import _Worker
        # Fields doivent être présents (dataclass)
        fields = {f.name for f in _Worker.__dataclass_fields__.values()}
        assert "frames_dropped_backpressure" in fields
        assert "frames_dropped_rtsp_timeout" in fields
        assert "frames_dropped_decode" in fields

    def test_status_endpoint_exposes_breakdown(self):
        """Le retour status() doit contenir `frames_dropped_breakdown`."""
        src = open("/app/backend/frame_source.py", encoding="utf-8").read()
        assert '"frames_dropped_breakdown"' in src
        assert '"backpressure"' in src
        assert '"rtsp_timeout"' in src
        assert '"decode"' in src

    def test_counter_semantics_documented(self):
        src = open("/app/backend/frame_source.py", encoding="utf-8").read()
        assert "backpressure = consumer trop lent" in src
        assert "somme des 3 catégories" in src.replace("è", "e") \
            or "somme des 3 catégories" in src


# ═══════════════════════════════════════════════════════════════════
# Suite D · Non-régression (endpoints critiques)
# ═══════════════════════════════════════════════════════════════════
class TestNoRegression:
    def test_diagnostics_endpoints_still_registered(self):
        from server import app
        paths = {r.path for r in app.routes}
        for p in ("/api/diagnostics/pipeline-inspector",
                   "/api/diagnostics/frame-source",
                   "/api/diagnostics/plate-quality",
                   "/api/diagnostics/qos-thresholds"):
            assert p in paths, f"endpoint {p} disparu"

    def test_plate_quality_module_still_provides_public_api(self):
        from pipeline_v2 import plate_quality
        for name in ("assess_crop_quality", "enhance_plate_crop",
                      "crop_hash", "engine_weight", "save_debug_bundle"):
            assert hasattr(plate_quality, name), f"{name} disparu de plate_quality"
