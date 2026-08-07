"""v0.8-rc1 · Camera Health + Capabilities Matrix — tests."""
from __future__ import annotations

import os
import pytest


os.environ["TESTING"] = "1"


class TestCameraHealthCompute:
    def test_returns_error_for_unknown_camera(self):
        import asyncio
        from services.camera_health import compute_health
        r = asyncio.get_event_loop().run_until_complete(compute_health("does-not-exist-999")) \
            if not asyncio.get_event_loop().is_running() \
            else asyncio.new_event_loop().run_until_complete(compute_health("does-not-exist-999"))
        assert r.get("error") == "camera_not_found"

    def test_band_thresholds(self):
        from services.camera_health import _band
        assert _band(100) == "healthy"
        assert _band(80) == "healthy"
        assert _band(79) == "degraded"
        assert _band(55) == "degraded"
        assert _band(54) == "critical"
        assert _band(0) == "critical"


class TestEndpointsRegistered:
    def test_endpoints_exist(self):
        from server import app
        paths = {r.path for r in app.routes}
        assert "/api/cameras/{camera_id}/health" in paths
        assert "/api/cameras/health" in paths
        assert "/api/cameras/capabilities-matrix" in paths


class TestCapabilitiesMatrixSummary:
    def test_vendor_summary_counts_correctly(self):
        from routes.health_dashboard import _summarize_by_vendor
        rows = [
            {"vendor": "hikvision", "capabilities": {"ptz": True, "audio_input": True}},
            {"vendor": "hikvision", "capabilities": {"ptz": True, "audio_input": False}},
            {"vendor": "reolink", "capabilities": {"ptz": False, "audio_input": True}},
        ]
        all_caps = {"ptz", "audio_input"}
        s = _summarize_by_vendor(rows, all_caps)
        assert s["hikvision"]["count"] == 2
        assert s["hikvision"]["caps_present"]["ptz"] == 2
        assert s["hikvision"]["caps_present"]["audio_input"] == 1
        assert s["reolink"]["count"] == 1
        assert s["reolink"]["caps_present"]["audio_input"] == 1
        assert "ptz" not in s["reolink"]["caps_present"]
