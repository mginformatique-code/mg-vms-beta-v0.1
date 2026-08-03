"""Tests P2 · Plugin SDK — scaffolder + packager."""
import json
import tarfile
from pathlib import Path

import pytest

from plugin_sdk import scaffold as scaffold_mod
from plugin_sdk import pack as pack_mod


def test_scaffold_creates_expected_layout(tmp_path):
    root = scaffold_mod.scaffold("cool-detector", "FrameAnalyzer", out_dir=tmp_path)
    assert root.name == "cool-detector"
    assert (root / "manifest.yaml").is_file()
    assert (root / "plugin.py").is_file()
    assert (root / "config" / "schema.json").is_file()
    assert (root / "README.md").is_file()


def test_scaffold_manifest_matches_slug_and_interface(tmp_path):
    root = scaffold_mod.scaffold("Super Détecteur !", "FrameAnalyzer", out_dir=tmp_path)
    manifest = (root / "manifest.yaml").read_text()
    assert "name: super-d-tecteur" in manifest.lower() or "name: super-detecteur" in manifest.lower()
    assert "interface: FrameAnalyzer" in manifest
    assert "className: " in manifest


def test_scaffold_plugin_py_contains_class_stub(tmp_path):
    root = scaffold_mod.scaffold("my-tracker", "Tracker", out_dir=tmp_path)
    code = (root / "plugin.py").read_text()
    assert "class MyTrackerPlugin(Tracker):" in code
    assert "async def on_load" in code
    assert "async def update" in code


def test_scaffold_all_interfaces(tmp_path):
    for iface in ("FrameAnalyzer", "PlateRecognizer", "Tracker",
                  "Segmenter", "PipelineConsumer", "EventConsumer"):
        root = scaffold_mod.scaffold(f"test-{iface.lower()}", iface, out_dir=tmp_path)
        code = (root / "plugin.py").read_text()
        assert f"({iface}):" in code, f"plugin.py doit hériter de {iface}"


def test_scaffold_rejects_unknown_interface(tmp_path):
    with pytest.raises(ValueError):
        scaffold_mod.scaffold("bad", "NotAnInterface", out_dir=tmp_path)


def test_scaffold_rejects_existing_folder(tmp_path):
    scaffold_mod.scaffold("dup", "FrameAnalyzer", out_dir=tmp_path)
    with pytest.raises(FileExistsError):
        scaffold_mod.scaffold("dup", "FrameAnalyzer", out_dir=tmp_path)


def test_scaffold_schema_is_valid_json(tmp_path):
    root = scaffold_mod.scaffold("sch-test", "FrameAnalyzer", out_dir=tmp_path)
    schema = json.loads((root / "config" / "schema.json").read_text())
    assert schema["type"] == "object"
    assert "properties" in schema


def test_pack_produces_mgpkg(tmp_path):
    root = scaffold_mod.scaffold("packable", "FrameAnalyzer", out_dir=tmp_path)
    out_dir = tmp_path / "dist"
    pkg = pack_mod.pack(root, out_dir=out_dir)
    assert pkg.suffix == ".mgpkg"
    assert pkg.stat().st_size > 0
    # Vérifier structure interne
    with tarfile.open(pkg, "r:gz") as tar:
        names = tar.getnames()
    assert "packable/manifest.yaml" in names
    assert "packable/plugin.py" in names
    assert "packable/config/schema.json" in names


def test_pack_uses_manifest_version_in_filename(tmp_path):
    root = scaffold_mod.scaffold("versioned", "FrameAnalyzer", out_dir=tmp_path)
    # Modifier la version dans le manifest
    manifest = (root / "manifest.yaml")
    text = manifest.read_text()
    text = text.replace('version: "0.1.0"', 'version: "2.5.3"')
    manifest.write_text(text)
    pkg = pack_mod.pack(root, out_dir=tmp_path / "dist")
    assert pkg.name == "versioned-2.5.3.mgpkg"


def test_pack_rejects_folder_without_manifest(tmp_path):
    root = tmp_path / "bad"
    root.mkdir()
    (root / "plugin.py").write_text("pass")
    with pytest.raises(FileNotFoundError):
        pack_mod.pack(root)


def test_pack_excludes_pycache(tmp_path):
    root = scaffold_mod.scaffold("clean-me", "FrameAnalyzer", out_dir=tmp_path)
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "junk.pyc").write_bytes(b"junk")
    pkg = pack_mod.pack(root, out_dir=tmp_path / "dist")
    with tarfile.open(pkg, "r:gz") as tar:
        names = tar.getnames()
    assert not any("__pycache__" in n for n in names)
    assert not any(n.endswith(".pyc") for n in names)
