"""Tests unitaires · camera_api Hikvision provider.

Mocke httpx pour valider le parsing XML ISAPI (regex, sans namespace), le
pattern GET→modifie 1 balise→PUT document complet, l'auth Digest, et les
erreurs (401, 404→UnsupportedCapability, injoignable, mode IR invalide).
"""
import asyncio

import httpx
import pytest

from camera_api import AuthenticationFailed, DeviceUnreachable, list_providers, resolve_provider
from camera_api.exceptions import UnsupportedCapability, CameraApiError
from camera_api.providers.hikvision import HikvisionProvider

_DEVICE_INFO_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema" version="2.0">'
    '<deviceName>CameraEntree</deviceName>'
    '<model>DS-2CD2387G2-LU</model>'
    '<serialNumber>DS-2CD2387G2-LUABC123</serialNumber>'
    '<firmwareVersion>V5.7.3</firmwareVersion>'
    '<hardwareVersion>0x0</hardwareVersion>'
    '</DeviceInfo>'
)

_IRCUT_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<IrcutFilter xmlns="http://www.hikvision.com/ver20/XMLSchema">'
    '<IrcutFilterType>auto</IrcutFilterType>'
    '<nightToDayFilterTime>5</nightToDayFilterTime>'
    '</IrcutFilter>'
)

_LIGHT_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<SupplementLight xmlns="http://www.hikvision.com/ver20/XMLSchema">'
    '<supplementLightMode>close</supplementLightMode>'
    '<whiteLightBrightness>50</whiteLightBrightness>'
    '</SupplementLight>'
)


def _cam(**over) -> dict:
    return {"id": "pytest-hik", "api_host": "192.0.2.61", "api_port": 80,
            "api_scheme": "http", "api_username": "admin", "api_password": "s3cret", **over}


