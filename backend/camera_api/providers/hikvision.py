"""Hikvision ISAPI provider — /ISAPI/*.

Protocole :
    - Auth HTTP **Digest** par requête (comme Dahua) — pas de token/session.
      httpx.DigestAuth gère le handshake.
    - Requêtes/réponses en **XML** (pas de JSON), namespace par défaut sur la
      racine (`xmlns="http://www.hikvision.com/ver20/XMLSchema"`) qui ne
      préfixe PAS les balises enfants dans le texte brut — on peut donc les
      extraire par regex simple sans parser XML complet ni gérer les
      namespaces.
    - `PUT` attend en général le document **complet** en retour (pas de PATCH
      partiel propre) : on fait systématiquement GET → modifie 1 balise par
      regex → PUT le document entier, pour ne jamais écraser des champs
      qu'on ne connaît pas (varie selon génération de firmware).

Endpoints utilisés (ISAPI standard, documentation SDK Hikvision publique) :
    - System/deviceInfo                          (info appareil)
    - PTZCtrl/channels/1/continuous               (PTZ, très stable/répandu)
    - PTZCtrl/channels/1/status                   (sonde capacité PTZ)
    - Image/channels/1/ircutFilter                (IR jour/nuit/auto)
    - Image/channels/1/supplementLight            (projecteur blanc — caméras
      ColorVu/dual-light ; absent sur les modèles IR-only classiques)

Fiabilité : PTZ et IR élevée (API ancienne, très répandue). Projecteur blanc
moyenne (dépend du modèle — l'endpoint peut renvoyer 404 sur du matériel
IR-only, ce qui remonte proprement via `Capabilities.light=False`).

Sirène : **non implémentée**. Le contrôle de la sirène/strobe audible varie
trop selon la génération ("AcuSense one-key" vs ancien relais d'alarme) pour
deviner une commande fiable sans le modèle exact — `get_siren`/`set_siren`
restent `UnsupportedCapability`, comme pour Dahua.

Aucun de ces appels n'a été testé sur du matériel Hikvision réel dans cet
environnement — à valider au premier essai terrain.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx

from ..base import CameraApiProvider, Capabilities, DeviceInfo
from ..exceptions import (AuthenticationFailed, CameraApiError, DeviceUnreachable,
                            UnsupportedCapability)
from ..http_client import make_client, request_with_retry
from ..registry import register_provider

logger = logging.getLogger("camera_api.hikvision")


@register_provider
class HikvisionProvider(CameraApiProvider):
    name = "hikvision"

    _IR_PATH = "/ISAPI/Image/channels/1/ircutFilter"
    _LIGHT_PATH = "/ISAPI/Image/channels/1/supplementLight"
    _PTZ_PATH = "/ISAPI/PTZCtrl/channels/1/continuous"
    _PTZ_STATUS_PATH = "/ISAPI/PTZCtrl/channels/1/status"

    def __init__(self, config: dict):
        super().__init__(config)
        host = (config.get("api_host") or config.get("ip") or "").strip()
        scheme = (config.get("api_scheme") or "http").lower()
        port = int(config.get("api_port") or (443 if scheme == "https" else 80))
        self.base_url = f"{scheme}://{host}:{port}"
        self.verify_ssl = bool(config.get("api_verify_ssl", False))
        self.username = config.get("api_username") or config.get("username") or ""
        self.password = self._resolve_password(config)
        self._client = make_client(
            base_url=self.base_url, verify_ssl=self.verify_ssl,
            auth=httpx.DigestAuth(self.username, self.password) if self.username else None,
        )

    @staticmethod
    def _resolve_password(config: dict) -> str:
        enc = config.get("api_password_enc") or config.get("password_enc")
        if enc:
            try:
                from crypto_utils import decrypt_secret
                return decrypt_secret(enc)
            except Exception:
                logger.warning("hikvision[%s]: déchiffrement password échoué", config.get("id", "?"))
        return config.get("api_password") or config.get("password") or ""

    # ── Session (stateless — Digest rejoué à chaque requête) ───────────────

    async def login(self) -> None:
        if not self.username or not self.password:
            raise AuthenticationFailed("username/password requis (api_username / api_password)")
        await self._get_xml("/ISAPI/System/deviceInfo")

    async def logout(self) -> None:
        pass

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass

    # ── Requêtes génériques (XML) ────────────────────────────────────────────

    async def _get_xml(self, path: str) -> str:
        try:
            r = await request_with_retry(self._client, "GET", path)
        except (ConnectionError, TimeoutError) as e:
            raise DeviceUnreachable(f"caméra injoignable ({self.base_url}) — {e}") from e
        if r.status_code == 401:
            raise AuthenticationFailed(f"HTTP 401 sur {path}")
        if r.status_code == 404:
            raise UnsupportedCapability(f"{self.name}: {path} absent sur ce modèle (HTTP 404)")
        if r.status_code >= 400:
            raise CameraApiError(f"HTTP {r.status_code} sur {path}",
                                  detail={"body": (r.text or "")[:300]})
        return r.text or ""

    async def _put_xml(self, path: str, xml_body: str) -> str:
        try:
            r = await request_with_retry(self._client, "PUT", path,
                                          content=xml_body.encode("utf-8"),
                                          headers={"Content-Type": "application/xml"})
        except (ConnectionError, TimeoutError) as e:
            raise DeviceUnreachable(f"caméra injoignable ({self.base_url}) — {e}") from e
        if r.status_code == 401:
            raise AuthenticationFailed(f"HTTP 401 sur {path}")
        if r.status_code >= 400:
            raise CameraApiError(f"HTTP {r.status_code} sur {path}",
                                  detail={"body": (r.text or "")[:300]})
        return r.text or ""

    async def _probe_xml(self, path: str) -> bool:
        try:
            await self._get_xml(path)
            return True
        except CameraApiError:
            return False

    @staticmethod
    def _xml_get_field(raw_xml: str, tag: str) -> Optional[str]:
        m = re.search(rf"<{tag}\b[^>]*>([^<]*)</{tag}>", raw_xml)
        return m.group(1) if m else None

    @staticmethod
    def _xml_set_field(raw_xml: str, tag: str, value: str) -> str:
        """Remplace le contenu d'UNE balise dans le document complet, pour
        pouvoir le renvoyer intact en PUT sans reconstruire tout le schéma
        (dont on ne connaît pas tous les champs selon firmware)."""
        pattern = re.compile(rf"(<{tag}\b[^>]*>)[^<]*(</{tag}>)")
        new_xml, n = pattern.subn(rf"\g<1>{value}\g<2>", raw_xml, count=1)
        if n == 0:
            raise CameraApiError(f"champ XML introuvable : <{tag}>")
        return new_xml

    # ── Info & Capabilities ─────────────────────────────────────────────────

    async def get_device_info(self) -> DeviceInfo:
        text = await self._get_xml("/ISAPI/System/deviceInfo")

        def f(tag: str) -> str:
            return (self._xml_get_field(text, tag) or "").strip()

        return DeviceInfo(
            manufacturer="Hikvision",
            model=f("model"),
            firmware=f("firmwareVersion"),
            hardware=f("hardwareVersion"),
            serial=f("serialNumber"),
            name=f("deviceName"),
            channels=1,
            raw={},
        )

    async def get_capabilities(self) -> Capabilities:
        """Pas d'endpoint d'ability unique — on sonde chaque ressource
        (404/erreur = non supporté sur ce modèle)."""
        ptz_ok = await self._probe_xml(self._PTZ_STATUS_PATH)
        ir_ok = await self._probe_xml(self._IR_PATH)
        light_ok = await self._probe_xml(self._LIGHT_PATH)
        return Capabilities(
            ptz=ptz_ok, ptz_zoom=ptz_ok,
            ir=ir_ok, ir_modes=["auto", "on", "off"] if ir_ok else [],
            light=light_ok,
            siren=False,   # cf. docstring module
            audio_talk=False,
            recording=True, sd_storage=True, motion_detection=True,
            ai_detection=False,
            channels=1, raw={},
        )

    # ── Contrôle — IR jour/nuit (ircutFilter) ───────────────────────────────

    async def get_ir(self) -> dict:
        text = await self._get_xml(self._IR_PATH)
        raw = (self._xml_get_field(text, "IrcutFilterType") or "auto").lower()
        mode = {"day": "off", "night": "on", "auto": "auto", "autoswitch": "auto"}.get(raw, "auto")
        return {"mode": mode}

    async def set_ir(self, mode: str) -> None:
        hik_type = {"auto": "auto", "on": "night", "off": "day"}.get((mode or "").lower())
        if hik_type is None:
            raise CameraApiError(f"mode IR invalide : {mode!r} (attendu auto|on|off)")
        current = await self._get_xml(self._IR_PATH)
        updated = self._xml_set_field(current, "IrcutFilterType", hik_type)
        await self._put_xml(self._IR_PATH, updated)

    # ── Contrôle — Projecteur blanc (supplementLight, modèles ColorVu) ─────

    async def get_light(self) -> dict:
        text = await self._get_xml(self._LIGHT_PATH)
        mode = (self._xml_get_field(text, "supplementLightMode") or "close").lower()
        bright = self._xml_get_field(text, "whiteLightBrightness")
        return {"enabled": mode != "close", "brightness": int(bright) if bright and bright.isdigit() else None}

    async def set_light(self, enabled: bool, brightness: Optional[int] = None) -> None:
        current = await self._get_xml(self._LIGHT_PATH)
        updated = self._xml_set_field(current, "supplementLightMode", "whiteLight" if enabled else "close")
        if enabled and brightness is not None:
            try:
                updated = self._xml_set_field(updated, "whiteLightBrightness",
                                               str(max(0, min(100, int(brightness)))))
            except CameraApiError:
                pass  # champ absent sur ce modèle — mode déjà appliqué, pas bloquant
        await self._put_xml(self._LIGHT_PATH, updated)

    async def get_siren(self) -> dict:
        raise UnsupportedCapability(
            f"{self.name}: get_siren non supporté (contrôle sirène/strobe trop variable "
            f"selon la génération — nécessite le modèle exact)")

    async def set_siren(self, enabled: bool, duration: Optional[int] = None) -> None:
        raise UnsupportedCapability(
            f"{self.name}: set_siren non supporté (contrôle sirène/strobe trop variable "
            f"selon la génération — nécessite le modèle exact)")

    # ── Contrôle — PTZ (continuous, protocole ISAPI très stable) ────────────

    _PTZ_VECTORS = {
        "up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0),
        "upleft": (-1, 1), "upright": (1, 1),
        "downleft": (-1, -1), "downright": (1, -1),
        "stop": (0, 0),
    }

    async def ptz_move(self, direction: str, speed: float = 0.5) -> None:
        vec = self._PTZ_VECTORS.get((direction or "").lower())
        if vec is None:
            raise CameraApiError(f"direction PTZ invalide : {direction!r}")
        pan_dir, tilt_dir = vec
        magnitude = max(1, min(100, round(float(speed) * 100)))
        pan, tilt = pan_dir * magnitude, tilt_dir * magnitude
        xml = f"<PTZData><pan>{pan}</pan><tilt>{tilt}</tilt><zoom>0</zoom></PTZData>"
        await self._put_xml(self._PTZ_PATH, xml)

    async def ptz_stop(self) -> None:
        xml = "<PTZData><pan>0</pan><tilt>0</tilt><zoom>0</zoom></PTZData>"
        await self._put_xml(self._PTZ_PATH, xml)
