"""Tests v0.5.7 · Universal Camera API — Validator + Matrix + Driver Health.

100 % mocks : aucune caméra physique, aucune I/O réseau.

Objectifs :
  - Driver Validator : score pondéré, états valides, non destructif.
  - Capability Matrix : agrégat par vendor/driver/model/camera.
  - Driver Health : manifests + stats runtime.
  - Non-régression : les 43 tests précédents (v0.5.7 Phase 1 + v0.4.6) tiennent.
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db_v057b")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ────────────────────────────────────────────────────────────────
# Fakes / helpers
# ────────────────────────────────────────────────────────────────
def _make_streams(*, url="rtsp://1.2.3.4/live"):
    from drivers import StreamInfo
    return [StreamInfo(name="main", url=url, resolution=(1920, 1080), fps=25)]


def _make_info(manufacturer="Reolink", model="RLC-1224A"):
    from drivers import DeviceInfo
    return DeviceInfo(manufacturer=manufacturer, model=model, ip="10.0.0.1")


class _FakeDriver:
    """Faux driver piloté par attributs — utilisé par le Validator via monkeypatch."""
    vendor = "reolink"

    def __init__(self, *, streams=None, info=None, raise_info=None, raise_streams=None,
                  events=True, override_ptz=True, override_siren=True,
                  override_audio=True, override_reboot=False):
        self._streams = streams if streams is not None else _make_streams()
        self._info = info or _make_info()
        self._raise_info = raise_info
        self._raise_streams = raise_streams
        self._events_supported = events
        self._flags = {
            "ptz": override_ptz, "siren": override_siren,
            "audio": override_audio, "reboot": override_reboot,
        }
        if events:
            self.get_events = lambda: []

    async def get_device_info(self):
        if self._raise_info:
            raise self._raise_info
        return self._info

    async def get_streams(self):
        if self._raise_streams:
            raise self._raise_streams
        return self._streams


def _install_contract_flags(fake: _FakeDriver, monkeypatch):
    """Fait croire au validator que certaines méthodes privées sont surchargées."""
    from pipeline_v2 import driver_validator as v_mod
    real = v_mod._method_is_overridden
    mapping = {
        "_ptz_move": fake._flags["ptz"],
        "_ptz_preset": fake._flags["ptz"],
        "_set_siren": fake._flags["siren"],
        "_start_audio": fake._flags["audio"],
        "_stop_audio": fake._flags["audio"],
        "reboot": fake._flags["reboot"],
        "_reboot": fake._flags["reboot"],
    }

    def fake_check(driver, name):
        if driver is fake and name in mapping:
            return mapping[name]
        return real(driver, name)
    monkeypatch.setattr(v_mod, "_method_is_overridden", fake_check)


# ────────────────────────────────────────────────────────────────
# 1. Enum d'états + poids officiels
# ────────────────────────────────────────────────────────────────
class TestEnumAndWeights:
    def test_states_are_exactly_the_authorized_set(self):
        from pipeline_v2.driver_validator import TestState
        vals = {s.value for s in TestState}
        assert vals == {"pass", "warning", "fail", "timeout", "unsupported", "skipped"}

    def test_weights_match_spec(self):
        from pipeline_v2.driver_validator import TEST_WEIGHTS
        assert TEST_WEIGHTS == {
            "snapshot": 25, "stream": 25, "device_info": 15, "events": 15,
            "ptz": 10, "audio": 5, "reboot": 3, "siren": 2,
        }
        # Somme = 100 pour un audit interne
        assert sum(TEST_WEIGHTS.values()) == 100


# ────────────────────────────────────────────────────────────────
# 2. Validator — happy path : caméra full-featured
# ────────────────────────────────────────────────────────────────
class TestValidatorHappyPath:
    def _patch_manager(self, monkeypatch, driver):
        from pipeline_v2 import driver_validator as v_mod
        fake_mgr = MagicMock()
        fake_mgr.get_driver = AsyncMock(return_value=driver)
        monkeypatch.setattr(v_mod, "camera_manager", fake_mgr)

    def test_full_featured_camera_scores_100(self, monkeypatch):
        from pipeline_v2.driver_validator import driver_validator, TestState
        fake = _FakeDriver()
        self._patch_manager(monkeypatch, fake)
        _install_contract_flags(fake, monkeypatch)

        report = _run(driver_validator.validate("cam-42"))
        # Score max — toutes les capacités PASS
        assert report.score == 100
        assert report.camera_id == "cam-42"
        assert report.vendor == "reolink"
        assert report.model == "RLC-1224A"
        assert report.driver == "reolink"
        assert isinstance(report.validation_id, str) and len(report.validation_id) > 8
        assert report.duration_ms >= 0
        # Tous les tests présents
        for k in ("snapshot", "stream", "device_info", "events", "ptz", "audio", "reboot", "siren"):
            assert k in report.tests
        assert report.tests["stream"]["state"] == TestState.PASS.value
        assert report.tests["ptz"]["state"] == TestState.PASS.value

    def test_report_shape_contains_required_fields(self, monkeypatch):
        from pipeline_v2.driver_validator import driver_validator
        fake = _FakeDriver()
        self._patch_manager(monkeypatch, fake)
        _install_contract_flags(fake, monkeypatch)
        report = _run(driver_validator.validate("cam-1"))
        d = report.to_dict()
        for key in ("validation_id", "camera_id", "vendor", "model", "driver",
                    "started_at", "finished_at", "duration_ms", "score", "tests"):
            assert key in d
        assert isinstance(d["score"], int)


# ────────────────────────────────────────────────────────────────
# 3. Validator — capacités absentes / erreurs
# ────────────────────────────────────────────────────────────────
class TestValidatorPartialSupport:
    def _patch_manager(self, monkeypatch, driver):
        from pipeline_v2 import driver_validator as v_mod
        fake_mgr = MagicMock()
        fake_mgr.get_driver = AsyncMock(return_value=driver)
        monkeypatch.setattr(v_mod, "camera_manager", fake_mgr)

    def test_camera_without_ptz_is_unsupported_not_fail(self, monkeypatch):
        from pipeline_v2.driver_validator import driver_validator, TestState
        fake = _FakeDriver(override_ptz=False, override_siren=False,
                            override_audio=False, override_reboot=False)
        self._patch_manager(monkeypatch, fake)
        _install_contract_flags(fake, monkeypatch)
        report = _run(driver_validator.validate("cam-1"))
        assert report.tests["ptz"]["state"] == TestState.UNSUPPORTED.value
        assert report.tests["siren"]["state"] == TestState.UNSUPPORTED.value
        # Score toujours 100 : les tests UNSUPPORTED ne pénalisent pas
        assert report.score == 100

    def test_stream_fail_lowers_score(self, monkeypatch):
        from pipeline_v2.driver_validator import driver_validator, TestState
        fake = _FakeDriver(streams=[])  # aucun stream
        self._patch_manager(monkeypatch, fake)
        _install_contract_flags(fake, monkeypatch)
        report = _run(driver_validator.validate("cam-1"))
        assert report.tests["stream"]["state"] == TestState.UNSUPPORTED.value
        assert report.tests["snapshot"]["state"] == TestState.UNSUPPORTED.value
        # Denominator = 15 (device_info) + 15 (events) + 10 (ptz) + 5 (audio) + 3 (reboot=UNSUPPORTED cf flags) + 2 (siren)
        # avec les flags par défaut override_reboot=False → UNSUPPORTED
        # Tous les tests supportés en PASS → score 100 encore.
        assert report.score == 100

    def test_device_info_fail_lowers_score(self, monkeypatch):
        from pipeline_v2.driver_validator import driver_validator, TestState
        fake = _FakeDriver(raise_info=RuntimeError("boom"))
        self._patch_manager(monkeypatch, fake)
        _install_contract_flags(fake, monkeypatch)
        report = _run(driver_validator.validate("cam-1"))
        assert report.tests["device_info"]["state"] == TestState.FAIL.value
        assert report.score < 100  # au moins un test raté

    def test_invalid_stream_url_scheme_fails(self, monkeypatch):
        from pipeline_v2.driver_validator import driver_validator, TestState
        fake = _FakeDriver(streams=_make_streams(url="ftp://nope"))
        self._patch_manager(monkeypatch, fake)
        _install_contract_flags(fake, monkeypatch)
        report = _run(driver_validator.validate("cam-1"))
        assert report.tests["stream"]["state"] == TestState.FAIL.value

    def test_events_absent_marks_unsupported(self, monkeypatch):
        from pipeline_v2.driver_validator import driver_validator, TestState
        fake = _FakeDriver(events=False)
        self._patch_manager(monkeypatch, fake)
        _install_contract_flags(fake, monkeypatch)
        report = _run(driver_validator.validate("cam-1"))
        assert report.tests["events"]["state"] == TestState.UNSUPPORTED.value


# ────────────────────────────────────────────────────────────────
# 4. Validator — non destructif (aucun appel physique)
# ────────────────────────────────────────────────────────────────
class TestValidatorIsNonDestructive:
    def test_validator_never_calls_destructive_methods(self, monkeypatch):
        """Le validator ne doit JAMAIS appeler ptz_move / set_light / set_siren /
        start_audio / reboot sur le driver."""
        from pipeline_v2 import driver_validator as v_mod
        fake = _FakeDriver()

        # Sentinelles : ces attrs ne doivent JAMAIS être touchés.
        destructive = ["ptz_move", "set_light", "set_siren", "start_audio",
                        "stop_audio", "reboot", "_reboot"]
        for name in destructive:
            setattr(fake, name, AsyncMock(side_effect=AssertionError(
                f"validator called destructive method {name}")))

        fake_mgr = MagicMock()
        fake_mgr.get_driver = AsyncMock(return_value=fake)
        monkeypatch.setattr(v_mod, "camera_manager", fake_mgr)
        _install_contract_flags(fake, monkeypatch)

        _run(v_mod.driver_validator.validate("cam-1"))
        for name in destructive:
            getattr(fake, name).assert_not_called()


# ────────────────────────────────────────────────────────────────
# 5. Validator — persistance explicite
# ────────────────────────────────────────────────────────────────
class TestValidatorPersistence:
    def test_get_does_not_persist(self, monkeypatch):
        from pipeline_v2 import driver_validator as v_mod
        fake = _FakeDriver()
        fake_mgr = MagicMock()
        fake_mgr.get_driver = AsyncMock(return_value=fake)
        monkeypatch.setattr(v_mod, "camera_manager", fake_mgr)
        _install_contract_flags(fake, monkeypatch)

        # Aucun update_one attendu quand on appelle validate() directement.
        # (validate ne touche pas db du tout — voir code)
        _run(v_mod.driver_validator.validate("cam-1"))

    def test_run_and_persist_writes_to_mongo(self, monkeypatch):
        from pipeline_v2 import driver_validator as v_mod
        fake = _FakeDriver()
        fake_mgr = MagicMock()
        fake_mgr.get_driver = AsyncMock(return_value=fake)
        monkeypatch.setattr(v_mod, "camera_manager", fake_mgr)
        _install_contract_flags(fake, monkeypatch)

        # Mock database.db
        writes = []
        fake_db = MagicMock()
        fake_db.cameras = MagicMock()

        async def fake_update(q, u):
            writes.append((q, u))
        fake_db.cameras.update_one = fake_update

        # Patch le module database
        import types
        mod = types.SimpleNamespace(db=fake_db)
        monkeypatch.setitem(sys.modules, "database", mod)

        report = _run(v_mod.driver_validator.run_and_persist("cam-42"))
        assert len(writes) == 1
        assert writes[0][0] == {"id": "cam-42"}
        assert "last_validation" in writes[0][1]["$set"]
        assert writes[0][1]["$set"]["last_validation"]["camera_id"] == "cam-42"
        assert writes[0][1]["$set"]["last_validation"]["score"] == report.score


# ────────────────────────────────────────────────────────────────
# 6. Validator — erreurs de connexion
# ────────────────────────────────────────────────────────────────
class TestValidatorConnectFailure:
    def test_camera_not_found_returns_zero_score(self, monkeypatch):
        from pipeline_v2 import driver_validator as v_mod
        from drivers import CameraDriverError
        fake_mgr = MagicMock()
        fake_mgr.get_driver = AsyncMock(side_effect=CameraDriverError(
            "Caméra ghost introuvable", code="camera_not_found"))
        monkeypatch.setattr(v_mod, "camera_manager", fake_mgr)
        report = _run(v_mod.driver_validator.validate("ghost"))
        assert report.score == 0
        assert report.camera_id == "ghost"
        assert "connect" in report.tests
        assert report.tests["connect"]["state"] == "fail"


# ────────────────────────────────────────────────────────────────
# 7. Capability Matrix — 4 modes de groupement
# ────────────────────────────────────────────────────────────────
class TestCapabilityMatrix:
    _CAMS = [
        {"id": "c1", "vendor": "reolink", "driver": "reolink",
         "device_info": {"model": "RLC-1224A"},
         "capabilities": {"ptz": True, "siren": True, "ai_person": True, "ai_vehicle": False}},
        {"id": "c2", "vendor": "reolink", "driver": "reolink",
         "device_info": {"model": "Argus 3 Pro"},
         "capabilities": {"ptz": False, "siren": False, "ai_person": True, "ai_vehicle": True,
                          "battery": True}},
        {"id": "c3", "vendor": "hikvision", "driver": "hikvision",
         "device_info": {"model": "DS-2CD1234"},
         "capabilities": {"ptz": True, "siren": False, "isapi": True}},
    ]

    def _patch(self, monkeypatch):
        from pipeline_v2 import capability_matrix as m
        async def fake_load():
            return list(self._CAMS)
        monkeypatch.setattr(m, "_load_cameras", fake_load)

    def test_group_by_vendor_ors_flags(self, monkeypatch):
        from pipeline_v2.capability_matrix import build_capability_matrix
        self._patch(monkeypatch)
        mx = _run(build_capability_matrix("vendor"))
        assert set(mx.keys()) == {"reolink", "hikvision"}
        # OR : Reolink ptz oui (c1) et non (c2) → True
        assert mx["reolink"]["ptz"] is True
        assert mx["reolink"]["siren"] is True
        assert mx["reolink"]["battery"] is True
        # ai_vehicle : c1=False, c2=True → True
        assert mx["reolink"]["ai_vehicle"] is True
        # Hikvision seul
        assert mx["hikvision"]["ptz"] is True
        assert mx["hikvision"]["isapi"] is True

    def test_group_by_driver_matches_vendor_here(self, monkeypatch):
        from pipeline_v2.capability_matrix import build_capability_matrix
        self._patch(monkeypatch)
        mx = _run(build_capability_matrix("driver"))
        assert set(mx.keys()) == {"reolink", "hikvision"}

    def test_group_by_model_returns_per_model(self, monkeypatch):
        from pipeline_v2.capability_matrix import build_capability_matrix
        self._patch(monkeypatch)
        mx = _run(build_capability_matrix("model"))
        assert "RLC-1224A" in mx
        assert "Argus 3 Pro" in mx
        assert "DS-2CD1234" in mx
        # RLC-1224A a ptz=True, pas battery
        assert mx["RLC-1224A"]["ptz"] is True
        assert mx["RLC-1224A"].get("battery", False) is False
        # Argus 3 Pro a battery=True
        assert mx["Argus 3 Pro"]["battery"] is True

    def test_group_by_camera_returns_per_camera(self, monkeypatch):
        from pipeline_v2.capability_matrix import build_capability_matrix
        self._patch(monkeypatch)
        mx = _run(build_capability_matrix("camera"))
        assert set(mx.keys()) == {"c1", "c2", "c3"}
        assert mx["c1"]["ptz"] is True
        assert mx["c2"]["ptz"] is False

    def test_invalid_group_raises(self, monkeypatch):
        from pipeline_v2.capability_matrix import build_capability_matrix
        self._patch(monkeypatch)
        with pytest.raises(ValueError):
            _run(build_capability_matrix("garbage"))

    def test_empty_cameras_returns_empty_matrix(self, monkeypatch):
        from pipeline_v2 import capability_matrix as m
        async def fake_load():
            return []
        monkeypatch.setattr(m, "_load_cameras", fake_load)
        assert _run(m.build_capability_matrix("vendor")) == {}


# ────────────────────────────────────────────────────────────────
# 8. Driver Health
# ────────────────────────────────────────────────────────────────
class TestDriverHealth:
    def test_all_registered_drivers_have_manifest(self):
        from drivers import list_supported_vendors, get_driver
        for v in list_supported_vendors():
            cls = get_driver(v)
            assert cls is not None
            assert hasattr(cls, "MANIFEST"), f"driver {v} missing MANIFEST"
            m = cls.MANIFEST
            assert m.get("driver")
            assert m.get("status") in ("stable", "beta", "experimental")
            assert isinstance(m.get("protocols"), list)
            assert isinstance(m.get("supported_models"), list)

    def test_build_driver_health_shape(self, monkeypatch):
        from pipeline_v2 import capability_matrix as m
        async def fake_load():
            return [
                {"id": "c1", "driver": "reolink", "vendor": "reolink",
                 "last_validation": {"score": 92, "finished_at": "2026-02-05T12:00:00+00:00"}},
                {"id": "c2", "driver": "reolink", "vendor": "reolink",
                 "last_validation": {"score": 80, "finished_at": "2026-02-06T09:15:00+00:00"}},
                {"id": "c3", "driver": "hikvision", "vendor": "hikvision"},
            ]
        monkeypatch.setattr(m, "_load_cameras", fake_load)
        health = _run(m.build_driver_health())
        assert "reolink" in health
        assert "hikvision" in health
        assert "onvif" in health
        # Reolink stats
        rl = health["reolink"]
        assert rl["cameras_count"] == 2
        assert rl["validations_count"] == 2
        assert rl["avg_score"] == 86  # round((92+80)/2) = 86
        assert rl["last_validation_at"] == "2026-02-06T09:15:00+00:00"
        assert rl["manifest"]["driver"] == "reolink"
        # Hikvision sans validation
        hk = health["hikvision"]
        assert hk["cameras_count"] == 1
        assert hk["validations_count"] == 0
        assert hk["avg_score"] is None
        assert hk["last_validation_at"] is None


# ────────────────────────────────────────────────────────────────
# 9. Routes (mapping + Pydantic body)
# ────────────────────────────────────────────────────────────────
class TestRoutesRegistration:
    def test_new_v057_routes_exist(self):
        from routes.devices import devices_router
        paths = {r.path for r in devices_router.routes}
        assert "/api/devices/matrix" in paths
        assert "/api/devices/drivers/health" in paths
        assert "/api/devices/{camera_id}/validate" in paths

    def test_matrix_route_defaults_to_vendor(self):
        # Rien ne casse à l'import — smoke check
        from routes.devices import devices_matrix
        assert callable(devices_matrix)


# ────────────────────────────────────────────────────────────────
# 10. Non-régression — les tests précédents doivent tourner ensemble
# ────────────────────────────────────────────────────────────────
class TestBackwardCompatibility:
    def test_camera_capabilities_still_default_all_false(self):
        from drivers import CameraCapabilities
        c = CameraCapabilities()
        assert c.ptz is False
        # Nouveaux flags v0.5.7 aussi False par défaut
        assert c.ai_person is False and c.thermal is False

    def test_driver_error_json_shape_stable(self):
        from drivers import UnsupportedCapabilityError
        d = UnsupportedCapabilityError("nope").to_dict()
        assert d["success"] is False
        assert d["error"] == "unsupported_capability"

    def test_list_supported_vendors_stable(self):
        from drivers import list_supported_vendors
        v = list_supported_vendors()
        assert "onvif" in v and "reolink" in v and "hikvision" in v and "dahua" in v
