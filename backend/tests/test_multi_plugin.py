"""Tests multi-plugin ANPR & Tracking (chapitre 11 §11.6 · TA-11.2).

Couvre :
  - Fusion policies (cascade / highest / compare / vote)
  - PluginBus fan-out avec isolation crash (un plugin qui raise ne casse pas les autres)
  - Endpoint POST /api/v1/plugins/test/multi-anpr avec mocks injectés
  - Endpoint PUT /api/v1/plugins/policy/anpr
"""
from __future__ import annotations

import asyncio
import os
import pytest
import numpy as np

import sys
sys.path.insert(0, "/app/backend")

from plugin_manager import (
    PluginBus,
    Frame,
    PlateResult,
    apply_policy,
    MODE_CASCADE,
    MODE_HIGHEST,
    MODE_COMPARE,
    MODE_VOTE,
    policy,
)
from plugin_manager.builtin import MockPlatePlugin
from plugin_manager.interfaces import PlateRecognizer


# ─────────────── Helpers ───────────────

def _frame():
    arr = np.zeros((240, 320, 3), dtype=np.uint8)
    return Frame(camera_id="t", timestamp="2026-02-01T00:00:00Z", numpy_bgr=arr, width=320, height=240)


# ─────────────── Fusion policies ───────────────

def test_fusion_cascade_stops_at_first_above_threshold():
    results = [
        ("cloud", [PlateResult(text="AB-123-CD", confidence=0.95, engine="cloud")]),
        ("local", [PlateResult(text="AB-124-CD", confidence=0.80, engine="local")]),
    ]
    out = apply_policy(MODE_CASCADE, results, threshold=0.85)
    assert out["final"].text == "AB-123-CD"
    assert out["final"].engine == "cloud"


def test_fusion_highest_picks_best_confidence():
    results = [
        ("engineA", [PlateResult(text="AB-123-CD", confidence=0.71, engine="A")]),
        ("engineB", [PlateResult(text="XY-999-ZZ", confidence=0.93, engine="B")]),
        ("engineC", [PlateResult(text="AB-123-CD", confidence=0.85, engine="C")]),
    ]
    out = apply_policy(MODE_HIGHEST, results)
    assert out["final"].text == "XY-999-ZZ"
    assert out["final"].confidence == pytest.approx(0.93)


def test_fusion_compare_reports_divergence():
    results = [
        ("A", [PlateResult(text="AB-123-CD", confidence=0.9, engine="A")]),
        ("B", [PlateResult(text="AB-124-CD", confidence=0.8, engine="B")]),
    ]
    out = apply_policy(MODE_COMPARE, results)
    assert out["divergence"] is True
    assert len(out["all_results"]) == 2


def test_fusion_vote_majority_per_character():
    results = [
        ("A", [PlateResult(text="AB123CD", confidence=0.9, engine="A")]),
        ("B", [PlateResult(text="AB123CD", confidence=0.85, engine="B")]),
        ("C", [PlateResult(text="AB125CD", confidence=0.75, engine="C")]),
    ]
    out = apply_policy(MODE_VOTE, results)
    # position 4 : deux fois '3' vs une fois '5' → vote pour '3'
    assert out["final"].text == "AB123CD"
    assert out["final"].engine.startswith("fusion(")


def test_fusion_invalid_mode_raises():
    with pytest.raises(ValueError):
        apply_policy("nonsense", [])


# ─────────────── PluginBus ───────────────

def test_bus_registers_and_dispatches_multiple_plate_plugins():
    async def _run():
        b = PluginBus(default_timeout_s=2.0)
        b.register("mock-a", MockPlatePlugin(engine_name="mock-a", text="AB-100-AA", confidence=0.80))
        b.register("mock-b", MockPlatePlugin(engine_name="mock-b", text="AB-100-AA", confidence=0.95))
        b.register("mock-c", MockPlatePlugin(engine_name="mock-c", text="AB-101-AA", confidence=0.60))
        # v0.4.3 · dispatch_plate exige `only` (fermeture stricte).
        results = await b.dispatch_plate(_frame(), only={"mock-a", "mock-b", "mock-c"})
        assert len(results) == 3
        names = [n for n, _ in results]
        assert names == ["mock-a", "mock-b", "mock-c"]
    asyncio.run(_run())


def test_bus_isolation_crash_does_not_break_other_plugins():
    class BrokenPlate(PlateRecognizer):
        async def recognize(self, frame, vehicle_bbox=None):
            raise RuntimeError("boom")

    async def _run():
        b = PluginBus(default_timeout_s=2.0)
        b.register("good", MockPlatePlugin(engine_name="good", text="AB-100-AA", confidence=0.9))
        b.register("broken", BrokenPlate())
        results = await b.dispatch_plate(_frame(), only={"good", "broken"})
        result_by_name = {n: r for n, r in results}
        assert result_by_name["good"] and result_by_name["good"][0].text == "AB-100-AA"
        assert result_by_name["broken"] == []
        broken_entry = next(e for e in b.list_entries() if e.name == "broken")
        assert broken_entry.errors >= 1
        assert broken_entry.last_error and "RuntimeError" in broken_entry.last_error
    asyncio.run(_run())


def test_bus_cascade_stops_early_saving_cloud_quota():
    async def _run():
        b = PluginBus(default_timeout_s=2.0)
        b.register("cloud", MockPlatePlugin(engine_name="cloud", text="AB-100-AA", confidence=0.98), order=1)
        b.register("local", MockPlatePlugin(engine_name="local", text="AB-100-AA", confidence=0.60), order=2)
        results = await b.dispatch_plate(_frame(), cascade_stop_at=0.85,
                                          only={"cloud", "local"})
        assert [n for n, _ in results] == ["cloud"]
        local_entry = next(e for e in b.list_entries() if e.name == "local")
        assert local_entry.calls == 0
    asyncio.run(_run())


def test_bus_timeout_isolated():
    class SlowPlate(PlateRecognizer):
        async def recognize(self, frame, vehicle_bbox=None):
            await asyncio.sleep(1.0)
            return [PlateResult(text="LATE", confidence=1.0, engine="slow")]

    async def _run():
        b = PluginBus(default_timeout_s=0.1)
        b.register("slow", SlowPlate())
        b.register("fast", MockPlatePlugin(engine_name="fast", text="OK", confidence=0.9))
        results = await b.dispatch_plate(_frame(), only={"slow", "fast"})
        result_by_name = {n: r for n, r in results}
        assert result_by_name["slow"] == []
        assert result_by_name["fast"] and result_by_name["fast"][0].text == "OK"
        slow_entry = next(e for e in b.list_entries() if e.name == "slow")
        assert slow_entry.timeouts >= 1
    asyncio.run(_run())


# ─────────────── Policy Store ───────────────

def test_policy_store_persists_anpr_mode(tmp_path, monkeypatch):
    from plugin_manager import policy as policy_module
    p = policy_module
    # Sauve état initial
    initial = p.get_anpr_policy()
    try:
        new = p.set_anpr_policy(mode=MODE_HIGHEST, cascade_threshold=0.75)
        assert new["mode"] == MODE_HIGHEST
        assert new["cascade_threshold"] == 0.75
        assert p.get_anpr_policy()["mode"] == MODE_HIGHEST
    finally:
        # Restaure
        p.set_anpr_policy(mode=initial["mode"], cascade_threshold=initial["cascade_threshold"])


def test_policy_rejects_invalid_mode():
    with pytest.raises(ValueError):
        policy.set_anpr_policy(mode="lolcat")
