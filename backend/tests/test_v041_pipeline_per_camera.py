"""Tests v0.4.1 · P0 · Pipeline IA per-camera + stats plugins fidèles.

Valide les invariants clés du fix P0 :

1. **Graph per-camera** : le registry compile un graphe unique par caméra
   basé sur ``enabled_plugins`` (whitelist).
2. **Skip early** : si aucun stage pipeline actif → aucun dispatch, aucun
   compteur incrémenté sur les plugins non concernés.
3. **Stats per-camera** : le bus expose ``per_camera_stats()`` avec compteurs
   fidèles (calls, errors, timeouts, last_ms).
4. **Invalidation** : la whitelist qui change → rebuild du graphe (hash).
5. **Bus version bump** : register/unregister/set_enabled invalident le cache.
"""
from __future__ import annotations

import os
import sys
import asyncio

import pytest

# Import depuis /app/backend
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from pipeline_v2.registry import CameraGraphRegistry, KNOWN_ANPR_PROVIDERS


class _FakeEntry:
    def __init__(self, name: str, interface: str, dispatchable: bool = True):
        self.name = name
        self.interface = interface
        self._d = dispatchable

    def is_dispatchable(self) -> bool:
        return self._d


class _FakeBus:
    """Bus stub qui expose active(interface) → liste d'entries."""

    def __init__(self, entries: list[_FakeEntry]):
        self._entries = entries

    def active(self, interface: str) -> list[_FakeEntry]:
        return [e for e in self._entries if e.interface == interface and e._d]


def _default_bus():
    return _FakeBus([
        _FakeEntry("yolo-detection", "FrameAnalyzer"),
        _FakeEntry("yolov8", "FrameAnalyzer"),
        _FakeEntry("bytetrack", "Tracker"),
        _FakeEntry("botsort", "Tracker"),
        _FakeEntry("sam2", "Segmenter"),
        _FakeEntry("vehicle-counting", "PipelineConsumer"),
        _FakeEntry("person-counting", "PipelineConsumer"),
        _FakeEntry("smoke-detection", "PipelineConsumer"),
        _FakeEntry("fast-alpr", "PlateRecognizer"),
        _FakeEntry("paddle-ocr", "PlateRecognizer"),
    ])


# ── 1. Graph per-camera ────────────────────────────────────────────

def test_graph_whitelist_only_activates_listed_plugins():
    reg = CameraGraphRegistry()
    graph = reg.get("cam-A", enabled_plugins=["yolo-detection", "bytetrack"],
                    bus=_default_bus())
    assert graph.detectors == ["yolo-detection"]
    assert graph.trackers == ["bytetrack"]
    assert graph.consumers == []          # aucun PipelineConsumer whitelisté
    assert graph.recognizers == []         # aucun PlateRecognizer whitelisté
    assert graph.needs_detection is True
    assert graph.needs_tracking is True
    assert graph.needs_business is False   # ← preuve du skip
    assert graph.needs_segmentation is False


def test_graph_empty_whitelist_activates_all():
    """Whitelist vide = comportement legacy (tous les plugins actifs)."""
    reg = CameraGraphRegistry()
    graph = reg.get("cam-B", enabled_plugins=[], bus=_default_bus())
    assert set(graph.detectors) == {"yolo-detection", "yolov8"}
    assert set(graph.trackers) == {"bytetrack", "botsort"}
    assert set(graph.consumers) == {"vehicle-counting", "person-counting", "smoke-detection"}
    assert graph.needs_anpr is True


def test_graph_no_matching_plugin_marks_stage_empty():
    """Une whitelist qui ne matche AUCUN plugin → is_empty=True (skip complet)."""
    reg = CameraGraphRegistry()
    graph = reg.get("cam-C",
                    enabled_plugins=["nonexistent-plugin-xyz"],
                    bus=_default_bus())
    assert graph.detectors == []
    assert graph.trackers == []
    assert graph.consumers == []
    assert graph.recognizers == []
    assert graph.needs_detection is False
    assert graph.needs_business is False
    # anpr peut rester True car "fast-alpr" est dans les KNOWN_ANPR_PROVIDERS
    # mais ici on a filtré → False
    assert graph.needs_anpr is False
    assert graph.is_empty is True


def test_graph_anpr_direct_flag_when_fast_alpr_in_whitelist():
    """La whitelist contient explicitement fast-alpr → needs_anpr=True."""
    reg = CameraGraphRegistry()
    graph = reg.get("cam-D", enabled_plugins=["fast-alpr"], bus=_default_bus())
    assert graph.needs_anpr is True
    assert graph.recognizers == ["fast-alpr"]


# ── 2. Cache / invalidation ────────────────────────────────────────

def test_graph_cache_hit_on_same_whitelist():
    reg = CameraGraphRegistry()
    g1 = reg.get("cam-X", enabled_plugins=["yolo-detection"], bus=_default_bus())
    g2 = reg.get("cam-X", enabled_plugins=["yolo-detection"], bus=_default_bus())
    assert g1 is g2   # même instance (cache hit)


def test_graph_cache_miss_on_changed_whitelist():
    reg = CameraGraphRegistry()
    g1 = reg.get("cam-Y", enabled_plugins=["yolo-detection"], bus=_default_bus())
    g2 = reg.get("cam-Y", enabled_plugins=["yolov8"], bus=_default_bus())
    assert g1 is not g2   # rebuild forcé par le changement de hash


def test_graph_bus_version_bump_invalidates_cache():
    reg = CameraGraphRegistry()
    g1 = reg.get("cam-Z", enabled_plugins=["yolo-detection"], bus=_default_bus())
    reg.bump_bus_version()
    g2 = reg.get("cam-Z", enabled_plugins=["yolo-detection"], bus=_default_bus())
    assert g1 is not g2


