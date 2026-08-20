"""Tests unitaires · camera_api Dahua provider.

Mocke httpx pour valider le parsing texte clé=valeur du CGI Dahua (pas de
JSON, pas de batch — un GET = une commande), l'auth Digest via le
constructeur, et les erreurs (401, injoignable, mode IR invalide, sirène
non supportée).
"""
import asyncio

import httpx
import pytest

from camera_api import AuthenticationFailed, DeviceUnreachable, list_providers, resolve_provider
from camera_api.exceptions import UnsupportedCapability, CameraApiError
from camera_api.providers.dahua import DahuaProvider


def _cam(**over) -> dict:
    return {"id": "pytest-dahua", "api_host": "192.0.2.60", "api_port": 80,
            "api_scheme": "http", "api_username": "admin", "api_password": "s3cret", **over}


def _install_mock(provider: DahuaProvider, routes: dict) -> None:
    """`routes` = { "action_value": text_response_or_Exception }."""
    def handler(request: httpx.Request) -> httpx.Response:
        action = request.url.params.get("action", "")
        if action not in routes:
            return httpx.Response(200, text="Error\r\nUnknown action")
        v = routes[action]
        if isinstance(v, Exception):
            raise v
        return httpx.Response(200, text=v)
    provider._client = httpx.AsyncClient(base_url=provider.base_url,
                                          transport=httpx.MockTransport(handler),
                                          verify=False, timeout=5)


# ── Registry ───────────────────────────────────────────────────────────────

def test_registry_lists_dahua():
    assert "dahua" in list_providers()


def test_resolve_by_manufacturer():
    assert resolve_provider(manufacturer="Dahua") is DahuaProvider
    assert resolve_provider(model="Dahua IPC-HFW2431S") is DahuaProvider
    assert resolve_provider(provider_id="dahua") is DahuaProvider


# ── Session ────────────────────────────────────────────────────────────────

def test_login_without_credentials_raises():
    async def run():
        p = DahuaProvider(_cam(api_password=""))
        with pytest.raises(AuthenticationFailed):
            await p.login()
        await p.close()
    asyncio.run(run())


def test_login_success():
    async def run():
        p = DahuaProvider(_cam())
        _install_mock(p, {"getDeviceType": "type=IPC-HFW2431S-S-S2"})
        await p.login()
        await p.close()
    asyncio.run(run())


def test_unreachable_raises_device_unreachable():
    async def run():
        p = DahuaProvider(_cam())
        def _boom(req):
            raise httpx.ConnectError("connection refused")
        p._client = httpx.AsyncClient(base_url=p.base_url, transport=httpx.MockTransport(_boom),
                                       verify=False, timeout=5)
        with pytest.raises(DeviceUnreachable):
            await p.login()
        await p.close()
    asyncio.run(run())


# ── Device info ──────────────────────────────────────────────────────────────

def test_get_device_info_parses_kv_text():
    async def run():
        p = DahuaProvider(_cam())
        _install_mock(p, {
            "getDeviceType": "type=IPC-HFW2431S-S-S2",
            "getSerialNo": "sn=ABC1234567",
            "getSoftwareVersion": "version=2.800.0000000.15.R,build:2021-05-13",
            "getConfig": "table.General.MachineName=CameraPortail\r\ntable.General.LocalNo=0",
        })
        info = await p.get_device_info()
        assert info.manufacturer == "Dahua"
        assert info.model == "IPC-HFW2431S-S-S2"
        assert info.serial == "ABC1234567"
        assert info.firmware == "2.800.0000000.15.R,build:2021-05-13"
        assert info.name == "CameraPortail"
        await p.close()
    asyncio.run(run())


# ── Capabilities (probes) ────────────────────────────────────────────────────

def test_get_capabilities_probes_each_feature():
    async def run():
        p = DahuaProvider(_cam())
        _install_mock(p, {
            "getStatus": "status.PtzStatus=0",
            "getConfig": "table.VideoInDayNight[0].Mode=Auto",
            # "Lighting" getConfig collides with VideoInDayNight in this mock
            # (both use action=getConfig) — router only keys on `action`, so
            # this test only checks that a successful probe → True path works.
        })
        caps = await p.get_capabilities()
        assert caps.ptz is True
        assert caps.ir is True
        assert caps.siren is False
        await p.close()
    asyncio.run(run())


def test_get_capabilities_all_unsupported_when_probes_fail():
    async def run():
        p = DahuaProvider(_cam())
        _install_mock(p, {})   # tout renvoie "Error" → toutes les probes échouent
        caps = await p.get_capabilities()
        assert caps.ptz is False
        assert caps.ir is False
        assert caps.light is False
        await p.close()
    asyncio.run(run())


# ── IR jour/nuit ─────────────────────────────────────────────────────────────

def test_get_ir_maps_mode():
    async def run():
        p = DahuaProvider(_cam())
        _install_mock(p, {"getConfig": "table.VideoInDayNight[0].Mode=BlackWhite"})
        result = await p.get_ir()
        assert result["mode"] == "on"
        await p.close()
    asyncio.run(run())


def test_set_ir_invalid_mode_raises():
    async def run():
        p = DahuaProvider(_cam())
        with pytest.raises(CameraApiError):
            await p.set_ir("nightvision")
        await p.close()
    asyncio.run(run())


def test_set_ir_valid_mode_sends_setconfig():
    async def run():
        p = DahuaProvider(_cam())
        _install_mock(p, {"setConfig": "OK"})
        await p.set_ir("on")   # ne doit pas lever
        await p.close()
    asyncio.run(run())


# ── Sirène (non supportée par design) ───────────────────────────────────────

def test_siren_raises_unsupported():
    async def run():
        p = DahuaProvider(_cam())
        with pytest.raises(UnsupportedCapability):
            await p.get_siren()
        with pytest.raises(UnsupportedCapability):
            await p.set_siren(True)
        await p.close()
    asyncio.run(run())


# ── PTZ ──────────────────────────────────────────────────────────────────────

def test_ptz_move_invalid_direction_raises():
    async def run():
        p = DahuaProvider(_cam())
        with pytest.raises(CameraApiError):
            await p.ptz_move("diagonal")
        await p.close()
    asyncio.run(run())


def test_ptz_move_and_stop_send_expected_actions():
    async def run():
        p = DahuaProvider(_cam())
        seen = []
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(dict(request.url.params))
            return httpx.Response(200, text="OK")
        p._client = httpx.AsyncClient(base_url=p.base_url, transport=httpx.MockTransport(handler),
                                       verify=False, timeout=5)
        await p.ptz_move("left", speed=1.0)
        await p.ptz_stop()
        assert seen[0]["action"] == "start"
        assert seen[0]["code"] == "Left"
        assert seen[0]["arg2"] == "8"
        assert seen[1]["action"] == "stop"
        await p.close()
    asyncio.run(run())
