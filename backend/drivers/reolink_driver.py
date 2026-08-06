"""Driver Reolink (API HTTP JSON propriétaire).

Reolink expose une API HTTP JSON documentée (endpoint ``/api.cgi``) qui va
bien au-delà d'ONVIF : spotlight, sirène, détection PIR, batterie, IA
embarquée (person / vehicle / animal), audio bidirectionnel.

Ce driver hérite d'ONVIFDriver pour la partie streaming/PTZ standard, et
ajoute les commandes propriétaires via HTTP.

Documentation officielle :
    https://reolink.com/support/documentation/reolink-api/
Endpoint type :
    POST http://<ip>/api.cgi?cmd=<Cmd>&user=<user>&password=<pass>
    body : [{"cmd": "<Cmd>", "action": 0, "param": {...}}]
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from .camera_models import (
    CameraCapabilities, DeviceInfo, DeviceStatus, IRMode, LightMode,
)
from .exceptions import (
    AuthenticationError, DeviceConnectionError, UnsupportedCapabilityError,
    CameraDriverError,
)
from .onvif_driver import ONVIFDriver
from .registry import register_driver

logger = logging.getLogger("drivers.reolink")


class ReolinkDriver(ONVIFDriver):
    """Driver Reolink — étend l'ONVIF avec l'API propriétaire.

    L'auth Reolink se fait par login (``Login`` command → token) OU par
    query params ``user=&password=`` (simplifié, retenu ici).
    """

    vendor = "reolink"

    def __init__(self, host: str, username: str, password: str,
                 port: Optional[int] = None):
        super().__init__(host, username, password, port or 80)
        # HTTP client réutilisable pour l'API JSON
        self._http: Optional[httpx.AsyncClient] = None
        self._api_url = f"http://{host}:{self.port}/api.cgi"

    async def connect(self) -> None:
        # Base ONVIF (streams, PTZ)
        try:
            await super().connect()
        except Exception as e:
            logger.debug("Reolink : ONVIF connect KO (%s), on continue avec HTTP", e)
            self._device_info_cache = DeviceInfo(manufacturer="Reolink", ip=self.host)
            self._connected = True
        # Session HTTP JSON
        self._http = httpx.AsyncClient(timeout=8.0)
        # Ping API JSON
        try:
            info = await self._call("GetDevInfo", {})
            if info:
                di = self._device_info_cache or DeviceInfo(ip=self.host)
                di.manufacturer = "Reolink"
                di.model = info.get("model") or di.model
                di.firmware = info.get("firmVer") or di.firmware
                di.serial = info.get("serial") or di.serial
                self._device_info_cache = di
        except AuthenticationError:
            raise
        except Exception:
            logger.debug("Reolink : GetDevInfo indispo (fallback ONVIF)")

    async def disconnect(self) -> None:
        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:
                pass
            self._http = None
        await super().disconnect()

    async def _call(self, cmd: str, param: dict, timeout: float = 6.0) -> Optional[dict]:
        """Envoi d'une commande Reolink JSON. Retourne le premier ``value``.

        Lève :
          - ``AuthenticationError`` si code -6/-7
          - ``CameraDriverError`` sur autre code d'erreur
        """
        if self._http is None:
            raise DeviceConnectionError("Session HTTP non initialisée")
        params = {"cmd": cmd, "user": self.username, "password": self.password}
        payload = [{"cmd": cmd, "action": 0, "param": param}]
        try:
            r = await self._http.post(self._api_url, params=params, json=payload,
                                       timeout=timeout)
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Reolink {self.host}: {e}")
        if r.status_code == 401:
            raise AuthenticationError("Reolink : identifiants rejetés")
        try:
            data = r.json()
        except Exception:
            raise CameraDriverError(f"Reolink : réponse non-JSON ({r.status_code})")
        if not isinstance(data, list) or not data:
            return None
        first = data[0]
        if first.get("code") != 0 or "error" in first:
            err = first.get("error") or {}
            rc = err.get("rspCode") if isinstance(err, dict) else None
            if rc in (-6, -7):
                raise AuthenticationError(f"Reolink code {rc}")
            detail = err.get("detail") if isinstance(err, dict) else str(err)
            raise CameraDriverError(f"Reolink {cmd} → {detail}", code="device_error")
        return first.get("value") or {}

    async def get_capabilities(self) -> CameraCapabilities:
        if self._caps is not None:
            return self._caps
        # Base ONVIF + surcouche
        caps = await super().get_capabilities()
        caps.reolink_api = True
        # GetAbility renvoie les capacités matérielles
        try:
            ab = await self._call("GetAbility", {"User": {"userName": self.username}})
            # Structure Ability : ab["Ability"]["abilityChn"][0]{...} + ab["Ability"]["abilityVer"]
            chns = (ab or {}).get("Ability", {}).get("abilityChn", [])
            if chns:
                ch = chns[0]
                # Format : {"key": {"ver": <int>, "permit": <int>}, ...}
                def _has(k: str) -> bool:
                    v = ch.get(k) or {}
                    return int(v.get("ver", 0)) > 0
                caps.spotlight = _has("floodLight") or _has("supportSpotLight")
                caps.siren = _has("supportBuzzer") or _has("supportAudioAlarm")
                caps.audio_input = _has("mainEncType") or _has("recAudio")
                caps.audio_output = _has("supportPowerSaveTip") or _has("audio")
                caps.two_way_audio = _has("supportAoAdjust") or _has("talk")
                caps.microphone = caps.audio_input
                caps.speaker = caps.audio_output
                caps.pir_sensor = _has("supportAlarmPir")
                caps.battery = _has("battery") or _has("supportPowerSaveTip")
                caps.onboard_ai = _has("supportAiAnimal") or _has("supportAiVehicle") or _has("supportAiPeople")
                ai_feats = []
                if _has("supportAiPeople"): ai_feats.append("person")
                if _has("supportAiVehicle"): ai_feats.append("vehicle")
                if _has("supportAiAnimal"): ai_feats.append("animal")
                if _has("supportAiFace"): ai_feats.append("face")
                caps.onboard_ai_features = tuple(ai_feats)
        except AuthenticationError:
            raise
        except Exception as e:
            logger.debug("Reolink GetAbility indispo (%s) — capacités ONVIF seules", e)
        self._caps = caps
        return caps

    async def get_status(self) -> DeviceStatus:
        st = await super().get_status()
        # GetBatteryInfo (batterie only)
        if self._caps and self._caps.battery:
            try:
                b = await self._call("GetBatteryInfo", {"channel": 0})
                if b:
                    st.battery_percent = int(b.get("batteryPercent", -1)) or None
            except Exception:
                pass
        # HddInfo (SD card)
        try:
            h = await self._call("GetHddInfo", {})
            if h and isinstance(h, dict):
                hdds = h.get("HddInfo") or []
                if hdds:
                    hdd = hdds[0]
                    used = int(hdd.get("size", 0)) - int(hdd.get("capacity", 0))
                    total = int(hdd.get("size", 0)) or 1
                    st.sd_card_used_percent = int(used * 100 / total)
                    st.sd_card_status = "ok" if hdd.get("mount") else "error"
        except Exception:
            pass
        return st

    # ── Spotlight ────────────────────────────────────────────────
    async def _set_light(self, enabled: bool, brightness: Optional[int],
                          mode: LightMode) -> None:
        param = {
            "WhiteLed": {
                "channel": 0,
                "state": 1 if enabled else 0,
                "mode": {LightMode.ON: 1, LightMode.OFF: 0, LightMode.AUTO: 3}[mode],
            }
        }
        if brightness is not None:
            param["WhiteLed"]["bright"] = max(0, min(100, int(brightness)))
        await self._call("SetWhiteLed", param)

    # ── Siren ─────────────────────────────────────────────────────
    async def _set_siren(self, enabled: bool, duration: Optional[int]) -> None:
        # AudioAlarmPlay v2 (durée ignorée par la caméra si sirène simple)
        param = {"channel": 0, "manualSwitch": 1 if enabled else 0,
                 "alarmMode": "manul"}
        if duration and enabled:
            param["duration"] = int(duration)
        await self._call("AudioAlarmPlay", param)

    # ── IR mode (surcharge : Reolink expose IRmode natif JSON) ──
    async def _set_ir_mode(self, mode: IRMode) -> None:
        m = {IRMode.AUTO: "Auto", IRMode.ON: "On", IRMode.OFF: "Off"}[mode]
        await self._call("SetIrLights", {"IrLights": {"channel": 0, "state": m}})

    # ── Audio (talkback pris en charge par sous-flux séparé) ───
    async def _start_audio(self) -> None:
        # Reolink : le talkback passe par un WebSocket ou par le sous-flux
        # audio dédié. Pour la V1, on utilise le "AudioAlarmPlay" en
        # mode ordinateur → pas de talkback réel ici, à raffiner.
        raise UnsupportedCapabilityError(
            "Talkback Reolink nécessite un client WebSocket dédié (à implémenter)")

    async def _stop_audio(self) -> None:
        raise UnsupportedCapabilityError("Cf _start_audio")


register_driver("reolink", ReolinkDriver)
