"""Dahua CGI API provider — /cgi-bin/*.cgi.

Protocole (très différent de Reolink) :
    - Pas de login/token JSON : chaque requête porte de l'auth HTTP **Digest**
      (RFC 2617), vérifiée par la caméra à chaque appel. httpx.DigestAuth gère
      le handshake (401 + nonce → retry avec Authorization) de façon
      transparente sur le client.
    - Pas de batch : une commande = un GET (`action=...&param=valeur`).
    - Réponses en texte brut `clé=valeur` (PAS du JSON), ex. `sn=ABC123`, ou
      `table.General.MachineName=Camera01` pour les tables de config.
    - Erreurs : HTTP != 200, ou corps texte commençant par "Error".

Endpoints utilisés (protocole CGI Dahua, documenté et repris par plusieurs
intégrations open-source — ex. composants Home Assistant non-officiels) :
    - magicBox.cgi?action=getDeviceType|getSerialNo|getSoftwareVersion
    - configManager.cgi?action=getConfig|setConfig&name=<Table>
    - ptz.cgi?action=start|stop&channel=1&code=<Dir>&arg1..3

Fiabilité par fonction (du + sûr au moins sûr) :
    - PTZ (ptz.cgi)              : élevée — API stable sur toute la gamme.
    - IR jour/nuit (VideoInDayNight) : élevée — table standard, ancienne.
    - Projecteur blanc (Lighting)    : moyenne — la table "Lighting" (classique)
      est utilisée ici plutôt que "Lighting_V2" (caméras dual-light récentes)
      pour la compatibilité la plus large ; certains modèles récents pourraient
      nécessiter Lighting_V2. À confirmer sur le matériel réel.
    - Sirène                     : **non implémentée**. Aucune commande CGI
      universelle fiable identifiée (varie fortement selon la gamme —
      classique vs "WizSense"/active deterrence) ; plutôt que deviner une
      commande qui pourrait échouer silencieusement, `get_siren`/`set_siren`
      restent `UnsupportedCapability` tant qu'on n'a pas le modèle exact.

Aucun de ces appels n'a été testé sur du matériel Dahua réel dans cet
environnement — à valider au premier essai terrain (routes/camera_api.py
remonte le detail brut de l'erreur en cas d'échec, ce qui permettra
d'ajuster rapidement la table/le champ en cause).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..base import CameraApiProvider, Capabilities, DeviceInfo
from ..exceptions import (AuthenticationFailed, CameraApiError, DeviceUnreachable,
                            UnsupportedCapability)
from ..http_client import make_client, request_with_retry
from ..registry import register_provider

logger = logging.getLogger("camera_api.dahua")


@register_provider
class DahuaProvider(CameraApiProvider):
    name = "dahua"

    def __init__(self, config: dict):
        super().__init__(config)
        host = (config.get("api_host") or config.get("ip") or "").strip()
        # Dahua : le CGI classique tourne en HTTP sur la plupart des
        # déploiements LAN (le support HTTPS du CGI varie selon
        # firmware/modèle) — contrairement à Reolink, on défaut sur http/80.
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
                logger.warning("dahua[%s]: déchiffrement password échoué", config.get("id", "?"))
        return config.get("api_password") or config.get("password") or ""

    # ── Session (stateless côté Dahua — Digest rejoué à chaque requête) ────

    async def login(self) -> None:
        if not self.username or not self.password:
            raise AuthenticationFailed("username/password requis (api_username / api_password)")
        # Pas de session à ouvrir : on valide juste creds/joignabilité tout
        # de suite plutôt qu'au premier appel métier (fail-fast).
        await self._get("/cgi-bin/magicBox.cgi", {"action": "getDeviceType"})

    async def logout(self) -> None:
        pass  # aucune session serveur à fermer

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass

    # ── Requête générique (texte clé=valeur, pas de JSON) ──────────────────

    async def _get(self, path: str, params: Optional[dict] = None) -> str:
        try:
            r = await request_with_retry(self._client, "GET", path, params=params)
        except (ConnectionError, TimeoutError) as e:
            raise DeviceUnreachable(f"caméra injoignable ({self.base_url}) — {e}") from e
        if r.status_code == 401:
            raise AuthenticationFailed(f"HTTP 401 sur {path}")
        if r.status_code >= 400:
            raise CameraApiError(f"HTTP {r.status_code} sur {path}",
                                  detail={"body": (r.text or "")[:200]})
        text = r.text or ""
        if text.strip().lower().startswith("error"):
            raise CameraApiError(f"erreur CGI sur {path}", detail={"body": text[:200]})
        return text

    async def _probe_ok(self, path: str, params: Optional[dict] = None) -> bool:
        try:
            await self._get(path, params)
            return True
        except CameraApiError:
            return False

    @staticmethod
    def _parse_kv(text: str) -> dict:
        out: dict = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
        return out

    @staticmethod
    def _kv_suffix(text: str, suffix: str) -> str:
        """Cherche une ligne `...<suffix>=valeur` (ex. suffix="MachineName")
        sans dépendre du préfixe exact de table (varie selon endpoint)."""
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip().endswith(f".{suffix}"):
                return value.strip()
        return ""

    # ── Info & Capabilities ─────────────────────────────────────────────────

    async def get_device_info(self) -> DeviceInfo:
        type_kv = self._parse_kv(await self._get("/cgi-bin/magicBox.cgi", {"action": "getDeviceType"}))
        sn_kv = self._parse_kv(await self._get("/cgi-bin/magicBox.cgi", {"action": "getSerialNo"}))
        ver_kv = self._parse_kv(await self._get("/cgi-bin/magicBox.cgi", {"action": "getSoftwareVersion"}))
        name = self._kv_suffix(
            await self._get("/cgi-bin/configManager.cgi", {"action": "getConfig", "name": "General"}),
            "MachineName")
        return DeviceInfo(
            manufacturer="Dahua",
            model=type_kv.get("type", ""),
            firmware=ver_kv.get("version", ""),
            hardware="",
            serial=sn_kv.get("sn", ""),
            name=name,
            channels=1,
            raw={},
        )

    async def get_capabilities(self) -> Capabilities:
        """Dahua n'a pas d'endpoint 'GetAbility' unique comme Reolink — on
        sonde chaque fonction en lisant sa config (erreur = non supporté)."""
        ptz_ok = await self._probe_ok("/cgi-bin/ptz.cgi", {"action": "getStatus", "channel": 1})
        ir_ok = await self._probe_ok("/cgi-bin/configManager.cgi",
                                      {"action": "getConfig", "name": "VideoInDayNight"})
        light_ok = await self._probe_ok("/cgi-bin/configManager.cgi",
                                         {"action": "getConfig", "name": "Lighting"})
        return Capabilities(
            ptz=ptz_ok, ptz_zoom=ptz_ok,
            ir=ir_ok, ir_modes=["auto", "on", "off"] if ir_ok else [],
            light=light_ok,
            siren=False,   # cf. docstring module — pas de commande fiable identifiée
            audio_talk=False,
            # Pas de sonde dédiée pour ces 3 flags (informatifs, non pilotables
            # via ce provider) — quasi toujours vrai sur une caméra IP Dahua.
            recording=True, sd_storage=True, motion_detection=True,
            ai_detection=False,
            channels=1, raw={},
        )

    # ── Contrôle — IR jour/nuit (VideoInDayNight) ───────────────────────────
    # Distinct du filtre "IrLights" Reolink (illuminateur) : ici c'est le
    # mode jour/nuit/IR-cut de l'entrée vidéo, le concept Dahua le plus
    # proche de la sémantique auto/on/off attendue par l'API commune.

    async def get_ir(self) -> dict:
        text = await self._get("/cgi-bin/configManager.cgi",
                                {"action": "getConfig", "name": "VideoInDayNight"})
        mode = self._kv_suffix(text, "Mode") or "Auto"
        mapped = {"auto": "auto", "color": "off", "blackwhite": "on"}.get(mode.lower(), "auto")
        return {"mode": mapped}

    async def set_ir(self, mode: str) -> None:
        dahua_mode = {"auto": "Auto", "on": "BlackWhite", "off": "Color"}.get((mode or "").lower())
        if dahua_mode is None:
            raise CameraApiError(f"mode IR invalide : {mode!r} (attendu auto|on|off)")
        await self._get("/cgi-bin/configManager.cgi", {
            "action": "setConfig",
            "VideoInDayNight[0].Mode": dahua_mode,
        })

    # ── Contrôle — Projecteur blanc (table Lighting classique) ─────────────

    async def get_light(self) -> dict:
        text = await self._get("/cgi-bin/configManager.cgi", {"action": "getConfig", "name": "Lighting"})
        mode = self._kv_suffix(text, "Mode") or "Off"
        bright = self._kv_suffix(text, "Light")
        return {"enabled": mode.lower() != "off", "brightness": int(bright) if bright.isdigit() else None}

    async def set_light(self, enabled: bool, brightness: Optional[int] = None) -> None:
        params: dict = {"action": "setConfig", "Lighting[0][0].Mode": "Manual" if enabled else "Off"}
        if enabled and brightness is not None:
            params["Lighting[0][0].MiddleLight[0].Light"] = max(0, min(100, int(brightness)))
        await self._get("/cgi-bin/configManager.cgi", params)

    async def get_siren(self) -> dict:
        raise UnsupportedCapability(
            f"{self.name}: get_siren non supporté (pas de commande CGI fiable identifiée "
            f"sans connaître le modèle exact — classique vs WizSense/active deterrence)")

    async def set_siren(self, enabled: bool, duration: Optional[int] = None) -> None:
        raise UnsupportedCapability(
            f"{self.name}: set_siren non supporté (pas de commande CGI fiable identifiée "
            f"sans connaître le modèle exact — classique vs WizSense/active deterrence)")

    # ── Contrôle — PTZ (ptz.cgi, protocole stable) ──────────────────────────

    _PTZ_CODES = {
        "up": "Up", "down": "Down", "left": "Left", "right": "Right",
        "upleft": "LeftUp", "upright": "RightUp",
        "downleft": "LeftDown", "downright": "RightDown",
    }

    async def ptz_move(self, direction: str, speed: float = 0.5) -> None:
        direction = (direction or "").lower()
        if direction == "stop":
            return await self.ptz_stop()
        code = self._PTZ_CODES.get(direction)
        if code is None:
            raise CameraApiError(f"direction PTZ invalide : {direction!r}")
        dahua_speed = max(1, min(8, round(float(speed) * 8)))
        await self._get("/cgi-bin/ptz.cgi", {
            "action": "start", "channel": 1, "code": code,
            "arg1": 0, "arg2": dahua_speed, "arg3": 0,
        })

    async def ptz_stop(self) -> None:
        await self._get("/cgi-bin/ptz.cgi", {
            "action": "stop", "channel": 1, "code": "Up",
            "arg1": 0, "arg2": 0, "arg3": 0,
        })
