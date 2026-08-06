"""MG-VMS · Camera Drivers · Abstraction constructeur (v0.4.5.a · placeholder).

⚠  Cette itération (v0.4.5.a Latence) **ne fournit aucune implémentation**.
   Seules les interfaces sont définies pour préparer v0.4.6.

Objectif v0.4.6 :
    Camera (DB record)
        │
        ▼
    CameraDriver (abstract)
        │
        ├── ONVIFDriver          (généraliste, fallback)
        ├── ReolinkDriver        (API HTTP JSON)
        ├── DahuaDriver          (CGI HTTP)
        ├── HikvisionDriver      (ISAPI XML)
        ├── AxisDriver           (VAPIX)
        ├── HanwhaDriver         (Sunapi)
        └── UniviewDriver        (LAPI)

Chaque driver expose la même API haute niveau — l'IA et l'UI ne
manipulent plus jamais directement de RelayOutputState() ONVIF qui
casse une caméra sur deux. Le driver s'occupe des détails constructeur.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CameraCapabilities:
    """Ce que la caméra peut réellement faire (rempli par ``probe``)."""
    has_ptz: bool = False
    has_spotlight: bool = False
    has_siren: bool = False
    has_relay: bool = False
    has_audio_out: bool = False
    has_onboard_ai: bool = False       # IA embarquée constructeur
    onboard_ai_features: tuple = ()    # ex : ("person", "vehicle", "face")
    has_night_mode: bool = False
    max_resolution: tuple = (0, 0)
    firmware_version: Optional[str] = None
    model: Optional[str] = None
    vendor: Optional[str] = None


@dataclass
class DeviceInfo:
    """Informations statiques d'une caméra."""
    vendor: str
    model: str
    firmware: Optional[str] = None
    serial: Optional[str] = None
    mac: Optional[str] = None


class CameraDriver(ABC):
    """Contrat unique pour toute caméra IP, quel que soit le constructeur.

    ⚠ v0.4.5.a : squelette non implémenté. Les méthodes lèvent
    ``NotImplementedError`` pour bloquer tout code qui tenterait d'appeler
    ces API prématurément. v0.4.6 fournira les implémentations concrètes.

    Chaque méthode DOIT être idempotente et thread-safe.
    """

    def __init__(self, host: str, username: str, password: str,
                 port: Optional[int] = None):
        self.host = host
        self.username = username
        self.password = password
        self.port = port

    # ── Introspection ─────────────────────────────────────────
    @abstractmethod
    async def probe(self) -> CameraCapabilities:
        """Auto-détecte les capacités réelles de la caméra."""
        raise NotImplementedError

    @abstractmethod
    async def device_info(self) -> DeviceInfo:
        raise NotImplementedError

    # ── Streaming ─────────────────────────────────────────────
    @abstractmethod
    async def rtsp_urls(self) -> list[dict]:
        """Retourne la liste des sous-flux RTSP disponibles :
        ``[{"name": "main", "url": "rtsp://...", "resolution": (w,h),
            "codec": "h264"}, ...]``."""
        raise NotImplementedError

    # ── Contrôles physiques ──────────────────────────────────
    @abstractmethod
    async def spotlight(self, on: bool, brightness: Optional[int] = None) -> None:
        """Allume/éteint le spotlight — utilise l'API constructeur si dispo,
        JAMAIS RelayOutputState() ONVIF (qui casse une caméra sur deux)."""
        raise NotImplementedError

    @abstractmethod
    async def siren(self, on: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    async def audio_play(self, url_or_bytes: Any) -> None:
        raise NotImplementedError

    # ── IA embarquée constructeur ────────────────────────────
    @abstractmethod
    async def onboard_ai_events(self):
        """Async generator qui yield les événements IA constructeur
        (personne, véhicule, plaque, franchissement…) — permet à MG-VMS
        d'exploiter l'IA de la caméra sans re-faire l'inférence côté serveur.
        Format : ``{"type": "person", "bbox": [...], "confidence": 0.9, ...}``."""
        raise NotImplementedError
        yield  # pragma: no cover  (async gen contract)

    # ── PTZ (si supporté) ─────────────────────────────────────
    async def ptz_move(self, pan: float, tilt: float, zoom: float) -> None:
        raise NotImplementedError

    async def ptz_preset(self, preset_id: int) -> None:
        raise NotImplementedError


# Registre des drivers · rempli en v0.4.6
_DRIVERS: dict[str, type[CameraDriver]] = {}


def register_driver(vendor: str, driver_cls: type[CameraDriver]) -> None:
    """Enregistre un driver pour un constructeur (appelé par chaque module)."""
    _DRIVERS[vendor.lower()] = driver_cls


def get_driver(vendor: str) -> Optional[type[CameraDriver]]:
    return _DRIVERS.get((vendor or "").lower())


def list_supported_vendors() -> list[str]:
    return sorted(_DRIVERS.keys())
