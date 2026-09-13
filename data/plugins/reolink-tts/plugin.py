"""Plugin EventConsumer — TTS natif Reolink via Baichuan (v3.85).

Contexte : le plugin `tts-notifier` existant fonctionne via go2rtc + le
back-channel audio ONVIF — mais certains modèles Reolink (ex. RLC-1224A,
confirmé en conditions réelles) ont un vrai haut-parleur utilisable par
leur appli officielle, sans jamais exposer `GetAudioOutputs` en ONVIF
standard (`AudioOutputs` renvoie une liste vide côté caméra). Sur ces
modèles, le TTS via go2rtc/ONVIF échoue systématiquement ("can't find
consumer"), alors que le haut-parleur existe bel et bien.

Ce plugin parle DIRECTEMENT le protocole propriétaire Reolink ("Baichuan",
port TCP 9000 par défaut) — le même protocole que l'appli officielle
utilise pour son talk bidirectionnel — sans passer par go2rtc ni ONVIF.
Il réutilise la connexion Baichuan DÉJÀ authentifiée par `reolink-aio`
(`camera_device_service.get_driver()` → `ReolinkDriver._host_api.baichuan`),
la même connexion qui fait déjà fonctionner la sirène/lumière/IR —
évite une session concurrente et le conflit "un autre client parle déjà"
que la caméra peut renvoyer sinon.

Protocole (reverse-engineered publiquement par le projet neolink, non
affilié à Reolink — voir https://github.com/thirtythreeforty/neolink) :

  1. `TalkAbility` (cmd_id 10, GET) → la caméra annonce le format audio
     qu'elle accepte : toujours `adpcm` (IMA-ADPCM / DVI-4), sample_rate
     et lengthPerEncoder variables selon le modèle (1024 échantillons/bloc
     confirmé sur RLC-1224A et E1 Outdoor Pro).
  2. `TalkConfig` (cmd_id 201, SET) → on renvoie EXACTEMENT la config
     annoncée pour démarrer une session de talk. Code 422 = un autre
     client parle déjà → on envoie `TalkReset` puis on réessaie une fois
     (comportement du client officiel, repris tel quel).
  3. `Talk` (cmd_id 202) → paquets audio binaires (pas de XML), chaque
     bloc encaudré par un en-tête `BcMedia` ADPCM propre (magic
     0x62773130, longueur, magic secondaire 0x0100, taille de bloc) —
     rythmé en temps réel (on attend la durée réelle du son envoyé avant
     d'envoyer le paquet suivant, sinon le buffer de la caméra déborde).
  4. `TalkReset` (cmd_id 11) → ferme proprement la session à la fin.

`reolink-aio` n'implémente PAS ce protocole (uniquement des presets fixes
: sirène, quick-reply, chime) — seule sa couche transport (connexion,
authentification, chiffrement AES, framing des messages) est réutilisée
ici via des attributs "privés" (`_aes_encrypt`, `_connection`, `_mess_id`)
faute d'API publique équivalente pour un payload binaire arbitraire.
"""
from __future__ import annotations

import asyncio
import os
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Optional

from plugin_manager.interfaces import EventConsumer, MGVMSEvent, ConsumerResult

_DEFAULT_VOICE = "fr_FR-siwis-medium"
_SYNTH_TIMEOUT_S = 20
_VOICE_DOWNLOAD_TIMEOUT_S = 60
_CHANNEL = 0

# ── Constantes du protocole Baichuan (reverse-engineered par neolink) ──────
_MSG_ID_TALKABILITY = 10
_MSG_ID_TALKRESET = 11
_MSG_ID_TALKCONFIG = 201
_MSG_ID_TALK = 202

_ADPCM_MAGIC = 0x62773130  # "bw10" — en-tête de chaque bloc BcMedia ADPCM
_ADPCM_DATA_MAGIC = 0x0100
_PAD_SIZE = 8
_BLOCKS_PER_MESSAGE = 4  # même valeur que le client de référence

_TALK_CONFIG_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<body>
<TalkConfig version="1.1">
<channelId>{channel}</channelId>
<duplex>{duplex}</duplex>
<audioStreamMode>{audio_stream_mode}</audioStreamMode>
<audioConfig>
<audioType>{audio_type}</audioType>
<sampleRate>{sample_rate}</sampleRate>
<samplePrecision>{sample_precision}</samplePrecision>
<lengthPerEncoder>{length_per_encoder}</lengthPerEncoder>
<soundTrack>{sound_track}</soundTrack>
</audioConfig>
</TalkConfig>
</body>
"""

_BINARY_EXTENSION_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<Extension version="1.1">
<binaryData>1</binaryData>
<channelId>{channel}</channelId>
</Extension>
"""


class TalkNotSupportedError(Exception):
    pass


