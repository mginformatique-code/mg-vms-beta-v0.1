"""Route module — Service temporaire de fichiers audio TTS (v3.59).

Le plugin `tts-notifier` (voir /app/data/plugins/tts-notifier) génère un
WAV via Piper puis demande à go2rtc de le pousser vers le haut-parleur
d'une caméra (`POST {GO2RTC_URL}/api/streams?dst=...&src=ffmpeg:<url>`).
go2rtc tourne dans un CONTENEUR SÉPARÉ (`mgvms-go2rtc`) — aucun volume
partagé writable n'existe entre backend et go2rtc pour échanger un
fichier local (voir docker-compose.yml : go2rtc ne monte que
`recordings:ro` et son propre `go2rtc.yaml`). Ce module sert donc le WAV
généré via une URL HTTP interne éphémère que go2rtc peut fetcher lui-même
(`http://backend:8001/...`, réseau Docker interne), plutôt que d'inventer
un volume partagé supplémentaire.

Sécurité : jeton aléatoire à haute entropie (32 octets) dans l'URL, valable
le temps d'une fenêtre courte (TTL) puis supprimé du disque — pas d'auth
sur cet endpoint par nécessité : go2rtc, dans son propre conteneur, n'a pas
de session MG-VMS à présenter, la sécurité vient de l'entropie du jeton et
du TTL. Servi PLUSIEURS fois pendant le TTL (pas à usage unique) : constaté
en conditions réelles que go2rtc fait deux requêtes GET distinctes sur la
même source ffmpeg — une pour sonder les codecs lors du `POST /api/streams`,
une seconde pour la lecture effective — un jeton à usage unique fait donc
échouer la seconde lecture (404) et par ricochet tout le push (500).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger("tts_audio")

tts_audio_router = APIRouter(prefix="/api/internal/tts-audio", tags=["tts-audio"])

_TTL_S = 60.0
_FILES: dict[str, tuple[str, float]] = {}  # token -> (filepath, expires_at)


def register_tts_audio(filepath: str, token: str) -> None:
    """Enregistre un fichier WAV généré, récupérable plusieurs fois par
    go2rtc pendant le TTL — appelé par le plugin tts-notifier juste avant
    de déclencher le push go2rtc."""
    _FILES[token] = (filepath, time.monotonic() + _TTL_S)

    async def _expire():
        await asyncio.sleep(_TTL_S)
        _FILES.pop(token, None)
        try:
            os.unlink(filepath)
        except OSError:
            pass
    asyncio.create_task(_expire())


@tts_audio_router.get("/{token}.wav")
async def get_tts_audio(token: str):
    entry = _FILES.get(token)
    if not entry:
        raise HTTPException(404, "Fichier audio introuvable ou expiré")
    filepath, expires_at = entry
    if time.monotonic() > expires_at or not os.path.exists(filepath):
        raise HTTPException(410, "Fichier audio expiré")
    return FileResponse(filepath, media_type="audio/wav")
