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
