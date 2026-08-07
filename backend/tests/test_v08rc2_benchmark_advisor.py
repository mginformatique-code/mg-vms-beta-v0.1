"""v0.8-rc2 · Camera Benchmark + Advisor — tests."""
from __future__ import annotations

import os
os.environ["TESTING"] = "1"


class TestBenchmarkVerdict:
    def test_grades_scale(self):
        from services.camera_benchmark import _verdict
        # 0 échantillons
        v = _verdict([], 0)
        assert v["grade"] == "F"
        # Hors ligne
        v = _verdict([{"fps": 0, "total_avg_ms": 0, "errors": 0}] * 3, 0)
        assert v["grade"] == "F"
        # Excellent
        v = _verdict([{"fps": 15, "total_avg_ms": 80, "errors": 0}] * 5, 20)
        assert v["grade"] == "A"
        # Bon
        v = _verdict([{"fps": 10, "total_avg_ms": 150, "errors": 1}] * 5, 15)
        assert v["grade"] == "B"
        # Limite
        v = _verdict([{"fps": 8, "total_avg_ms": 350, "errors": 0}] * 5, 8)
        assert v["grade"] == "C"
        # Insuffisant
        v = _verdict([{"fps": 3, "total_avg_ms": 600, "errors": 10}] * 5, 2)
        assert v["grade"] == "D"


class TestEndpointsRegistered:
    def test_endpoints_exist(self):
        from server import app
        paths = {r.path for r in app.routes}
        assert "/api/cameras/{camera_id}/benchmark" in paths
        assert "/api/cameras/{camera_id}/benchmarks" in paths
        assert "/api/cameras/{camera_id}/advisor" in paths
        assert "/api/cameras/advisor" in paths


class TestAdvisorNoCamera:
    def test_returns_error_for_unknown(self):
        import asyncio
        from services.camera_advisor import advise
        r = asyncio.new_event_loop().run_until_complete(advise("does-not-exist-999"))
        assert r.get("error") == "camera_not_found"
