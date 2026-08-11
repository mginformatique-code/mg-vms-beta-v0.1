"""Tests unitaires · camera_api Reolink provider.

Valide le protocole Reolink JSON API en mockant httpx : login → token,
parsing GetDevInfo / GetAbility / GetLocalLink / GetNetPort / GetUser,
et gestion d'erreurs (401 creds, 503 unreachable, rspCode -7, self-signed).
"""
import asyncio
from typing import Any

import httpx
import pytest

from camera_api import (AuthenticationFailed, DeviceUnreachable, list_providers,
                          resolve_provider)
from camera_api.providers.reolink import ReolinkProvider


def _mock_transport(scenario: dict) -> httpx.MockTransport:
    """`scenario` = { "<cmd>": <value_dict or exception> } — parse le body JSON
    du POST et renvoie une réponse assemblée selon scenario."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/cgi-bin/api.cgi"
        body = request.read()
        import json
        cmds = json.loads(body.decode())
        result = []
        for c in cmds:
            cmd = c.get("cmd")
            if cmd in scenario:
                v = scenario[cmd]
                if isinstance(v, Exception):
                    raise v
                if isinstance(v, dict) and "__error__" in v:
                    result.append({"cmd": cmd, "code": 1,
                                    "error": v["__error__"]})
                else:
                    result.append({"cmd": cmd, "code": 0, "value": v})
            else:
                result.append({"cmd": cmd, "code": 1,
                                "error": {"detail": "unknown", "rspCode": -1}})
        return httpx.Response(200, json=result)
    return httpx.MockTransport(handler)


def _cam(**over) -> dict:
    return {"id": "pytest-reolink", "api_host": "192.0.2.55", "api_port": 443,
            "api_scheme": "https", "api_verify_ssl": False,
            "api_username": "admin", "api_password": "s3cret", **over}


# ── Registry ───────────────────────────────────────────────────────────────

def test_registry_lists_reolink():
    assert "reolink" in list_providers()


def test_resolve_by_manufacturer():
    from camera_api.providers.reolink import ReolinkProvider as R
    assert resolve_provider(manufacturer="Reolink") is R
    assert resolve_provider(model="Reolink RLC-81MA") is R
    assert resolve_provider(provider_id="reolink") is R


def test_resolve_unknown_raises():
    from camera_api.exceptions import ProviderNotFound
    with pytest.raises(ProviderNotFound):
        resolve_provider(manufacturer="unknownvendor", model="xyz")


# ── Reolink protocol ───────────────────────────────────────────────────────

def _install_mock(provider: ReolinkProvider, scenario: dict) -> None:
    provider._client = httpx.AsyncClient(base_url=provider.base_url,
                                          transport=_mock_transport(scenario),
                                          verify=False, timeout=5)


def test_login_success_sets_token():
    async def run():
        p = ReolinkProvider(_cam())
        _install_mock(p, {"Login": {"Token": {"name": "abcd1234", "leaseTime": 3600}}})
        await p.login()
        assert p.token == "abcd1234"
        assert p.token_expires_at > 0
        await p.close()
    asyncio.run(run())


def test_login_wrong_password_raises_auth_failed():
    async def run():
        p = ReolinkProvider(_cam())
        _install_mock(p, {"Login": {"__error__": {"detail": "login failed",
                                                     "rspCode": -7,
                                                     "auth_warning_info": {
                                                         "remain_times": 9,
                                                         "unlock_time": 0}}}})
        with pytest.raises(AuthenticationFailed) as ei:
            await p.login()
        assert "login failed" in str(ei.value)
        assert ei.value.detail["rspCode"] == -7
        assert ei.value.detail["auth_warning_info"]["remain_times"] == 9
        await p.close()
    asyncio.run(run())


def test_login_without_credentials_raises():
    async def run():
        p = ReolinkProvider(_cam(api_password=""))
        with pytest.raises(AuthenticationFailed):
            await p.login()
        await p.close()
    asyncio.run(run())


def test_get_device_info_parses_devinfo():
    async def run():
        p = ReolinkProvider(_cam())
        _install_mock(p, {
            "Login": {"Token": {"name": "tk", "leaseTime": 3600}},
            "GetDevInfo": {"DevInfo": {
                "model": "RLC-81MA", "firmVer": "v3.1.0",
                "hardVer": "IPC_523128M8MP", "serial": "S123456",
                "name": "MaCamera", "channelNum": 1,
            }},
        })
        await p.login()
        info = await p.get_device_info()
        assert info.manufacturer == "Reolink"
        assert info.model == "RLC-81MA"
        assert info.firmware == "v3.1.0"
        assert info.serial == "S123456"
        assert info.channels == 1
        await p.close()
    asyncio.run(run())


def test_get_capabilities_flags_from_ability():
    async def run():
        p = ReolinkProvider(_cam())
        _install_mock(p, {
            "Login": {"Token": {"name": "tk", "leaseTime": 3600}},
            "GetAbility": {"Ability": {
                "hddManage": {"permit": 1, "ver": 0},
                "abilityChn": [{
                    "ptzCtrl": {"permit": 1, "ver": 0},
                    "ptzZoom": {"permit": 1, "ver": 0},
                    "supportIrMode": {"permit": 1, "ver": 0},
                    "whiteLed": {"permit": 1, "ver": 0},
                    "supportAudioAlarm": {"permit": 1, "ver": 0},
                    "recCfg": {"permit": 1, "ver": 0},
                    "supportAiPeople": {"permit": 1, "ver": 0},
                }],
            }},
        })
        await p.login()
        caps = await p.get_capabilities()
        assert caps.ptz is True
        assert caps.ptz_zoom is True
        assert caps.ir is True and "auto" in caps.ir_modes
        assert caps.light is True
        assert caps.siren is True
        assert caps.recording is True
        assert caps.sd_storage is True
        assert caps.ai_detection is True
        assert caps.channels == 1
        await p.close()
    asyncio.run(run())


def test_get_network_info_extracts_ports_and_mac():
    async def run():
        p = ReolinkProvider(_cam())
        _install_mock(p, {
            "Login": {"Token": {"name": "tk", "leaseTime": 3600}},
            "GetLocalLink": {"LocalLink": {"mac": "aa:bb:cc:dd:ee:ff",
                                             "type": "DHCP",
                                             "static": {"ip": "192.168.1.55",
                                                        "gateway": "192.168.1.1",
                                                        "mask": "255.255.255.0"}}},
            "GetNetPort": {"NetPort": {"httpPort": 80, "httpsPort": 443,
                                         "rtspPort": 554, "onvifPort": 8000}},
        })
        await p.login()
        net = await p.get_network_info()
        assert net.ip == "192.168.1.55"
        assert net.mac == "aa:bb:cc:dd:ee:ff"
        assert net.https_port == 443
        assert net.rtsp_port == 554
        assert net.onvif_port == 8000
        await p.close()
    asyncio.run(run())


def test_get_users_maps_roles():
    async def run():
        p = ReolinkProvider(_cam())
        _install_mock(p, {
            "Login": {"Token": {"name": "tk", "leaseTime": 3600}},
            "GetUser": {"User": [
                {"userName": "admin", "level": 0},
                {"userName": "invite", "level": 1},
            ]},
        })
        await p.login()
        users = await p.get_users()
        assert len(users) == 2
        assert users[0].username == "admin"
        assert users[0].role == "admin"
        await p.close()
    asyncio.run(run())


def test_unreachable_raises_device_unreachable():
    async def run():
        p = ReolinkProvider(_cam())
        # Transport qui raise ConnectError
        def _boom(req):
            raise httpx.ConnectError("connection refused")
        p._client = httpx.AsyncClient(base_url=p.base_url,
                                       transport=httpx.MockTransport(_boom),
                                       verify=False, timeout=5)
        with pytest.raises(DeviceUnreachable):
            await p.login()
        await p.close()
    asyncio.run(run())


# ── Credentials redaction ──────────────────────────────────────────────────

def test_redact_url_hides_credentials_and_token():
    from camera_api.http_client import redact_url
    assert "s3cret" not in redact_url("rtsp://admin:s3cret@192.168.1.55:554/live")
    assert "******" in redact_url("rtsp://admin:s3cret@192.168.1.55:554/live")
    r = redact_url("https://cam/cgi-bin/api.cgi?token=abcdef123456&cmd=Ping")
    assert "abcdef123456" not in r
    assert "token=******" in r


def test_context_manager_calls_login_and_logout():
    async def run():
        p = ReolinkProvider(_cam())
        _install_mock(p, {
            "Login": {"Token": {"name": "tk", "leaseTime": 3600}},
            "Logout": {},
            "GetDevInfo": {"DevInfo": {"model": "X", "channelNum": 1}},
        })
        async with p:
            info = await p.get_device_info()
            assert info.model == "X"
        assert p.token is None
    asyncio.run(run())
