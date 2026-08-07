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
from starlette.middleware.trustedhost import TrustedHostMiddleware

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
from routes.workflows import workflows_router
from routes.timeline import timeline_router
from routes.welcome import welcome_router
from routes.site_manager import site_manager_router
from routes.security import security_router
from routes.tls import tls_router
from routes.camera_control import camera_control_router
from routes.devices import devices_router
from routes.vehicles import vehicles_router
from routes.smart_search import smart_search_router
from routes.discovery import discovery_router
from wsdl_path import validate_wsdl_dir

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("mg-vms")

# ─── Validation WSDL au démarrage ─────────────────────────────────────
# Vérifie que les fichiers WSDL essentiels ONVIF sont présents dans
# backend/wsdl/ pour rendre la découverte ONVIF opérationnelle sans
# dépendre du package Python (voir wsdl_path.py).
_wsdl_status = validate_wsdl_dir()

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
app.include_router(plugin_config_router)  # ordre : AVANT plugins_bus_router pour éviter la collision avec /api/plugins/{name}/config
app.include_router(plugins_bus_router)
app.include_router(health_dashboard_router)
app.include_router(dashboard_router)
app.include_router(audit_router)
app.include_router(users_router)
app.include_router(database_router)
app.include_router(smart_zones_router)
app.include_router(workflows_router)
app.include_router(timeline_router)
app.include_router(camera_control_router)
app.include_router(devices_router)
app.include_router(vehicles_router)
app.include_router(smart_search_router)
app.include_router(discovery_router)
app.include_router(api_router)
app.include_router(notif_router)
app.include_router(realtime_router)
app.include_router(plugins_router)
app.include_router(storage_router)
app.include_router(network_router)
app.include_router(reports_router)
app.include_router(hardware_router)
app.include_router(welcome_router)
app.include_router(site_manager_router)
app.include_router(security_router)
app.include_router(tls_router)   # v0.7.f · Wave G · sous-menu HTTPS/TLS

app.add_middleware(SecurityMiddleware)

# v0.5.1.b · TrustedHost — bloque les requêtes avec Host header inconnu
# (protection contre l'usurpation de Host, obligatoire derrière un reverse proxy).
# En dev : "*" par défaut. En prod : configurer MGVMS_TRUSTED_HOSTS=vms.exemple.com.
_trusted = [h.strip() for h in os.environ.get("MGVMS_TRUSTED_HOSTS", "*").split(",") if h.strip()]
if _trusted and _trusted != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted)

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
    # ─── v0.4 · Boot info : versions Torch/CUDA/GPU + WSDL ────────────────
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
        gpu_line = "aucun (mode CPU)"
        gpu_mem = ""
        if cuda_ok:
            try:
                gpu_line = torch.cuda.get_device_name(0)
                props = torch.cuda.get_device_properties(0)
                gpu_mem = f" · {props.total_memory / (1024**3):.1f} GB"
            except Exception:
                pass
        try:
            import torchvision
            tv = torchvision.__version__
        except Exception:
            tv = "n/a"
        logger.info(
            "GPU · Torch=%s TorchVision=%s CUDA=%s (v%s) · Device=%s%s",
            torch.__version__, tv,
            "OK" if cuda_ok else "INDISPONIBLE",
            torch.version.cuda or "n/a",
            gpu_line, gpu_mem,
        )
    except Exception as e:
        logger.warning("GPU · impossible de logger l'état Torch/CUDA : %s", e)

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
    # v0.7.h · Wave I · Axe QoS · Surveillance permanente + alertes Ops Center
    from pipeline_v2.qos_alerts import qos_watcher_loop
    asyncio.create_task(qos_watcher_loop())
    # v0.8-rc7 · Sprint 4 P4 · Stability Watcher 72 h (minute-par-minute)
    from pipeline_v2.stability_watcher import watcher as _stability_watcher
    _stability_watcher.start()
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


# ═════════════════════════════════════════════════════════════════
# Healthcheck ultra-léger pour Docker / Kubernetes probes.
# STRICTEMENT : aucune dépendance externe (Mongo, go2rtc, GPU, Pipeline).
# Réponse < 5 ms garanti. Le diagnostic complet reste dans /api/system-health.
# ═════════════════════════════════════════════════════════════════
@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
