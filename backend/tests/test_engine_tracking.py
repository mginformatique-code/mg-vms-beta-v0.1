"""Tests P8+ · Traçabilité des moteurs (engine) sur plaques et événements."""
import asyncio

import httpx


BASE = "http://localhost:8001"
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


def _token():
    r = httpx.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=10)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d.get("token")


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


def test_existing_plates_have_engine_field():
    """Backfill : toutes les plaques doivent avoir un champ `engine` (défaut fast-alpr)."""
    r = httpx.get(f"{BASE}/api/plates?limit=50", headers=_auth(), timeout=15)
    assert r.status_code == 200
    plates = r.json()
    if not plates:
        return  # aucune plaque en DB → test passe trivialement
    for p in plates:
        assert "engine" in p, f"plaque {p.get('plate')} n'a pas de champ engine"
        assert p["engine"], f"plaque {p.get('plate')} : engine vide"


def test_backfill_migration_populated_engine():
    """Vérifie qu'aucune plaque n'a un engine manquant après migration."""
    async def _run():
        import os
        os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
        os.environ.setdefault("DB_NAME", "test_database")
        from database import db
        missing = await db.plates.count_documents({"engine": {"$exists": False}})
        assert missing == 0, f"{missing} plaques sans engine après migration"
    asyncio.run(_run())
