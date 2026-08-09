"""Tests v1.0-rc4.6 · Account lockout / brute-force protection.

Motor (pilote Mongo async) attache son client à la première event loop qui
l'utilise. `asyncio.run()` crée/détruit une loop par test — après le 1er, la
loop de motor est fermée. On force donc un client motor FRAIS par test,
re-injecté dans les modules qui l'importent (auth, scripts.mgvms_admin).
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest


def _fresh_motor_client():
    """Recrée un AsyncIOMotorClient attaché à la loop courante et l'injecte
    dans tous les modules qui font `from database import db`."""
    import motor.motor_asyncio
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
    new_db = client[db_name]
    # Re-bind dans tous les modules importateurs
    for mod_name in ("database", "auth", "scripts.mgvms_admin"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "db"):
            mod.db = new_db
    return new_db


def _mk_user_doc(email: str, uid: str, **extra) -> dict:
    from auth import hash_password
    return {
        "id": uid, "email": email, "name": "Lockout Test",
        "password_hash": hash_password("CorrectPassword123"),
        "role": "client", "active": True, "twofa_enabled": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }


def test_lockout_full_lifecycle():
    """4 échecs OK → 5e = locked → CLI unlock → reset compteur."""

    async def run():
        db = _fresh_motor_client()
        os.environ["TESTING"] = "0"
        try:
            from auth import _account_track_failure, _account_track_success
            from scripts.mgvms_admin import cmd_unlock_user

            email = f"lockout-{uuid.uuid4().hex[:8]}@mgvms.test"
            uid = str(uuid.uuid4())
            await db.users.insert_one(_mk_user_doc(email, uid))
            try:
                for i in range(4):
                    r = await _account_track_failure(email, f"10.0.0.{i}")
                    assert r["count"] == i + 1
                    assert r["locked"] is False
                u = await db.users.find_one({"email": email})
                assert not u.get("locked")
                assert u["failed_login_count"] == 4

                r5 = await _account_track_failure(email, "10.0.0.99")
                assert r5["count"] == 5
                assert r5["locked"] is True
                u = await db.users.find_one({"email": email})
                assert u["locked"] is True
                assert u.get("locked_at")
                assert u["last_failed_login_ip"] == "10.0.0.99"

                rc = await cmd_unlock_user(email)
                assert rc == 0
                u = await db.users.find_one({"email": email})
                assert u["locked"] is False
                assert u["failed_login_count"] == 0
                assert "locked_at" not in u

                await _account_track_success({"id": uid}, "192.168.1.100")
                u = await db.users.find_one({"email": email})
                assert u["failed_login_count"] == 0
                assert u["last_login_ip"] == "192.168.1.100"
                assert u.get("last_login_at")
            finally:
                await db.users.delete_one({"email": email})
        finally:
            os.environ["TESTING"] = "1"

    asyncio.run(run())


def test_unknown_email_no_write():
    """Email inconnu ne doit pas créer de doc (anti-énumération)."""

    async def run():
        db = _fresh_motor_client()
        os.environ["TESTING"] = "0"
        try:
            from auth import _account_track_failure
            email = f"noexist-{uuid.uuid4().hex[:8]}@mgvms.test"
            r = await _account_track_failure(email, "10.0.0.1")
            assert r == {}
            u = await db.users.find_one({"email": email})
            assert u is None
        finally:
            os.environ["TESTING"] = "1"

    asyncio.run(run())


def test_cli_unlock_returns_1_when_user_absent():
    async def run():
        _fresh_motor_client()
        from scripts.mgvms_admin import cmd_unlock_user
        rc = await cmd_unlock_user("does-not-exist-xyz@mgvms.test")
        assert rc == 1

    asyncio.run(run())


def test_is_main_admin_flag():
    from auth import _is_main_admin
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@mg-vms.com")
    assert _is_main_admin(admin_email) is True
    assert _is_main_admin(admin_email.upper()) is True
    assert _is_main_admin("nobody@nowhere.local") is False
    assert _is_main_admin("") is False


def test_public_user_defaults_and_populated():
    from auth import public_user
    u = {"id": "x", "email": "y@z.com", "name": "T", "role": "client", "active": True}
    pub = public_user(u)
    assert pub["locked"] is False
    assert pub["failed_login_count"] == 0
    assert pub["locked_at"] is None
    assert pub["is_main_admin"] is False

    u2 = {
        "id": "x", "email": "y@z.com", "name": "T", "role": "client",
        "active": True, "locked": True, "failed_login_count": 5,
        "locked_at": "2026-08-09T20:00:00+00:00",
        "last_failed_login_ip": "1.2.3.4",
    }
    pub2 = public_user(u2)
    assert pub2["locked"] is True
    assert pub2["failed_login_count"] == 5
    assert pub2["locked_at"] == "2026-08-09T20:00:00+00:00"
    assert pub2["last_failed_login_ip"] == "1.2.3.4"

