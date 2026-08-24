"""Driver Reolink — wrapper autour de la librairie ``reolink-aio``.

v3.5 · Remplace l'implémentation HTTP JSON faite main (v3.4) par la
librairie tierce ``reolink-aio`` (utilisée par l'intégration officielle
Home Assistant) : gère les DEUX protocoles Reolink — l'API JSON HTTP
(``/api.cgi``, port 443) ET le protocole binaire propriétaire Baichuan
(port 9000, chiffré, utilisé par l'app mobile officielle — identifié par
capture Wireshark) — avec auth par token et retries intégrés.

Contexte (voir CHANGELOG v3.4.x pour le détail) : le driver fait main
détectait déjà correctement les capacités une fois le port et les clés
``GetAbility`` corrigés, mais TOUTES les commandes de contrôle
(``SetWhiteLed``, ``SetIrLights``, ``AudioAlarmPlay``) échouaient avec
``ability error`` (rspCode -26). Confirmé avec reolink-aio (implémentation
indépendante) : même erreur avec le compte "test" (utilisateur, pas admin),
succès immédiat avec le compte "admin" — c'était une restriction de
permission côté compte caméra, jamais un bug de code.

reolink-aio est conservé malgré cette conclusion car il ouvre l'accès aux
enregistrements SD card (``request_vod_files``/``download_vod``),
totalement absent du driver fait main — cf. ``get_storage()`` /
``search_recordings()`` ci-dessous.

Documentation officielle Reolink : https://reolink.com/support/documentation/reolink-api/
Librairie : https://github.com/starkillerOG/reolink_aio
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from reolink_aio.api import Host
from reolink_aio.exceptions import (
    ApiError, CredentialsInvalidError, LoginError, ReolinkConnectionError,
    ReolinkError, ReolinkTimeoutError,
)

from .camera_models import (
    CameraCapabilities, DeviceInfo, DeviceStatus, IRMode, LightMode,
)
from .exceptions import (
    AuthenticationError, DeviceConnectionError, UnsupportedCapabilityError,
    CameraDriverError, CommandTimeoutError,
)
from .onvif_driver import ONVIFDriver
from .registry import register_driver

logger = logging.getLogger("drivers.reolink")

#: MG-VMS ne gère pas encore les NVR Reolink multi-canaux — chaque
#: caméra MG-VMS correspond à un unique channel 0 côté reolink-aio.
_CHANNEL = 0


class ReolinkDriver(ONVIFDriver):
    """Driver Reolink — étend l'ONVIF avec la librairie ``reolink-aio``."""

    vendor = "reolink"

    #: Métadonnées v3.5 · Driver Health
    MANIFEST: dict = {
        "driver": "reolink",
        "version": "2.0",
        "status": "stable",
        "api": "reolink-aio (JSON API + Baichuan) + ONVIF fallback",
        "protocols": ["reolink_api", "baichuan", "onvif", "rtsp", "http"],
        "supported_models": [
            "RLC-1224A", "RLC-820A", "RLC-810A", "RLC-410A", "RLC-510A",
            "RLC-511WA", "RLC-81MA", "Argus 3 Pro", "Duo 2", "TrackMix", "Doorbell",
        ],
        "coverage_pct": 92,
    }

    def __init__(self, host: str, username: str, password: str,
                 port: Optional[int] = None):
        # `port` ici est le port ONVIF (transmis par
        # camera_device_service.get_driver()) — reolink-aio gère lui-même
        # la découverte des ports HTTP(S)/Baichuan réels de la caméra,
        # aucun besoin de le lui transmettre.
        super().__init__(host, username, password, port or 80)
        self._host_api: Optional[Host] = None

    async def connect(self) -> None:
        # Base ONVIF (streams, PTZ) — best-effort, reolink-aio est la
        # source de vérité pour le reste.
        try:
            await super().connect()
        except Exception as e:
            logger.debug("Reolink : ONVIF connect KO (%s), on continue avec reolink-aio", e)
            self._device_info_cache = DeviceInfo(manufacturer="Reolink", ip=self.host)
            self._connected = True

        self._host_api = Host(self.host, self.username, self.password)
        try:
            await self._host_api.get_host_data()
        except CredentialsInvalidError as e:
            raise AuthenticationError(f"Reolink : identifiants rejetés ({e})") from e
        except LoginError as e:
            raise AuthenticationError(f"Reolink : login refusé ({e})") from e
        except ReolinkTimeoutError as e:
            raise CommandTimeoutError(f"Reolink {self.host} : délai dépassé ({e})") from e
        except ReolinkConnectionError as e:
            raise DeviceConnectionError(f"Reolink {self.host} injoignable ({e})") from e
        except ReolinkError as e:
            raise CameraDriverError(f"Reolink {self.host} : {e}") from e

        di = self._device_info_cache or DeviceInfo(ip=self.host)
        di.manufacturer = "Reolink"
        di.model = self._host_api.model or di.model
        di.firmware = self._host_api.sw_version or di.firmware
        di.serial = self._host_api.serial(_CHANNEL) or di.serial
        di.mac = self._host_api.mac_address or di.mac
        self._device_info_cache = di
        self._connected = True

    async def disconnect(self) -> None:
        if self._host_api is not None:
            try:
                await self._host_api.logout()
            except Exception:
                pass
            self._host_api = None
        await super().disconnect()

    async def get_capabilities(self) -> CameraCapabilities:
        if self._caps is not None:
            return self._caps
        # Base ONVIF + surcouche
        caps = await super().get_capabilities()
        caps.reolink_api = True
        # SetIrLights est l'une des commandes Reolink les plus universelles
        # — la détection ONVIF standard (IrCutFilter) est peu fiable sur
        # ces caméras et laissait ir_control à False.
        caps.ir_control = True

        chn_caps: set = set()
        if self._host_api is not None:
            try:
                chn_caps = set(self._host_api.capabilities.get(_CHANNEL) or [])
            except Exception:
                chn_caps = set()

        # v3.5 · Clés confirmées via host.capabilities réel (RLC-81MA,
        # reolink-aio 0.21.10) — remplace les clés GetAbility brutes
        # (alarmAudio/supportFLswitch/…) par les noms normalisés de la
        # librairie, plus stables entre modèles/firmwares.
        caps.spotlight = "floodLight" in chn_caps
        caps.siren = "siren" in chn_caps
        caps.audio_input = "audio" in chn_caps
        caps.audio_output = "volume" in chn_caps
        caps.two_way_audio = caps.audio_input and caps.audio_output
        caps.microphone = caps.audio_input
        caps.speaker = caps.audio_output
        caps.pir_sensor = "PIR" in chn_caps

        ai_map = {"ai_people": "person", "ai_vehicle": "vehicle",
                  "ai_dog_cat": "animal", "ai_face": "face"}
        ai_feats = [label for key, label in ai_map.items() if key in chn_caps]
        caps.onboard_ai = bool(ai_feats)
        caps.onboard_ai_features = tuple(ai_feats)

        try:
            caps.battery = self._host_api.battery_percentage(_CHANNEL) is not None
        except Exception:
            caps.battery = False

        # v3.4 · `sdcard` existait dans CameraCapabilities mais rien ne le
        # renseignait jamais pour Reolink. reolink-aio expose hdd_list +
        # hdd_available() directement (confirmé en prod : hdd 0 = carte SD).
        try:
            caps.sdcard = any(self._host_api.hdd_available(i) for i in self._host_api.hdd_list)
        except Exception:
            caps.sdcard = False

        self._caps = caps
        return caps

    async def get_status(self) -> DeviceStatus:
        st = await super().get_status()
        if self._host_api is not None:
            if self._caps and self._caps.battery:
                try:
                    st.battery_percent = self._host_api.battery_percentage(_CHANNEL)
                except Exception:
                    pass
            try:
                hdds = self._host_api.hdd_list
                if hdds:
                    idx = hdds[0]
                    available = self._host_api.hdd_available(idx)
                    st.sd_card_status = "ok" if available else "missing"
                    if available:
                        # v3.7 · hdd_storage() renvoie le pourcentage UTILISÉ,
                        # pas libre — la docstring de reolink-aio dit bien
                        # "amount of storage used in %" et son calcul est
                        # `100 * (1 - size/capacity)` où `size` est l'espace
                        # LIBRE restant et `capacity` le total. La v3.5
                        # faisait `100 - valeur`, inversant l'affichage (une
                        # carte pleine à 99 % s'affichait à 1 % d'usage).
                        st.sd_card_used_percent = max(0, min(100, round(self._host_api.hdd_storage(idx))))
            except Exception:
                pass
        return st

    # ── Spotlight ────────────────────────────────────────────────
    async def _set_light(self, enabled: bool, brightness: Optional[int],
                          mode: LightMode) -> None:
        try:
            await self._host_api.set_whiteled(
                _CHANNEL, state=enabled,
                brightness=brightness if brightness is not None else None,
            )
        except ApiError as e:
            raise CameraDriverError(f"Reolink SetWhiteLed → {e}", code="device_error") from e

    # ── Siren ─────────────────────────────────────────────────────
    async def _set_siren(self, enabled: bool, duration: Optional[int]) -> None:
        try:
            await self._host_api.set_siren(
                _CHANNEL, enable=enabled, duration=duration if enabled else None,
            )
        except ApiError as e:
            raise CameraDriverError(f"Reolink SetSiren → {e}", code="device_error") from e

    # ── IR mode ───────────────────────────────────────────────────
    async def _set_ir_mode(self, mode: IRMode) -> None:
        try:
            if mode == IRMode.AUTO:
                # reolink-aio set_ir_lights est un simple ON/OFF forcé — le
                # mode Auto natif Reolink se pilote via SetIrLights state="Auto",
                # non exposé en high-level. On retombe sur ON (comportement
                # "actif la nuit" par défaut) plutôt que de lever une erreur.
                await self._host_api.set_ir_lights(_CHANNEL, True)
            else:
                await self._host_api.set_ir_lights(_CHANNEL, mode == IRMode.ON)
        except ApiError as e:
            raise CameraDriverError(f"Reolink SetIrLights → {e}", code="device_error") from e

    # ── Audio (talkback nécessite un flux temps réel séparé) ─────
    async def _start_audio(self) -> None:
        raise UnsupportedCapabilityError(
            "Talkback Reolink nécessite un flux audio temps réel dédié (à implémenter)")

    async def _stop_audio(self) -> None:
        raise UnsupportedCapabilityError("Cf _start_audio")

    # ── Réseau (v3.7) ────────────────────────────────────────────
    async def get_network(self) -> dict:
        """Ports, protocoles et identité réseau remontés par reolink-aio."""
        if self._host_api is None:
            raise UnsupportedCapabilityError("Session Reolink non initialisée")
        h = self._host_api

        def _safe(name):
            try:
                v = getattr(h, name)
                return v() if callable(v) else v
            except Exception:
                return None

        return {
            "mac": _safe("mac_address"),
            "uid": _safe("uid"),
            "wifi": _safe("wifi_connection"),
            "wifi_signal": _safe("wifi_signal") if _safe("wifi_connection") else None,
            "ports": {
                "http/https": _safe("port"),
                "rtsp": _safe("rtsp_port"),
                "rtmp": _safe("rtmp_port"),
                "onvif": _safe("onvif_port"),
            },
            "protocols": {
                "rtsp": _safe("rtsp_enabled"),
                "rtmp": _safe("rtmp_enabled"),
                "onvif": _safe("onvif_enabled"),
            },
        }

    # ── SD card / enregistrements locaux (nouveau, v3.5) ─────────
    async def get_storage(self) -> list[dict]:
        """Liste les supports de stockage locaux (carte SD / eMMC)."""
        if self._host_api is None:
            raise UnsupportedCapabilityError("Session Reolink non initialisée")
        out = []
        # `hdd_info` brut : capacity = total (Mo), size = espace LIBRE (Mo).
        raw = {int(h.get("number", i)): h for i, h in enumerate(self._host_api.hdd_info or [])}
        for idx in self._host_api.hdd_list:
            try:
                h = raw.get(idx, {})
                total_mb = float(h.get("capacity") or 0)
                free_mb = float(h.get("size") or 0)
                out.append({
                    "index": idx,
                    "available": self._host_api.hdd_available(idx),
                    "type": self._host_api.hdd_type(idx),
                    # v3.7 · hdd_storage() = pourcentage UTILISÉ (cf. get_status)
                    "used_percent": round(self._host_api.hdd_storage(idx)),
                    "total_bytes": int(total_mb * 1024 * 1024),
                    "free_bytes": int(free_mb * 1024 * 1024),
                })
            except Exception as e:
                logger.debug("Reolink hdd %s indispo (%s)", idx, e)
        return out

    async def search_recordings(self, start: datetime, end: datetime,
                                 stream: str = "main") -> list[dict]:
        """Liste les enregistrements présents sur la carte SD entre ``start`` et ``end``.

        v3.7.2 · La recherche est découpée en tranches d'UNE JOURNÉE.
        L'API Reolink ne sait pas répondre sur une plage qui traverse
        plusieurs jours calendaires : elle renvoie une liste VIDE, sans
        erreur, au lieu d'agréger. Mesuré sur une RLC-81MA :
          - 23 août 00:00 → 23 août 23:59  →  240 fichiers
          - 23 août 14:15 → 24 août 14:15  →    1 fichier (!)
          - 23 août 00:00 → 25 août 00:00  →    0 fichier
        Une recherche « 24 dernières heures » (le défaut de l'UI) tombait
        donc systématiquement dans ce piège et n'affichait qu'une poignée
        d'enregistrements sur des centaines réellement présents — sans le
        moindre message d'erreur. On interroge donc jour par jour puis on
        agrège, en bornant chaque tranche à l'intervalle demandé.

        ``stream`` : "main" (HD) ou "sub" (SD, plus léger).
        """
        if self._host_api is None:
            raise UnsupportedCapabilityError("Session Reolink non initialisée")
        if end <= start:
            return []

        out: list[dict] = []
        seen: set[str] = set()
        # Journées calendaires couvertes par [start, end]
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while day < end:
            day_end = day + timedelta(days=1)
            chunk_start = max(start, day)
            # 23:59:59 plutôt que minuit pile : la borne haute est inclusive
            # côté caméra et minuit appartient déjà au jour suivant.
            chunk_end = min(end, day_end - timedelta(seconds=1))
            if chunk_end > chunk_start:
                try:
                    _statuses, files = await self._host_api.request_vod_files(
                        _CHANNEL, chunk_start, chunk_end, stream=stream)
                except ApiError as e:
                    raise CameraDriverError(f"Reolink request_vod_files → {e}",
                                             code="device_error") from e
                except Exception as e:
                    logger.warning("Reolink recherche VOD %s : %s", chunk_start.date(), e)
                    files = []
                for f in files:
                    if f.file_name in seen:
                        continue
                    seen.add(f.file_name)
                    out.append({
                        "file_name": f.file_name,
                        "start_time": f.start_time.isoformat(),
                        "end_time": f.end_time.isoformat(),
                        "duration_s": f.duration.total_seconds(),
                        "size_bytes": f.size,
                        "type": f.type,
                    })
            day = day_end
        out.sort(key=lambda r: r["start_time"])
        return out

    async def get_recording_source(self, file_name: str, stream: str = "main") -> str:
        """URL de téléchargement d'un enregistrement SD (MP4 direct).

        v3.7 · Utilise ``VodRequestType.DOWNLOAD`` et non le défaut FLV.
        Le mode FLV par défaut construit une URL ``/flv?…&user=&password=``
        vers un service RTMP interne (port 1935) que la caméra referme
        immédiatement après le handshake TLS — confirmé en conditions
        réelles : ffmpeg ET curl échouent tous deux ("Error in the pull
        function" / "unexpected eof while reading"), aucun octet reçu.
        Le mode DOWNLOAD renvoie une URL ``/cgi-bin/api.cgi?cmd=Download``
        authentifiée par token qui sert le MP4 tel quel — vérifié : 200,
        ~5 Mo pour un clip de 5 min.

        ⚠ Le token de cette URL expire en quelques secondes : l'appelant
        DOIT la consommer immédiatement (le proxy ffmpeg de
        ``routes/devices.py`` la résout juste avant de lancer ffmpeg).
        Ne jamais la mettre en cache ni la renvoyer à un client.
        """
        if self._host_api is None:
            raise UnsupportedCapabilityError("Session Reolink non initialisée")
        from reolink_aio.enums import VodRequestType
        try:
            _mime, url = await self._host_api.get_vod_source(
                _CHANNEL, file_name, stream=stream,
                request_type=VodRequestType.DOWNLOAD)
        except ApiError as e:
            raise CameraDriverError(f"Reolink get_vod_source → {e}", code="device_error") from e
        return url


register_driver("reolink", ReolinkDriver)
