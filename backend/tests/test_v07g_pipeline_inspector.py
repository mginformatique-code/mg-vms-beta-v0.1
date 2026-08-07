"""v0.7.g · Wave H · Pipeline Inspector Live + Robustesse — tests."""
from __future__ import annotations

import os
import time
from pathlib import Path

os.environ["TESTING"] = "1"


class TestInspectorPercentiles:
    def test_stat_exposes_p50_p95_p99(self):
        from pipeline_v2.inspector import _StageStat
        stat = _StageStat()
        # Injecte 100 samples de 10ms + 5 samples de 500ms → p99 doit être 500
        now = time.time()
        for _ in range(100):
            stat.record(10.0)
        for _ in range(5):
            stat.record(500.0)
        d = stat.to_dict()
        assert "p50_60s" in d
        assert "p95_60s" in d
        assert "p99_60s" in d
        assert d["samples_60s"] > 0
        # p50 doit être proche de 10 (majorité), p99 doit toucher les 500
        assert d["p50_60s"] < 50
        assert d["p99_60s"] >= 500 - 1

    def test_stat_empty_returns_zero_percentiles(self):
        from pipeline_v2.inspector import _StageStat
        stat = _StageStat()
        d = stat.to_dict()
        assert d["p50_60s"] == 0.0
        assert d["p95_60s"] == 0.0
        assert d["p99_60s"] == 0.0


class TestPipelineInspectorEndpoint:
    def test_endpoint_registered(self):
        from server import app
        paths = {r.path for r in app.routes}
        assert "/api/diagnostics/pipeline-inspector" in paths


class TestFrontendErrorBoundary:
    """Wave H · l'ErrorBoundary est monté à la racine et le handler
    unhandledrejection est enregistré dans index.js."""

    def test_error_boundary_registered_at_root(self):
        p = Path(__file__).resolve().parents[2] / "frontend" / "src" / "index.js"
        content = p.read_text()
        assert "import ErrorBoundary" in content
        assert "<ErrorBoundary>" in content
        assert "unhandledrejection" in content

    def test_error_boundary_component_exists(self):
        p = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "ErrorBoundary.jsx"
        assert p.exists()
        content = p.read_text()
        assert "componentDidCatch" in content
        assert "getDerivedStateFromError" in content
        assert 'data-testid="error-boundary"' in content


class TestPipelineInspectorLivePage:
    def test_page_exists_and_consumes_three_endpoints(self):
        p = Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "PipelineInspectorLive.jsx"
        assert p.exists()
        content = p.read_text()
        # Doit consommer les 3 endpoints de diagnostic exposés en v0.7.e
        assert "/diagnostics/pipeline-inspector" in content
        assert "/diagnostics/hot-reload" in content
        assert "/diagnostics/plate-quality" in content
        # Doit afficher les percentiles Wave H
        assert "p95_60s" in content
        assert "p99_60s" in content