def _adpcm_frame(block: bytes) -> bytes:
    """Encadre un bloc ADPCM brut (4 octets d'état prédicteur + nibbles)
    dans l'en-tête BcMedia attendu par la caméra. Format confirmé via le
    code source de neolink (bcmedia/model.rs + bcmedia/ser.rs)."""
    n = len(block)
    header = struct.pack(
        "<IHHHH",
        _ADPCM_MAGIC,
        n + 4,
        n + 4,
        _ADPCM_DATA_MAGIC,
        (n - 4) // 2,
    )
    pad = (-n) % _PAD_SIZE
    return header + block + b"\x00" * pad


# ── Encodeur IMA-ADPCM (DVI-4) — implémentation directe ────────────────────
# ffmpeg impose que son option prive `-block_size` de l'encodeur adpcm_ima_wav
# soit une puissance de 2 (constaté en conditions réelles) — inutilisable ici
# puisque le bloc attendu par la caméra fait systématiquement
# `lengthPerEncoder/2 + 4` octets (516 pour lengthPerEncoder=1024, jamais une
# puissance de 2). Plutôt que de lutter contre cette contrainte de l'encodeur
# ffmpeg, l'algorithme IMA-ADPCM standard (table de pas + table d'index,
# spécification IMA de référence — le même algorithme que ffmpeg implémente
# en interne) est réimplémenté ici en pur Python : quelques dizaines de
# lignes, aucune dépendance supplémentaire, contrôle total du découpage en
# blocs pour coller exactement à ce que la caméra annonce dans TalkAbility.
_STEP_TABLE = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143,
    157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658,
    724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024,
    3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899,
    15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
]
_INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8]


def _pcm_to_ima_adpcm_blocks(pcm: bytes, samples_per_block: int) -> bytes:
    """Encode du PCM s16le mono en blocs IMA-ADPCM (format WAV standard) :
    chaque bloc = 4 octets d'en-tête (1er échantillon brut + step_index +
    réservé) puis `samples_per_block` échantillons codés en nibbles (2 par
    octet). `samples_per_block` doit correspondre à `lengthPerEncoder`
    annoncé par la caméra. Retourne les blocs concaténés (4 + samples_per_block/2
    octets chacun), dernier bloc complété par du silence si nécessaire."""
    n_samples = len(pcm) // 2
    samples = struct.unpack(f"<{n_samples}h", pcm)

    blocks = bytearray()
    step_index = 0
    i = 0
    while i < n_samples:
        chunk = samples[i:i + 1 + samples_per_block]
        if len(chunk) < 1 + samples_per_block:
            chunk = chunk + (0,) * (1 + samples_per_block - len(chunk))
        predictor = chunk[0]
        blocks += struct.pack("<hBB", predictor, step_index, 0)

        nibbles = []
        for sample in chunk[1:]:
            step = _STEP_TABLE[step_index]
            diff = sample - predictor
            sign = 8 if diff < 0 else 0
            diff = abs(diff)

            delta = 0
            temp = step
            if diff >= temp:
                delta = 4
                diff -= temp
            temp >>= 1
            if diff >= temp:
                delta |= 2
                diff -= temp
            temp >>= 1
            if diff >= temp:
                delta |= 1
            nibble = sign | delta
            nibbles.append(nibble)

            diffq = step >> 3
            if delta & 4:
                diffq += step
            if delta & 2:
                diffq += step >> 1
            if delta & 1:
                diffq += step >> 2
            predictor = predictor - diffq if sign else predictor + diffq
            predictor = max(-32768, min(32767, predictor))
            step_index = max(0, min(len(_STEP_TABLE) - 1, step_index + _INDEX_TABLE[nibble & 0x07]))

        for j in range(0, len(nibbles), 2):
            byte = nibbles[j] & 0x0F
            if j + 1 < len(nibbles):
                byte |= (nibbles[j + 1] & 0x0F) << 4
            blocks.append(byte)

        i += samples_per_block
    return bytes(blocks)


