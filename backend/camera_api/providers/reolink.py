"""Reolink JSON API provider — /cgi-bin/api.cgi.

Protocole :
    POST /cgi-bin/api.cgi                          (login)
        Content-Type: application/json
        Body : [{"cmd":"Login","action":0,"param":{"User":{"userName":"...",
                                                             "password":"..."}}}]
        Réponse : [{"cmd":"Login","code":0,
                     "value":{"Token":{"name":"<token>","leaseTime":3600}}}]

    POST /cgi-bin/api.cgi?token=<token>            (toutes commandes ensuite)
        Body : batch de commandes JSON

Codes standard :
    - `code` (dans la réponse par cmd) = 0 → OK, ≠0 → erreur
    - `error.rspCode` = code d'erreur métier Reolink
        · -7  : login failed / creds invalides
        · -3  : session expirée
        · -4  : token invalide

Login retry / lockout :
    Reolink expose `auth_warning_info.remain_times` et `unlock_time` — on remonte
    ces valeurs dans AuthenticationFailed.detail pour l'UI.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from ..base import (CameraApiProvider, Capabilities, DeviceInfo, NetworkInfo,
                     UserInfo)
from ..exceptions import (AuthenticationFailed, CameraApiError, DeviceUnreachable,
                            UnsupportedCapability)
from ..http_client import make_client, redact_url, request_with_retry
from ..registry import register_provider

logger = logging.getLogger("camera_api.reolink")


@register_provider
class ReolinkProvider(CameraApiProvider):
    name = "reolink"

    def __init__(self, config: dict):
        super().__init__(config)
        host = (config.get("api_host") or config.get("ip") or "").strip()
        scheme = (config.get("api_scheme") or "https").lower()
        port = int(config.get("api_port") or (443 if scheme == "https" else 80))
        self.base_url = f"{scheme}://{host}:{port}"
        self.verify_ssl = bool(config.get("api_verify_ssl", scheme == "https" and False))
        # Note : par défaut HTTPS Reolink LAN = self-signed → verify_ssl=False raisonnable
        # côté LAN. La caméra est fixée à l'IP → pas de risque MITM significatif.
        self.username = config.get("api_username") or config.get("username") or ""
        self.password = self._resolve_password(config)
        self.token: Optional[str] = None
        self.token_expires_at: float = 0.0
        self._client = make_client(base_url=self.base_url, verify_ssl=self.verify_ssl)

    @staticmethod
    def _resolve_password(config: dict) -> str:
        """Récupère le mdp caméra (déchiffre si stocké encrypté en base)."""
        enc = config.get("api_password_enc") or config.get("password_enc")
        if enc:
            try:
                from crypto_utils import decrypt_secret
                return decrypt_secret(enc)
            except Exception:
                logger.warning("reolink[%s]: déchiffrement password échoué", config.get("id", "?"))
        # Fallback : plaintext transitoire (test/dev). En prod, on utilise l'encrypté.
        return config.get("api_password") or config.get("password") or ""

    # ── Session ────────────────────────────────────────────────────────────

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass

    async def login(self) -> None:
        if not self.username or not self.password:
            raise AuthenticationFailed("username/password requis (api_username / api_password)")
        payload = [{"cmd": "Login", "action": 0,
                    "param": {"User": {"userName": self.username, "password": self.password}}}]
        result = await self._post("/cgi-bin/api.cgi", payload)
        entry = result[0] if result else {}
        if entry.get("code") == 0:
            token = ((entry.get("value") or {}).get("Token") or {})
            self.token = token.get("name") or ""
            lease = int(token.get("leaseTime") or 3600)
            self.token_expires_at = time.monotonic() + max(60, lease - 30)   # marge 30 s
            if not self.token:
                raise AuthenticationFailed("réponse Login sans token", detail=entry)
            logger.info("reolink[%s]: login OK · token=%s… · lease=%ds",
                         self.camera_id, self.token[:6], lease)
            return
        err = (entry.get("error") or {})
        detail = {"rspCode": err.get("rspCode"), "auth_warning_info": err.get("auth_warning_info")}
        raise AuthenticationFailed(err.get("detail") or "login failed", detail=detail)

    async def logout(self) -> None:
        if not self.token:
            return
        try:
            await self._post("/cgi-bin/api.cgi",
                              [{"cmd": "Logout", "action": 0, "param": {}}],
                              use_token=True)
        finally:
            self.token = None
            self.token_expires_at = 0.0

    async def _ensure_token(self) -> None:
        if not self.token or time.monotonic() >= self.token_expires_at:
            await self.login()

    # ── Requête générique ─────────────────────────────────────────────────

    async def _post(self, path: str, payload: list, *, use_token: bool = False) -> list:
        params = {"token": self.token} if use_token and self.token else None
        try:
            r = await request_with_retry(self._client, "POST", path,
                                          json=payload, params=params)
        except (ConnectionError, TimeoutError) as e:
            raise DeviceUnreachable(f"caméra injoignable ({self.base_url}) — {e}") from e
        if r.status_code == 401:
            raise AuthenticationFailed(f"HTTP 401 sur {path}")
        if r.status_code >= 400:
            raise CameraApiError(f"HTTP {r.status_code} sur {path}",
                                  detail={"body": (r.text or "")[:200]})
        try:
            data = r.json()
        except ValueError as e:
            raise CameraApiError(f"réponse non-JSON sur {path}",
                                  detail={"body": (r.text or "")[:200]}) from e
        if not isinstance(data, list):
            raise CameraApiError(f"réponse inattendue sur {path} (pas une liste)",
                                  detail={"body": str(data)[:200]})
        return data

    async def batch(self, commands: list[dict]) -> list[dict]:
        """Envoie un batch de commandes en un seul POST (Reolink accepte les batchs)."""
        await self._ensure_token()
        return await self._post("/cgi-bin/api.cgi", commands, use_token=True)

    @staticmethod
    def _entry_by_cmd(results: list[dict], cmd: str) -> dict:
        for e in results:
            if (e or {}).get("cmd") == cmd:
                return e
        return {}

    @staticmethod
    def _value(entry: dict) -> dict:
        if entry.get("code") != 0:
            err = (entry.get("error") or {})
            raise CameraApiError(err.get("detail") or f"cmd {entry.get('cmd')} failed",
                                  detail={"rspCode": err.get("rspCode"),
                                          "cmd": entry.get("cmd")})
        return entry.get("value") or {}

    # ── Info & Capabilities ────────────────────────────────────────────────

    async def get_device_info(self) -> DeviceInfo:
        """GetDevInfo — retourne name/model/firmware/hardware/serial/channelNum."""
        results = await self.batch([{"cmd": "GetDevInfo", "action": 0, "param": {}}])
        v = self._value(self._entry_by_cmd(results, "GetDevInfo"))
        di = v.get("DevInfo") or {}
        return DeviceInfo(
            manufacturer="Reolink",
            model=str(di.get("model") or ""),
            firmware=str(di.get("firmVer") or ""),
            hardware=str(di.get("hardVer") or ""),
            serial=str(di.get("serial") or ""),
            name=str(di.get("name") or ""),
            channels=int(di.get("channelNum") or 1),
            raw=di,
        )

    async def get_capabilities(self) -> Capabilities:
        """GetAbility — parse le blob (énorme) et aplatit les flags utiles."""
        results = await self.batch(
            [{"cmd": "GetAbility", "action": 0,
              "param": {"User": {"userName": self.username}}}])
        v = self._value(self._entry_by_cmd(results, "GetAbility"))
        ab = v.get("Ability") or {}
        # Reolink : chaque flag = {"permit": int, "ver": int}. permit != 0 → dispo.
        def has(key: str) -> bool:
            e = ab.get(key)
            return bool(isinstance(e, dict) and (e.get("permit") or 0) != 0)

        def has_channel_flag(chan: dict, key: str) -> bool:
            e = (chan or {}).get(key)
            return bool(isinstance(e, dict) and (e.get("permit") or 0) != 0)

        # Reolink structure : Ability.abilityChn[<idx>].<flag>
        chan_list = ab.get("abilityChn") or []
        chan0 = chan_list[0] if chan_list else {}

        ir_modes: list[str] = []
        if has_channel_flag(chan0, "supportIrMode") or has_channel_flag(chan0, "ircut"):
            ir_modes = ["auto", "on", "off"]

        return Capabilities(
            ptz=has_channel_flag(chan0, "ptzCtrl") or has_channel_flag(chan0, "ptzType"),
            ptz_zoom=has_channel_flag(chan0, "ptzZoom") or has_channel_flag(chan0, "ptzCtrl"),
            ir=bool(ir_modes),
            ir_modes=ir_modes,
            light=has_channel_flag(chan0, "supportWhiteDark")
                  or has_channel_flag(chan0, "floodLight")
                  or has_channel_flag(chan0, "whiteLed"),
            siren=has_channel_flag(chan0, "supportAudioAlarm")
                  or has_channel_flag(chan0, "alarmAudio"),
            audio_talk=has_channel_flag(chan0, "talk") or has("talk"),
            recording=has_channel_flag(chan0, "recCfg") or has("recCfg"),
            sd_storage=has("hddManage") or has("sdCard"),
            motion_detection=has_channel_flag(chan0, "mdWithPic") or has_channel_flag(chan0, "alarmMd"),
            ai_detection=has_channel_flag(chan0, "supportAiPeople")
                         or has_channel_flag(chan0, "aiTrack"),
            channels=len(chan_list) or 1,
            raw=ab,
        )

    async def get_network_info(self) -> NetworkInfo:
        """GetLocalLink + GetNetPort en un batch."""
        results = await self.batch([
            {"cmd": "GetLocalLink", "action": 0, "param": {}},
            {"cmd": "GetNetPort", "action": 0, "param": {}},
        ])
        link = self._value(self._entry_by_cmd(results, "GetLocalLink"))
        ports = self._value(self._entry_by_cmd(results, "GetNetPort"))
        ll = link.get("LocalLink") or {}
        static = ll.get("static") or {}
        np = ports.get("NetPort") or {}
        return NetworkInfo(
            ip=str(static.get("ip") or ll.get("ip") or ""),
            mac=str(ll.get("mac") or ""),
            gateway=str(static.get("gateway") or ""),
            netmask=str(static.get("mask") or ""),
            dhcp=str(ll.get("dns", {}).get("auto") or ll.get("type") or "").lower() == "dhcp",
            http_port=int(np.get("httpPort") or 0) or None,
            https_port=int(np.get("httpsPort") or 0) or None,
            rtsp_port=int(np.get("rtspPort") or 0) or None,
            onvif_port=int(np.get("onvifPort") or 0) or None,
        )

    async def get_users(self) -> list[UserInfo]:
        results = await self.batch([{"cmd": "GetUser", "action": 0, "param": {}}])
        v = self._value(self._entry_by_cmd(results, "GetUser"))
        out: list[UserInfo] = []
        for u in (v.get("User") or []):
            lvl = u.get("level")
            role = {"admin": "admin", "guest": "viewer", "user": "user"}.get(
                str(u.get("userLevel") or "").lower(),
                "admin" if lvl == 0 else ("user" if lvl == 1 else "viewer"))
            out.append(UserInfo(username=str(u.get("userName") or ""), role=role, level=lvl))
        return out

    # ── Contrôle (v3.1.4) ────────────────────────────────────────────────
    # get_capabilities() détectait déjà supportWhiteDark/floodLight/whiteLed,
    # supportAudioAlarm/alarmAudio, ptzCtrl/ptzType, supportIrMode/ircut —
    # mais aucune des méthodes de contrôle correspondantes n'était codée,
    # elles retombaient toutes sur UnsupportedCapability (base.py). Commandes
    # CGI Reolink documentées (protocole stable, utilisé par ex. par
    # l'intégration Home Assistant reolink_aio) :
    #   - IrLights   : illuminateur IR (LEDs infrarouge physiques, PAS le
    #                  filtre IR-cut mécanique — celui-là reste géré côté
    #                  ONVIF dans routes/camera_control.py::_onvif_ir_cut).
    #   - WhiteLed   : projecteur blanc (spotlight).
    #   - AudioAlarmPlay : déclenchement manuel de la sirène ("manul" est
    #                  bien la faute d'orthographe du fabricant dans son
    #                  API, pas une erreur ici — vérifié sur plusieurs
    #                  générations de firmware).
    #   - PtzCtrl    : mouvement PTZ continu (pas de rappel Stop auto côté
    #                  caméra — c'est à l'appelant d'envoyer Stop).
    # Non vérifié sur matériel réel dans cet environnement (pas d'accès
    # caméra ici) — à confirmer sur le premier essai terrain, notamment le
    # champ `mode` de WhiteLed dont la numérotation varie parfois selon le
    # firmware (3 = manuel sur la majorité des modèles testés ailleurs).

    async def get_ir(self) -> dict:
        results = await self.batch([{"cmd": "GetIrLights", "action": 0, "param": {}}])
        v = self._value(self._entry_by_cmd(results, "GetIrLights"))
        state = str((v.get("IrLights") or {}).get("state") or "Auto")
        return {"mode": state.lower()}

    async def set_ir(self, mode: str) -> None:
        reolink_state = {"auto": "Auto", "on": "On", "off": "Off"}.get((mode or "").lower())
        if reolink_state is None:
            raise CameraApiError(f"mode IR invalide : {mode!r} (attendu auto|on|off)")
        await self.batch([{
            "cmd": "SetIrLights", "action": 0,
            "param": {"IrLights": {"channel": 0, "state": reolink_state}},
        }])

    async def get_light(self) -> dict:
        results = await self.batch([{"cmd": "GetWhiteLed", "action": 0, "param": {}}])
        v = self._value(self._entry_by_cmd(results, "GetWhiteLed"))
        wl = v.get("WhiteLed") or {}
        return {"enabled": bool(wl.get("state")), "brightness": wl.get("bright")}

    async def set_light(self, enabled: bool, brightness: Optional[int] = None) -> None:
        payload = {"channel": 0, "mode": 3, "state": 1 if enabled else 0}
        if brightness is not None:
            payload["bright"] = max(0, min(100, int(brightness)))
        await self.batch([{"cmd": "SetWhiteLed", "action": 0, "param": {"WhiteLed": payload}}])

    async def get_siren(self) -> dict:
        # Reolink n'expose pas d'état "sirène en cours" propre — GetAudioAlarmV20
        # ne renvoie que la config des règles automatiques, pas l'état d'un
        # déclenchement manuel via AudioAlarmPlay.
        raise UnsupportedCapability(f"{self.name}: get_siren non supporté (pas d'état lisible côté API)")

    async def set_siren(self, enabled: bool, duration: Optional[int] = None) -> None:
        param: dict = {"alarm_mode": "manul", "manual_switch": 1 if enabled else 0}
        if enabled:
            param["times"] = max(1, int(duration)) if duration else 1
        await self.batch([{"cmd": "AudioAlarmPlay", "action": 0, "param": param}])

    _PTZ_OPS = {
        "up": "Up", "down": "Down", "left": "Left", "right": "Right",
        "upleft": "LeftUp", "upright": "RightUp",
        "downleft": "LeftDown", "downright": "RightDown",
        "stop": "Stop",
    }

    async def ptz_move(self, direction: str, speed: float = 0.5) -> None:
        op = self._PTZ_OPS.get((direction or "").lower())
        if op is None:
            raise CameraApiError(f"direction PTZ invalide : {direction!r}")
        reolink_speed = max(1, min(64, round(float(speed) * 64)))
        await self.batch([{
            "cmd": "PtzCtrl", "action": 0,
            "param": {"channel": 0, "op": op, "speed": reolink_speed},
        }])

    async def ptz_stop(self) -> None:
        await self.batch([{
            "cmd": "PtzCtrl", "action": 0,
            "param": {"channel": 0, "op": "Stop"},
        }])