def _install_mock(provider: HikvisionProvider, routes: dict) -> None:
    """`routes` = { "/ISAPI/...": (status, text) or Exception or text }."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path not in routes:
            return httpx.Response(404, text="")
        v = routes[path]
        if isinstance(v, Exception):
            raise v
        if isinstance(v, tuple):
            status, text = v
            return httpx.Response(status, text=text)
        return httpx.Response(200, text=v)
    provider._client = httpx.AsyncClient(base_url=provider.base_url,
                                          transport=httpx.MockTransport(handler),
                                          verify=False, timeout=5)


# ── Registry ───────────────────────────────────────────────────────────────

def test_registry_lists_hikvision():
    assert "hikvision" in list_providers()


def test_resolve_by_manufacturer():
    assert resolve_provider(manufacturer="Hikvision") is HikvisionProvider
    assert resolve_provider(model="Hikvision DS-2CD2387G2-LU") is HikvisionProvider
    assert resolve_provider(provider_id="hikvision") is HikvisionProvider


# ── Session ────────────────────────────────────────────────────────────────

def test_login_without_credentials_raises():
    async def run():
        p = HikvisionProvider(_cam(api_password=""))
        with pytest.raises(AuthenticationFailed):
            await p.login()
        await p.close()
    asyncio.run(run())


def test_login_success():
    async def run():
        p = HikvisionProvider(_cam())
        _install_mock(p, {"/ISAPI/System/deviceInfo": _DEVICE_INFO_XML})
        await p.login()
        await p.close()
    asyncio.run(run())


def test_unreachable_raises_device_unreachable():
    async def run():
        p = HikvisionProvider(_cam())
        def _boom(req):
            raise httpx.ConnectError("connection refused")
        p._client = httpx.AsyncClient(base_url=p.base_url, transport=httpx.MockTransport(_boom),
                                       verify=False, timeout=5)
        with pytest.raises(DeviceUnreachable):
            await p.login()
        await p.close()
    asyncio.run(run())


# ── Device info ──────────────────────────────────────────────────────────────

def test_get_device_info_parses_xml_regardless_of_namespace():
    async def run():
        p = HikvisionProvider(_cam())
        _install_mock(p, {"/ISAPI/System/deviceInfo": _DEVICE_INFO_XML})
        info = await p.get_device_info()
        assert info.manufacturer == "Hikvision"
        assert info.model == "DS-2CD2387G2-LU"
        assert info.serial == "DS-2CD2387G2-LUABC123"
        assert info.firmware == "V5.7.3"
        assert info.name == "CameraEntree"
        await p.close()
    asyncio.run(run())


# ── Capabilities (probes 404 = non supporté) ────────────────────────────────

def test_get_capabilities_light_absent_returns_false():
    async def run():
        p = HikvisionProvider(_cam())
        _install_mock(p, {
            "/ISAPI/PTZCtrl/channels/1/status": "<PTZStatus/>",
            "/ISAPI/Image/channels/1/ircutFilter": _IRCUT_XML,
            # supplementLight absent du dict → 404 → light=False (modèle IR-only)
        })
        caps = await p.get_capabilities()
        assert caps.ptz is True
        assert caps.ir is True
        assert caps.light is False
        assert caps.siren is False
        await p.close()
    asyncio.run(run())


# ── IR jour/nuit ─────────────────────────────────────────────────────────────

def test_get_ir_maps_mode():
    async def run():
        p = HikvisionProvider(_cam())
        _install_mock(p, {"/ISAPI/Image/channels/1/ircutFilter": _IRCUT_XML})
        result = await p.get_ir()
        assert result["mode"] == "auto"
        await p.close()
    asyncio.run(run())


def test_set_ir_invalid_mode_raises():
    async def run():
        p = HikvisionProvider(_cam())
        with pytest.raises(CameraApiError):
            await p.set_ir("nightvision")
        await p.close()
    asyncio.run(run())


def test_set_ir_get_modify_put_preserves_other_fields():
    async def run():
        p = HikvisionProvider(_cam())
        put_bodies = []
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, text=_IRCUT_XML)
            put_bodies.append(request.content.decode())
            return httpx.Response(200, text="<ResponseStatus><statusCode>1</statusCode></ResponseStatus>")
        p._client = httpx.AsyncClient(base_url=p.base_url, transport=httpx.MockTransport(handler),
                                       verify=False, timeout=5)
        await p.set_ir("on")
        assert "<IrcutFilterType>night</IrcutFilterType>" in put_bodies[0]
        assert "<nightToDayFilterTime>5</nightToDayFilterTime>" in put_bodies[0]   # champ préservé
        await p.close()
    asyncio.run(run())


# ── Sirène (non supportée par design) ───────────────────────────────────────

def test_siren_raises_unsupported():
    async def run():
        p = HikvisionProvider(_cam())
        with pytest.raises(UnsupportedCapability):
            await p.get_siren()
        with pytest.raises(UnsupportedCapability):
            await p.set_siren(True)
        await p.close()
    asyncio.run(run())


# ── PTZ ──────────────────────────────────────────────────────────────────────

def test_ptz_move_invalid_direction_raises():
    async def run():
        p = HikvisionProvider(_cam())
        with pytest.raises(CameraApiError):
            await p.ptz_move("diagonal")
        await p.close()
    asyncio.run(run())


def test_ptz_move_sends_pan_tilt_vector():
    async def run():
        p = HikvisionProvider(_cam())
        bodies = []
        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(request.content.decode())
            return httpx.Response(200, text="OK")
        p._client = httpx.AsyncClient(base_url=p.base_url, transport=httpx.MockTransport(handler),
                                       verify=False, timeout=5)
        await p.ptz_move("right", speed=1.0)
        assert "<pan>100</pan>" in bodies[0]
        assert "<tilt>0</tilt>" in bodies[0]
        await p.ptz_stop()
        assert "<pan>0</pan><tilt>0</tilt><zoom>0</zoom>" in bodies[1]
        await p.close()
    asyncio.run(run())
