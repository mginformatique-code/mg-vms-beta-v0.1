"""Tests P8 · ANPR E/P/S state machine plugin."""
import asyncio
import sys
import time
from pathlib import Path

# Ajoute /app/data/plugins/anpr-eps au path pour import direct
sys.path.insert(0, "/app/data/plugins/anpr-eps")


class _FakeCtx:
    def __init__(self):
        self.config = {"exit_threshold_seconds": 2, "min_confidence": 0.5}
        self.db = None  # pas de DB en test
        self.state = "ready"
        self.state_message = None

        class _Log:
            def info(self, *a, **kw): pass
            def warning(self, *a, **kw): pass
            def error(self, *a, **kw): pass
        self.log = _Log()

    def set_state(self, s, msg=None):
        self.state = s
        self.state_message = msg


def _pipeline_result(camera_id: str, plates: list[tuple[str, float]]):
    from plugin_manager.interfaces import PipelineResult
    return PipelineResult(
        camera_id=camera_id,
        timestamp=None,
        detections=[],
        tracks=[],
        masks=[],
        business_events=[
            {"type": "plate_recognized", "plate": p, "confidence": c}
            for p, c in plates
        ],
        timing_ms={},
        plugins_used={},
    )


def _fake_frame(camera_id: str):
    from plugin_manager.interfaces import Frame
    return Frame(camera_id=camera_id, timestamp="now", numpy_bgr=None, width=0, height=0)


def _new_plugin():
    from plugin import AnprEpsPlugin
    p = AnprEpsPlugin()
    ctx = _FakeCtx()

    async def _init():
        await p.on_load(ctx)
    asyncio.run(_init())
    return p, ctx


def test_first_sight_emits_plate_entered():
    p, ctx = _new_plugin()

    async def _run():
        evs = await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", [("AB-123-CD", 0.9)]))
        assert len(evs) == 1
        assert evs[0]["type"] == "plate_entered"
        assert evs[0]["data"]["plate"] == "AB-123-CD"
        assert p._get_state("cam1", "AB-123-CD") == "entered"
    asyncio.run(_run())


def test_second_sight_stays_silent_present():
    p, ctx = _new_plugin()

    async def _run():
        await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", [("AB-123-CD", 0.9)]))
        # 2ème appel : même plaque, doit être silencieux
        evs = await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", [("AB-123-CD", 0.92)]))
        assert evs == []
        assert p._get_state("cam1", "AB-123-CD") == "present"
    asyncio.run(_run())


def test_thousand_frames_produce_only_one_event():
    """Le vrai but du P8 : une voiture stationnée = 1 seul event, pas 1000."""
    p, ctx = _new_plugin()

    async def _run():
        total = 0
        for _ in range(1000):
            evs = await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", [("STATIONARY-1", 0.9)]))
            total += len(evs)
        assert total == 1, f"Attendu 1 event pour 1000 frames, obtenu {total}"
    asyncio.run(_run())


def test_exit_after_threshold_emits_plate_exited():
    p, ctx = _new_plugin()

    async def _run():
        await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", [("EXIT-1", 0.9)]))
        # Fast-forward : simule le temps en manipulant l'état interne
        key = ("cam1", "EXIT-1")
        p._state[key]["last_seen_ts"] = time.time() - 10  # 10s ago > exit_s (2s)
        # Frame sans la plaque → doit émettre plate_exited
        evs = await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", []))
        types = [e["type"] for e in evs]
        assert "plate_exited" in types
        assert p._get_state("cam1", "EXIT-1") == "exited"
    asyncio.run(_run())


def test_reentry_after_exit_starts_new_cycle():
    p, ctx = _new_plugin()

    async def _run():
        await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", [("RE-1", 0.9)]))
        p._state[("cam1", "RE-1")]["last_seen_ts"] = time.time() - 10
        await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", []))
        assert p._get_state("cam1", "RE-1") == "exited"
        # Nouvelle apparition → doit re-émettre `plate_entered`
        evs = await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", [("RE-1", 0.9)]))
        assert any(e["type"] == "plate_entered" for e in evs)
        assert p._get_state("cam1", "RE-1") == "entered"
    asyncio.run(_run())


def test_low_confidence_ignored():
    p, ctx = _new_plugin()
    ctx.config["min_confidence"] = 0.8

    async def _run():
        # confidence 0.3 → sous le seuil → aucun event
        evs = await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", [("LOW-1", 0.3)]))
        assert evs == []
        assert p._get_state("cam1", "LOW-1") is None
    asyncio.run(_run())


def test_per_camera_isolation():
    """Une plaque vue sur cam1 ne doit pas être 'sortie' à cause de son absence sur cam2."""
    p, ctx = _new_plugin()

    async def _run():
        await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", [("MULTI-1", 0.9)]))
        p._state[("cam1", "MULTI-1")]["last_seen_ts"] = time.time() - 10
        # Frame sur cam2 sans la plaque : cam1 doit être marqué EXITED, cam2 rien
        evs = await p.consume(_fake_frame("cam2"), _pipeline_result("cam2", []))
        # cam2 n'a jamais vu la plaque → 0 event sur ce cycle
        assert evs == []
        # État sur cam1 doit rester 'entered' (le cycle n'a pas passé sur cam1)
        assert p._get_state("cam1", "MULTI-1") == "entered"
        # Frame sur cam1 sans plaque → maintenant sortie
        evs = await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", []))
        assert any(e["type"] == "plate_exited" for e in evs)
    asyncio.run(_run())


def test_heartbeat_emits_when_enabled():
    p, ctx = _new_plugin()
    ctx.config["emit_presence_heartbeats"] = True
    ctx.config["heartbeat_minutes"] = 0  # heartbeat sur chaque appel (interval 0s)

    async def _run():
        await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", [("HB-1", 0.9)]))
        # Force le heartbeat interval à 0 après entrée pour tester la logique
        # Le premier appel a émis plate_entered et set last_hb_ts=now.
        # Le second doit émettre heartbeat car interval = 0
        p._state[("cam1", "HB-1")]["last_hb_ts"] = time.time() - 1
        evs = await p.consume(_fake_frame("cam1"), _pipeline_result("cam1", [("HB-1", 0.9)]))
        assert any(e["type"] == "plate_present_heartbeat" for e in evs)
    asyncio.run(_run())
