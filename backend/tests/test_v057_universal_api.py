"""Tests v0.5.7 · Universal Camera API — Phase 1 (consolidation contrat).

Vérifications :

  1. ``pipeline_v2.camera_driver`` ré-exporte les mêmes objets que
     ``drivers`` — pas de duplication.
  2. Le nouveau ``CameraCapabilities`` accepte les flags v0.5.7 sans
     casser les tests existants.
  3. ``CameraDriverProtocol`` reconnaît structurellement une instance
     ``CameraDriver``.
  4. ``CameraManager`` délègue proprement au ``CameraDeviceService``.
  5. ``CameraManager.validate_camera_doc`` détecte les IP manquantes
     sans I/O.
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db_v057")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ────────────────────────────────────────────────────────────────
# 1. Identité des exports — un seul contrat, deux chemins d'import
# ────────────────────────────────────────────────────────────────
class TestSingleSourceOfTruth:
    def test_camera_driver_class_is_identical(self):
        from drivers import CameraDriver as A
        from pipeline_v2.camera_driver import CameraDriver as B
        assert A is B, "CameraDriver doit être unique — pas de duplication"

    def test_capabilities_class_is_identical(self):
        from drivers import CameraCapabilities as A
        from pipeline_v2.camera_driver import CameraCapabilities as B
        assert A is B

    def test_deviceinfo_class_is_identical(self):
        from drivers import DeviceInfo as A
        from pipeline_v2.camera_driver import DeviceInfo as B
        assert A is B

    def test_exceptions_are_identical(self):
        from drivers import (
            CameraDriverError as A1, UnsupportedCapabilityError as B1,
            AuthenticationError as C1, DeviceConnectionError as D1,
        )
        from pipeline_v2.camera_driver import (
            CameraDriverError as A2, UnsupportedCapabilityError as B2,
            AuthenticationError as C2, DeviceConnectionError as D2,
        )
        assert (A1, B1, C1, D1) == (A2, B2, C2, D2)

    def test_registry_functions_are_identical(self):
        from drivers import (
            register_driver as r1, get_driver as g1,
            resolve_driver as re1, list_supported_vendors as l1,
        )
        from pipeline_v2.camera_driver import (
            register_driver as r2, get_driver as g2,
            resolve_driver as re2, list_supported_vendors as l2,
        )
        assert (r1, g1, re1, l1) == (r2, g2, re2, l2)


# ────────────────────────────────────────────────────────────────
# 2. Enrichissement backward-compatible de CameraCapabilities
# ────────────────────────────────────────────────────────────────
class TestCapabilitiesEnrichment:
    def test_default_construction_still_works(self):
        from drivers import CameraCapabilities
        caps = CameraCapabilities()
        # Anciens flags par défaut à False
        assert caps.ptz is False
        assert caps.siren is False
        assert caps.onboard_ai is False
        # Nouveaux flags par défaut à False (aucune régression)
        assert caps.multi_stream is False
        assert caps.codec_h265 is False
        assert caps.ai_person is False
        assert caps.thermal is False
        assert caps.wifi is False
        assert caps.proprietary_api is False

    def test_new_flags_are_settable(self):
        from drivers import CameraCapabilities
        caps = CameraCapabilities(
            ai_person=True, ai_vehicle=True, ai_anpr=True,
            thermal=True, wifi=True, poe=True, sdcard=True,
            codec_h265=True, multi_stream=True,
        )
        assert caps.ai_person and caps.ai_vehicle and caps.ai_anpr
        assert caps.thermal and caps.wifi and caps.poe
        assert caps.sdcard and caps.codec_h265 and caps.multi_stream

    def test_to_dict_includes_new_flags(self):
        from drivers import CameraCapabilities
        caps = CameraCapabilities(ai_person=True, sdcard=True)
        d = caps.to_dict()
        assert d["ai_person"] is True
        assert d["sdcard"] is True
        # Anciens champs toujours présents
        assert d["ptz"] is False
        assert d["onvif"] is False
        assert d["max_resolution"] == [0, 0]

    def test_legacy_reolink_test_still_works(self):
        """Un dataclass initialisé avec les mots-clefs historiques
        (avant v0.5.7) fonctionne toujours — pas de field renommé."""
        from drivers import CameraCapabilities
        caps = CameraCapabilities(
            spotlight=True, siren=True, pir_sensor=True, battery=True,
            onboard_ai=True, onboard_ai_features=("person", "vehicle"),
            reolink_api=True,
        )
        assert caps.spotlight and caps.siren and caps.pir_sensor
        assert caps.battery and caps.onboard_ai
        assert "person" in caps.onboard_ai_features
        assert caps.reolink_api


# ────────────────────────────────────────────────────────────────
# 3. Facette Protocol structurelle
# ────────────────────────────────────────────────────────────────
class TestCameraDriverProtocol:
    def test_onvif_driver_matches_protocol(self):
        from pipeline_v2.camera_driver import CameraDriverProtocol
        from drivers.onvif_driver import ONVIFDriver
        d = ONVIFDriver("1.2.3.4", "u", "p")
        assert isinstance(d, CameraDriverProtocol)

    def test_reolink_driver_matches_protocol(self):
        from pipeline_v2.camera_driver import CameraDriverProtocol
        from drivers.reolink_driver import ReolinkDriver
        d = ReolinkDriver("1.2.3.4", "u", "p")
        assert isinstance(d, CameraDriverProtocol)

    def test_plain_object_does_not_match(self):
        from pipeline_v2.camera_driver import CameraDriverProtocol
        assert not isinstance(object(), CameraDriverProtocol)


# ────────────────────────────────────────────────────────────────
# 4. CameraManager — délégation stricte
# ────────────────────────────────────────────────────────────────
class TestCameraManagerDelegation:
    def test_supported_vendors_matches_registry(self):
        from pipeline_v2.camera_manager import camera_manager
        from drivers import list_supported_vendors
        assert camera_manager.supported_vendors() == list_supported_vendors()

    def test_get_driver_delegates_to_service(self, monkeypatch):
        """``manager.get_driver`` doit appeler ``camera_device_service.get_driver``."""
        from pipeline_v2 import camera_manager as mgr_mod
        fake_driver = MagicMock(name="FakeDriver")
        fake_service = MagicMock()
        fake_service.get_driver = AsyncMock(return_value=fake_driver)
        monkeypatch.setattr(mgr_mod, "camera_device_service", fake_service)

        result = _run(mgr_mod.camera_manager.get_driver("cam-42"))

        fake_service.get_driver.assert_awaited_once_with("cam-42")
        assert result is fake_driver

    def test_release_delegates_to_service(self, monkeypatch):
        from pipeline_v2 import camera_manager as mgr_mod
        fake_service = MagicMock()
        fake_service.release = AsyncMock(return_value=None)
        monkeypatch.setattr(mgr_mod, "camera_device_service", fake_service)

        _run(mgr_mod.camera_manager.release("cam-7"))
        fake_service.release.assert_awaited_once_with("cam-7")

    def test_discover_delegates_to_service(self, monkeypatch):
        from pipeline_v2 import camera_manager as mgr_mod
        expected = {"info": {}, "capabilities": {}, "streams": [], "driver": "onvif"}
        fake_service = MagicMock()
        fake_service.discover = AsyncMock(return_value=expected)
        monkeypatch.setattr(mgr_mod, "camera_device_service", fake_service)

        result = _run(mgr_mod.camera_manager.discover("cam-1"))
        fake_service.discover.assert_awaited_once_with("cam-1")
        assert result == expected


class TestCameraManagerValidation:
    def test_validate_accepts_valid_camera(self):
        from pipeline_v2.camera_manager import camera_manager
        assert camera_manager.validate_camera_doc(
            {"id": "c1", "ip": "10.0.0.1", "vendor": "reolink"}
        ) is None

    def test_validate_accepts_host_as_alias_for_ip(self):
        from pipeline_v2.camera_manager import camera_manager
        assert camera_manager.validate_camera_doc(
            {"id": "c1", "host": "cam.local"}
        ) is None

    def test_validate_rejects_missing_ip(self):
        from pipeline_v2.camera_manager import camera_manager
        err = camera_manager.validate_camera_doc({"id": "c1"})
        assert err == "camera_missing_ip"

    def test_validate_rejects_non_dict(self):
        from pipeline_v2.camera_manager import camera_manager
        assert camera_manager.validate_camera_doc(None) is not None
        assert camera_manager.validate_camera_doc("not a dict") is not None


# ────────────────────────────────────────────────────────────────
# 5. Manager purement passif — pas de logique métier
# ────────────────────────────────────────────────────────────────
class TestCameraManagerHasNoBusinessLogic:
    def test_manager_does_not_expose_ptz_or_light_methods(self):
        """Règle v0.5.7 : CameraManager ne doit PAS exposer de commandes
        métier. Ces commandes passent par le driver."""
        from pipeline_v2.camera_manager import CameraManager
        m = CameraManager()
        assert not hasattr(m, "ptz_move")
        assert not hasattr(m, "set_light")
        assert not hasattr(m, "set_siren")
        assert not hasattr(m, "start_audio")
        assert not hasattr(m, "snapshot")
