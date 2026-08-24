"""Driver Dahua — API CGI (``configManager.cgi`` + ``mediaFileFind.cgi``).

Interface CGI HTTP standard Dahua : ``http://<ip>/cgi-bin/…``, auth Digest.

v3.6 · Implémentation complète (remplace le squelette v0.4.6 qui ne
couvrait que la lumière blanche). Contrairement à Reolink et Hikvision
dans ce même correctif, **aucune caméra Dahua physique n'était disponible
en test** — cette implémentation suit les conventions CGI Dahua les plus
largement documentées et utilisées par les intégrations tierces connues
(Home Assistant, ffmpeg/VLC wikis, SDK CGI officiel), mais n'a PAS été
vérifiée en conditions réelles comme l'ont été ``reolink_driver.py`` et
``hikvision_driver.py`` (root cause caméra confirmées par test croisé, pas
ici). À valider sur un vrai modèle Dahua dès que possible — cf.
``coverage_pct`` réduit dans ``MANIFEST`` pour refléter ce statut.

Endpoints utilisés :
  - Lumière (``Lighting_V2``) : lecture/écriture déjà en place depuis
    v0.4.6, conservée. Capacité lue via ``action=getConfigCap``.
  - IR / Day-Night (``VideoInDayNightMode``) : ``Config[0].Mode`` ∈
    {Color, BlackWhite, Auto}.
  - Sirène / sortie relais (``AlarmOut``) : ``Mode`` 0/1.
  - Stockage (``storageDevice.cgi?action=getDeviceAllInfo``) : état/quota
    carte SD.
  - Enregistrements (``mediaFileFind.cgi``) : cycle factory.create →
    findFile → findNextFile → close/destroy, standard SDK CGI Dahua.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote as _urlquote

import httpx

from .camera_models import CameraCapabilities, DeviceStatus, IRMode, LightMode
from .exceptions import (
    CameraDriverError, DeviceConnectionError, UnsupportedCapabilityError,
)
from .onvif_driver import ONVIFDriver
from .registry import register_driver

logger = logging.getLogger("drivers.dahua")


def _parse_kv(text: str) -> dict:
    """Parse le format ``table.clef=valeur`` (une paire par ligne) renvoyé
    par la quasi-totalité des endpoints ``configManager.cgi``."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


