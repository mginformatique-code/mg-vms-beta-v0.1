"""Point d'entrée FastAPI MG-VMS — API + WebSocket, préfixe /api."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.v1 import (
    ai, audit, auth, cameras, events, health, maps, monitoring,
    notifications, playback, recordings, settings as settings_router,
    sites, storage, streams, users,
)
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.security import hash_password, verify_password
from app.db.session import SessionLocal
from app.models import Role, User
from app.ws import manager, start_subscriber

setup_logging()
logger = logging.getLogger("main")

ROLES = [(1, "admin", 1), (2, "technician", 2), (3, "operator", 3)]


async def seed() -> None:
    """Rôles + compte admin initial (idempotent)."""
    s = get_settings()
    async with SessionLocal() as db:
        for role_id, code, level in ROLES:
            if not await db.get(Role, role_id):
                db.add(Role(id=role_id, code=code, level=level))
        await db.commit()
        admin = await db.scalar(select(User).where(User.email == s.ADMIN_EMAIL.lower()))
        if admin is None:
            db.add(User(email=s.ADMIN_EMAIL.lower(), password_hash=hash_password(s.ADMIN_PASSWORD),
                        name="Administrateur", role_id=1, permissions={}))
            await db.commit()
            logger.info("Compte admin initial créé : %s", s.ADMIN_EMAIL)
        elif not verify_password(s.ADMIN_PASSWORD, admin.password_hash):
            admin.password_hash = hash_password(s.ADMIN_PASSWORD)
            await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed()
    task = start_subscriber()
    yield
    task.cancel()


app = FastAPI(title="MG-VMS API", version="2.0.0", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (auth.router, users.router, sites.router, cameras.router, streams.router,
               recordings.router, playback.router, events.router, ai.router,
               notifications.router, maps.router, storage.router, monitoring.router,
               audit.router, settings_router.router, health.router):
    app.include_router(router, prefix="/api")


@app.websocket("/api/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive côté client
    except WebSocketDisconnect:
        manager.disconnect(ws)
