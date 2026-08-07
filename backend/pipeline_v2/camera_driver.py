"""v0.5.7 Phase 1 · Universal Camera API — Fondations.

Objectif : le reste de MG-VMS (pipeline, plugins, workflows, UI) ne
doit **jamais** connaître un constructeur (Reolink, Hikvision, Dahua…).
Toute la logique constructeur est confinée aux ``CameraDriver``.

Architecture :

    CameraManager (existant, DB)
        ↓
    CameraDeviceService (façade)
        ↓
    DriverRegistry.get(camera) → CameraDriver
        ↓
    Driver constructeur (ONVIF, Reolink HTTP, Hikvision ISAPI, …)
        ↓
    Caméra physique

Chaque driver expose un contrat unique (`CameraDriver` Protocol). Le
service demande une capabilité, le driver la traduit vers l'API native
ou lève une ``NotSupportedError`` qui devient un ``501 Not Implemented``
côté HTTP.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional, Protocol, runtime_checkable


# ═════════════════════════════════════════════════════════════════════════
# Capabilities — modèle universel
# ═════════════════════════════════════════════════════════════════════════
@dataclass
class Capabilities:
    """Capabilities déclarées par un driver.

    Chaque champ est un ``bool`` (supporté / non supporté). Le frontend
    lit ces flags pour n'afficher que les onglets/commandes pertinents.
    Zéro `if brand == "Reolink"` — uniquement `if caps.speaker`.
    """
    # Vidéo
    video: bool = True
    snapshot: bool = True
    multi_stream: bool = False       # profils HD + SD
    codec_h265: bool = False
    # Audio
    audio: bool = False
    speaker: bool = False
    microphone: bool = False
    talkback: bool = False
    siren: bool = False
    upload_wav: bool = False
    # Lumière
    ir: bool = False
    white_led: bool = False
    spotlight: bool = False
    flash: bool = False
    # PTZ
    ptz: bool = False
    zoom: bool = False
    ptz_presets: bool = False
    ptz_patrol: bool = False
    ptz_tracking: bool = False
    # IA embarquée
    ai_motion: bool = False
    ai_person: bool = False
    ai_vehicle: bool = False
    ai_animal: bool = False
    ai_face: bool = False
    ai_helmet: bool = False
    ai_anpr: bool = False
    ai_line_crossing: bool = False
    ai_intrusion: bool = False
    # Capteurs
    thermal: bool = False
    radar: bool = False
    pir: bool = False
    # I/O
    relay: bool = False
    digital_io: bool = False
    # Connectique
    wifi: bool = False
    poe: bool = False
    battery: bool = False
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
    # Interface caméra
    onvif: bool = True
    proprietary_api: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


# ═════════════════════════════════════════════════════════════════════════
# Erreurs
# ═════════════════════════════════════════════════════════════════════════
class DriverError(Exception):
    """Erreur générique d'un driver caméra."""


class NotSupportedError(DriverError):
    """La caméra ne supporte pas cette capacité (ex : PTZ sur une caméra fixe)."""


class AuthError(DriverError):
    """Authentification refusée (credentials invalides)."""


class UnreachableError(DriverError):
    """Caméra injoignable (timeout réseau)."""


# ═════════════════════════════════════════════════════════════════════════
# Interface CameraDriver
# ═════════════════════════════════════════════════════════════════════════
@dataclass
class DeviceInfo:
    """Informations d'identité + santé d'une caméra."""
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    firmware: Optional[str] = None
    serial: Optional[str] = None
    mac: Optional[str] = None
    ip: Optional[str] = None
    hardware_id: Optional[str] = None
    onvif_version: Optional[str] = None
    api_version: Optional[str] = None
    uptime_s: Optional[int] = None
    cpu_percent: Optional[float] = None
    ram_percent: Optional[float] = None
    temperature_c: Optional[float] = None
    poe: Optional[bool] = None
    wifi_rssi: Optional[int] = None
    battery_percent: Optional[int] = None
    storage: dict[str, Any] = field(default_factory=dict)
    network: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CameraDriver(Protocol):
    """Contrat d'un driver caméra.

    Un driver **doit** implémenter :
      - ``name`` : identifiant unique ("onvif-generic", "reolink", …)
      - ``capabilities()`` : retourne la matrice Capabilities.
      - ``get_info()`` : identité + santé.

    Les méthodes de commande (``snapshot``, ``ptz_move``, ``reboot``…)
    sont **optionnelles** : elles lèvent ``NotSupportedError`` si non
    implémentées. La façade ``CameraDeviceService`` transforme cette
    exception en HTTP 501.
    """
    name: str

    def capabilities(self) -> Capabilities: ...
    async def get_info(self) -> DeviceInfo: ...
    async def snapshot(self) -> bytes: ...
    async def reboot(self) -> None: ...
    # Commandes optionnelles — non-implémentées lèvent NotSupportedError.


# ═════════════════════════════════════════════════════════════════════════
# Registry
# ═════════════════════════════════════════════════════════════════════════
class DriverRegistry:
    """Registry des drivers disponibles.

    Chaque driver s'enregistre au chargement via ``registry.register()``.
    Le service demande un driver par nom :

        registry.register("onvif-generic", OnvifGenericDriver)
        registry.register("reolink", ReolinkDriver)
        driver = registry.build("reolink", camera)

    ``build()`` instancie le driver avec le doc caméra
    (`{ip, port, username, password, ...}`). Les instances ne sont
    **pas** mémoïsées (une nouvelle instance par appel) — les drivers
    doivent maintenir leur propre pool HTTP interne s'ils veulent.
    """
    def __init__(self) -> None:
        self._factories: dict[str, type] = {}
        self._default = "onvif-generic"

    def register(self, name: str, factory: type) -> None:
        self._factories[name] = factory

    def known(self) -> list[str]:
        return sorted(self._factories.keys())

    def build(self, name: str, camera: dict) -> Optional[CameraDriver]:
        factory = self._factories.get(name)
        if factory is None:
            return None
        try:
            return factory(camera)
        except Exception:
            return None

    def build_for(self, camera: dict) -> tuple[CameraDriver | None, str, str | None]:
        """Retourne (driver, name_effectif, warning|None) selon la caméra.

        Priorité :
          1. ``camera['driver']`` explicite (ex : « reolink »).
          2. ``camera['brand']`` mappé (ex : brand=reolink → driver=reolink).
          3. Fallback ``onvif-generic``.
        """
        requested = camera.get("driver") or camera.get("brand") or self._default
        requested = str(requested).lower().strip()
        # Mapping tolérant (brand → driver name)
        alias = {
            "onvif": "onvif-generic",
            "hikvision": "hikvision",
            "reolink": "reolink",
            "dahua": "dahua",
        }
        requested = alias.get(requested, requested)

        driver = self.build(requested, camera)
        if driver is not None:
            return driver, requested, None
        # Fallback vers ONVIF générique.
        fallback = self.build(self._default, camera)
        warning = (
            f"Driver '{requested}' introuvable (connus: {self.known()}). "
            f"Fallback vers '{self._default}'."
        )
        return fallback, self._default, warning


# Instance globale — les drivers concrets s'enregistrent au chargement
# (voir `pipeline_v2/drivers/*.py`).
driver_registry = DriverRegistry()