class DahuaDriver(ONVIFDriver):
    vendor = "dahua"

    #: Métadonnées v3.6 · Driver Health
    MANIFEST: dict = {
        "driver": "dahua",
        "version": "1.0",
        "status": "beta",           # non vérifié sur matériel réel — voir docstring
        "api": "CGI (configManager + mediaFileFind) + ONVIF fallback",
        "protocols": ["cgi", "onvif", "rtsp", "http"],
        "supported_models": ["IPC-HFW*", "IPC-HDW*", "SD*"],
        "coverage_pct": 65,
    }

    def __init__(self, host: str, username: str, password: str,
                 port: Optional[int] = None):
        super().__init__(host, username, password, port or 80)
        self._http: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        try:
            await super().connect()
        except Exception as e:
            logger.debug("Dahua : ONVIF connect KO (%s), on continue avec CGI", e)
            self._connected = True
        auth = httpx.DigestAuth(self.username, self.password)
        self._http = httpx.AsyncClient(auth=auth, timeout=8.0)
        try:
            r = await self._http.get(
                f"http://{self.host}/cgi-bin/magicBox.cgi",
                params={"action": "getDeviceType"}, timeout=6.0)
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Dahua {self.host} injoignable (CGI) : {e}") from e
        if r.status_code == 401:
            from .exceptions import AuthenticationError
            raise AuthenticationError("Dahua : identifiants CGI rejetés")
        self._connected = True

    async def disconnect(self) -> None:
        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:
                pass
            self._http = None
        await super().disconnect()

    async def get_capabilities(self) -> CameraCapabilities:
        if self._caps is not None:
            return self._caps
        caps = await super().get_capabilities()
        caps.cgi = True

        if self._http is not None:
            # ── Lumière blanche (Lighting_V2) ────────────────────────
            try:
                r = await self._http.get(
                    f"http://{self.host}/cgi-bin/configManager.cgi",
                    params={"action": "getConfig", "name": "Lighting_V2"}, timeout=5.0)
                if r.status_code == 200 and "table.Lighting_V2" in r.text:
                    caps.white_light = True
            except Exception as e:
                logger.debug("Dahua Lighting_V2 indispo (%s)", e)

            # ── IR / Day-Night (VideoInDayNightMode) ─────────────────
            try:
                r = await self._http.get(
                    f"http://{self.host}/cgi-bin/configManager.cgi",
                    params={"action": "getConfig", "name": "VideoInDayNightMode"}, timeout=5.0)
                if r.status_code == 200 and "table.VideoInDayNightMode" in r.text:
                    caps.ir_control = True
                    caps.ir_cut_filter = True
            except Exception as e:
                logger.debug("Dahua VideoInDayNightMode indispo (%s)", e)

            # ── Sirène / sortie relais (AlarmOut) ────────────────────
            try:
                r = await self._http.get(
                    f"http://{self.host}/cgi-bin/configManager.cgi",
                    params={"action": "getConfig", "name": "AlarmOut"}, timeout=5.0)
                if r.status_code == 200 and "table.AlarmOut" in r.text:
                    caps.siren = True
                    caps.alarm_output = True
                    caps.relay = True
            except Exception as e:
                logger.debug("Dahua AlarmOut indispo (%s)", e)

            # ── Stockage local (carte SD) ────────────────────────────
            try:
                r = await self._http.get(
                    f"http://{self.host}/cgi-bin/storageDevice.cgi",
                    params={"action": "getDeviceAllInfo"}, timeout=6.0)
                if r.status_code == 200 and "info" in r.text:
                    caps.sdcard = True
            except Exception as e:
                logger.debug("Dahua storageDevice indispo (%s)", e)

        self._caps = caps
        return caps

    async def get_status(self) -> DeviceStatus:
        st = await super().get_status()
        if self._http is not None and self._caps and self._caps.sdcard:
            try:
                r = await self._http.get(
                    f"http://{self.host}/cgi-bin/storageDevice.cgi",
                    params={"action": "getDeviceAllInfo"}, timeout=6.0)
                if r.status_code == 200:
                    kv = _parse_kv(r.text)
                    state = kv.get("info.0.State", "")
                    st.sd_card_status = "ok" if state.lower() == "normal" else (state or "error")
                    total = float(kv.get("info.0.TotalBytes", 0) or 0)
                    used = float(kv.get("info.0.UsedBytes", 0) or 0)
                    if total > 0:
                        st.sd_card_used_percent = round(100 * used / total)
            except Exception:
                pass
        return st

    # ── Lumière ──────────────────────────────────────────────────
    async def _set_light(self, enabled: bool, brightness: Optional[int],
                          mode: LightMode) -> None:
        if self._http is None:
            raise DeviceConnectionError("Session CGI Dahua non initialisée")
        params = {
            "action": "setConfig",
            "Lighting_V2[0][0].Mode": "Manual" if enabled else "Off",
        }
        if enabled and brightness is not None:
            params["Lighting_V2[0][0].FarLight[0].Light"] = str(max(0, min(100, int(brightness))))
        try:
            r = await self._http.get(
                f"http://{self.host}/cgi-bin/configManager.cgi", params=params, timeout=6.0)
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Dahua Lighting_V2 : {e}") from e
        if r.status_code != 200 or "OK" not in r.text:
            raise CameraDriverError(f"Dahua Lighting_V2 → {r.status_code} {r.text[:150]}",
                                     code="device_error")

    # ── IR / Day-Night ───────────────────────────────────────────
    async def _set_ir_mode(self, mode: IRMode) -> None:
        if self._http is None:
            raise DeviceConnectionError("Session CGI Dahua non initialisée")
        m = {IRMode.AUTO: "Auto", IRMode.ON: "BlackWhite", IRMode.OFF: "Color"}[mode]
        params = {
            "action": "setConfig",
            "VideoInDayNightMode[0].Config[0].Mode": m,
        }
        try:
            r = await self._http.get(
                f"http://{self.host}/cgi-bin/configManager.cgi", params=params, timeout=6.0)
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Dahua VideoInDayNightMode : {e}") from e
        if r.status_code != 200 or "OK" not in r.text:
            raise CameraDriverError(f"Dahua VideoInDayNightMode → {r.status_code} {r.text[:150]}",
                                     code="device_error")

    # ── Sirène / sortie relais ───────────────────────────────────
    async def _set_siren(self, enabled: bool, duration: Optional[int]) -> None:
        if self._http is None:
            raise DeviceConnectionError("Session CGI Dahua non initialisée")
        params = {
            "action": "setConfig",
            "AlarmOut[0].Mode": "1" if enabled else "0",
        }
        try:
            r = await self._http.get(
                f"http://{self.host}/cgi-bin/configManager.cgi", params=params, timeout=6.0)
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Dahua AlarmOut : {e}") from e
        if r.status_code != 200 or "OK" not in r.text:
            raise CameraDriverError(f"Dahua AlarmOut → {r.status_code} {r.text[:150]}",
                                     code="device_error")

    # ── Audio (talkback nécessite un flux temps réel séparé) ──────
    async def _start_audio(self) -> None:
        raise UnsupportedCapabilityError(
            "Talkback Dahua nécessite un flux audio temps réel dédié (à implémenter)")

    async def _stop_audio(self) -> None:
        raise UnsupportedCapabilityError("Cf _start_audio")

    # ── SD card / enregistrements locaux (v3.6) ───────────────────
    async def get_storage(self) -> list[dict]:
        if self._http is None:
            raise UnsupportedCapabilityError("Session CGI Dahua non initialisée")
        try:
            r = await self._http.get(
                f"http://{self.host}/cgi-bin/storageDevice.cgi",
                params={"action": "getDeviceAllInfo"}, timeout=6.0)
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Dahua storageDevice : {e}") from e
        if r.status_code != 200:
            raise CameraDriverError(f"Dahua storageDevice → {r.status_code}", code="device_error")
        kv = _parse_kv(r.text)
        out = []
        i = 0
        while f"info.{i}.State" in kv or f"info.{i}.Name" in kv:
            # CGI Dahua : TotalBytes / UsedBytes déjà en octets.
            total = float(kv.get(f"info.{i}.TotalBytes", 0) or 0)
            used = float(kv.get(f"info.{i}.UsedBytes", 0) or 0)
            out.append({
                "index": i,
                "available": kv.get(f"info.{i}.State", "").lower() == "normal",
                "type": "SD",
                "used_percent": round(100 * used / total) if total > 0 else 0,
                "total_bytes": int(total),
                "free_bytes": int(max(0, total - used)),
            })
            i += 1
        return out

    async def search_recordings(self, start: datetime, end: datetime) -> list[dict]:
        if self._http is None:
            raise UnsupportedCapabilityError("Session CGI Dahua non initialisée")

        def _fmt(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        base = f"http://{self.host}/cgi-bin/mediaFileFind.cgi"
        try:
            r = await self._http.get(base, params={"action": "factory.create"}, timeout=6.0)
            obj = _parse_kv(r.text).get("result")
            if not obj:
                raise CameraDriverError("Dahua mediaFileFind : impossible de créer l'objet de recherche",
                                         code="device_error")
            await self._http.get(base, params={
                "action": "findFile", "object": obj,
                "condition.Channel": "0",
                "condition.StartTime": _fmt(start),
                "condition.EndTime": _fmt(end),
                "condition.Types[0]": "dav",
            }, timeout=6.0)
            r2 = await self._http.get(base, params={
                "action": "findNextFile", "object": obj, "count": "100",
            }, timeout=10.0)
            kv = _parse_kv(r2.text)
            out = []
            i = 0
            while f"items[{i}].FilePath" in kv:
                out.append({
                    "file_name": kv.get(f"items[{i}].FilePath", ""),
                    "start_time": kv.get(f"items[{i}].StartTime", ""),
                    "end_time": kv.get(f"items[{i}].EndTime", ""),
                    "duration_s": None,
                    "size_bytes": int(kv[f"items[{i}].Length"]) if f"items[{i}].Length" in kv else None,
                    "type": kv.get(f"items[{i}].Type", "dav"),
                })
                i += 1
            await self._http.get(base, params={"action": "close", "object": obj}, timeout=5.0)
            await self._http.get(base, params={"action": "destroy", "object": obj}, timeout=5.0)
            return out
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Dahua mediaFileFind : {e}") from e

    async def get_recording_source(self, file_name: str) -> str:
        if not file_name:
            raise CameraDriverError("Dahua : chemin d'enregistrement vide", code="device_error")
        # Téléchargement direct du fichier .dav via RPC_Loadfile — convention
        # CGI Dahua standard (file_name = FilePath renvoyé par mediaFileFind,
        # ex. "/mnt/sd/2026-08-24/001/dav/00/00.00.00-01.00.00[M][0@0][0].dav").
        # Endpoint protégé par Digest Auth (comme tout /cgi-bin/) — credentials
        # injectés dans l'URL (même convention que Hikvision/streaming.py) car
        # cette valeur est consommée UNIQUEMENT côté serveur (ffmpeg), jamais
        # renvoyée telle quelle à un client HTTP/frontend.
        path = file_name if file_name.startswith("/") else f"/{file_name}"
        u = _urlquote(self.username, safe="")
        p = _urlquote(self.password, safe="")
        return f"http://{u}:{p}@{self.host}/cgi-bin/RPC_Loadfile{path}"


register_driver("dahua", DahuaDriver)
