from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
os.environ["PATH"] = "/app/bin:" + os.environ.get("PATH", "")  # ffmpeg statique persistant
import asyncio
import logging
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from database import create_indexes
from auth import auth_router
from routers import api_router
from notifications import notif_router
from realtime import realtime_router, metrics_broadcaster
from plugins import plugins_router, seed_plugins
from plugin_config import plugin_config_router
from storage import storage_router
from network import network_router, network_poll_broadcaster
from reports import reports_router
from hardware import hardware_router, seed_hardware
from security import SecurityMiddleware
from streaming import stream_router, sync_all_streams, camera_status_loop
from recorder import recorder_loop, stop_all_recorders, sweep_orphan_recorders
from ai_engine import ai_loop
from seed import seed
from routes.plugins_bus import plugins_bus_router
from routes.health_dashboard import health_dashboard_router
from routes.dashboard import dashboard_router
from routes.audit import audit_router
from routes.users import users_router
from routes.public_status import public_router
from routes.database_settings import database_router
from routes.smart_zones import smart_zones_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("mg-vms")

app = FastAPI(title="MG-VMS API", version="2.30.0-preview-ng", description="MG-VMS - Plateforme de vidéosurveillance professionnelle")

# ─── Middleware de compat versioning (ADR-08 · roadmap v2.30 chantier D) ──
# Objectif : préparer la cible v3.0 où toutes les URLs seront préfixées `/api/v1/*`.
# En v2.30 (Preview NG) : le backend accepte les DEUX préfixes en parallèle
# (`/api/*` legacy + `/api/v1/*` cible), sans dupliquer les routes. Un middleware
# léger réécrit `/api/v1/...` → `/api/...` en amont du routing. Émet un header
# `X-API-Version-Alias` pour tracer l'usage. Compat 24 mois (chapitre 27).
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as _Response

class ApiVersionAliasMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        original_path = request.scope.get("path", "")
        if original_path.startswith("/api/v1/"):
            # Réécrit le path pour que les routers `/api/*` matchent
            request.scope["path"] = "/api/" + original_path[len("/api/v1/"):]
            request.scope["raw_path"] = request.scope["path"].encode()
            response: _Response = await call_next(request)
            response.headers["X-API-Version-Alias"] = "v1"
            return response
        return await call_next(request)

app.add_middleware(ApiVersionAliasMiddleware)

app.include_router(auth_router)
app.include_router(public_router)
app.include_router(stream_router)
app.include_router(plugins_bus_router)
app.include_router(health_dashboard_router)
app.include_router(dashboard_router)
app.include_router(audit_router)
app.include_router(users_router)
app.include_router(database_router)
app.include_router(smart_zones_router)
app.include_router(api_router)
app.include_router(notif_router)
app.include_router(realtime_router)
app.include_router(plugins_router)
app.include_router(plugin_config_router)
app.include_router(storage_router)
app.include_router(network_router)
app.include_router(reports_router)
app.include_router(hardware_router)

app.add_middleware(SecurityMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)


@app.on_event("startup")
async def on_startup():
    await create_indexes()
    await seed()
    await seed_hardware()
    await seed_plugins()
    await sweep_orphan_recorders()
    # Bootstrap Plugin Manager NG : enregistre les plugins bundle sur le bus
    from plugin_manager.bootstrap import bootstrap_bundle
    await bootstrap_bundle()
    # Re-hydrate le journal lifecycle depuis MongoDB (survit aux redémarrages backend)
    from lifecycle import hydrate_journal_from_db
    await hydrate_journal_from_db()
    asyncio.create_task(metrics_broadcaster())
    asyncio.create_task(network_poll_broadcaster())
    asyncio.create_task(sync_all_streams())
    asyncio.create_task(camera_status_loop())
    asyncio.create_task(recorder_loop())
    asyncio.create_task(ai_loop())
    logger.info("MG-VMS API démarré - données initialisées + broadcaster temps réel actif")


@app.on_event("shutdown")
async def on_shutdown():
    await stop_all_recorders()
    # Arrêt propre des workers ffmpeg-CUDA persistants (frame_source)
    try:
        from frame_source import stop_all as _fs_stop_all
        _fs_stop_all()
    except Exception:
        pass
    logger.info("MG-VMS API arrêté — enregistreurs ffmpeg + workers IA terminés")


@app.get("/api/")
async def root():
    return {"app": "MG-VMS", "status": "ok"}
