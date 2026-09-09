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
import sys
import tempfile

from plugin_manager.interfaces import EventConsumer, MGVMSEvent, ConsumerResult

_DEFAULT_VOICE = "fr_FR-siwis-medium"
_GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://go2rtc:1984")
_BACKEND_BASE_URL = os.environ.get("MGVMS_INTERNAL_URL", "http://backend:8001")
_SYNTH_TIMEOUT_S = 20
_DOWNLOAD_TIMEOUT_S = 60


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

    def _voice(self) -> str:
        cfg = self._ctx.config or {}
        return cfg.get("voice_model") or _DEFAULT_VOICE

    async def _ensure_voice_downloaded(self, voice: str) -> None:
        # v3.59 · Piper ne télécharge PAS automatiquement une voix absente
        # au moment de la synthèse (vérifié dans la doc CLI officielle) —
        # un appel explicite est requis une fois. `download_voices` est
        # idempotent (no-op si déjà présent), donc appelé systématiquement
        # avant chaque synthèse plutôt que de gérer un cache d'état
        # supplémentaire ici.
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

    async def _synthesize(self, text: str, voice: str) -> str:
        fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="mgvms-tts-")
        os.close(fd)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "piper", "-m", voice, "-f", wav_path, "--", text,
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

    async def on_event(self, event: MGVMSEvent) -> ConsumerResult:
        text = (event.data or {}).get("text") or (event.data or {}).get("message") or ""
        text = text.strip()
        if not text:
            return ConsumerResult(handled=False, error="text requis")
        if not event.camera_id:
            return ConsumerResult(handled=False, error="camera_id requis")

        voice = self._voice()
        try:
            await self._ensure_voice_downloaded(voice)
            wav_path = await self._synthesize(text, voice)
        except Exception as e:
            self._ctx.log.warning("tts-notifier: synthèse échouée (%s)", e)
            return ConsumerResult(handled=False, error=str(e))

        from routes.tts_audio import register_tts_audio
        token = secrets.token_urlsafe(24)
        register_tts_audio(wav_path, token)
        audio_url = f"{_BACKEND_BASE_URL}/api/internal/tts-audio/{token}.wav"
        stream_name = f"cam_{event.camera_id}"

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{_GO2RTC_URL}/api/streams",
                    params={"dst": stream_name, "src": f"ffmpeg:{audio_url}#audio=pcma#input=file"},
                )
            if r.status_code >= 400:
                self._ctx.log.warning("tts-notifier: go2rtc %s body=%s", r.status_code, r.text[:500])
                return ConsumerResult(handled=False, error=f"go2rtc a refusé la diffusion ({r.status_code})")
        except Exception as e:
            self._ctx.log.warning("tts-notifier: push go2rtc échoué (%s)", e)
            return ConsumerResult(handled=False, error=str(e))

        return ConsumerResult(handled=True)

    async def on_unload(self) -> None:
        pass
