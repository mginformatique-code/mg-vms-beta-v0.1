"""Camera API · Contract commun (ABC) + dataclasses de sortie.

Toutes les méthodes lèvent des exceptions typées de `exceptions.py`.
Les méthodes non supportées par un provider lèvent `UnsupportedCapability`.
"""
from __future__ import annotations

import abc
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .exceptions import UnsupportedCapability


# ── Dataclasses de sortie (JSON-friendly) ──────────────────────────────────

@dataclass
class DeviceInfo:
    manufacturer: str = ""
    model: str = ""
    firmware: str = ""
    hardware: str = ""
    serial: str = ""
    name: str = ""
    channels: int = 1
    raw: dict = field(default_factory=dict)   # payload brut du provider (debug)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)     # jamais dans les réponses API par défaut
        return d


@dataclass
class Capabilities:
    """Capacités détectées. Structure APLATIE et STABLE, indépendante du provider."""
    ptz: bool = False
    ptz_zoom: bool = False
    ir: bool = False
    ir_modes: list[str] = field(default_factory=list)
    light: bool = False
    siren: bool = False
    audio_talk: bool = False
    recording: bool = False
    sd_storage: bool = False
    motion_detection: bool = False
    ai_detection: bool = False
    channels: int = 1
    raw: dict = field(default_factory=dict)   # payload brut (debug/évolutions)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d


@dataclass
class NetworkInfo:
    ip: str = ""
    mac: str = ""
    gateway: str = ""
    netmask: str = ""
    dhcp: bool = False
    http_port: Optional[int] = None
    https_port: Optional[int] = None
    rtsp_port: Optional[int] = None
    onvif_port: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UserInfo:
    username: str = ""
    role: str = ""      # admin | user | viewer | ...
    level: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Contract commun ────────────────────────────────────────────────────────

class CameraApiProvider(abc.ABC):
    """Abstract Base Class — TOUS les providers en héritent.

    Cycle de vie recommandé :
        provider = SomeProvider(cam_config)
        async with provider:
            info = await provider.get_device_info()
            caps = await provider.get_capabilities()

    `__aenter__` = login() ; `__aexit__` = logout() + close(). Idempotent.
    """

    #: Identifiant technique du provider — utilisé par le registry (ex. "reolink")
    name: str = "base"

    def __init__(self, config: dict):
        """`config` = fiche caméra (dict) — voir `_cam_to_config()` côté routes."""
        self.config = config
        self.camera_id: str = config.get("id", "")

    # ── async context manager (login/logout auto) ──
    async def __aenter__(self):
        await self.login()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            await self.logout()
        except Exception:
            pass
        await self.close()

    # ── Contrat obligatoire ──
    @abc.abstractmethod
    async def login(self) -> None:
        """Ouvre la session (token/digest/cookie). Lève AuthenticationFailed
        ou DeviceUnreachable en cas d'échec — jamais silencieux."""

    @abc.abstractmethod
    async def logout(self) -> None:
        """Ferme la session côté caméra si applicable (idempotent)."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Libère les ressources locales (client HTTP, sockets)."""

    @abc.abstractmethod
    async def get_device_info(self) -> DeviceInfo:
        ...

    @abc.abstractmethod
    async def get_capabilities(self) -> Capabilities:
        ...

    # ── Optionnel (fallback = UnsupportedCapability) ──
    async def get_network_info(self) -> NetworkInfo:
        raise UnsupportedCapability(f"{self.name}: get_network_info non supporté")

    async def get_users(self) -> list[UserInfo]:
        raise UnsupportedCapability(f"{self.name}: get_users non supporté")

    async def get_ir(self) -> dict:
        raise UnsupportedCapability(f"{self.name}: get_ir non supporté")

    async def set_ir(self, mode: str) -> None:
        raise UnsupportedCapability(f"{self.name}: set_ir non supporté")

    async def get_ptz(self) -> dict:
        raise UnsupportedCapability(f"{self.name}: get_ptz non supporté")

    async def ptz_move(self, direction: str, speed: float = 0.5) -> None:
        raise UnsupportedCapability(f"{self.name}: ptz_move non supporté")

    async def ptz_stop(self) -> None:
        raise UnsupportedCapability(f"{self.name}: ptz_stop non supporté")

    async def get_light(self) -> dict:
        raise UnsupportedCapability(f"{self.name}: get_light non supporté")

    async def set_light(self, enabled: bool, brightness: Optional[int] = None) -> None:
        raise UnsupportedCapability(f"{self.name}: set_light non supporté")

    async def get_siren(self) -> dict:
        raise UnsupportedCapability(f"{self.name}: get_siren non supporté")

    async def set_siren(self, enabled: bool, duration: Optional[int] = None) -> None:
        raise UnsupportedCapability(f"{self.name}: set_siren non supporté")

    async def get_storage(self) -> list[dict]:
        raise UnsupportedCapability(f"{self.name}: get_storage non supporté")

    async def search_recordings(self, *, channel: int = 0, start: Any = None,
                                  end: Any = None) -> list[dict]:
        raise UnsupportedCapability(f"{self.name}: search_recordings non supporté")
