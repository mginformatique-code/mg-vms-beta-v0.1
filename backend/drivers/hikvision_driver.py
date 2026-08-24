"""Driver Hikvision — API ISAPI (XML + Digest Auth).

Interface ISAPI Hikvision : ``http://<ip>/ISAPI/…``.

v3.6 · Implémentation complète (remplace le squelette v0.4.6 — ONVIF
fallback + simple probe GET sans aucun contrôle réel). Schémas XML et
endpoints ci-dessous vérifiés en conditions réelles sur une DS-2CD2086G2-I
(firmware V5.7.2) :

  - Lumière : ``/ISAPI/Image/channels/{ch}/supplementLight`` (+ son
    sous-endpoint ``/capabilities`` pour l'énumération des modes
    réellement câblés sur le modèle — un modèle IR-only annonce
    ``supplementLightMode opt="irLight,close"`` SANS "whiteLight", donc
    aucune commande blanche possible malgré la présence du champ
    ``whiteLightBrightness`` dans le schéma générique — piège confirmé en
    conditions réelles, d'où la détection via l'énumération plutôt qu'un
    simple GET 200).
  - IR : ``/ISAPI/Image/channels/{ch}/ircutFilter`` (``IrcutFilterType``
    auto/day/night) — plus fiable que le filtre IR ONVIF générique sur
    ce constructeur, donc surchargé ici.
  - Stockage / enregistrements SD : ``/ISAPI/ContentMgmt/Storage`` (liste
    HDD/SD) + ``/ISAPI/ContentMgmt/search`` (recherche VOD par plage de
    temps, POST XML ``CMSearchDescription`` — schéma + espace de noms
    vérifiés en conditions réelles, un XML mal formé sans
    ``xmlns=".../ver20/XMLSchema" version="2.0"`` explicite sur la racine
    est rejeté).
  - Sirène / IO relais : ``/ISAPI/System/IO/outputs/{id}/trigger`` —
    endpoint confirmé réel (liste vide renvoyée proprement, pas de 404)
    mais PAS testé en écriture faute de caméra équipée d'une sortie
    relais/sirène disponible pour ce correctif ; gardé derrière
    ``IOCap.isSupportStrobeLamp`` / ``IOOutputPortNums`` pour ne
    l'exposer que sur les modèles qui l'annoncent.
  - Deux-way audio : ``voicetalkNums`` dans
    ``/ISAPI/System/capabilities`` — 0 sur ce modèle (turret sans jack
    audio), capacité correctement à False. Pas de primitive haut niveau
    "démarrer un appel" trouvée côté ISAPI standard — même limite que
    Reolink (flux temps réel dédié requis, hors scope).

Documentation officielle : ISAPI & OTAP Developer Guide (tpp.hikvision.com,
accès par modèle).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote as _urlquote
from xml.etree import ElementTree as ET

import httpx

from .camera_models import CameraCapabilities, DeviceStatus, IRMode, LightMode
from .exceptions import (
    AuthenticationError, CameraDriverError, DeviceConnectionError,
    UnsupportedCapabilityError,
)
from .onvif_driver import ONVIFDriver
from .registry import register_driver

logger = logging.getLogger("drivers.hikvision")

_NS = "{http://www.hikvision.com/ver20/XMLSchema}"
_CHANNEL = 1   # Hikvision numérote les canaux à partir de 1 (contrairement à Reolink : 0)


def _strip_ns(elem: ET.Element) -> ET.Element:
    for e in elem.iter():
        if "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
    return elem


class HikvisionDriver(ONVIFDriver):
    vendor = "hikvision"

    #: Métadonnées v3.6 · Driver Health
    MANIFEST: dict = {
        "driver": "hikvision",
        "version": "2.0",
        "status": "stable",
        "api": "ISAPI (XML + Digest Auth) + ONVIF fallback",
        "protocols": ["isapi", "onvif", "rtsp", "http"],
        "supported_models": ["DS-2CD*", "DS-2DE*", "iDS-2CD*"],
        "coverage_pct": 85,
    }

    def __init__(self, host: str, username: str, password: str,
                 port: Optional[int] = None):
        super().__init__(host, username, password, port or 80)
        self._http: Optional[httpx.AsyncClient] = None
        # Capacités IO / audio lues une fois via /System/capabilities,
        # réutilisées par _set_siren / _start_audio pour ne pas re-fetcher.
        self._io_output_count = 0
        self._supports_strobe = False

    async def connect(self) -> None:
        try:
            await super().connect()
        except Exception as e:
            logger.debug("Hikvision : ONVIF connect KO (%s), on continue avec ISAPI", e)
            self._connected = True
        auth = httpx.DigestAuth(self.username, self.password)
        self._http = httpx.AsyncClient(auth=auth, timeout=8.0)
        try:
            r = await self._http.get(f"http://{self.host}/ISAPI/System/deviceInfo", timeout=6.0)
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Hikvision {self.host} injoignable (ISAPI) : {e}") from e
        if r.status_code == 401:
            raise AuthenticationError("Hikvision : identifiants ISAPI rejetés")
        if r.status_code == 404 and "ONVIF integrate function is disabled" not in r.text:
            # Message ONVIF spécifique déjà géré par le fallback ONVIF ci-dessus ;
            # ici un vrai 404 ISAPI = ISAPI lui-même désactivé sur la caméra.
            raise DeviceConnectionError(
                f"Hikvision {self.host} : endpoint ISAPI /System/deviceInfo introuvable "
                f"(ISAPI est-il activé dans Configuration > Réseau > Protocole d'intégration ?)")
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
        caps.isapi = True

        # ── Lumière : n'annoncer white_light QUE si le modèle expose
        # réellement "whiteLight"/"mixLight" dans l'énumération — un
        # simple GET 200 sur /supplementLight ne suffit pas (le schéma
        # générique répond toujours 200 même sur un modèle IR-only).
        if self._http is not None:
            try:
                r = await self._http.get(
                    f"http://{self.host}/ISAPI/Image/channels/{_CHANNEL}/supplementLight/capabilities",
                    timeout=5.0)
                if r.status_code == 200:
                    root = _strip_ns(ET.fromstring(r.text))
                    mode_el = root.find("supplementLightMode")
                    opts = (mode_el.get("opt") or "").split(",") if mode_el is not None else []
                    caps.white_light = any(o in opts for o in ("whiteLight", "mixLight"))
            except Exception as e:
                logger.debug("Hikvision supplementLight/capabilities indispo (%s)", e)

            # ── IR : quasi universel sur cette gamme, ircutFilter répond
            # 200 dès que le endpoint existe.
            try:
                r = await self._http.get(
                    f"http://{self.host}/ISAPI/Image/channels/{_CHANNEL}/ircutFilter", timeout=5.0)
                if r.status_code == 200:
                    caps.ir_control = True
                    caps.ir_cut_filter = True
            except Exception as e:
                logger.debug("Hikvision ircutFilter indispo (%s)", e)

            # ── IO / sirène / audio : capacités globales déclarées par
            # la caméra elle-même (IOCap, voicetalkNums).
            try:
                r = await self._http.get(f"http://{self.host}/ISAPI/System/capabilities", timeout=6.0)
                if r.status_code == 200:
                    root = _strip_ns(ET.fromstring(r.text))
                    io_cap = root.find(".//IOCap")
                    if io_cap is not None:
                        self._io_output_count = int((io_cap.findtext("IOOutputPortNums") or "0"))
                        self._supports_strobe = (io_cap.findtext("isSupportStrobeLamp") or "false") == "true"
                        caps.alarm_output = self._io_output_count > 0
                        caps.siren = self._supports_strobe or caps.alarm_output
                        caps.relay = caps.alarm_output
                    voicetalk = int(root.findtext("voicetalkNums") or "0")
                    caps.audio_output = voicetalk > 0
                    caps.speaker = caps.audio_output
                    caps.two_way_audio = caps.audio_output
                    caps.talkback = caps.audio_output
            except Exception as e:
                logger.debug("Hikvision System/capabilities indispo (%s)", e)

            # ── Stockage local (carte SD / eMMC) ─────────────────────
            try:
                r = await self._http.get("http://{}/ISAPI/ContentMgmt/Storage".format(self.host), timeout=6.0)
                if r.status_code == 200:
                    root = _strip_ns(ET.fromstring(r.text))
                    hdds = root.find("hddList")
                    caps.sdcard = hdds is not None and len(list(hdds)) > 0
            except Exception as e:
                logger.debug("Hikvision ContentMgmt/Storage indispo (%s)", e)

        self._caps = caps
        return caps

    async def get_status(self) -> DeviceStatus:
        st = await super().get_status()
        if self._http is not None and self._caps and self._caps.sdcard:
            try:
                r = await self._http.get(f"http://{self.host}/ISAPI/ContentMgmt/Storage", timeout=6.0)
                if r.status_code == 200:
                    root = _strip_ns(ET.fromstring(r.text))
                    hdd = root.find("hddList/hdd")
                    if hdd is not None:
                        capacity = float(hdd.findtext("capacity") or 0)
                        freespace = float(hdd.findtext("freeSpace") or 0)
                        status = hdd.findtext("status") or ""
                        st.sd_card_status = "ok" if status == "ok" else (status or "error")
                        if capacity > 0:
                            st.sd_card_used_percent = round(100 * (capacity - freespace) / capacity)
            except Exception:
                pass
        return st

    # ── Lumière ──────────────────────────────────────────────────
    async def _set_light(self, enabled: bool, brightness: Optional[int],
                          mode: LightMode) -> None:
        if self._http is None:
            raise DeviceConnectionError("Session ISAPI Hikvision non initialisée")
        supplement_mode = "whiteLight" if enabled else "close"
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<SupplementLight version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">'
            f"<supplementLightMode>{supplement_mode}</supplementLightMode>"
        )
        if enabled and brightness is not None:
            body += f"<whiteLightBrightness>{max(0, min(100, int(brightness)))}</whiteLightBrightness>"
        body += "</SupplementLight>"
        try:
            r = await self._http.put(
                f"http://{self.host}/ISAPI/Image/channels/{_CHANNEL}/supplementLight",
                content=body, headers={"Content-Type": "application/xml"}, timeout=6.0)
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Hikvision supplementLight : {e}") from e
        if r.status_code != 200 or "<statusCode>1</statusCode>" not in r.text:
            raise CameraDriverError(f"Hikvision supplementLight → {r.status_code} {r.text[:150]}",
                                     code="device_error")

    # ── IR (surcharge ISAPI — plus fiable que ONVIF IrCutFilter ici) ──
    async def _set_ir_mode(self, mode: IRMode) -> None:
        if self._http is None:
            raise DeviceConnectionError("Session ISAPI Hikvision non initialisée")
        m = {IRMode.AUTO: "auto", IRMode.ON: "night", IRMode.OFF: "day"}[mode]
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<IrcutFilter version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">'
            f"<IrcutFilterType>{m}</IrcutFilterType>"
            "</IrcutFilter>"
        )
        try:
            r = await self._http.put(
                f"http://{self.host}/ISAPI/Image/channels/{_CHANNEL}/ircutFilter",
                content=body, headers={"Content-Type": "application/xml"}, timeout=6.0)
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Hikvision ircutFilter : {e}") from e
        if r.status_code != 200 or "<statusCode>1</statusCode>" not in r.text:
            raise CameraDriverError(f"Hikvision ircutFilter → {r.status_code} {r.text[:150]}",
                                     code="device_error")

    # ── Sirène / sortie relais (modèles avec IOOutputPortNums > 0) ──
    async def _set_siren(self, enabled: bool, duration: Optional[int]) -> None:
        if self._http is None:
            raise DeviceConnectionError("Session ISAPI Hikvision non initialisée")
        if self._io_output_count < 1:
            raise UnsupportedCapabilityError(
                "Aucune sortie relais/sirène déclarée par cette caméra (IOOutputPortNums=0)")
        state = "high" if enabled else "low"
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<IOPortData version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">'
            f"<outputState>{state}</outputState>"
            "</IOPortData>"
        )
        try:
            r = await self._http.put(
                f"http://{self.host}/ISAPI/System/IO/outputs/1/trigger",
                content=body, headers={"Content-Type": "application/xml"}, timeout=6.0)
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Hikvision IO output trigger : {e}") from e
        if r.status_code != 200:
            raise CameraDriverError(f"Hikvision IO output → {r.status_code} {r.text[:150]}",
                                     code="device_error")

    # ── Audio (talkback nécessite un flux temps réel séparé) ──────
    async def _start_audio(self) -> None:
        raise UnsupportedCapabilityError(
            "Talkback Hikvision nécessite un flux audio temps réel dédié (à implémenter)")

    async def _stop_audio(self) -> None:
        raise UnsupportedCapabilityError("Cf _start_audio")

    # ── SD card / enregistrements locaux (v3.6) ───────────────────
    async def get_storage(self) -> list[dict]:
        if self._http is None:
            raise UnsupportedCapabilityError("Session ISAPI Hikvision non initialisée")
        try:
            r = await self._http.get(f"http://{self.host}/ISAPI/ContentMgmt/Storage", timeout=6.0)
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Hikvision ContentMgmt/Storage : {e}") from e
        if r.status_code != 200:
            raise CameraDriverError(f"Hikvision ContentMgmt/Storage → {r.status_code}",
                                     code="device_error")
        root = _strip_ns(ET.fromstring(r.text))
        out = []
        for hdd in root.findall("hddList/hdd"):
            capacity = float(hdd.findtext("capacity") or 0)
            freespace = float(hdd.findtext("freeSpace") or 0)
            out.append({
                "index": hdd.findtext("id"),
                "available": (hdd.findtext("status") or "") == "ok",
                "type": hdd.findtext("hddType") or "SD",
                "free_percent": round(100 * freespace / capacity) if capacity > 0 else 0,
            })
        return out

    async def search_recordings(self, start: datetime, end: datetime) -> list[dict]:
        if self._http is None:
            raise UnsupportedCapabilityError("Session ISAPI Hikvision non initialisée")
        def _fmt(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<CMSearchDescription xmlns="http://www.hikvision.com/ver20/XMLSchema" version="2.0">'
            "<searchID>MG-VMS-1</searchID>"
            f"<trackList><trackID>{_CHANNEL}01</trackID></trackList>"
            f"<timeSpanList><timeSpan><startTime>{_fmt(start)}</startTime>"
            f"<endTime>{_fmt(end)}</endTime></timeSpan></timeSpanList>"
            "<maxResults>40</maxResults><searchResultPostion>0</searchResultPostion>"
            "</CMSearchDescription>"
        )
        try:
            r = await self._http.post(
                f"http://{self.host}/ISAPI/ContentMgmt/search",
                content=body, headers={"Content-Type": "application/xml"}, timeout=15.0)
        except httpx.HTTPError as e:
            raise DeviceConnectionError(f"Hikvision ContentMgmt/search : {e}") from e
        if r.status_code != 200:
            raise CameraDriverError(f"Hikvision ContentMgmt/search → {r.status_code} {r.text[:150]}",
                                     code="device_error")
        root = _strip_ns(ET.fromstring(r.text))
        out = []
        for item in root.findall("matchList/searchMatchItem"):
            uri = item.findtext("mediaSegmentDescriptor/playbackURI") or item.findtext("playbackURI") or ""
            out.append({
                "file_name": uri,      # Hikvision : pas de nom de fichier, l'URI de lecture EST l'identifiant
                "start_time": item.findtext("timeSpan/startTime") or "",
                "end_time": item.findtext("timeSpan/endTime") or "",
                "duration_s": None,
                "size_bytes": None,
                "type": item.findtext("mediaSegmentDescriptor/contentType") or "video",
            })
        return out

    async def get_recording_source(self, file_name: str) -> str:
        # Le "file_name" retourné par search_recordings EST déjà l'URI RTSP
        # de lecture (playbackURI) — pas de résolution supplémentaire à faire,
        # sauf l'injection des identifiants (ISAPI ne les inclut jamais dans
        # l'URI générée ; le flux RTSP de lecture exige le même Digest Auth
        # que le live — même convention que streaming.py::_build_rtsp_url).
        # ⚠ Valeur RÉSERVÉE AU SERVEUR (ffmpeg côté backend) — ne jamais
        # renvoyer cette URL telle quelle à un client HTTP/frontend.
        if not re.match(r"^rtsps?://", file_name or ""):
            raise CameraDriverError(
                "Hikvision : identifiant d'enregistrement invalide (attendu une playbackURI RTSP "
                "issue de search_recordings)", code="device_error")
        if "@" in file_name.split("://", 1)[1].split("/", 1)[0]:
            return file_name  # déjà pourvue de credentials
        scheme, rest = file_name.split("://", 1)
        u = _urlquote(self.username, safe="")
        p = _urlquote(self.password, safe="")
        return f"{scheme}://{u}:{p}@{rest}"


register_driver("hikvision", HikvisionDriver)
