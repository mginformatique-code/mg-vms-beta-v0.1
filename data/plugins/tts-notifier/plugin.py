"""Plugin EventConsumer — TTS (v3.59, Piper local + haut-parleur go2rtc).

Comble le chantier v3.20 (TTS) resté à l'état de tuyauterie : le routage
existait déjà (backend/routes/camera_control.py::play_tts →
smart_zones/actuators.py::_run_tts) mais déléguait à un plugin
`tts-notifier` jamais écrit. Ce plugin :

  1. Génère la voix via Piper (moteur local, gratuit — invoqué en
     sous-processus CLI plutôt qu'importé en Python : Piper est publié
     sous GPL-3.0, un appel en sous-processus reste une utilisation
     arm's-length classique, contrairement à un `import piper` qui lie le
     code directement dans le process).
  2. Sert le WAV généré via une URL HTTP interne éphémère (voir
     routes/tts_audio.py — go2rtc tourne dans un conteneur séparé, sans
     volume partagé writable avec le backend).
  3. Demande à go2rtc de pousser cet audio vers le haut-parleur de la
     caméra : `POST /api/streams?dst=cam_{id}&src=ffmpeg:<url>#audio=pcma`
     — go2rtc gère lui-même la négociation du back-channel audio ONVIF/
     propriétaire, aucun protocole à réimplémenter ici.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import struct
import sys
import tempfile
import time
import wave

from plugin_manager.interfaces import EventConsumer, MGVMSEvent, ConsumerResult

_DEFAULT_VOICE = "fr_FR-siwis-medium"
_GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://go2rtc:1984")
_BACKEND_BASE_URL = os.environ.get("MGVMS_INTERNAL_URL", "http://backend:8001")
_SYNTH_TIMEOUT_S = 20
_DOWNLOAD_TIMEOUT_S = 60
_WARMUP_WAV_PATH = os.path.join(tempfile.gettempdir(), "mgvms-tts-warmup.wav")
_WARMUP_SETTLE_S = 2.5
_NO_SPEAKER_MARKER = "can't find consumer"
_COOLDOWN_S = 15.0
_last_call_at: dict[str, float] = {}  # camera_id -> monotonic timestamp


def _ensure_warmup_wav() -> str:
    """v3.60 · Blip silencieux (1.5s) rejoué UNE FOIS avant le vrai message.

    Root cause d'un TTS audible par intermittence (constaté en conditions
    réelles, à répétition) : la connexion ONVIF back-channel vers la caméra
    est établie PARESSEUSEMENT par go2rtc, à la demande — rien ne la tient
    ouverte en continu. Le tout premier appel doit donc, à chaque fois,
    ouvrir une session RTSP+ONVIF fraîche pendant que ffmpeg envoie déjà
    ses paquets ; si le message réel est court, une partie (voire sa
    totalité) part avant que la session soit prête et se perd. Un blip
    silencieux jetable absorbe ce temps d'établissement — le vrai message
    n'est envoyé qu'une fois la voie confirmée ouverte.
    """
    if os.path.exists(_WARMUP_WAV_PATH):
        return _WARMUP_WAV_PATH
    with wave.open(_WARMUP_WAV_PATH, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        frames = int(8000 * 1.5)
        w.writeframes(struct.pack("<%dh" % frames, *([0] * frames)))
    return _WARMUP_WAV_PATH


class TtsNotifierPlugin(EventConsumer):
    name = "tts-notifier"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        try:
            import piper  # noqa — vérifie seulement l'installation, jamais appelé directement
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install piper-tts (bouton Installer du Plugin Center)")
            return
        self._ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        pass

    def _voice(self, override: str | None = None) -> str:
        cfg = self._ctx.config or {}
        return override or cfg.get("voice_model") or _DEFAULT_VOICE

    def _length_scale(self, override: float | None = None) -> float:
        # v3.60 · Piper : `length_scale` est l'INVERSE de la vitesse
        # (1.0 = normal, >1 = plus lent, <1 = plus rapide) — on expose côté
        # config/appel une "vitesse" intuitive (1.0 = normal, 1.5 = +50%
        # rapide) et on la convertit ici, plutôt que d'exposer le paramètre
        # Piper brut, contre-intuitif pour l'utilisateur.
        cfg = self._ctx.config or {}
        speed = override if override is not None else cfg.get("speech_rate")
        try:
            speed = float(speed) if speed is not None else 1.0
        except (TypeError, ValueError):
            speed = 1.0
        speed = max(0.5, min(2.0, speed))
        return round(1.0 / speed, 3)

    async def _ensure_voice_downloaded(self, voice: str) -> None:
        # v3.59 · Piper ne télécharge PAS automatiquement une voix absente
        # au moment de la synthèse (vérifié dans la doc CLI officielle) —
        # un appel explicite est requis une fois. Constaté en conditions
        # réelles : invoquer `download_voices` à CHAQUE appel (même une fois
        # le modèle déjà présent) coûte assez pour dépasser à l'occasion le
        # timeout de 5s du bus de plugins (plugin_bus._call_one) — on
        # vérifie donc d'abord la présence du fichier .onnx (même
        # répertoire que celui utilisé par `-m` dans _synthesize).
        if os.path.exists(f"{voice}.onnx"):
            return
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "piper.download_voices", voice,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=_DOWNLOAD_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Téléchargement de la voix Piper '{voice}' : timeout")
        if proc.returncode != 0:
            raise RuntimeError(f"Téléchargement de la voix Piper '{voice}' échoué : {out.decode(errors='replace')[-500:]}")

    async def _synthesize(self, text: str, voice: str, length_scale: float = 1.0) -> str:
        fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="mgvms-tts-")
        os.close(fd)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "piper", "-m", voice, "-f", wav_path,
            "--length_scale", str(length_scale), "--", text,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=_SYNTH_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("Synthèse Piper : timeout")
        if proc.returncode != 0 or not os.path.exists(wav_path):
            raise RuntimeError(f"Synthèse Piper échouée : {out.decode(errors='replace')[-500:]}")
        return wav_path

    async def _push_audio(self, client, stream_name: str, audio_url: str, codecs=("pcmu", "pcma")) -> tuple[str | None, str | None]:
        """POST une source audio vers go2rtc. Retourne (codec_qui_a_marché, erreur)."""
        last_error = None
        for codec in codecs:
            r = await client.post(
                f"{_GO2RTC_URL}/api/streams",
                params={"dst": stream_name, "src": f"ffmpeg:{audio_url}#audio={codec}#input=file"},
            )
            if r.status_code < 400:
                return codec, None
            last_error = f"go2rtc a refusé la diffusion (codec {codec}, {r.status_code}) : {r.text[:200]}"
            self._ctx.log.warning("tts-notifier: go2rtc %s codec=%s body=%s", r.status_code, codec, r.text[:500])
        return None, last_error

    async def on_event(self, event: MGVMSEvent) -> ConsumerResult:
        data = event.data or {}
        text = data.get("text") or data.get("message") or ""
        text = text.strip()
        if not text:
            return ConsumerResult(handled=False, error="text requis")
        if not event.camera_id:
            return ConsumerResult(handled=False, error="camera_id requis")

        # v3.60 · Anti-rafale : constaté en conditions réelles (à répétition)
        # qu'un 2e message envoyé peu après un premier sur la MÊME caméra
        # échoue silencieusement (aucune erreur, mais rien d'audible) —
        # cohérent avec une session ONVIF back-channel qui a besoin d'un
        # temps de « repos » avant d'en accepter une nouvelle. Un message
        # espacé fonctionne de façon fiable ; un message rapproché non.
        # Plutôt que d'échouer en silence, on refuse explicitement avec un
        # message clair — l'appelant sait qu'il doit réessayer un peu plus tard.
        now = time.monotonic()
        last = _last_call_at.get(event.camera_id)
        if last is not None and (now - last) < _COOLDOWN_S:
            wait_s = round(_COOLDOWN_S - (now - last), 1)
            return ConsumerResult(handled=False, error=f"Merci de patienter {wait_s}s avant un nouveau message sur cette caméra (session audio en cours d'utilisation)")

        stream_name = f"cam_{event.camera_id}"
        from routes.tts_audio import register_tts_audio

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                # v3.60 · Étape 1 : blip silencieux jetable pour absorber le
                # temps d'établissement de la session ONVIF back-channel
                # (connexion PARESSEUSE côté go2rtc, jamais tenue ouverte en
                # continu) — voir docstring de _ensure_warmup_wav. Fait AVANT
                # la synthèse Piper (coûteuse) : si la caméra n'a pas de
                # back-channel du tout (pas de haut-parleur — ex. Reolink
                # RLC-820A, micro seul, confirmé par la doc constructeur),
                # go2rtc répond "can't find consumer" pour CHAQUE codec —
                # on le détecte ici et on échoue vite avec un message clair,
                # sans gaspiller de synthèse vocale pour rien.
                warmup_token = secrets.token_urlsafe(24)
                register_tts_audio(_ensure_warmup_wav(), warmup_token)
                warmup_url = f"{_BACKEND_BASE_URL}/api/internal/tts-audio/{warmup_token}.wav"
                working_codec, warmup_error = await self._push_audio(client, stream_name, warmup_url)
                if warmup_error:
                    if _NO_SPEAKER_MARKER in warmup_error:
                        return ConsumerResult(handled=False, error="Cette caméra n'a pas de haut-parleur compatible (aucun canal audio retour détecté)")
                    self._ctx.log.warning("tts-notifier: warm-up échoué, tentative directe (%s)", warmup_error)
                else:
                    await asyncio.sleep(_WARMUP_SETTLE_S)
                _last_call_at[event.camera_id] = now

                voice = self._voice(data.get("voice"))
                length_scale = self._length_scale(data.get("speed"))
                try:
                    await self._ensure_voice_downloaded(voice)
                    wav_path = await self._synthesize(text, voice, length_scale)
                except Exception as e:
                    self._ctx.log.warning("tts-notifier: synthèse échouée (%s)", e)
                    return ConsumerResult(handled=False, error=str(e))

                # v3.59 · Le back-channel ONVIF d'une Reolink E1 Outdoor Pro
                # annonce PCMU/8000, pas PCMA — codec réellement supporté
                # variable selon le modèle/fabricant, d'où le fallback.
                # Si le warm-up a déjà trouvé le bon codec, on le réutilise
                # directement (évite une tentative PCMA inutile à chaque fois).
                token = secrets.token_urlsafe(24)
                register_tts_audio(wav_path, token)
                audio_url = f"{_BACKEND_BASE_URL}/api/internal/tts-audio/{token}.wav"
                codecs = (working_codec,) if working_codec else ("pcmu", "pcma")
                _, error = await self._push_audio(client, stream_name, audio_url, codecs=codecs)
            if error:
                return ConsumerResult(handled=False, error=error)
        except Exception as e:
            self._ctx.log.warning("tts-notifier: push go2rtc échoué (%s)", e)
            return ConsumerResult(handled=False, error=str(e))

        return ConsumerResult(handled=True)

    async def on_unload(self) -> None:
        pass
