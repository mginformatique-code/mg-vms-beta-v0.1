from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
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
from security import SecurityMiddleware
from seed import seed, seed_recordings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("mg-vms")

app = FastAPI(title="MG-VMS API", version="1.0.0", description="MG-VMS - Plateforme de vidéosurveillance professionnelle")

app.include_router(auth_router)
app.include_router(api_router)
app.include_router(notif_router)
app.include_router(realtime_router)
app.include_router(plugins_router)

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
    await seed_recordings()
    await seed_plugins()
    asyncio.create_task(metrics_broadcaster())
    logger.info("MG-VMS API démarré - données initialisées + broadcaster temps réel actif")


@app.get("/api/")
async def root():
    return {"app": "MG-VMS", "status": "ok"}
