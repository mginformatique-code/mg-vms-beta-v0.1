"""iter27 — Bug fix : Live SD/HD toggle réel + miniatures d'événements HD.

Bugs utilisateur (2026-07):
1. Le bouton SD/HD du Live n'avait aucun effet — la prévisualisation restait toujours
   sur le sous-flux 640x480. Cause : `_mjpeg_stream()` retournait toujours `{name}_sd`.
   Fix : nouvelle variante `{name}_hd` (MJPEG résolution native), et l'endpoint
   `/api/stream/{id}/live.mjpeg` accepte désormais `?hd=1`.
2. Les miniatures des événements étaient trop faibles (360px @ q60) pour identifier
   personnes/plaques/objets. Fix : `_jpeg_data_uri` passe à 1280 max_width @ q85, et
   les événements YOLO stockent la scène complète HD comme `thumbnail` (le crop
   du bbox reste disponible sous `crop_thumbnail`).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch


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

import streaming as S  # noqa: E402
import ai_engine as AI  # noqa: E402


class TestMjpegStreamSelector:
    """Le sélecteur MJPEG doit distinguer HD (native) et SD (640)."""

    def test_sd_default(self):
        assert S._mjpeg_stream("cam-x") == "cam_cam-x_sd"

    def test_sd_explicit(self):
        assert S._mjpeg_stream("cam-x", hd=False) == "cam_cam-x_sd"

    def test_hd_variant(self):
        # Résolution native — nom différent de la variante SD.
        assert S._mjpeg_stream("cam-x", hd=True) == "cam_cam-x_hd"


class TestJpegDataUri:
    """La miniature par défaut doit être HD (>= 960 wide) et qualité >= 80."""

    def _make_bgr(self, w, h):
        import numpy as np
        # Image factice (blanche pour reproductibilité)
        return np.full((h, w, 3), 255, dtype="uint8")

    def test_default_wide_hd(self):
        # Image 1920x1080 doit être compressée à max 1280 wide (default).
        img = self._make_bgr(1920, 1080)
        data_uri = AI._jpeg_data_uri(img)
        assert data_uri is not None
        assert data_uri.startswith("data:image/jpeg;base64,")
        # Décode et vérifie la résolution
        import base64
        import io
        from PIL import Image
        b = base64.b64decode(data_uri.split(",", 1)[1])
        decoded = Image.open(io.BytesIO(b))
        assert decoded.size[0] == 1280, f"largeur = {decoded.size[0]} (attendu 1280)"
        assert decoded.size[1] == 720

    def test_no_upscale(self):
        # Image plus petite que max_width : ne doit PAS être agrandie.
        img = self._make_bgr(320, 240)
        data_uri = AI._jpeg_data_uri(img)
        import base64
        import io
        from PIL import Image
        b = base64.b64decode(data_uri.split(",", 1)[1])
        decoded = Image.open(io.BytesIO(b))
        assert decoded.size == (320, 240), "Le upscale est interdit"

    def test_custom_max_width_for_plate_crops(self):
        img = self._make_bgr(1200, 300)
        data_uri = AI._jpeg_data_uri(img, max_width=240)
        import base64
        import io
        from PIL import Image
        b = base64.b64decode(data_uri.split(",", 1)[1])
        decoded = Image.open(io.BytesIO(b))
        assert decoded.size[0] == 240

    def test_returns_none_on_empty(self):
        import numpy as np
        assert AI._jpeg_data_uri(np.zeros((0, 0, 3), dtype="uint8")) is None
        assert AI._jpeg_data_uri(None) is None


class TestLiveMjpegEndpointRoutingHD:
    """Sanity : `_quality_stream` et `_mjpeg_stream` retournent des noms distincts.

    Note : le test réel de l'endpoint (bytes reçus 1280x720 en HD, 640x360 en SD)
    est effectué par le testing_agent via curl (voir iteration_27 report).
    """

    def test_names_distinct(self):
        sd = S._mjpeg_stream("abc", hd=False)
        hd = S._mjpeg_stream("abc", hd=True)
        assert sd != hd
        assert sd.endswith("_sd")
        assert hd.endswith("_hd")
