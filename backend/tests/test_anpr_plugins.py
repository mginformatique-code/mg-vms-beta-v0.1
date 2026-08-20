"""Tests d'intégration : 7 plugins ANPR découverts par le loader dynamique.

v3.1.4 · openalpr, google-vision, azure-vision (APIs cloud jamais configurées
en pratique) et custom-plugin-template (template dev, pas un vrai moteur)
retirés du catalogue — ils s'activaient sans jamais rien produire, source de
confusion (caméra affichée "ANPR actif" sans qu'aucun de ces moteurs ne
sorte de résultat). Voir data/plugins/openalpr/plugin.py (avant suppression) :
`_evaluate_state()` bloquait en "not_configured" sans `secret_key`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "/app/backend")

from plugin_manager.loader import PluginLoader
from plugin_manager.bus import PluginBus
from plugin_manager.config_store import PluginConfigStore

# Les 7 plugins ANPR + 1 FrameAnalyzer YOLO attendus
EXPECTED_ANPR = {
    "fast-alpr", "plate-recognizer", "codeproject-ai",
    "paddle-ocr", "easyocr", "tesseract", "opencv-ocr",
}
EXPECTED_ALL = EXPECTED_ANPR | {"yolo-detection"}


def test_all_anpr_plugins_are_discovered():
    loader = PluginLoader(Path("/app/data/plugins"))
    manifests = loader.discover()
    names = {m.parent.name for m in manifests}
    missing = EXPECTED_ALL - names
    assert not missing, f"Plugins ANPR manquants dans /app/data/plugins: {missing}"


def test_all_plugins_have_valid_manifest_and_schema():
    async def _run():
        loader = PluginLoader(Path("/app/data/plugins"))
        results = await loader.discover_and_load_all()
        # Tous doivent parser sans erreur de manifest (loading peut échouer selon deps)
        for r in results:
            # Tous doivent avoir un config_schema
            assert r.config_schema is not None, f"{r.name} n'a pas de config/schema.json"
            # Le schema doit avoir un titre
            assert "title" in r.config_schema, f"{r.name} schema sans title"
    asyncio.run(_run())


def test_all_anpr_plugins_are_plate_recognizer_interface():
    async def _run():
        loader = PluginLoader(Path("/app/data/plugins"))
        results = await loader.discover_and_load_all()
        for r in results:
            if r.name == "yolo-detection":
                assert r.interface == "FrameAnalyzer"
            elif r.name in EXPECTED_ANPR:
                assert r.interface == "PlateRecognizer", \
                    f"{r.name} devrait être PlateRecognizer, pas {r.interface}"
    asyncio.run(_run())


def test_unconfigured_plugins_are_not_dispatchable():
    """Un plugin sans config valide doit rester enregistré mais NON dispatchable."""
    async def _run():
        loader = PluginLoader(Path("/app/data/plugins"))
        await loader.discover_and_load_all()
        from plugin_manager.bus import bus as global_bus
        # Compte les plugins ANPR dispatchables (state=ready)
        anpr_entries = [e for e in global_bus.list_entries() if e.interface == "PlateRecognizer"]
        # Sans credentials, la plupart des cloud/local doivent être non-dispatchables
        assert len(anpr_entries) >= 6, f"Moins de 6 ANPR enregistrés: {len(anpr_entries)}"
        # Vérifie que active() filtre bien
        active_anpr = global_bus.active("PlateRecognizer")
        # Aucun plugin cloud ne devrait être actif sans clés
        active_names = {e.name for e in active_anpr}
        assert "plate-recognizer" not in active_names, \
            "plate-recognizer ne devrait pas être active sans api_token"
    asyncio.run(_run())


def test_config_store_persists_across_instances(tmp_path):
    p = tmp_path / "cfg.json"
    s1 = PluginConfigStore(p)
    s1.set("plate-recognizer", {"api_token": "TOKEN123", "regions": ["fr"]})
    s2 = PluginConfigStore(p)
    got = s2.get("plate-recognizer")
    assert got["api_token"] == "TOKEN123"
    assert got["regions"] == ["fr"]


