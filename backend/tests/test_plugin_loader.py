"""Tests loader dynamique YOLO plugin (chapitre 11 §11.4.1)."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "/app/backend")

from plugin_manager.loader import PluginLoader


def test_yolo_manifest_is_discovered_and_loaded():
    """Le plugin yolo-detection livré dans /app/data/plugins doit être découvert."""
    loader = PluginLoader(Path("/app/data/plugins"))
    manifests = loader.discover()
    assert any("yolo-detection" in str(m) for m in manifests), \
        f"yolo-detection manifest introuvable: {manifests}"


def test_loader_validates_manifest_and_registers():
    async def _run():
        loader = PluginLoader(Path("/app/data/plugins"))
        results = await loader.discover_and_load_all()
        assert len(results) >= 1
        yolo = next((r for r in results if r.name == "yolo-detection"), None)
        assert yolo is not None, "yolo-detection non chargé"
        assert yolo.error is None, f"erreur inattendue: {yolo.error}"
        assert yolo.entry is not None, "pas d'entrée bus"
        assert yolo.interface == "FrameAnalyzer"
        assert yolo.config_schema is not None
        assert yolo.config_schema.get("title") == "Configuration YOLO Detection"
    asyncio.run(_run())


def test_loader_rejects_invalid_manifest():
    """Un manifest cassé (apiVersion incorrect) doit être ignoré sans crasher le loader."""
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad-plugin"
            bad.mkdir()
            (bad / "manifest.yaml").write_text(
                "apiVersion: mgvms.io/v99\nkind: Plugin\nmetadata:\n  name: bad\n"
            )
            (bad / "plugin.py").write_text("# empty\n")
            loader = PluginLoader(Path(td))
            results = await loader.discover_and_load_all()
            assert len(results) == 1
            assert results[0].error is not None
            assert "apiVersion" in results[0].error
            assert results[0].entry is None
    asyncio.run(_run())


def test_loader_handles_missing_entrypoint():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "no-code"
            bad.mkdir()
            (bad / "manifest.yaml").write_text("""apiVersion: mgvms.io/v1
kind: Plugin
metadata:
  name: no-code
  version: "1.0"
spec:
  runtime: python
  entrypoint: missing.py
  interface: FrameAnalyzer
""")
            loader = PluginLoader(Path(td))
            results = await loader.discover_and_load_all()
            assert len(results) == 1
            assert "entrypoint introuvable" in (results[0].error or "")
    asyncio.run(_run())
