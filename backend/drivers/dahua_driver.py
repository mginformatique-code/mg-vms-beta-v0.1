"""Driver Dahua CGI (préparé, minimal — v0.4.6).

Interface CGI HTTP standard Dahua : ``http://<ip>/cgi-bin/…``.
Auth digest requise.

Cette V1 fournit :
  - Fallback ONVIF pour info / streams / PTZ (via héritage)
  - Squelette CGI pour white light + IR (à implémenter)

Extensions v0.4.7+ prévues : sirène (audioAlarm), MPTZ preset.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from .camera_models import CameraCapabilities, LightMode, IRMode
from .exceptions import UnsupportedCapabilityError, DeviceConnectionError
from .onvif_driver import ONVIFDriver
from .registry import register_driver

logger = logging.getLogger("drivers.dahua")


class DahuaDriver(ONVIFDriver):
    vendor = "dahua"

    #: Métadonnées v0.5.7 · Driver Health
    MANIFEST: dict = {
        "driver": "dahua",
        "version": "0.5",
        "status": "beta",
        "api": "CGI (configManager) + ONVIF fallback",
        "protocols": ["cgi", "onvif", "rtsp", "http"],
        "supported_models": ["IPC-HFW*", "IPC-HDW*", "SD*"],
        "coverage_pct": 50,
    }

    def __init__(self, host: str, username: str, password: str,
                 port: Optional[int] = None):
        super().__init__(host, username, password, port or 80)
        self._http: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        await super().connect()
        auth = httpx.DigestAuth(self.username, self.password)
        self._http = httpx.AsyncClient(auth=auth, timeout=8.0)

    async def disconnect(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        await super().disconnect()

    async def get_capabilities(self) -> CameraCapabilities:
        caps = await super().get_capabilities()
        caps.cgi = True
        # Sonde CGI : présence du endpoint whiteLight ?
        if self._http is not None:
            try:
                r = await self._http.get(
                    f"http://{self.host}/cgi-bin/configManager.cgi",
                    params={"action": "getConfig", "name": "Lighting_V2"}, timeout=4.0)
                if r.status_code == 200 and "table.Lighting_V2" in r.text:
                    caps.white_light = True
            except Exception:
                pass
        self._caps = caps
        return caps

    async def _set_light(self, enabled: bool, brightness: Optional[int],
                          mode: LightMode) -> None:
        if self._http is None:
            raise DeviceConnectionError("Session HTTP Dahua non initialisée")
        # Table Lighting_V2 : Mode=Manual + FarLight[0].Light=<brightness>
        params = {
            "action": "setConfig",
            "Lighting_V2[0][0].Mode": "Manual" if enabled else "Off",
        }
        if brightness is not None:
            params["Lighting_V2[0][0].FarLight[0].Light"] = str(max(0, min(100, brightness)))
        try:
            r = await self._http.get(
                f"http://{self.host}/cgi-bin/configManager.cgi",
                params=params, timeout=6.0)
            if r.status_code != 200 or "OK" not in r.text:
                raise DeviceConnectionError(f"Dahua white light: {r.status_code} {r.text[:80]}")
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Dahua CGI: {e}")


register_driver("dahua", DahuaDriver)
