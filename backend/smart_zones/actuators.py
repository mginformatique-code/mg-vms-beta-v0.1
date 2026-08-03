"""Smart Zones — Actionneurs (dispatchers).

Chaque actionneur est **isolé** dans une fonction async qui reçoit :
- `config` : la config utilisateur de l'action
- `context` : un dict avec les métadonnées de l'événement (zone_name, camera_id, detection, timestamp, ...)

Toute erreur d'un actionneur est **capturée** — un actionneur qui plante ne casse
jamais l'évaluation ni les autres actions.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger("smart_zones.actuators")


async def _run_webhook(config: dict, context: dict) -> dict:
    """Envoie une requête HTTP. Config : {url, method?, headers?, body?}."""
    import httpx
    url = config.get("url")
    if not url:
        return {"ok": False, "error": "url manquante"}
    method = (config.get("method") or "POST").upper()
    headers = dict(config.get("headers") or {})
    body = config.get("body")
    # Interpolation des placeholders {zone_name}, {camera_id}, ...
    payload = _interpolate(body, context)
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.request(
            method, url, headers=headers,
            json=payload if isinstance(payload, (dict, list)) else None,
            content=(payload if isinstance(payload, str) else None),
        )
    return {"ok": r.status_code < 400, "status": r.status_code}


async def _run_mqtt(config: dict, context: dict) -> dict:
    """Publie sur un broker MQTT. Config : {broker, port?, topic, payload, username?, password?, tls?}."""
    try:
        import paho.mqtt.publish as publish
    except ImportError:
        return {"ok": False, "error": "paho-mqtt non installé"}
    broker = config.get("broker") or config.get("host")
    port = int(config.get("port") or 1883)
    topic = config.get("topic")
    payload = _interpolate(config.get("payload"), context)
    if not broker or not topic:
        return {"ok": False, "error": "broker et topic requis"}
    auth = None
    if config.get("username"):
        auth = {"username": config["username"], "password": config.get("password") or ""}
    tls = {"tls_version": 2} if config.get("tls") else None
    # paho publie en sync → wrap dans executor
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: publish.single(
        topic,
        payload=json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload),
        hostname=broker, port=port, auth=auth, tls=tls,
        keepalive=10,
    ))
    return {"ok": True, "topic": topic}


async def _run_home_assistant(config: dict, context: dict) -> dict:
    """Appel service HA. Config : {base_url, token, service (ex 'light.turn_on'), data}.

    Ex : {"service":"light.turn_on","data":{"entity_id":"light.entree"}}
    """
    import httpx
    base = (config.get("base_url") or "").rstrip("/")
    token = config.get("token")
    service = config.get("service", "")
    data = _interpolate(config.get("data") or {}, context)
    if not base or not token or "." not in service:
        return {"ok": False, "error": "base_url + token + service (domain.service) requis"}
    domain, service_name = service.split(".", 1)
    url = f"{base}/api/services/{domain}/{service_name}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url,
                              headers={"Authorization": f"Bearer {token}",
                                       "Content-Type": "application/json"},
                              json=data if isinstance(data, dict) else {})
    return {"ok": r.status_code < 400, "status": r.status_code}


async def _run_tuya(config: dict, context: dict) -> dict:
    """Envoi de commandes Tuya Cloud. Config : {access_id, access_secret, device_id, commands, region?}.

    `commands` : liste de dicts type `[{"code":"switch_1","value":true}]`.
    L'authentification Tuya utilise HMAC-SHA256. Voir doc Tuya Cloud API v1.0.
    """
    import hashlib, hmac, time
    import httpx
    access_id = config.get("access_id")
    access_secret = (config.get("access_secret") or "").encode()
    device_id = config.get("device_id")
    commands = config.get("commands") or []
    region = (config.get("region") or "eu").lower()  # eu | us | in | cn
    if not (access_id and access_secret and device_id and commands):
        return {"ok": False, "error": "access_id, access_secret, device_id, commands requis"}
    endpoints = {
        "eu": "https://openapi.tuyaeu.com",
        "us": "https://openapi.tuyaus.com",
        "in": "https://openapi.tuyain.com",
        "cn": "https://openapi.tuyacn.com",
    }
    base = endpoints.get(region, endpoints["eu"])

    # Etape 1 : token
    def _sign(msg: str) -> str:
        return hmac.new(access_secret, msg.encode(), hashlib.sha256).hexdigest().upper()

    def _headers(sign: str, t: str, token: str = "") -> dict:
        return {"client_id": access_id, "sign": sign, "sign_method": "HMAC-SHA256",
                "t": t, "access_token": token, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=10) as client:
        # Token
        t1 = str(int(time.time() * 1000))
        path_token = "/v1.0/token?grant_type=1"
        # Signature v3 simplifiée
        str_to_sign = "GET\n" + hashlib.sha256(b"").hexdigest() + "\n\n" + path_token
        sign1 = _sign(access_id + t1 + str_to_sign)
        r = await client.get(base + path_token, headers=_headers(sign1, t1))
        if r.status_code != 200:
            return {"ok": False, "error": f"tuya token http {r.status_code}"}
        tok_data = r.json()
        if not tok_data.get("success"):
            return {"ok": False, "error": f"tuya token: {tok_data.get('msg')}"}
        access_token = tok_data["result"]["access_token"]

        # Commande
        cmds = {"commands": _interpolate(commands, context)}
        body = json.dumps(cmds, separators=(",", ":"))
        t2 = str(int(time.time() * 1000))
        path_cmd = f"/v1.0/devices/{device_id}/commands"
        content_sha = hashlib.sha256(body.encode()).hexdigest()
        str_to_sign2 = "POST\n" + content_sha + "\n\n" + path_cmd
        sign2 = _sign(access_id + access_token + t2 + str_to_sign2)
        r2 = await client.post(base + path_cmd, headers=_headers(sign2, t2, access_token), content=body)
    return {"ok": r2.status_code < 400 and r2.json().get("success", False),
            "status": r2.status_code, "response": r2.json()}


async def _run_plugin(config: dict, context: dict) -> dict:
    """Envoie un événement synthétique vers un plugin EventConsumer nommé.
    Config : {plugin_name, event_type?, message?, data?}.
    """
    from plugin_manager.bus import bus
    from plugin_manager.interfaces import MGVMSEvent
    from datetime import datetime, timezone
    name = config.get("plugin_name")
    if not name or name not in bus._entries:
        return {"ok": False, "error": f"plugin '{name}' introuvable"}
    ev = MGVMSEvent(
        type=config.get("event_type") or "zone.trigger",
        camera_id=context.get("camera_id"),
        data={
            **_interpolate(config.get("data") or {}, context),
            "zone_name": context.get("zone_name"),
            "message": _interpolate(config.get("message") or "", context),
        },
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    # dispatch ciblé (single entry)
    entry = bus._entries[name]
    if not entry.is_dispatchable():
        return {"ok": False, "error": f"plugin '{name}' non dispatchable ({entry.state})"}
    await bus._call_one(entry, lambda inst, e=ev: inst.on_event(e))
    return {"ok": True, "plugin": name}


async def _run_tts(config: dict, context: dict) -> dict:
    """Text-to-speech via un service configuré (Google/Azure/OpenAI/local).
    MVP : envoie l'ordre à un plugin EventConsumer dédié 'tts-notifier' si présent.
    Config : {text, voice?, language?}.
    """
    text = _interpolate(config.get("text") or "", context)
    if not text:
        return {"ok": False, "error": "text requis"}
    return await _run_plugin({
        "plugin_name": config.get("plugin_name") or "tts-notifier",
        "event_type": "zone.tts",
        "message": text,
        "data": {"text": text, "voice": config.get("voice"), "language": config.get("language")},
    }, context)


ACTUATORS = {
    "webhook":         _run_webhook,
    "mqtt":            _run_mqtt,
    "home_assistant":  _run_home_assistant,
    "tuya":            _run_tuya,
    "plugin":          _run_plugin,
    "tts":             _run_tts,
}


def _interpolate(value: Any, context: dict) -> Any:
    """Remplace {zone_name}, {camera_id}, {detection.class}, {timestamp} dans strings, dict et listes."""
    if isinstance(value, str):
        try:
            return value.format(**_flatten(context))
        except (KeyError, IndexError, ValueError):
            return value
    if isinstance(value, dict):
        return {k: _interpolate(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, context) for v in value]
    return value


def _flatten(d: dict, parent: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{parent}.{k}" if parent else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
        # Toujours exposer sans prefix aussi
        if not parent:
            out[k] = v
    return out


async def dispatch_action(action: dict, context: dict) -> dict:
    """Point d'entrée unique — dispatch une action selon son type.

    Retourne {"type", "ok", ...} pour tracing. Ne lève JAMAIS d'exception.
    """
    atype = action.get("type", "").lower()
    fn = ACTUATORS.get(atype)
    if not fn:
        return {"type": atype, "ok": False, "error": f"type d'action inconnu : {atype}"}
    try:
        result = await asyncio.wait_for(fn(action.get("config") or {}, context), timeout=15)
        return {"type": atype, **(result or {})}
    except asyncio.TimeoutError:
        logger.warning("actuator.timeout type=%s", atype)
        return {"type": atype, "ok": False, "error": "timeout"}
    except Exception as e:  # pragma: no cover — isolation crash
        logger.warning("actuator.error type=%s err=%s", atype, e)
        return {"type": atype, "ok": False, "error": f"{type(e).__name__}: {e}"}
