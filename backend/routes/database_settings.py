"""Route module — Database configuration (P2, Feb 2026).

Permet à l'admin de :
  1. Voir la config actuelle (redactée, sans mot de passe)
  2. Tester une nouvelle URI MongoDB avec un ping + comptage caméras
  3. Enregistrer une nouvelle config dans `/app/backend/.env` (redémarrage requis)

Note : ce module NE bascule PAS la connexion à chaud (le client `motor` est
créé au module-level dans `database.py`). L'admin doit relancer le backend
via supervisor pour que la nouvelle URI soit prise en compte.
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_role, log_audit
from database import db

database_router = APIRouter(prefix="/api", tags=["database"])

ENV_PATH = Path("/app/backend/.env")


def _redact_uri(uri: str) -> str:
    """Masque le mot de passe dans une URI type `mongodb://user:pass@host/db`."""
    if not uri:
        return ""
    return re.sub(r"://([^:@/]+):([^@]+)@", r"://\1:***@", uri)


class DatabaseConfigInput(BaseModel):
    mongo_url: str
    db_name: str


@database_router.get("/settings/database")
async def get_database_config(user: dict = Depends(require_role("admin"))):
    """Retourne la config DB courante (mot de passe masqué)."""
    current_url = os.environ.get("MONGO_URL", "")
    current_db = os.environ.get("DB_NAME", "")
    # Ping actif pour valider que la DB courante répond
    ping_ms = None
    status = "unknown"
    try:
        import time
        t0 = time.perf_counter()
        await asyncio.wait_for(db.command("ping"), timeout=5)
        ping_ms = int((time.perf_counter() - t0) * 1000)
        status = "ok"
    except Exception as e:
        status = f"error: {type(e).__name__}"

    # Compteurs de sanity
    try:
        collections_count = len(await db.list_collection_names())
    except Exception:
        collections_count = None

    return {
        "current": {
            "mongo_url_redacted": _redact_uri(current_url),
            "db_name": current_db,
            "status": status,
            "ping_ms": ping_ms,
            "collections": collections_count,
        },
        "engine": "mongodb",
        "supported_engines": ["mongodb"],  # SQL/MariaDB à venir (roadmap P2+)
        "note": ("Le changement d'URI nécessite un redémarrage du backend "
                 "(supervisor restart backend). Utilisez POST /api/settings/database/test "
                 "avant d'appliquer pour valider la nouvelle URI."),
    }


@database_router.post("/settings/database/test")
async def test_database_config(data: DatabaseConfigInput,
                                user: dict = Depends(require_role("admin"))):
    """Teste une URI + db_name en se connectant temporairement, sans persister.

    Retourne :
      - status: ok | error
      - ping_ms: latence du ping
      - collections: nombre de collections trouvées
      - error: message si échec
    """
    from motor.motor_asyncio import AsyncIOMotorClient
    import time

    if not data.mongo_url.startswith(("mongodb://", "mongodb+srv://")):
        raise HTTPException(400,
            "URI invalide — doit commencer par mongodb:// ou mongodb+srv://")
    if not data.db_name or not re.match(r"^[a-zA-Z0-9_-]+$", data.db_name):
        raise HTTPException(400, "db_name invalide (alphanumeric, _, - uniquement)")

    client = None
    try:
        client = AsyncIOMotorClient(data.mongo_url, serverSelectionTimeoutMS=5000)
        t0 = time.perf_counter()
        await asyncio.wait_for(client.admin.command("ping"), timeout=8)
        ping_ms = int((time.perf_counter() - t0) * 1000)
        target_db = client[data.db_name]
        collections = await target_db.list_collection_names()
        cams = await target_db.cameras.count_documents({}) if "cameras" in collections else 0
        return {
            "status": "ok",
            "ping_ms": ping_ms,
            "collections": len(collections),
            "cameras_count": cams,
            "collections_sample": collections[:10],
        }
    except asyncio.TimeoutError:
        raise HTTPException(504, "Timeout (>8s) — serveur MongoDB injoignable")
    except Exception as e:
        raise HTTPException(502, f"Connexion échouée : {type(e).__name__}: {str(e)[:200]}")
    finally:
        if client is not None:
            client.close()


@database_router.put("/settings/database")
async def update_database_config(data: DatabaseConfigInput,
                                  user: dict = Depends(require_role("admin"))):
    """Persiste la nouvelle config dans `/app/backend/.env`.

    **Ne bascule PAS la connexion à chaud** — un redémarrage du backend est
    obligatoire (`sudo supervisorctl restart backend`).

    Ne modifie que les lignes MONGO_URL et DB_NAME ; les autres variables sont
    préservées à l'octet près.
    """
    # Auto-test pour éviter de casser la prod avec une URI invalide
    await test_database_config(data, user)  # lève HTTPException si KO

    if not ENV_PATH.exists():
        raise HTTPException(500, "backend/.env introuvable")

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    updated_mongo = False
    updated_db = False
    new_lines = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("MONGO_URL="):
            new_lines.append(f"MONGO_URL={data.mongo_url}")
            updated_mongo = True
        elif stripped.startswith("DB_NAME="):
            new_lines.append(f"DB_NAME={data.db_name}")
            updated_db = True
        else:
            new_lines.append(line)
    if not updated_mongo:
        new_lines.append(f"MONGO_URL={data.mongo_url}")
    if not updated_db:
        new_lines.append(f"DB_NAME={data.db_name}")

    # Backup atomique
    backup = ENV_PATH.with_suffix(".env.bak")
    backup.write_text(ENV_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    await log_audit(user, "database_config_updated",
                    _redact_uri(data.mongo_url), data.db_name)

    return {
        "status": "saved",
        "mongo_url_redacted": _redact_uri(data.mongo_url),
        "db_name": data.db_name,
        "backup": str(backup),
        "restart_required": True,
        "restart_command": "sudo supervisorctl restart backend",
    }


class RestartInput(BaseModel):
    confirm: bool = False


@database_router.post("/settings/database/restart-backend")
async def restart_backend(data: RestartInput,
                          user: dict = Depends(require_role("admin"))):
    """Redémarre le backend via supervisor pour appliquer la nouvelle config DB.

    Le client HTTP recevra probablement une déconnexion — c'est attendu.
    """
    if not data.confirm:
        raise HTTPException(400, "Confirmation requise : envoyez `{'confirm': true}`")
    await log_audit(user, "backend_restart", "database_config_change")
    # Lance supervisorctl en tâche différée pour que la réponse HTTP parte d'abord
    asyncio.get_event_loop().call_later(
        0.5,
        lambda: os.system("sudo supervisorctl restart backend"),
    )
    return {"status": "restarting", "eta_seconds": 3}
