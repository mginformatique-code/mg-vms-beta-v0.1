"""Tests P2 finalisation · Marketplace upload .mgpkg + PluginDB namespace isolé."""
import asyncio
import io
import os

import httpx
import pytest

from plugin_sdk import scaffold as scaffold_mod, pack as pack_mod

BASE = "http://localhost:8001"
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


def _token():
    r = httpx.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=10)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d.get("token")


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


# ── PluginDB namespace isolé ───────────────────────────────────────────
def test_plugin_db_uses_scoped_collection_name():
    from plugin_manager.context import PluginDB
    db = PluginDB("my-plugin")
    assert db.collection_name == "plugin_data_my-plugin"
    # Nom sanitisé pour caractères exotiques
    db2 = PluginDB("bad name!@#")
    assert "plugin_data_" in db2.collection_name
    assert "!" not in db2.collection_name
    assert "@" not in db2.collection_name


def test_plugin_db_crud_roundtrip_and_isolation():
    """CRUD complet + isolation entre plugins (dans une seule event loop)."""
    async def _run():
        from plugin_manager.context import PluginDB
        db = PluginDB("test-plugin-crud")
        await db.delete({})
        await db.insert({"key": "hello", "n": 1})
        await db.insert({"key": "world", "n": 2})
        assert len(await db.find({})) == 2
        doc = await db.find_one({"key": "hello"})
        assert doc["n"] == 1
        assert await db.update({"key": "hello"}, {"$set": {"n": 42}}) == 1
        doc = await db.find_one({"key": "hello"})
        assert doc["n"] == 42
        assert await db.count() == 2
        assert await db.count({"key": "hello"}) == 1
        assert await db.delete({"key": "hello"}) == 1
        assert await db.count() == 1
        await db.delete({})

        # Isolation entre plugins
        a = PluginDB("plugin-a")
        b = PluginDB("plugin-b")
        await a.delete({}); await b.delete({})
        await a.insert({"owner": "A"})
        await b.insert({"owner": "B"})
        assert await a.count() == 1
        assert await b.count() == 1
        assert (await a.find_one({}))["owner"] == "A"
        assert (await b.find_one({}))["owner"] == "B"
        await a.delete({}); await b.delete({})
    asyncio.run(_run())


def test_plugin_context_receives_db():
    """Après on_load, tout plugin chargé a un ctx.db non-null."""
    async def _run():
        from pathlib import Path
        from plugin_manager.loader import PluginLoader
        pl = PluginLoader(Path("/app/data/plugins"))
        await pl.discover_and_load_all()
        from plugin_manager.bus import bus
        # yolo-detection est un plugin standard chargé au boot
        entry = bus._entries.get("yolo-detection")
        assert entry is not None, "yolo-detection devrait être enregistré"
        ctx = getattr(entry.instance, "_mgvms_ctx", None)
        assert ctx is not None
        assert ctx.db is not None
        assert ctx.db.collection_name == "plugin_data_yolo-detection"
    asyncio.run(_run())


# ── Marketplace upload .mgpkg ──────────────────────────────────────────
def test_marketplace_upload_rejects_bad_extension(tmp_path):
    r = httpx.post(
        f"{BASE}/api/plugins/marketplace/upload",
        files={"file": ("test.zip", b"junk", "application/zip")},
        headers=_auth(), timeout=10,
    )
    assert r.status_code == 400
    assert ".mgpkg" in r.text


def test_marketplace_upload_rejects_corrupt_archive(tmp_path):
    r = httpx.post(
        f"{BASE}/api/plugins/marketplace/upload",
        files={"file": ("bad.mgpkg", b"not_a_tarball", "application/gzip")},
        headers=_auth(), timeout=10,
    )
    assert r.status_code == 400


def test_marketplace_upload_installs_valid_mgpkg(tmp_path):
    """End-to-end : scaffold → pack → upload → vérifie plugin installé."""
    # 1. Scaffold un nouveau plugin
    root = scaffold_mod.scaffold("marketplace-test", "FrameAnalyzer", out_dir=tmp_path)
    # 2. Pack en .mgpkg
    pkg = pack_mod.pack(root, out_dir=tmp_path / "dist")
    # 3. Upload
    with open(pkg, "rb") as f:
        r = httpx.post(
            f"{BASE}/api/plugins/marketplace/upload",
            files={"file": (pkg.name, f, "application/gzip")},
            headers=_auth(), timeout=30,
        )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "marketplace-test"
    assert d["reloaded"] is True
    # 4. Vérifie que le fichier est bien sur disque
    assert os.path.isfile("/app/data/plugins/marketplace-test/manifest.yaml")
    # 5. Vérifie qu'il apparaît dans le bus
    r = httpx.get(f"{BASE}/api/plugins/bus", headers=_auth(), timeout=10)
    names = [e["name"] for e in r.json()["entries"]]
    assert "marketplace-test" in names

    # Cleanup pour ne pas polluer les autres tests
    import shutil
    shutil.rmtree("/app/data/plugins/marketplace-test", ignore_errors=True)


def test_marketplace_upload_rejects_path_traversal(tmp_path):
    """Un .mgpkg malicieux avec `../../etc/passwd` doit être rejeté."""
    import tarfile
    pkg = tmp_path / "evil.mgpkg"
    with tarfile.open(pkg, "w:gz") as tar:
        # Crée un fichier avec path traversal
        info = tarfile.TarInfo(name="../../../etc/evil.txt")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"boom"))
    with open(pkg, "rb") as f:
        r = httpx.post(
            f"{BASE}/api/plugins/marketplace/upload",
            files={"file": ("evil.mgpkg", f, "application/gzip")},
            headers=_auth(), timeout=10,
        )
    # Doit rejeter en 400
    assert r.status_code == 400
