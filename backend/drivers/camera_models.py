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

    # Alarmes physiques
    siren: bool = False
    alarm_output: bool = False      # sortie relais 0/12V

    # Capteurs
    pir_sensor: bool = False        # détecteur mouvement PIR (Reolink)
    battery: bool = False           # caméra sur batterie

    # Événements IA embarqués
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
