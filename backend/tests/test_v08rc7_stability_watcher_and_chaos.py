"""v0.8-rc7 · FEATURE FREEZE · Stabilisation Sprint 4

Priorité #4 · Stability Watcher 72 h (minute-par-minute)
Priorité #3 · Chaos Test Harness (auto-résilience validée)

Chaque test = preuve mesurable exigée par le mandat.
"""
from __future__ import annotations

import asyncio
import os
import time
import pytest


os.environ["TESTING"] = "1"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ═══════════════════════════════════════════════════════════════════
# Suite A · Stability Watcher — collecteurs individuels
# ═══════════════════════════════════════════════════════════════════
class TestStabilityCollectors:
    def test_collect_backend_returns_valid_metrics(self):
        from pipeline_v2.stability_watcher import _collect_backend
        r = _collect_backend()
        # RAM/CPU/RSS/threads doivent tous être présents (pas d'erreur)
        for k in ("ram_percent", "cpu_percent", "process_rss_mb",
                   "threads", "asyncio_tasks"):
            assert k in r, f"champ {k} manquant"
        assert 0 <= r["ram_percent"] <= 100
        assert r["threads"] >= 1

    def test_collect_pipeline_reflects_inspector(self):
        from pipeline_v2.inspector import inspector
        from pipeline_v2.stability_watcher import _collect_pipeline
        inspector.reset("stability-test-cam")
        inspector.record("stability-test-cam", "yolo", 42.0)
        r = _collect_pipeline()
        assert "cameras" in r
        assert "stability-test-cam" in r["cameras"]
        inspector.reset("stability-test-cam")

    def test_collect_mongo_tolerates_failure(self):
        """Preuve : si Mongo est HS, on retourne {ok: False, error: str}."""
        from pipeline_v2 import stability_watcher as sw
        import database as dbmod

        class BrokenDB:
            async def command(self, *_a, **_k):
                raise RuntimeError("simulated mongo down")

        original = dbmod.db
        dbmod.db = BrokenDB()   # type: ignore
        try:
            r = _run(sw._collect_mongo())
        finally:
            dbmod.db = original
        assert r["ok"] is False
        assert "error" in r


class TestStabilityWatcherRingBuffer:
    def test_ring_buffer_caps_at_max_snapshots(self):
        from pipeline_v2.stability_watcher import StabilityWatcher, MAX_SNAPSHOTS, Snapshot
        w = StabilityWatcher()
        # Injecte MAX+50 snapshots directement (bypass loop pour vitesse)
        for i in range(MAX_SNAPSHOTS + 50):
            w._snapshots.append(Snapshot(ts=time.time() + i))
        assert len(w._snapshots) == MAX_SNAPSHOTS

    def test_snapshot_window_slicing(self):
        from pipeline_v2.stability_watcher import StabilityWatcher, Snapshot
        w = StabilityWatcher()
        w._started_at = time.time()
        # Injecte 100 snapshots
        for i in range(100):
            snap = Snapshot(ts=time.time() + i)
            snap.backend = {"ram_percent": 40.0 + i * 0.1, "cpu_percent": 20.0,
                             "process_rss_mb": 800.0}
            snap.mongo = {"ok": True}
            snap.go2rtc = {"ok": True}
            w._snapshots.append(snap)
        r = w.snapshot("1h")
        # 1h = 60 snaps
        assert r["snapshot_count"] == 60
        # p50/p95/p99 doivent être définis
        agg = r["aggregates"]
        assert "ram_percent" in agg
        assert "p50" in agg["ram_percent"]
        assert agg["mongo_uptime_pct"] == 100.0

    def test_percentiles_correctness(self):
        from pipeline_v2.stability_watcher import _percentiles
        r = _percentiles([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        assert r["min"] == 1
        assert r["max"] == 10
        assert r["p50"] == 5   # (0.5 * 9) = 4.5 → round → index 4 → 5
        assert r["p95"] == 10  # (0.95 * 9) = 8.55 → round → index 9 → 10
        assert r["count"] == 10


class TestStabilityEndpoints:
    def test_endpoints_registered(self):
        from server import app
        paths = {r.path for r in app.routes}
        for p in ("/api/diagnostics/stability",
                   "/api/diagnostics/stability/latest",
                   "/api/diagnostics/stability/clear"):
            assert p in paths, f"endpoint {p} manquant"


# ═══════════════════════════════════════════════════════════════════
# Suite B · Chaos Test Harness — tous les scénarios doivent passer
# ═══════════════════════════════════════════════════════════════════
class TestChaosScenarios:
    def test_rtsp_worker_state_is_captured(self):
        from stress.chaos import chaos_rtsp_worker_state
        r = _run(chaos_rtsp_worker_state())
        assert r.ok
        assert r.after["gave_up"] is True
        assert r.after["consecutive_failures"] == 10

    def test_inspector_flood_bounded_at_300(self):
        from stress.chaos import chaos_inspector_flood
        r = chaos_inspector_flood()
        assert r.ok
        assert r.after["window_size_60s"] <= 300

    def test_trace_buffer_capped_at_50(self):
        from stress.chaos import chaos_trace_buffer_overflow
        from pipeline_v2.trace import MAX_TRACES
        r = chaos_trace_buffer_overflow()
        assert r.ok
        assert r.after["retained"] == MAX_TRACES
        assert r.after["max"] == MAX_TRACES

    def test_qos_alert_flood_blocked_by_backoff(self):
        from stress.chaos import chaos_qos_alert_flood
        r = _run(chaos_qos_alert_flood())
        assert r.ok
        # 100 tentatives → 1 émis (backoff)
        assert r.after["emitted"] == 1
        assert r.after["blocked_by_backoff"] == 99

    def test_mongo_collector_tolerates_failure(self):
        from stress.chaos import chaos_mongo_collector_tolerates_failure
        r = _run(chaos_mongo_collector_tolerates_failure())
        assert r.ok
        assert r.after["ok"] is False


class TestChaosBatchRunner:
    def test_run_all_scenarios_pass(self):
        """Preuve globale : la campagne complète est verte."""
        from stress.chaos import run_all
        report = _run(run_all())
        assert report["all_ok"] is True, \
            f"Chaos campaign FAILED: {report}"
        assert report["passed"] == report["total"]
        assert report["total"] >= 5


# ═══════════════════════════════════════════════════════════════════
# Suite C · Non-régression Sprint 3
# ═══════════════════════════════════════════════════════════════════
class TestNoRegression:
    def test_sprint3_endpoints_still_present(self):
        from server import app
        paths = {r.path for r in app.routes}
        for p in ("/api/diagnostics/traces",
                   "/api/diagnostics/camera-state",
                   "/api/diagnostics/pipeline-inspector",
                   "/api/diagnostics/hot-reload",
                   "/api/diagnostics/qos-thresholds"):
            assert p in paths, f"endpoint {p} disparu"
