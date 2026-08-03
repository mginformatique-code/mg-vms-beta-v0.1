"""Tests P2 · Sandbox comportementale (quarantine auto après N échecs)."""
import asyncio

from plugin_manager.bus import PluginBus
from plugin_manager.interfaces import FrameAnalyzer, Frame


class _AlwaysCrash(FrameAnalyzer):
    async def on_load(self, ctx): pass
    async def on_config_change(self, cfg): pass
    async def analyze(self, frame, camera_config=None):
        raise RuntimeError("boom")


class _AlwaysSlow(FrameAnalyzer):
    async def on_load(self, ctx): pass
    async def on_config_change(self, cfg): pass
    async def analyze(self, frame, camera_config=None):
        await asyncio.sleep(10)


class _AlwaysGood(FrameAnalyzer):
    async def on_load(self, ctx): pass
    async def on_config_change(self, cfg): pass
    async def analyze(self, frame, camera_config=None):
        return []


def _fake_frame():
    return Frame(camera_id="c1", timestamp="now", numpy_bgr=None, width=0, height=0)


def test_quarantine_after_threshold_crashes():
    async def _run():
        bus = PluginBus(default_timeout_s=0.5)
        bus.register("crash", _AlwaysCrash(), order=10)
        assert bus._entries["crash"].state == "ready"
        for _ in range(bus.QUARANTINE_THRESHOLD):
            await bus.dispatch_frame(_fake_frame())
        entry = bus._entries["crash"]
        assert entry.state == "quarantined"
        assert entry.consecutive_errors >= bus.QUARANTINE_THRESHOLD
        assert entry.quarantined_at
        assert entry.quarantine_reason
        assert not entry.is_dispatchable()
    asyncio.run(_run())


def test_quarantine_after_timeouts():
    async def _run():
        bus = PluginBus(default_timeout_s=0.05)
        bus.register("slow", _AlwaysSlow(), order=10)
        for _ in range(bus.QUARANTINE_THRESHOLD):
            await bus.dispatch_frame(_fake_frame())
        entry = bus._entries["slow"]
        assert entry.state == "quarantined"
        assert entry.timeouts >= bus.QUARANTINE_THRESHOLD
    asyncio.run(_run())


def test_success_resets_consecutive_errors():
    async def _run():
        bus = PluginBus(default_timeout_s=0.5)
        bus.register("good", _AlwaysGood(), order=10)
        entry = bus._entries["good"]
        entry.consecutive_errors = 3
        await bus.dispatch_frame(_fake_frame())
        assert entry.consecutive_errors == 0
    asyncio.run(_run())


def test_unquarantine_restores_dispatch():
    async def _run():
        bus = PluginBus(default_timeout_s=0.5)
        bus.register("crash", _AlwaysCrash(), order=10)
        for _ in range(bus.QUARANTINE_THRESHOLD):
            await bus.dispatch_frame(_fake_frame())
        assert bus._entries["crash"].state == "quarantined"
        ok = bus.unquarantine("crash")
        assert ok is True
        entry = bus._entries["crash"]
        assert entry.state == "ready"
        assert entry.consecutive_errors == 0
        assert entry.quarantined_at is None
        assert entry.is_dispatchable()
    asyncio.run(_run())


def test_unquarantine_no_op_when_not_quarantined():
    async def _run():
        bus = PluginBus(default_timeout_s=0.5)
        bus.register("good", _AlwaysGood(), order=10)
        assert bus.unquarantine("good") is False
    asyncio.run(_run())


def test_summary_includes_quarantine_fields():
    bus = PluginBus(default_timeout_s=0.5)
    bus.register("good", _AlwaysGood(), order=10)
    s = bus._entries["good"].summary()
    for k in ("consecutive_errors", "quarantined_at", "quarantine_reason"):
        assert k in s
