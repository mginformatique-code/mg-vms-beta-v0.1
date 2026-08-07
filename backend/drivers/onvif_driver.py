"""Driver ONVIF universel (base commune de toutes les caméras IP).

Utilise la librairie ``onvif_zeep`` (déjà pinnée dans requirements.txt).
Compatible avec toute caméra ONVIF Profile S/T (99% du marché IP).

Points couverts :
  - `connect()` : ouverture session Device Management + Media
  - `get_device_info()` : Manufacturer / Model / Firmware / Serial / MAC
  - `get_capabilities()` : lecture ONVIF ``GetCapabilities`` + probes PTZ/audio
  - `get_streams()` : ``GetProfiles`` + ``GetStreamUri`` par profil
  - `ptz_move` / `ptz_preset` : Profile S PTZ
  - IR (``ImagingSettings.IrCutFilter``)

Ce driver ne prétend PAS gérer sirène, spotlight, PIR — ces fonctions sont
propriétaires et sont fournies par les drivers constructeur (Reolink, Dahua…).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional
from urllib.parse import urlparse

from .camera_driver import CameraDriver
from .camera_models import (
    CameraCapabilities, DeviceInfo, DeviceStatus, StreamInfo, IRMode, LightMode,
)
from .exceptions import (
    DeviceConnectionError, AuthenticationError, UnsupportedCapabilityError,
)
from .registry import register_driver

logger = logging.getLogger("drivers.onvif")


class ONVIFDriver(CameraDriver):
    """Driver ONVIF universel (Profile S/T).

    Ce driver est le fallback pour toutes les caméras non identifiées et
    la base pour les drivers constructeur (qui étendent les capacités
    propriétaires manquantes).
    """

    vendor = "onvif"

    #: Métadonnées v0.5.7 · Driver Health
    MANIFEST: dict = {
        "driver": "onvif",
        "version": "1.0",
        "status": "stable",
        "api": "ONVIF Profile S/T (SOAP + Zeep)",
        "protocols": ["onvif", "rtsp", "http"],
        "supported_models": ["*"],
        "coverage_pct": 90,
    }

    def __init__(self, host: str, username: str, password: str,
                 port: Optional[int] = None):
        super().__init__(host, username, password, port or 80)
        self._camera = None    # onvif.ONVIFCamera lazy
        self._media = None
        self._ptz = None
        self._imaging = None
        self._device_info_cache: Optional[DeviceInfo] = None

    async def connect(self) -> None:
        """Instancie l'objet ONVIF et vérifie la connexion.

        L'appel ONVIF est sync (zeep) — délégué à un thread pour ne pas
        bloquer la boucle asyncio.
        """
        try:
            await asyncio.to_thread(self._sync_connect)
            self._connected = True
        except AuthenticationError:
            raise
        except Exception as e:
            msg = str(e).lower()
            if "auth" in msg or "unauthorized" in msg or "401" in msg:
                raise AuthenticationError(str(e))
            raise DeviceConnectionError(f"ONVIF connect {self.host}:{self.port} — {e}")

    def _sync_connect(self) -> None:
        # Import paresseux (onvif_zeep est lourd)
        from onvif import ONVIFCamera
        self._camera = ONVIFCamera(self.host, self.port, self.username,
                                   self.password, no_cache=True)
        # Vérifie tout de suite l'auth via GetDeviceInformation
        info = self._camera.devicemgmt.GetDeviceInformation()
        self._device_info_cache = DeviceInfo(
            manufacturer=info.Manufacturer or "",
            model=info.Model or "",
            firmware=info.FirmwareVersion or None,
            serial=info.SerialNumber or None,
            hardware=info.HardwareId or None,
            ip=self.host,
        )
        # Récupère MAC via network interfaces (best-effort)
        try:
            nets = self._camera.devicemgmt.GetNetworkInterfaces() or []
            if nets and nets[0].Info:
                self._device_info_cache.mac = nets[0].Info.HwAddress
        except Exception:
            pass
        # Media service (streams)
        try:
            self._media = self._camera.create_media_service()
        except Exception as e:
            logger.debug("ONVIF media service indispo pour %s (%s)", self.host, e)
        # PTZ service (optionnel)
        try:
            self._ptz = self._camera.create_ptz_service()
        except Exception:
            self._ptz = None
        # Imaging service (IR filter)
        try:
            self._imaging = self._camera.create_imaging_service()
        except Exception:
            self._imaging = None

    async def get_device_info(self) -> DeviceInfo:
        if not self._connected:
            await self.connect()
        return self._device_info_cache or DeviceInfo(ip=self.host)

    async def get_capabilities(self) -> CameraCapabilities:
        if self._caps is not None:
            return self._caps
        if not self._connected:
            await self.connect()
        caps = CameraCapabilities(onvif=True)
        # PTZ ?
        if self._ptz is not None:
            try:
                # GetConfigurations lève si aucun PTZ
                cfgs = await asyncio.to_thread(self._ptz.GetConfigurations)
                if cfgs:
                    caps.ptz = True
                    caps.zoom = True   # supposé (à raffiner selon config)
            except Exception:
                pass
        # Imaging → IR cut filter
        if self._imaging is not None:
            try:
                vsrcs = await asyncio.to_thread(self._imaging.GetVideoSources)
                if vsrcs:
                    settings = await asyncio.to_thread(
                        self._imaging.GetImagingSettings, {"VideoSourceToken": vsrcs[0].token})
                    if getattr(settings, "IrCutFilter", None) is not None:
                        caps.ir_cut_filter = True
                        caps.ir_control = True
            except Exception:
                pass
        # Streams
        try:
            streams = await self.get_streams()
            if streams:
                # Max résolution / fps depuis le profil main
                main = streams[0]
                caps.max_resolution = main.resolution
                caps.max_fps = main.fps
        except Exception:
            pass
        self._caps = caps
        return caps

    async def get_streams(self) -> list[StreamInfo]:
        if not self._connected:
            await self.connect()
        if self._media is None:
            return []
        try:
            profiles = await asyncio.to_thread(self._media.GetProfiles) or []
        except Exception:
            return []
        out: list[StreamInfo] = []
        for i, p in enumerate(profiles):
            try:
                req = self._media.create_type("GetStreamUri")
                req.ProfileToken = p.token
                req.StreamSetup = {
                    "Stream": "RTP-Unicast",
                    "Transport": {"Protocol": "RTSP"},
                }
                uri = await asyncio.to_thread(self._media.GetStreamUri, req)
                v = getattr(p, "VideoEncoderConfiguration", None)
                resolution = (0, 0)
                fps = 0
                codec = "h264"
                bitrate = 0
                if v:
                    res = getattr(v, "Resolution", None)
                    if res:
                        resolution = (int(res.Width or 0), int(res.Height or 0))
                    rate = getattr(v, "RateControl", None)
                    if rate:
                        fps = int(getattr(rate, "FrameRateLimit", 0) or 0)
                        bitrate = int(getattr(rate, "BitrateLimit", 0) or 0)
                    encoding = getattr(v, "Encoding", "H264") or "H264"
                    codec = "h265" if "265" in str(encoding).upper() else "h264"
                out.append(StreamInfo(
                    name=("main" if i == 0 else "sub" if i == 1 else f"stream{i}"),
                    url=uri.Uri,
                    resolution=resolution, fps=fps, codec=codec,
                    bitrate_kbps=bitrate,
                ))
            except Exception as e:
                logger.debug("ONVIF GetStreamUri profil %s indispo (%s)", p.token, e)
        return out

    # ── PTZ ─────────────────────────────────────────────────────
    async def _ptz_move(self, direction: str, speed: float) -> None:
        if self._ptz is None:
            raise UnsupportedCapabilityError("Service PTZ indispo sur cette caméra ONVIF")
        # Table simple direction → PanTilt.x/y
        mapping = {
            "up": (0.0, 1.0), "down": (0.0, -1.0),
            "left": (-1.0, 0.0), "right": (1.0, 0.0),
            "upleft": (-1.0, 1.0), "upright": (1.0, 1.0),
            "downleft": (-1.0, -1.0), "downright": (1.0, -1.0),
            "stop": (0.0, 0.0),
        }
        x, y = mapping.get(direction.lower(), (0.0, 0.0))
        v = max(0.0, min(1.0, speed))
        profiles = await asyncio.to_thread(self._media.GetProfiles)
        if not profiles:
            raise UnsupportedCapabilityError("Aucun profil ONVIF pour PTZ")
        token = profiles[0].token
        req = self._ptz.create_type("ContinuousMove")
        req.ProfileToken = token
        req.Velocity = {"PanTilt": {"x": x * v, "y": y * v}}
        if direction == "stop":
            await asyncio.to_thread(self._ptz.Stop, {"ProfileToken": token})
        else:
            await asyncio.to_thread(self._ptz.ContinuousMove, req)

    async def _ptz_zoom(self, value: float) -> None:
        if self._ptz is None:
            raise UnsupportedCapabilityError("Service PTZ indispo")
        v = max(-1.0, min(1.0, value))
        profiles = await asyncio.to_thread(self._media.GetProfiles)
        req = self._ptz.create_type("ContinuousMove")
        req.ProfileToken = profiles[0].token
        req.Velocity = {"Zoom": {"x": v}}
        await asyncio.to_thread(self._ptz.ContinuousMove, req)

    async def _ptz_preset(self, preset_id: int) -> None:
        if self._ptz is None:
            raise UnsupportedCapabilityError("Service PTZ indispo")
        profiles = await asyncio.to_thread(self._media.GetProfiles)
        req = self._ptz.create_type("GotoPreset")
        req.ProfileToken = profiles[0].token
        req.PresetToken = str(preset_id)
        await asyncio.to_thread(self._ptz.GotoPreset, req)

    # ── IR (bascule cut filter) ─────────────────────────────────
    async def _set_ir_mode(self, mode: IRMode) -> None:
        if self._imaging is None:
            raise UnsupportedCapabilityError("Service Imaging ONVIF indispo")
        vsrcs = await asyncio.to_thread(self._imaging.GetVideoSources)
        if not vsrcs:
            raise UnsupportedCapabilityError("Aucune source vidéo ONVIF")
        token = vsrcs[0].token
        # ONVIF IrCutFilter accepte AUTO / ON / OFF
        onvif_mode = {IRMode.AUTO: "AUTO", IRMode.ON: "ON", IRMode.OFF: "OFF"}[mode]
        req = self._imaging.create_type("SetImagingSettings")
        req.VideoSourceToken = token
        req.ImagingSettings = {"IrCutFilter": onvif_mode}
        await asyncio.to_thread(self._imaging.SetImagingSettings, req)


register_driver("onvif", ONVIFDriver)
register_driver("generic", ONVIFDriver)
