"""Tests P3.c · Smart Zones engine — évaluation temps réel avec detections/tracks."""
import asyncio

from smart_zones.engine import SmartZonesEngine


def test_engine_no_zones_returns_empty():
    async def _run():
        e = SmartZonesEngine()
        e._zones_cache = []
        e._cache_ts = 1e12  # cache "frais"
        events = await e.evaluate("cam1", [], [])
        assert events == []
    asyncio.run(_run())


def test_engine_triggers_enter_on_new_track_in_polygon():
    async def _run():
        e = SmartZonesEngine()
        e._zones_cache = [{
            "id": "z1",
            "name": "Test",
            "camera_id": "cam1",
            "polygon": [],  # tout le frame
            "detect": {"classes": ["person"], "min_confidence": 0.5, "cooldown_seconds": 0},
            "trigger_on": ["enter"],
            "actions": [],
        }]
        e._cache_ts = 1e12  # évite reload DB
        tracks = [{"track_id": "t1", "class": "person", "confidence": 0.9,
                   "bbox": (0.4, 0.4, 0.2, 0.2)}]
        events = await e.evaluate("cam1", [], tracks)
        types = [ev["type"] for ev in events]
        assert "zone.enter" in types
    asyncio.run(_run())


def test_engine_no_retrigger_second_frame_same_track():
    async def _run():
        e = SmartZonesEngine()
        e._zones_cache = [{
            "id": "z1", "name": "Test", "camera_id": "cam1", "polygon": [],
            "detect": {"classes": ["person"], "min_confidence": 0.5, "cooldown_seconds": 0},
            "trigger_on": ["enter"], "actions": [],
        }]
        e._cache_ts = 1e12
        tracks = [{"track_id": "t1", "class": "person", "confidence": 0.9,
                   "bbox": (0.4, 0.4, 0.2, 0.2)}]
        await e.evaluate("cam1", [], tracks)
        # 2e passage : même track → aucun enter
        events = await e.evaluate("cam1", [], tracks)
        assert all(ev["type"] != "zone.enter" for ev in events)
    asyncio.run(_run())


def test_engine_triggers_exit_when_track_leaves():
    async def _run():
        e = SmartZonesEngine()
        e._zones_cache = [{
            "id": "z1", "name": "Test", "camera_id": "cam1", "polygon": [],
            "detect": {"classes": ["person"], "min_confidence": 0.5, "cooldown_seconds": 0},
            "trigger_on": ["enter", "exit"], "actions": [],
        }]
        e._cache_ts = 1e12
        tracks = [{"track_id": "t1", "class": "person", "confidence": 0.9,
                   "bbox": (0.4, 0.4, 0.2, 0.2)}]
        await e.evaluate("cam1", [], tracks)
        # Frame suivante sans track_id t1
        events = await e.evaluate("cam1", [], [])
        types = [ev["type"] for ev in events]
        assert "zone.exit" in types
    asyncio.run(_run())


def test_engine_polygon_filters_out_of_zone_tracks():
    async def _run():
        e = SmartZonesEngine()
        e._zones_cache = [{
            "id": "z1", "name": "Test", "camera_id": "cam1",
            "polygon": [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]],  # centre uniquement
            "detect": {"classes": ["person"], "min_confidence": 0.5, "cooldown_seconds": 0},
            "trigger_on": ["enter"], "actions": [],
        }]
        e._cache_ts = 1e12
        # Track dans le coin haut-gauche → hors zone
        tracks = [{"track_id": "t1", "class": "person", "confidence": 0.9,
                   "bbox": (0.0, 0.0, 0.1, 0.1)}]
        events = await e.evaluate("cam1", [], tracks)
        assert all(ev["type"] != "zone.enter" for ev in events)
    asyncio.run(_run())


def test_engine_class_filter():
    async def _run():
        e = SmartZonesEngine()
        e._zones_cache = [{
            "id": "z1", "name": "Test", "camera_id": "cam1", "polygon": [],
            "detect": {"classes": ["car"], "min_confidence": 0.5, "cooldown_seconds": 0},
            "trigger_on": ["enter"], "actions": [],
        }]
        e._cache_ts = 1e12
        # Track "person" → doit être ignoré
        tracks = [{"track_id": "t1", "class": "person", "confidence": 0.9,
                   "bbox": (0.5, 0.5, 0.1, 0.1)}]
        events = await e.evaluate("cam1", [], tracks)
        assert events == []
    asyncio.run(_run())


def test_engine_plate_class_filter():
    async def _run():
        e = SmartZonesEngine()
        e._zones_cache = [{
            "id": "z1", "name": "Test", "camera_id": "cam1", "polygon": [],
            "detect": {"classes": ["plate:AB-123-CD"], "min_confidence": 0.5, "cooldown_seconds": 0},
            "trigger_on": ["enter"], "actions": [],
        }]
        e._cache_ts = 1e12
        plates = [{"plate": "AB-123-CD", "confidence": 0.9, "bbox": (0, 0, 10, 10)}]
        events = await e.evaluate("cam1", [], [], plates)
        types = [ev["type"] for ev in events]
        assert "zone.enter" in types
    asyncio.run(_run())


def test_engine_cooldown_prevents_retrigger():
    async def _run():
        e = SmartZonesEngine()
        e._zones_cache = [{
            "id": "z1", "name": "Test", "camera_id": "cam1", "polygon": [],
            "detect": {"classes": ["person"], "min_confidence": 0.5, "cooldown_seconds": 3600},
            "trigger_on": ["enter"], "actions": [],
        }]
        e._cache_ts = 1e12
        tracks_a = [{"track_id": "ta", "class": "person", "confidence": 0.9,
                     "bbox": (0.5, 0.5, 0.1, 0.1)}]
        tracks_b = [{"track_id": "tb", "class": "person", "confidence": 0.9,
                     "bbox": (0.5, 0.5, 0.1, 0.1)}]
        await e.evaluate("cam1", [], tracks_a)
        events = await e.evaluate("cam1", [], tracks_b)  # cooldown actif
        assert events == []
    asyncio.run(_run())