class ReolinkTtsPlugin(EventConsumer):
    name = "reolink-tts"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        try:
            import piper  # noqa — vérifie seulement l'installation
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install piper-tts (bouton Installer du Plugin Center)")
            return
        self._ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        pass

    def _voice(self, override: Optional[str] = None) -> str:
        cfg = self._ctx.config or {}
        return override or cfg.get("voice_model") or _DEFAULT_VOICE

    def _length_scale(self, override: Optional[float] = None) -> float:
        cfg = self._ctx.config or {}
        speed = override if override is not None else cfg.get("speech_rate")
        try:
            speed = float(speed) if speed is not None else 1.0
        except (TypeError, ValueError):
            speed = 1.0
        speed = max(0.5, min(2.0, speed))
        return round(1.0 / speed, 3)

    async def _ensure_voice_downloaded(self, voice: str) -> None:
        if os.path.exists(f"{voice}.onnx"):
            return
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "piper.download_voices", voice,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=_VOICE_DOWNLOAD_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Téléchargement de la voix Piper '{voice}' : timeout")
        if proc.returncode != 0:
            raise RuntimeError(f"Téléchargement de la voix Piper '{voice}' échoué : {out.decode(errors='replace')[-500:]}")

    async def _synthesize(self, text: str, voice: str, length_scale: float) -> str:
        import tempfile
        fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="mgvms-reolink-tts-")
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

    async def _encode_adpcm(self, wav_path: str, sample_rate: int, samples_per_block: int) -> bytes:
        """Convertit le WAV Piper en PCM brut au sample_rate annoncé par la
        caméra (ffmpeg — simple resampling, aucun souci de format ici), puis
        encode en IMA-ADPCM via `_pcm_to_ima_adpcm_blocks` avec le découpage
        en blocs (`samples_per_block` = lengthPerEncoder) exact attendu."""
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-hide_banner", "-v", "error",
            "-i", wav_path,
            "-ar", str(sample_rate), "-ac", "1",
            "-f", "s16le", "-acodec", "pcm_s16le",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        pcm, err = await asyncio.wait_for(proc.communicate(), timeout=_SYNTH_TIMEOUT_S)
        if proc.returncode != 0 or not pcm:
            raise RuntimeError(f"Rééchantillonnage PCM (ffmpeg) échoué : {err.decode(errors='replace')[-500:]}")
        # v3.85 · ~0.3s de silence en tête, pour la même raison que le délai
        # après TalkConfig ci-dessus — si le tout premier fragment audio réel
        # arrive avant que le DSP soit prêt, il se perd silencieusement.
        silence = b"\x00\x00" * int(sample_rate * 0.3)
        return _pcm_to_ima_adpcm_blocks(silence + pcm, samples_per_block)

    # ── Bas niveau Baichuan : envoi d'un payload binaire arbitraire ────
    # `Baichuan.send()` (reolink-aio) n'accepte qu'un `body: str` encodé en
    # UTF-8 — inutilisable pour de l'audio binaire. On reproduit ici EXACTEMENT
    # la construction d'en-tête + chiffrement AES de `send()`, mais avec des
    # `bytes` bruts au lieu d'une chaîne, pour le message TALK uniquement.
    async def _bc_send_binary(self, bc, cmd_id: int, channel: int, payload: bytes) -> None:
        from reolink_aio.baichuan.util import HEADER_MAGIC

        ext_bytes = _BINARY_EXTENSION_XML.format(channel=channel).encode("utf-8")
        body_bytes = payload
        ext_len = len(ext_bytes)
        mess_len = ext_len + len(body_bytes)

        bc._mess_id = (bc._mess_id + 1) % 16777216
        ch_id = channel + 1

        cmd_id_bytes = cmd_id.to_bytes(4, byteorder="little")
        mess_len_bytes = mess_len.to_bytes(4, byteorder="little")
        mess_id_bytes = ch_id.to_bytes(1, byteorder="little") + bc._mess_id.to_bytes(3, byteorder="little")
        full_mess_id = int.from_bytes(mess_id_bytes, byteorder="little")
        payload_offset_bytes = ext_len.to_bytes(4, byteorder="little")

        status_code = "0000"
        header = (
            bytes.fromhex(HEADER_MAGIC) + cmd_id_bytes + mess_len_bytes + mess_id_bytes
            + bytes.fromhex(status_code + "1464") + payload_offset_bytes
        )
        enc_body_bytes = bc._aes_encrypt(ext_bytes) + bc._aes_encrypt(body_bytes)

        await bc._connect_if_needed()
        await bc._connection.send(header + enc_body_bytes, cmd_id, full_mess_id, channel, "")

    async def _do_talk(self, bc, channel: int, adpcm_data: bytes, audio_cfg: dict) -> None:
        block_size = int(audio_cfg["lengthPerEncoder"]) // 2
        full_block_size = block_size + 4
        sample_rate = int(audio_cfg["sampleRate"])

        for i in range(0, len(adpcm_data), full_block_size * _BLOCKS_PER_MESSAGE):
            payload_bytes = adpcm_data[i:i + full_block_size * _BLOCKS_PER_MESSAGE]
            payload = b""
            samples_sent = 0
            for j in range(0, len(payload_bytes), full_block_size):
                block = payload_bytes[j:j + full_block_size]
                if len(block) < full_block_size:
                    block = block + b"\x00" * (full_block_size - len(block))
                payload += _adpcm_frame(block)
                samples_sent += (len(block) - 4) * 2 + 1

            await self._bc_send_binary(bc, _MSG_ID_TALK, channel, payload)
            await asyncio.sleep(samples_sent / sample_rate)

    async def _talk_config_start(self, bc, channel: int) -> dict:
        ability_xml = await bc.send(cmd_id=_MSG_ID_TALKABILITY, channel=channel)
        root = ET.fromstring(ability_xml)
        cfg_el = root.find(".//audioConfigList/audioConfig")
        if cfg_el is None:
            raise TalkNotSupportedError("Cette caméra n'annonce aucune configuration audio pour le talk (TalkAbility vide)")
        audio_cfg = {child.tag: child.text for child in cfg_el}
        if audio_cfg.get("audioType") != "adpcm":
            raise TalkNotSupportedError(f"Format audio non supporté par ce plugin : {audio_cfg.get('audioType')!r} (attendu 'adpcm')")

        duplex_el = root.find(".//duplexList/duplex")
        mode_el = root.find(".//audioStreamModeList/audioStreamMode")
        duplex = duplex_el.text if duplex_el is not None else "FDX"
        audio_stream_mode = mode_el.text if mode_el is not None else "followVideoStream"

        config_xml = _TALK_CONFIG_XML.format(
            channel=channel, duplex=duplex, audio_stream_mode=audio_stream_mode,
            audio_type=audio_cfg["audioType"], sample_rate=audio_cfg["sampleRate"],
            sample_precision=audio_cfg["samplePrecision"],
            length_per_encoder=audio_cfg["lengthPerEncoder"], sound_track=audio_cfg["soundTrack"],
        )

        try:
            await bc.send(cmd_id=_MSG_ID_TALKCONFIG, channel=channel, body=config_xml)
        except Exception:
            # v3.85 · Code 422 = un autre client (appli officielle, ou un appel
            # TTS précédent mal terminé) tient déjà la session de talk — le
            # client officiel Reolink envoie TalkReset puis réessaie une fois,
            # comportement repris ici tel quel (voir neolink talk.rs).
            await bc.send(cmd_id=_MSG_ID_TALKRESET, channel=channel)
            await bc.send(cmd_id=_MSG_ID_TALKCONFIG, channel=channel, body=config_xml)

        # v3.85 · Délai de stabilisation après TalkConfig — même logique que
        # le blip de préconnexion déjà utilisé côté ONVIF/go2rtc (plugin
        # tts-notifier) : rien ne garantit que le DSP audio de la caméra soit
        # immédiatement prêt à décoder de l'ADPCM juste après avoir accepté
        # la config. Coût négligeable, absorbe un éventuel temps
        # d'initialisation silencieux.
        await asyncio.sleep(0.3)

        return audio_cfg

    async def on_event(self, event: MGVMSEvent) -> ConsumerResult:
        data = event.data or {}
        text = (data.get("text") or data.get("message") or "").strip()
        if not text:
            return ConsumerResult(handled=False, error="text requis")
        if not event.camera_id:
            return ConsumerResult(handled=False, error="camera_id requis")

        from services.camera_device_service import camera_device_service
        from drivers.reolink_driver import ReolinkDriver

        try:
            drv = await camera_device_service.get_driver(event.camera_id)
        except Exception as e:
            return ConsumerResult(handled=False, error=f"Connexion caméra impossible : {e}")

        if not isinstance(drv, ReolinkDriver) or drv._host_api is None:
            return ConsumerResult(handled=False, error="Cette caméra n'est pas pilotée par le driver Reolink natif — utilisez plutôt le plugin tts-notifier")

        bc = drv._host_api.baichuan

        voice = self._voice(data.get("voice"))
        length_scale = self._length_scale(data.get("speed"))
        wav_path = None
        try:
            await self._ensure_voice_downloaded(voice)
            wav_path = await self._synthesize(text, voice, length_scale)
        except Exception as e:
            self._ctx.log.warning("reolink-tts: synthèse échouée (%s)", e)
            return ConsumerResult(handled=False, error=str(e))

        try:
            audio_cfg = await self._talk_config_start(bc, _CHANNEL)
            adpcm_data = await self._encode_adpcm(
                wav_path, int(audio_cfg["sampleRate"]), int(audio_cfg["lengthPerEncoder"]),
            )
            await self._do_talk(bc, _CHANNEL, adpcm_data, audio_cfg)
            await bc.send(cmd_id=_MSG_ID_TALKRESET, channel=_CHANNEL)
        except TalkNotSupportedError as e:
            return ConsumerResult(handled=False, error=str(e))
        except Exception as e:
            self._ctx.log.warning("reolink-tts: échec envoi audio natif (%s)", e)
            try:
                await bc.send(cmd_id=_MSG_ID_TALKRESET, channel=_CHANNEL)
            except Exception:
                pass
            return ConsumerResult(handled=False, error=str(e))
        finally:
            if wav_path:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

        return ConsumerResult(handled=True)

    async def on_unload(self) -> None:
        pass
