"""v0.8-rc3 · MongoDB indexes bootstrap + Frontend virtualization — tests.

Vérifie :
  A) `create_indexes()` est idempotent + résilient (safe_index tolère les conflits)
  B) Toutes les collections critiques ont bien les indexes attendus
  C) Le composant VirtualGrid.jsx expose les data-testid documentés
"""
from __future__ import annotations

import asyncio
import os
import pytest


os.environ["TESTING"] = "1"


def _run(coro):
    """Helper : exécute une coroutine dans une boucle dédiée (compat sync test)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestSafeIndexHelper:
    def test_safe_index_swallows_conflicts(self):
        from database import _safe_index
        from pymongo.errors import OperationFailure

        class FakeCollection:
            name = "fake"

            def __init__(self):
                self.calls = 0

            async def create_index(self, keys, **opts):
                self.calls += 1
                # Simule un conflit d'options (code 85)
                raise OperationFailure("conflict test", code=85)

        col = FakeCollection()
        # Ne doit PAS lever
        _run(_safe_index(col, "some_field"))
        assert col.calls == 1

    def test_safe_index_swallows_generic_errors(self):
        from database import _safe_index

        class BrokenCollection:
            name = "broken"

            async def create_index(self, keys, **opts):
                raise RuntimeError("boom")

        # Ne doit PAS lever
        _run(_safe_index(BrokenCollection(), "x"))


class TestIndexesCreatedAtBootstrap:
    """Le backend a créé les indexes au démarrage (voir server.on_startup).
    Ces tests vérifient leur présence via un client Mongo dédié à la loop de test."""

    def test_critical_collections_have_expected_indexes(self):
        from motor.motor_asyncio import AsyncIOMotorClient

        async def check():
            cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
            try:
                db = cli[os.environ["DB_NAME"]]
                # Ces champs DOIVENT être indexés (recommandations mongo_audit.py)
                expectations = {
                    "cameras": {"id", "site_id", "status"},
                    "events": {"timestamp", "camera_id", "type", "kind"},
                    "plates": {"timestamp", "camera_id", "plate", "track_id"},
                    "recordings": {"camera_id", "start_ts", "end_ts"},
                    "audit_logs": {"timestamp", "actor"},
                    "users": {"email"},
                    "sessions": {"user_id", "created_at"},
                    "tls_certificates": {"id", "active"},
                    "alerts": {"timestamp", "camera_id"},
                }
                for col, expected in expectations.items():
                    idxs = await db[col].list_indexes().to_list(None)
                    fields = set()
                    for ix in idxs:
                        for k in (ix.get("key") or {}).keys():
                            fields.add(k)
                    missing = expected - fields
                    assert not missing, f"{col} missing {missing} (present: {fields})"
            finally:
                cli.close()

        _run(check())

    def test_create_indexes_helper_is_defined(self):
        """Le helper _safe_index doit être défini + create_indexes exposée."""
        from database import create_indexes, _safe_index
        assert callable(create_indexes)
        assert callable(_safe_index)


class TestVirtualGridComponentContract:
    """Vérifie côté fichier que le composant VirtualGrid.jsx expose l'API documentée."""
    def test_component_exists_and_exports_default(self):
        path = "/app/frontend/src/components/VirtualGrid.jsx"
        assert os.path.exists(path), "VirtualGrid.jsx missing"
        src = open(path, encoding="utf-8").read()
        assert "export default function VirtualGrid" in src
        assert "react-window" in src
        # Contrat props
        for prop in ("items", "renderItem", "itemKey", "rowHeight",
                     "minColumnWidth", "maxColumns", "threshold"):
            assert prop in src, f"prop {prop} not documented in VirtualGrid.jsx"

    def test_component_exposes_testid(self):
        src = open("/app/frontend/src/components/VirtualGrid.jsx", encoding="utf-8").read()
        assert 'data-testid={testid}' in src
        assert 'virtual-grid' in src  # default testid


class TestVehiclesPageUsesVirtualGrid:
    def test_vehicles_imports_virtual_grid(self):
        src = open("/app/frontend/src/pages/Vehicles.jsx", encoding="utf-8").read()
        assert 'from "@/components/VirtualGrid"' in src
        assert "<VirtualGrid" in src
        # Le fallback CSS grid (grid-cols-*) doit être remplacé
        assert 'renderItem={(v) => <VehicleCard' in src
