"""iter28 — Perf fix : encodage lazy de frame_thumb (régression ANPR).

Bug utilisateur (2026-07): "Le dernier push est beaucoup plus lent, moins réactif"
sur l'ANPR. Cause racine : depuis v2.13.0, `_jpeg_data_uri` compressait par défaut
à 1280 wide @ q85 (au lieu de 360 @ q60), et `_analyze_frame` encodait
systématiquement `frame_thumb` à chaque cycle IA — même si aucun événement n'était
créé. Sur cams 2K en parallèle, gain d'encodage ~30-80 ms/cycle en vain.

Fix : `_analyze_frame` retourne l'image numpy (`_img_bgr`) au lieu de la base64.
Un helper `_ensure_frame_thumb(result)` encode à la demande, avec mémoïsation :
- 0 event ce cycle → 0 encodage HD (économie ~30-80 ms/cycle)
- N events ce cycle → 1 seul encodage (mémoïsé dans `result["frame_thumb"]`)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock


def _read_env(path, key):
    try:
        with open(path) as f:
            for ln in f:
                if ln.startswith(key + "="):
                    return ln.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return None


ENV_PATH = str(Path(__file__).parent.parent / ".env")
for _key in ("MONGO_URL", "DB_NAME", "JWT_SECRET"):
    if not os.environ.get(_key):
        val = _read_env(ENV_PATH, _key)
        if val:
            os.environ[_key] = val

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_engine as AI  # noqa: E402


class TestLazyFrameThumbEncoding:
    """Le champ `frame_thumb` ne doit exister que si `_ensure_frame_thumb` est appelé."""

    def _make_img(self, w=1280, h=720):
        import numpy as np
        return np.full((h, w, 3), 128, dtype="uint8")

    def test_result_without_encoding_has_no_thumb(self):
        """Sans appel à `_ensure_frame_thumb`, `frame_thumb` doit être absent —
        le coût CPU d'encodage n'est PAS payé sur les cycles sans événement."""
        result = {"_img_bgr": self._make_img(), "detections": []}
        assert "frame_thumb" not in result

    def test_ensure_encodes_on_demand(self):
        result = {"_img_bgr": self._make_img(), "detections": []}
        thumb = AI._ensure_frame_thumb(result)
        assert thumb is not None
        assert thumb.startswith("data:image/jpeg;base64,")
        assert "frame_thumb" in result

    def test_ensure_is_memoized_single_encoding(self):
        """Appels multiples dans le même cycle → 1 seul encodage."""
        result = {"_img_bgr": self._make_img(), "detections": []}
        thumb1 = AI._ensure_frame_thumb(result)
        # Simule que quelqu'un a modifié _img_bgr après le 1er encode
        result["_img_bgr"] = self._make_img(w=100, h=100)  # image très différente
        thumb2 = AI._ensure_frame_thumb(result)
        # Doit renvoyer la même chose (mémoïsation) — pas re-encodée
        assert thumb1 == thumb2

    def test_ensure_returns_none_when_no_image(self):
        result = {"_img_bgr": None, "detections": []}
        assert AI._ensure_frame_thumb(result) is None

    def test_ensure_returns_hd_resolution(self):
        """Le rendu HD reste 1280 wide q85 (comportement v2.13.0 conservé)."""
        import base64
        import io
        from PIL import Image
        result = {"_img_bgr": self._make_img(1920, 1080), "detections": []}
        thumb = AI._ensure_frame_thumb(result)
        raw = base64.b64decode(thumb.split(",", 1)[1])
        img = Image.open(io.BytesIO(raw))
        assert img.size[0] == 1280
        assert img.size[1] == 720


class TestEvaluateScenariosLazy:
    """`_evaluate_scenarios` NE DOIT PAS encoder de miniature quand aucun scénario ne
    se déclenche (régression ANPR — sinon le fix lazy est neutralisé).
    """

    def test_no_encoding_when_no_detections(self, monkeypatch):
        """0 détection → 0 encodage HD (le cas le plus fréquent en pratique)."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        import numpy as np

        # Rules avec tous scénarios activés — pour vérifier qu'ils sont bien évalués
        # mais qu'aucun ne se déclenche faute de détection.
        rules = {
            "intrusion_nocturne": {"enabled": True, "night_start": 22, "night_end": 6, "webhook": ""},
            "vol_vehicule": {"enabled": True, "night_start": 22, "night_end": 6, "webhook": ""},
            "rodeur": {"enabled": True, "consecutive": 5, "webhook": ""},
            "attroupement": {"enabled": True, "min_persons": 5, "webhook": ""},
            "vive_allure": {"enabled": True, "motion_pct": 90.0, "webhook": ""},
            "collision": {"enabled": True, "iou": 0.5, "webhook": ""},
            "enfant_route": {"enabled": True, "ratio": 0.5, "webhook": ""},
        }
        monkeypatch.setattr(AI, "_get_scenario_rules", AsyncMock(return_value=rules))
        monkeypatch.setattr(AI, "_raise_scenario_alert", AsyncMock())
        monkeypatch.setattr(AI, "_is_night", MagicMock(return_value=False))  # pas la nuit

        # Instrumente `_ensure_frame_thumb` — doit être appelé 0 fois si pas d'alerte.
        original_ensure = AI._ensure_frame_thumb
        call_count = {"n": 0}
        def spy(res):
            call_count["n"] += 1
            return original_ensure(res)
        monkeypatch.setattr(AI, "_ensure_frame_thumb", spy)

        result = {
            "_img_bgr": np.full((720, 1280, 3), 128, dtype="uint8"),
            "detections": [],  # aucune détection
            "motion_pct": 0.0,
        }
        cam = {"id": "test-cam-1", "name": "Test", "site_id": "", "site_name": ""}
        from datetime import datetime
        asyncio.get_event_loop().run_until_complete(
            AI._evaluate_scenarios(cam, result, datetime.now())
        )
        assert call_count["n"] == 0, f"_ensure_frame_thumb appelé {call_count['n']}× sans détection → régression ANPR persiste"

    def test_encoding_only_when_scenario_triggers(self, monkeypatch):
        """1 attroupement déclenché → 1 seul encodage (mémoïsé)."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        import numpy as np
        rules = {
            "intrusion_nocturne": {"enabled": False, "night_start": 22, "night_end": 6, "webhook": ""},
            "vol_vehicule": {"enabled": False, "night_start": 22, "night_end": 6, "webhook": ""},
            "rodeur": {"enabled": False, "consecutive": 5, "webhook": ""},
            "attroupement": {"enabled": True, "min_persons": 2, "webhook": ""},  # seul activé
            "vive_allure": {"enabled": False, "motion_pct": 90.0, "webhook": ""},
            "collision": {"enabled": False, "iou": 0.5, "webhook": ""},
            "enfant_route": {"enabled": False, "ratio": 0.5, "webhook": ""},
        }
        monkeypatch.setattr(AI, "_get_scenario_rules", AsyncMock(return_value=rules))
        monkeypatch.setattr(AI, "_raise_scenario_alert", AsyncMock())
        monkeypatch.setattr(AI, "_is_night", MagicMock(return_value=False))

        original_ensure = AI._ensure_frame_thumb
        call_count = {"n": 0}
        def spy(res):
            call_count["n"] += 1
            return original_ensure(res)
        monkeypatch.setattr(AI, "_ensure_frame_thumb", spy)

        result = {
            "_img_bgr": np.full((720, 1280, 3), 128, dtype="uint8"),
            "detections": [
                {"class": "person", "_bbox": [10, 10, 100, 200]},
                {"class": "person", "_bbox": [110, 10, 200, 200]},
            ],
            "motion_pct": 0.0,
        }
        cam = {"id": "test-cam-2", "name": "Test2", "site_id": "", "site_name": ""}
        from datetime import datetime
        asyncio.get_event_loop().run_until_complete(
            AI._evaluate_scenarios(cam, result, datetime.now())
        )
        # 1 seul scénario matche → 1 appel à thumb() → 1 encodage
        assert call_count["n"] == 1, f"Expected 1 lazy encoding, got {call_count['n']}"
