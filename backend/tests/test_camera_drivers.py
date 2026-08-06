"""Tests v0.4.6 · Camera Device Layer.

Ces tests utilisent des MOCKS des drivers ONVIF/Reolink — aucune caméra
physique n'est requise. Ils vérifient :

  1. Contrat CameraDriver (base + implémentations concrètes)
  2. Découverte + probe de capacités
  3. Commandes propres (light / IR / siren / PTZ)
  4. Erreurs propres pour capacités non supportées (JAMAIS 500)
  5. Registry + fallback ONVIF
  6. Service : cache par camera_id, persistance Mongo
  7. Routes API : codes HTTP corrects par type d'erreur
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db_v046")

from drivers import (  # noqa: E402
    CameraDriver, CameraCapabilities, DeviceInfo, DeviceStatus, StreamInfo,
    LightMode, IRMode,
    UnsupportedCapabilityError, DeviceConnectionError, AuthenticationError,
    CameraDriverError,
    register_driver, get_driver, resolve_driver, list_supported_vendors,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ────────────────────────────────────────────────────────────────
# 1. Registry + fallback ONVIF
# ────────────────────────────────────────────────────────────────

class TestRegistry:
    def test_supported_vendors_include_all(self):
        vendors = list_supported_vendors()
        assert "onvif" in vendors
        assert "reolink" in vendors
        assert "dahua" in vendors
        assert "hikvision" in vendors
        assert "generic" in vendors

    def test_unknown_vendor_falls_back_to_onvif(self):
        cls = get_driver("brand-that-does-not-exist")
        from drivers.onvif_driver import ONVIFDriver
        assert cls is ONVIFDriver

    def test_resolve_driver_returns_correct_class(self):
        d = resolve_driver("reolink", "1.2.3.4", "admin", "pwd", port=80)
        from drivers.reolink_driver import ReolinkDriver
        assert isinstance(d, ReolinkDriver)
        assert d.host == "1.2.3.4"


# ────────────────────────────────────────────────────────────────
# 2. Contrat CameraDriver — capacités bloquent les commandes
# ────────────────────────────────────────────────────────────────

class _MockDriver(CameraDriver):
    """Driver mock complet pour tester le contrat."""
    vendor = "mock"

    async def connect(self):
        self._connected = True

    async def get_device_info(self):
        return DeviceInfo(manufacturer="MockCorp", model="MK-1000", ip=self.host)

    async def get_capabilities(self):
        return self._caps or CameraCapabilities()


class TestCapabilityGuards:
    def _make(self, **caps_kwargs):
        d = _MockDriver("1.1.1.1", "u", "p")
        d._caps = CameraCapabilities(**caps_kwargs)
        return d

    def test_light_blocked_without_capability(self):
        d = self._make()
        with pytest.raises(UnsupportedCapabilityError) as exc:
            _run(d.set_light(enabled=True))
        assert exc.value.code == "unsupported_capability"

    def test_light_allowed_with_spotlight(self):
        d = self._make(spotlight=True)
        # Aucun _set_light concret → doit lever "non implémenté" (mais après le require)
        with pytest.raises(UnsupportedCapabilityError):
            _run(d.set_light(enabled=True))

    def test_siren_blocked_without_capability(self):
        d = self._make()
        with pytest.raises(UnsupportedCapabilityError):
            _run(d.set_siren(enabled=True))

    def test_ptz_blocked_without_capability(self):
        d = self._make()
        with pytest.raises(UnsupportedCapabilityError):
            _run(d.ptz_move("up"))
        with pytest.raises(UnsupportedCapabilityError):
            _run(d.ptz_zoom(0.5))
        with pytest.raises(UnsupportedCapabilityError):
            _run(d.ptz_preset(1))

    def test_audio_blocked_without_capability(self):
        d = self._make()
        with pytest.raises(UnsupportedCapabilityError):
            _run(d.start_audio())
        with pytest.raises(UnsupportedCapabilityError):
            _run(d.stop_audio())

    def test_error_payload_serialization(self):
        """Une UnsupportedCapabilityError doit produire un JSON propre."""
        d = self._make()
        try:
            _run(d.set_siren(enabled=True))
        except UnsupportedCapabilityError as e:
            payload = e.to_dict()
            assert payload["success"] is False
            assert payload["error"] == "unsupported_capability"
            assert "sirène" in payload["message"].lower() or "siren" in payload["message"].lower()


# ────────────────────────────────────────────────────────────────
# 3. Reolink API — mock httpx et vérifier commandes JSON
# ────────────────────────────────────────────────────────────────

class TestReolinkDriver:
    def test_get_capabilities_via_mocked_get_ability(self):
        from drivers.reolink_driver import ReolinkDriver
        d = ReolinkDriver("192.168.1.10", "admin", "pass")
        d._connected = True
        d._device_info_cache = DeviceInfo(manufacturer="Reolink", ip="192.168.1.10")

        # Mock _call pour simuler GetAbility d'une caméra floodlight+siren+PIR
        async def fake_call(cmd, param, timeout=6.0):
            if cmd == "GetAbility":
                return {"Ability": {"abilityChn": [{
                    "floodLight": {"ver": 1, "permit": 6},
                    "supportBuzzer": {"ver": 1, "permit": 6},
                    "supportAlarmPir": {"ver": 1, "permit": 6},
                    "supportAiPeople": {"ver": 1, "permit": 6},
                    "supportAiVehicle": {"ver": 1, "permit": 6},
                    "battery": {"ver": 1, "permit": 6},
                }]}}
            return {}

        d._call = fake_call
        # Bypass parent get_capabilities (qui appelle ONVIF)
        d._caps = None
        original_super_caps = CameraCapabilities(onvif=False)
        with patch("drivers.reolink_driver.ONVIFDriver.get_capabilities",
                    new=AsyncMock(return_value=original_super_caps)):
            caps = _run(d.get_capabilities())
        assert caps.spotlight is True
        assert caps.siren is True
        assert caps.pir_sensor is True
        assert caps.battery is True
        assert caps.onboard_ai is True
        assert "person" in caps.onboard_ai_features
        assert "vehicle" in caps.onboard_ai_features
        assert caps.reolink_api is True

    def test_set_light_calls_setwhiteled(self):
        from drivers.reolink_driver import ReolinkDriver
        d = ReolinkDriver("192.168.1.10", "admin", "pass")
        d._connected = True
        d._caps = CameraCapabilities(spotlight=True)

        calls = []
        async def fake_call(cmd, param, timeout=6.0):
            calls.append((cmd, param))
            return {}
        d._call = fake_call
        _run(d.set_light(enabled=True, brightness=80, mode=LightMode.ON))
        assert calls[0][0] == "SetWhiteLed"
        assert calls[0][1]["WhiteLed"]["state"] == 1
        assert calls[0][1]["WhiteLed"]["bright"] == 80

    def test_set_siren_calls_audio_alarm_play(self):
        from drivers.reolink_driver import ReolinkDriver
        d = ReolinkDriver("192.168.1.10", "admin", "pass")
        d._connected = True
        d._caps = CameraCapabilities(siren=True)
        calls = []
        async def fake_call(cmd, param, timeout=6.0):
            calls.append((cmd, param))
            return {}
        d._call = fake_call
        _run(d.set_siren(enabled=True, duration=10))
        assert calls[0][0] == "AudioAlarmPlay"
        assert calls[0][1]["manualSwitch"] == 1
        assert calls[0][1]["duration"] == 10

    def test_auth_error_maps_correctly(self):
        from drivers.reolink_driver import ReolinkDriver
        d = ReolinkDriver("192.168.1.10", "admin", "pass")
        d._connected = True

        class _FakeResp:
            status_code = 200
            def json(self):
                return [{"cmd": "X", "code": 1, "error": {"rspCode": -6, "detail": "user error"}}]

        class _FakeClient:
            async def post(self, *a, **kw):
                return _FakeResp()
            async def aclose(self):
                pass

        d._http = _FakeClient()
        with pytest.raises(AuthenticationError):
            _run(d._call("GetAbility", {}))


# ────────────────────────────────────────────────────────────────
# 4. Service — cache + persistance
# ────────────────────────────────────────────────────────────────

class TestCameraDeviceService:
    def test_get_driver_caches_per_camera(self):
        """Deux appels get_driver pour la même caméra → même instance."""
        from services.camera_device_service import CameraDeviceService
        svc = CameraDeviceService()

        # Mock _load_camera + resolve_driver
        async def fake_load(cam_id):
            return {"id": cam_id, "ip": "10.0.0.1", "username": "u",
                    "password": "p", "vendor": "reolink"}
        svc._load_camera = fake_load

        # Mock resolve_driver pour retourner un driver mock connecté
        fake_drv = MagicMock()
        fake_drv._connected = False
        async def fake_connect():
            fake_drv._connected = True
        fake_drv.connect = fake_connect

        with patch("services.camera_device_service.resolve_driver", return_value=fake_drv):
            d1 = _run(svc.get_driver("cam-1"))
            d2 = _run(svc.get_driver("cam-1"))
        assert d1 is d2
        assert d1._connected is True

    def test_missing_ip_raises_clean_error(self):
        from services.camera_device_service import CameraDeviceService
        svc = CameraDeviceService()

        async def fake_load(cam_id):
            return {"id": cam_id, "vendor": "onvif"}  # pas d'IP
        svc._load_camera = svc._load_camera  # garde l'original

        # Injecte la caméra directement en Mongo mock : on utilise _load_camera direct
        # via patch de la méthode privée
        async def _load_raw(cam_id):
            # Simule le comportement natif : raise si pas d'IP
            cam = {"id": cam_id, "vendor": "onvif"}
            if not cam.get("ip") and not cam.get("host"):
                raise CameraDriverError(f"Caméra {cam_id} sans IP configurée",
                                         code="camera_missing_ip")
            return cam

        svc._load_camera = _load_raw
        with pytest.raises(CameraDriverError) as exc:
            _run(svc.get_driver("cam-no-ip"))
        assert exc.value.code == "camera_missing_ip"


# ────────────────────────────────────────────────────────────────
# 5. Routes API — HTTP status codes propres
# ────────────────────────────────────────────────────────────────

class TestDeviceRoutesErrorMapping:
    def test_unsupported_capability_maps_to_400(self):
        from routes.devices import _driver_error_response
        exc = _driver_error_response(UnsupportedCapabilityError("nope"))
        assert exc.status_code == 400
        assert exc.detail["error"] == "unsupported_capability"

    def test_camera_not_found_maps_to_404(self):
        from routes.devices import _driver_error_response
        exc = _driver_error_response(CameraDriverError("nope", code="camera_not_found"))
        assert exc.status_code == 404

    def test_auth_failed_maps_to_401(self):
        from routes.devices import _driver_error_response
        exc = _driver_error_response(AuthenticationError("bad creds"))
        assert exc.status_code == 401

    def test_device_unreachable_maps_to_503(self):
        from routes.devices import _driver_error_response
        exc = _driver_error_response(DeviceConnectionError("timeout"))
        assert exc.status_code == 503

    def test_missing_ip_maps_to_400(self):
        from routes.devices import _driver_error_response
        exc = _driver_error_response(CameraDriverError("no ip", code="camera_missing_ip"))
        assert exc.status_code == 400


# ────────────────────────────────────────────────────────────────
# 6. Camera sans certaines capacités — flow métier standard
# ────────────────────────────────────────────────────────────────

class TestCameraWithoutCapabilities:
    def test_camera_without_audio_rejects_start_audio(self):
        d = _MockDriver("1.1.1.1", "u", "p")
        d._caps = CameraCapabilities(ptz=True, zoom=True)  # PTZ oui, audio non
        with pytest.raises(UnsupportedCapabilityError) as exc:
            _run(d.start_audio())
        assert exc.value.to_dict()["error"] == "unsupported_capability"

    def test_camera_without_ptz_rejects_ptz(self):
        d = _MockDriver("1.1.1.1", "u", "p")
        d._caps = CameraCapabilities(spotlight=True)
        with pytest.raises(UnsupportedCapabilityError):
            _run(d.ptz_preset(1))
