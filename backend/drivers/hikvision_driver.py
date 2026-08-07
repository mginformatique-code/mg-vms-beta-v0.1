"""Driver Hikvision ISAPI (préparé, minimal — v0.4.6).

Interface ISAPI Hikvision : ``http://<ip>/ISAPI/…`` — XML + Digest Auth.

Cette V1 fournit :
  - Fallback ONVIF pour info / streams / PTZ (via héritage)
  - Squelette ISAPI pour supplement light

Extensions v0.4.7+ : ISAPI event stream, PTZ patterns.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from .camera_models import CameraCapabilities, LightMode
from .exceptions import DeviceConnectionError, UnsupportedCapabilityError
from .onvif_driver import ONVIFDriver
from .registry import register_driver

logger = logging.getLogger("drivers.hikvision")


class HikvisionDriver(ONVIFDriver):
    vendor = "hikvision"

    #: Métadonnées v0.5.7 · Driver Health
    MANIFEST: dict = {
        "driver": "hikvision",
        "version": "0.5",
        "status": "beta",
        "api": "ISAPI (XML + Digest Auth)",
        "protocols": ["isapi", "onvif", "rtsp", "http"],
        "supported_models": ["DS-2CD*", "DS-2DE*", "iDS-2CD*"],
        "coverage_pct": 55,
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
        caps.isapi = True
        if self._http is not None:
            try:
                r = await self._http.get(
                    f"http://{self.host}/ISAPI/Image/channels/1/supplementLight",
                    timeout=4.0)
                if r.status_code == 200:
                    caps.white_light = True
            except Exception:
                pass
        self._caps = caps
        return caps


register_driver("hikvision", HikvisionDriver)
