"""iter26 — Sélection ONVIF main/sub respectée : aucune substitution de variante.

Bug utilisateur (2026-07): le profil ONVIF choisi (main/sub) n'était pas persisté.
Le POST /cameras générait des variantes RTSP (main+sub) et gardait la première
qui répondait — potentiellement le sub. Fix : `_ffprobe_validate_exact` valide
uniquement l'URL exacte du profil, fallback TCP↔UDP mais AUCUN changement d'URL.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

# Charge les variables d'environnement du backend AVANT tout import du module streaming
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


class TestExactValidation:
    """Valide que `_ffprobe_validate_exact` ne modifie JAMAIS l'URL de base."""

    def test_returns_exact_url_on_success(self):
        base = "rtsp://192.0.2.10:554/h264Preview_02_main"
        fake_details = {"resolution": "2304x1296", "fps": 20,
                         "codec": "H264", "bitrate": 4096000, "transport": "tcp"}
        with patch.object(S, "_ffprobe", return_value=dict(fake_details)):
            url, details, attempts = S._ffprobe_validate_exact(base, "tcp", "u", "p")
        assert url == base, "L'URL retournée doit être EXACTEMENT celle passée"
        assert details is not None
        assert details["rtsp_url_used"] == base
        assert details["transport_used"] == "tcp"
        assert len(attempts) == 1
        assert attempts[0]["ok"] is True

    def test_falls_back_to_udp_but_keeps_url(self):
        base = "rtsp://192.0.2.10:554/h264Preview_02_main"

        def fake_ffprobe(url, transport):
            # Échoue en TCP, réussit en UDP
            if transport == "tcp":
                return None
            return {"resolution": "2304x1296", "fps": 20, "codec": "H264",
                    "bitrate": 4096000, "transport": "udp"}
        with patch.object(S, "_ffprobe", side_effect=fake_ffprobe):
            url, details, attempts = S._ffprobe_validate_exact(base, "tcp", "u", "p")
        assert url == base
        assert details is not None
        assert details["transport_used"] == "udp"
        assert len(attempts) == 2
        assert attempts[0]["ok"] is False and attempts[1]["ok"] is True

    def test_never_substitutes_main_with_sub(self):
        """Même si sub répondait, l'URL retournée reste celle passée (main)."""
        base = "rtsp://192.0.2.10:554/h264Preview_02_main"
        # Simule : ffprobe réussit (mais peu importe l'URL — _ffprobe_validate_exact
        # ne teste QUE l'URL passée, pas de variantes)
        with patch.object(S, "_ffprobe",
                          return_value={"resolution": "640x360", "fps": 15,
                                        "codec": "H264", "bitrate": 500000,
                                        "transport": "tcp"}):
            url, details, _ = S._ffprobe_validate_exact(base, "tcp", "u", "p")
        # L'URL doit rester la base — jamais remplacée par h264Preview_01_sub etc.
        assert url == base
        assert "sub" not in url
        assert details["rtsp_url_used"] == base

    def test_returns_none_details_when_both_transports_fail(self):
        base = "rtsp://192.0.2.10:554/h264Preview_02_main"
        with patch.object(S, "_ffprobe", return_value=None):
            url, details, attempts = S._ffprobe_validate_exact(base, "tcp", "u", "p")
        assert url == base  # URL toujours retournée telle quelle
        assert details is None
        assert len(attempts) == 2  # tcp + udp
        assert all(a["ok"] is False for a in attempts)