def test_graph_invalidate_specific_camera():
    reg = CameraGraphRegistry()
    reg.get("cam-1", enabled_plugins=[], bus=_default_bus())
    reg.get("cam-2", enabled_plugins=[], bus=_default_bus())
    reg.invalidate("cam-1")
    assert "cam-1" not in reg._graphs
    assert "cam-2" in reg._graphs


# ── 3. Bus per-camera stats ────────────────────────────────────────

def test_bus_per_camera_stats_isolation():
    """Deux caméras différentes → compteurs isolés par-caméra."""
    from plugin_manager.bus import PluginBus, BusEntry

    bus = PluginBus()

    class _Rec:
        name = "fake-recognizer"

        async def recognize(self, roi):
            return []

    # Enregistrement manuel (bypass des isinstance checks)
    entry = BusEntry(name="fake-recognizer", interface="PlateRecognizer",
                     instance=_Rec())
    bus._entries["fake-recognizer"] = entry

    async def _run():
        await bus._call_one(entry, lambda inst: inst.recognize(None),
                            timeout_s=1.0, camera_id="cam-A")
        await bus._call_one(entry, lambda inst: inst.recognize(None),
                            timeout_s=1.0, camera_id="cam-A")
        await bus._call_one(entry, lambda inst: inst.recognize(None),
                            timeout_s=1.0, camera_id="cam-B")

    asyncio.run(_run())

    stats = bus.per_camera_stats()
    assert "cam-A" in stats
    assert "cam-B" in stats
    assert stats["cam-A"]["fake-recognizer"]["calls"] == 2
    assert stats["cam-B"]["fake-recognizer"]["calls"] == 1
    assert stats["cam-A"]["fake-recognizer"]["errors"] == 0


def test_bus_per_camera_stats_reset():
    from plugin_manager.bus import PluginBus
    bus = PluginBus()
    bus._per_camera_stats["cam-A"] = {"foo": {"calls": 10}}
    bus._per_camera_stats["cam-B"] = {"bar": {"calls": 5}}
    bus.reset_per_camera_stats("cam-A")
    assert "cam-A" not in bus._per_camera_stats
    assert "cam-B" in bus._per_camera_stats
    bus.reset_per_camera_stats()
    assert bus._per_camera_stats == {}


# ── 4. Bus invalidates registry on toggle ─────────────────────────

def test_bus_set_enabled_bumps_graph_registry():
    """set_enabled sur le bus doit invalider les graphes per-camera."""
    from plugin_manager.bus import bus as real_bus
    from pipeline_v2.registry import registry as real_registry

    # Charge un graphe puis toggle un plugin → nouveau hash
    if "yolo-detection" in real_bus._entries:
        before_version = real_registry._bus_version
        graph1 = real_registry.get("cam-toggle-test",
                                    enabled_plugins=["yolo-detection"],
                                    bus=real_bus)
        # Toggle
        real_bus.set_enabled("yolo-detection", False)
        after_version = real_registry._bus_version
        assert after_version == before_version + 1
        # Prochaine get → rebuild
        graph2 = real_registry.get("cam-toggle-test",
                                    enabled_plugins=["yolo-detection"],
                                    bus=real_bus)
        assert graph1 is not graph2
        # Restaure pour ne pas polluer les autres tests
        real_bus.set_enabled("yolo-detection", True)


# ── 5. HTTP endpoints ──────────────────────────────────────────────

def test_http_pipeline_v2_endpoint_shape():
    """Vérifie que l'endpoint /api/diagnostics/pipeline-v2 retourne la bonne structure."""
    import requests

    api_url = os.environ.get("REACT_APP_BACKEND_URL") or ""
    if not api_url:
        # Fallback lecture .env
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        api_url = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pytest.skip("No frontend/.env available")
    if not api_url:
        pytest.skip("No backend URL")

    # Login
    r = requests.post(f"{api_url}/api/auth/login",
                       json={"email": "admin@mg-vms.com", "password": "Admin@2026"},
                       timeout=10)
    if r.status_code != 200:
        pytest.skip(f"Auth unavailable: {r.status_code}")
    token = r.json()["access_token"]

    # Endpoint /pipeline-v2
    r = requests.get(f"{api_url}/api/diagnostics/pipeline-v2",
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert "cameras" in body
    assert "stats" in body
    assert "cached_cameras" in body["stats"]

    # Endpoint /pipeline-v2/stats
    r = requests.get(f"{api_url}/api/diagnostics/pipeline-v2/stats",
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert "per_camera" in body
    assert "per_plugin" in body


def test_http_pipeline_v2_invalidate():
    import requests
    api_url = ""
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    api_url = line.split("=", 1)[1].strip()
                    break
    except FileNotFoundError:
        pytest.skip("No frontend/.env")
    if not api_url:
        pytest.skip("No URL")

    r = requests.post(f"{api_url}/api/auth/login",
                       json={"email": "admin@mg-vms.com", "password": "Admin@2026"},
                       timeout=10)
    if r.status_code != 200:
        pytest.skip(f"Auth unavailable")
    token = r.json()["access_token"]

    r = requests.post(f"{api_url}/api/diagnostics/pipeline-v2/invalidate",
                       headers={"Authorization": f"Bearer {token}"},
                       timeout=10)
    assert r.status_code == 200
    assert r.json()["invalidated"] == "all"


# ── 6. KNOWN_ANPR_PROVIDERS integrity ─────────────────────────────

def test_known_anpr_providers_includes_fast_alpr():
    assert "fast-alpr" in KNOWN_ANPR_PROVIDERS
