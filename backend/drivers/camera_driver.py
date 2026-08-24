"""Contrat abstrait CameraDriver.

Chaque driver constructeur (ONVIF, Reolink, Dahua, Hikvision, …) implémente
cette interface. Le service caméra (``CameraDeviceService``) ne connaît que
cette classe.

Règle absolue (v0.4.6) :
    Une commande dont la caméra ne supporte pas la capacité DOIT lever
    ``UnsupportedCapabilityError`` — jamais retourner silencieusement.
    Vérification via ``self._require(capability_name)``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from .camera_models import (
    CameraCapabilities, DeviceInfo, DeviceStatus, StreamInfo,
    IRMode, LightMode,
)
from .exceptions import UnsupportedCapabilityError


class CameraDriver(ABC):
    """Contrat unique pour toutes les caméras IP.

    Toutes les méthodes sont ``async``. L'instance mémorise les
    ``CameraCapabilities`` remontées par ``probe()`` pour éviter les
    appels redondants et pour permettre à ``_require()`` de bloquer
    proprement les commandes non-supportées.

    v0.4.6 · les implémentations concrètes NE DOIVENT PAS être invoquées
    directement par le code métier. Toujours passer par
    ``CameraDeviceService.get_driver(camera_id)``.
    """

    vendor: str = "generic"

    def __init__(self, host: str, username: str, password: str,
                 port: Optional[int] = None):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self._caps: Optional[CameraCapabilities] = None
        self._connected: bool = False

    # ── Cycle de vie ─────────────────────────────────────────────
    @abstractmethod
    async def connect(self) -> None:
        """Ouvre la session avec la caméra (auth, handshake, découverte).

        Lève :
          - ``DeviceConnectionError`` si injoignable
          - ``AuthenticationError`` si identifiants rejetés
        """

    async def disconnect(self) -> None:
        """Ferme proprement la session. No-op par défaut (override si besoin)."""
        self._connected = False

    async def health(self) -> bool:
        """Renvoie True si la caméra répond à un ping/heartbeat léger."""
        try:
            await self.get_device_info()
            return True
        except Exception:
            return False

    # ── Introspection ────────────────────────────────────────────
    @abstractmethod
    async def get_device_info(self) -> DeviceInfo:
        """Manufacturer, model, firmware, serial, mac, ip."""

    @abstractmethod
    async def get_capabilities(self) -> CameraCapabilities:
        """Retourne (et mémorise) les capacités réelles de la caméra."""

    async def get_status(self) -> DeviceStatus:
        """État runtime — par défaut minimal, à surcharger si constructeur riche."""
        online = await self.health()
        return DeviceStatus(online=online)

    async def get_streams(self) -> list[StreamInfo]:
        """Liste des sous-flux vidéo. Par défaut : []."""
        return []

    # ── Commandes physiques (bloquées si non supportées) ─────────
    async def set_light(self, enabled: bool, brightness: Optional[int] = None,
                        mode: LightMode = LightMode.ON) -> None:
        """Contrôle spotlight / white light / supplement light unifié."""
        self._require_any("spotlight", "white_light")
        await self._set_light(enabled=enabled, brightness=brightness, mode=mode)

    async def set_ir_mode(self, mode: IRMode) -> None:
        """Contrôle IR unifié — bloqué si `ir_control` absent."""
        self._require("ir_control")
        await self._set_ir_mode(mode)

    async def set_siren(self, enabled: bool, duration: Optional[int] = None) -> None:
        """Déclenchement sirène (optionnel: durée en secondes)."""
        self._require("siren")
        await self._set_siren(enabled=enabled, duration=duration)

    async def start_audio(self) -> None:
        self._require("audio_output")
        await self._start_audio()

    async def stop_audio(self) -> None:
        self._require("audio_output")
        await self._stop_audio()

    async def talk_to_camera(self, pcm_bytes: bytes) -> None:
        """Talk-back : envoie un chunk audio (PCM 16-bit 8kHz mono standard)."""
        self._require("two_way_audio")
        await self._talk_to_camera(pcm_bytes)

    async def ptz_move(self, direction: str, speed: float = 0.5) -> None:
        """direction ∈ {up, down, left, right, upleft, upright, downleft, downright, stop}."""
        self._require("ptz")
        await self._ptz_move(direction, speed)

    async def ptz_zoom(self, value: float) -> None:
        """Zoom continu (-1.0 = tele → +1.0 = wide) ou position absolue (0…1)."""
        self._require("zoom")
        await self._ptz_zoom(value)

    async def ptz_preset(self, preset_id: int) -> None:
        """Rappel d'un preset PTZ enregistré côté caméra."""
        self._require("ptz")
        await self._ptz_preset(preset_id)

    # ── Stockage local / enregistrements (v3.5) ───────────────────
    async def get_storage(self) -> list[dict]:
        """Liste les supports de stockage locaux (carte SD / eMMC / HDD)."""
        self._require("sdcard")
        raise UnsupportedCapabilityError("Stockage local non implémenté par ce driver")

    async def search_recordings(self, start: datetime, end: datetime,
                                 stream: str = "main") -> list[dict]:
        """Liste les enregistrements présents sur le stockage local caméra.

        ``stream`` : "main" (HD) ou "sub" (SD). Les drivers qui n'exposent
        qu'un seul flux d'enregistrement ignorent simplement ce paramètre.
        """
        self._require("sdcard")
        raise UnsupportedCapabilityError("Enregistrements locaux non implémentés par ce driver")

    async def get_recording_source(self, file_name: str, stream: str = "main") -> str:
        """URL de lecture d'un enregistrement local (proxy/lecture directe)."""
        self._require("sdcard")
        raise UnsupportedCapabilityError("Lecture d'enregistrement local non implémentée par ce driver")

    # ── Réseau (v3.7) ─────────────────────────────────────────────
    async def get_network(self) -> dict:
        """Paramètres réseau détaillés (ports, protocoles, UID, WiFi…).

        Retourne un dict à clés libres — chaque driver remonte ce que son
        API expose réellement, le frontend n'affiche que les clés présentes.
        """
        raise UnsupportedCapabilityError("Paramètres réseau non implémentés par ce driver")

    # ── Hooks à implémenter par les drivers concrets ─────────────
    async def _set_light(self, enabled: bool, brightness: Optional[int],
                          mode: LightMode) -> None:
        raise UnsupportedCapabilityError("Contrôle lumière non implémenté par ce driver")

    async def _set_ir_mode(self, mode: IRMode) -> None:
        raise UnsupportedCapabilityError("Contrôle IR non implémenté par ce driver")

    async def _set_siren(self, enabled: bool, duration: Optional[int]) -> None:
        raise UnsupportedCapabilityError("Sirène non implémentée par ce driver")

    async def _start_audio(self) -> None:
        raise UnsupportedCapabilityError("Sortie audio non implémentée par ce driver")

    async def _stop_audio(self) -> None:
        raise UnsupportedCapabilityError("Sortie audio non implémentée par ce driver")

    async def _talk_to_camera(self, pcm_bytes: bytes) -> None:
        raise UnsupportedCapabilityError("Talk-back non implémenté par ce driver")

    async def _ptz_move(self, direction: str, speed: float) -> None:
        raise UnsupportedCapabilityError("PTZ non implémenté par ce driver")

    async def _ptz_zoom(self, value: float) -> None:
        raise UnsupportedCapabilityError("Zoom non implémenté par ce driver")

    async def _ptz_preset(self, preset_id: int) -> None:
        raise UnsupportedCapabilityError("Presets PTZ non implémentés par ce driver")

    # ── Utilitaires ──────────────────────────────────────────────
    def _require(self, cap: str) -> None:
        """Lève ``UnsupportedCapabilityError`` si la capacité n'est pas supportée."""
        caps = self._caps
        if caps is None:
            return  # probe pas encore fait, on laisse passer (le driver concret vérifiera)
        if not getattr(caps, cap, False):
            raise UnsupportedCapabilityError(
                f"Cette caméra ne supporte pas la capacité '{cap}'",
                code="unsupported_capability",
            )

    def _require_any(self, *caps: str) -> None:
        """Autorise si AU MOINS UNE des capacités est présente."""
        current = self._caps
        if current is None:
            return
        if not any(getattr(current, c, False) for c in caps):
            raise UnsupportedCapabilityError(
                f"Cette caméra ne supporte aucune des capacités : {', '.join(caps)}",
                code="unsupported_capability",
            )
