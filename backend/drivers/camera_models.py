"""Modèles standard exposés par tous les drivers.

Ces modèles sont sérialisables JSON directement (``.to_dict()``) et servent
d'interface stable entre le service caméra, l'API HTTP et la couche UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class LightMode(str, Enum):
    """Mode de la lumière (spotlight / white light / supplement light)."""
    OFF = "off"
    ON = "on"
    AUTO = "auto"


class IRMode(str, Enum):
    """Mode infrarouge."""
    AUTO = "auto"      # bascule automatique jour/nuit
    ON = "on"          # forcé ON (nuit)
    OFF = "off"        # forcé OFF (couleur permanente)


@dataclass
class CameraCapabilities:
    """Capacités matérielles d'une caméra — retour standard de ``probe()``.

    Une capacité à ``False`` signifie que le driver a testé et confirmé
    l'absence de la fonction. ``None`` = non-testé (inconnu).

    v0.5.7 · nouveaux flags optionnels ajoutés en bas (multi_stream,
    codec_h265, IA fine-grain, thermal, radar, io, storage…). Tous
    valent ``False`` par défaut → aucune régression pour un driver qui
    ne les remonte pas.
    """
    # PTZ / optique
    ptz: bool = False
    zoom: bool = False
    focus: bool = False

    # Audio
    audio_input: bool = False       # micro embarqué
    audio_output: bool = False      # HP embarqué
    microphone: bool = False        # alias sémantique (audio_input)
    speaker: bool = False           # alias sémantique (audio_output)
    two_way_audio: bool = False     # talk-back

    # Lumière & IR
    spotlight: bool = False         # blanc puissant (Reolink)
    white_light: bool = False       # blanc doux (Dahua)
    ir_control: bool = False        # IR LEDs contrôlables
    ir_cut_filter: bool = False     # bascule couleur/N&B

    # Incrustation (OSD — date/heure, nom caméra)
    osd: bool = False               # position/désactivation de l'incrustation caméra

    # Alarmes physiques
    siren: bool = False
    alarm_output: bool = False      # sortie relais 0/12V

    # Capteurs
    pir_sensor: bool = False        # détecteur mouvement PIR (Reolink)
    battery: bool = False           # caméra sur batterie

    # Événements IA embarqués (agrégat historique)
    onboard_ai: bool = False
    onboard_ai_features: tuple = field(default_factory=tuple)

    # Protocoles
    onvif: bool = False
    isapi: bool = False
    cgi: bool = False
    reolink_api: bool = False

    # Info matériel
    max_resolution: tuple = (0, 0)
    max_fps: int = 0

    # ── v0.5.7 · extensions Universal Camera API ─────────────────
    # Vidéo
    multi_stream: bool = False       # deux profils (main + sub)
    codec_h265: bool = False         # H.265 supporté
    # Audio étendu
    talkback: bool = False           # alias sémantique de two_way_audio
    upload_wav: bool = False         # upload d'un fichier audio custom
    # Lumière étendue
    flash: bool = False              # flash / stroboscope
    # PTZ étendu
    ptz_presets: bool = False        # rappel de presets
    ptz_patrol: bool = False         # rondes automatiques
    ptz_tracking: bool = False       # suivi auto d'une cible
    # IA embarquée fine-grain (booléens dérivables de onboard_ai_features)
    ai_motion: bool = False
    ai_person: bool = False
    ai_vehicle: bool = False
    ai_animal: bool = False
    ai_face: bool = False
    ai_helmet: bool = False
    ai_anpr: bool = False
    ai_line_crossing: bool = False
    ai_intrusion: bool = False
    # Capteurs additionnels
    thermal: bool = False
    radar: bool = False
    # I/O
    relay: bool = False              # sortie relais (alias sémantique alarm_output)
    digital_io: bool = False         # entrées/sorties numériques
    # Connectique
    wifi: bool = False
    poe: bool = False
    # Stockage
    sdcard: bool = False
    hdd: bool = False
    nas: bool = False
    ftp: bool = False
    smtp: bool = False
    cloud: bool = False
    # Sécurité
    https: bool = False
    vpn: bool = False
    # API propriétaire (générique — ex : Axis VAPIX, Hanwha SUNAPI…)
    proprietary_api: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["onboard_ai_features"] = list(self.onboard_ai_features)
        d["max_resolution"] = list(self.max_resolution)
        return d


@dataclass
class DeviceInfo:
    """Identité statique d'une caméra."""
    manufacturer: str = ""       # "Reolink", "Dahua", "Hikvision", "Axis"…
    model: str = ""
    firmware: Optional[str] = None
    serial: Optional[str] = None
    mac: Optional[str] = None
    ip: Optional[str] = None
    hardware: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StreamInfo:
    """Description d'un sous-flux vidéo (main / sub / etc.)."""
    name: str                        # "main" | "sub" | "third"
    url: str                         # rtsp://user:pass@ip:port/…
    resolution: tuple = (0, 0)       # (w, h)
    fps: int = 0
    codec: str = "h264"              # "h264" | "h265"
    bitrate_kbps: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["resolution"] = list(self.resolution)
        return d


@dataclass
class DeviceStatus:
    """État runtime dynamique."""
    online: bool = False
    uptime_s: Optional[int] = None
    cpu_percent: Optional[float] = None
    temperature_c: Optional[float] = None
    battery_percent: Optional[int] = None     # None si non-batterie
    sd_card_status: Optional[str] = None      # "ok" | "missing" | "full" | "error"
    sd_card_used_percent: Optional[int] = None
    last_seen_at: Optional[str] = None
    last_error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)
