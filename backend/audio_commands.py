"""Journal des commandes audio (TTS + sirène) — v3.82.

Le TTS et la sirène passent tous les deux par une couche externe (go2rtc /
back-channel ONVIF pour le TTS, protocole propriétaire constructeur pour la
sirène) qui peut accepter une commande sans que le son soit réellement
audible — un problème connu et documenté (voir CHANGELOG v3.60, limite
résiduelle go2rtc/Reolink). Ce module donne au moins de la visibilité :
chaque commande envoyée est journalisée avec un résultat et, en cas
d'échec détectable, un code d'erreur explicite — plutôt que de laisser la
seule alternative être "silence total, aucune trace".

Important : un statut "ok" ici signifie "la commande a été acceptée par
la couche de livraison (go2rtc / API caméra)", PAS "le son a été
effectivement entendu" — cette dernière vérification n'est pas possible
sans retour du matériel lui-même.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from database import db

COLLECTION = "audio_commands"

# Codes d'erreur TTS — dérivés du texte d'erreur renvoyé par
# smart_zones/actuators.py::dispatch_action (voir _classify_tts_error).
TTS_ERROR_CODES = {
    "text_missing": "text requis",
    "plugin_missing": "introuvable",
    "plugin_not_ready": "non dispatchable",
    "cooldown": "Merci de patienter",
    "no_speaker": "haut-parleur compatible",
    "synthesis_failed": "Synthèse Piper",
    "voice_download_failed": "Téléchargement de la voix",
    "go2rtc_rejected": "go2rtc a refusé",
    "timeout": "timeout",
}


def classify_tts_error(error: Optional[str]) -> str:
    """Classe le texte d'erreur libre renvoyé par dispatch_action en un
    code stable, exploitable par l'UI (couleur, filtre) sans dépendre du
    texte français exact."""
    if not error:
        return "unknown_error"
    for code, needle in TTS_ERROR_CODES.items():
        if needle.lower() in error.lower():
            return code
    return "unknown_error"


async def log_audio_command(
    *,
    type_: str,  # "tts" | "siren"
    camera_id: str,
    camera_name: str,
    requested_by: str,
    status: str,  # "ok" | "error"
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    text: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    await db[COLLECTION].insert_one({
        "id": str(uuid.uuid4()),
        "type": type_,
        "camera_id": camera_id,
        "camera_name": camera_name,
        "requested_by": requested_by,
        "status": status,
        "error_code": error_code,
        "error_message": (error_message or "")[:500] or None,
        "text": (text or "")[:200] or None,
        "duration_ms": duration_ms,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
