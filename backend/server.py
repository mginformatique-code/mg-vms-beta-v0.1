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
from network import network_router, network_poll_broadcaster
from reports import reports_router
from hardware import hardware_router, seed_hardware
from security import SecurityMiddleware
from streaming import stream_router, sync_all_streams, camera_status_loop
from recorder import recorder_loop, stop_all_recorders
from ai_engine import ai_loop
from seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("mg-vms")

app = FastAPI(title="MG-VMS API", version="1.0.0", description="MG-VMS - Plateforme de vidéosurveillance professionnelle")

app.include_router(auth_router)
app.include_router(api_router)
app.include_router(notif_router)
app.include_router(realtime_router)
app.include_router(plugins_router)
app.include_router(network_router)
app.include_router(reports_router)
app.include_router(hardware_router)
app.include_router(stream_router)

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
    logger.info("MG-VMS API arrêté — enregistreurs ffmpeg terminés")


@app.get("/api/")
async def root():
    return {"app": "MG-VMS", "status": "ok"}
