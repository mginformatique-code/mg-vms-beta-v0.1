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
from realtime import realtime_router, metrics_broadcaster, redis_bridge_loop
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
from routes.pipeline_diagnostic import pipeline_diag_router
# video-engine-v3 · legacy routes SUPPRIMÉES : go2rtc_diagnostic, mjpeg_direct, video
from routes.public_status import public_router
from routes.database_settings import database_router
from routes.license import license_router
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
from routes.llm_settings import llm_settings_router
from routes.discovery import discovery_router
from routes.system_admin import system_admin_router, auto_reboot_loop, ntp_resync_loop
from routes.console_ssh import console_router
from routes.live_layout import live_layout_router
from routes.vehicle_dedup import vehicle_dedup_router, dedup_batch_loop
from routes.anpr_tuning import anpr_tuning_router, anpr_tuning_loop
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
#
# v3.4 · ASGI pur, PAS BaseHTTPMiddleware : appliqué à CHAQUE requête (y
# compris les 99% qui ne sont pas /api/v1/*), `call_next()` bufferise/rewrap
# la réponse et casse le support natif des Range/206 de `FileResponse` —
# root cause confirmée du rechargement complet répété des vidéos
# d'événements (`/api/recordings/{id}/media`). Une réécriture ASGI directe
# du scope ne touche jamais au corps de la réponse pour les requêtes qui ne
# matchent pas /api/v1/*, donc aucun impact sur Range ailleurs.
from starlette.datastructures import MutableHeaders

class ApiVersionAliasMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/v1/"):
            return await self.app(scope, receive, send)

        scope = dict(scope)
        original_path = scope["path"]
        scope["path"] = "/api/" + original_path[len("/api/v1/"):]
        scope["raw_path"] = scope["path"].encode()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-API-Version-Alias"] = "v1"
            await send(message)

        await self.app(scope, receive, send_wrapper)

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
app.include_router(license_router)
app.include_router(smart_zones_router)
app.include_router(workflows_router)
app.include_router(timeline_router)
app.include_router(camera_control_router)
app.include_router(devices_router)
app.include_router(pipeline_diag_router)  # v1.0-rc4 · diagnostic pipeline vidéo multi-étages
# video-engine-v3 · legacy routes SUPPRIMÉES (go2rtc_diag, mjpeg_direct, /api/video/*)
from routes.camera_api import camera_api_router
app.include_router(camera_api_router)   # camera-api-v2.2 · HTTP/HTTPS layer (Reolink+)
from routes.live_v3 import live_v3_router
app.include_router(live_v3_router)   # video-engine-v3 · RTSP-native + aiortc WHEP
app.include_router(vehicles_router)
app.include_router(smart_search_router)
app.include_router(llm_settings_router)
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
app.include_router(system_admin_router)  # v3.19 · Paramètres système (date/heure, reboot)
app.include_router(console_router)  # v3.22 · Console shell hôte (Debug), admin uniquement
app.include_router(live_layout_router)  # v3.22 · Disposition personnalisée du Mur vidéo
app.include_router(vehicle_dedup_router)  # v3.20 · Doublons véhicule assistés par Qwen
app.include_router(anpr_tuning_router)  # v3.20 · Seuil confiance ANPR auto-réglé par Qwen

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
    # video-engine-v3 : migration & auto-start du Video Core RTSP-native
    # (les anciennes migrations pipeline v2 + MediaMTX sont supprimées)
    asyncio.create_task(metrics_broadcaster())
    asyncio.create_task(network_poll_broadcaster())
    # v3.22 · Chantier séparation pipeline IA / serveur API — pont Redis
    # pub/sub -> WebSocket local (voir realtime.py::redis_bridge_loop).
    asyncio.create_task(redis_bridge_loop())
    # video-engine-v3 · sync_all_streams (go2rtc) supprimé
    asyncio.create_task(camera_status_loop())
    asyncio.create_task(recorder_loop())
    asyncio.create_task(ai_loop())
    # v0.7.h · Wave I · Axe QoS · Surveillance permanente + alertes Ops Center
    from pipeline_v2.qos_alerts import qos_watcher_loop
    asyncio.create_task(qos_watcher_loop())
    # v0.8-rc7 · Sprint 4 P4 · Stability Watcher 72 h (minute-par-minute)
    from pipeline_v2.stability_watcher import watcher as _stability_watcher
    _stability_watcher.start()
    # v3.24 · Chantier séparation pipeline IA / serveur API, étape 2b —
    # snapshot Redis consolidé de l'état runtime pipeline (catégorie b),
    # lu côté API par les endpoints diagnostics via pipeline_snapshot.get_snapshot()
    # (voir routes/health_dashboard.py, routers.py). Démarré ici comme les
    # autres boucles background pipeline-adjacentes ci-dessus.
    from pipeline_snapshot import snapshot_loop
    asyncio.create_task(snapshot_loop())
    # v3.25 · Chantier séparation pipeline IA / serveur API, étape 2c —
    # consommateur de commandes Redis côté pipeline (catégorie c :
    # écriture/commande), voir pipeline_commands.py. Démarré ici comme
    # snapshot_loop() juste au-dessus (même chantier, même boundary).
    from pipeline_commands import command_loop
    asyncio.create_task(command_loop())
    asyncio.create_task(auto_reboot_loop())
    asyncio.create_task(ntp_resync_loop())
    asyncio.create_task(dedup_batch_loop())
    asyncio.create_task(anpr_tuning_loop())
    logger.info("MG-VMS API démarré - données initialisées + broadcaster temps réel actif")
    # v3.1.7 · SUPPRIMÉ : l'auto-start `VideoCoreManager.ensure_camera()` pour
    # chaque caméra ici ouvrait une 2e connexion RTSP DIRECTE vers la caméra
    # (PyAV, indépendante de go2rtc) sans jamais avoir le moindre consommateur
    # — `subscribe_packets()` n'est appelé nulle part avec le camera_id brut,
    # seul `webrtc_gateway` consomme la source `{camera_id}::webrtc`, créée à
    # la demande par `ensure_webrtc_source()` quand un viewer WHEP se connecte
    # réellement (routes/live_v3.py, webrtc_gateway). Reliquat de l'ancienne
    # architecture "video-engine-v3 WHEP-only" (voir CHANGELOG). Sur des
    # caméras Reolink qui limitent leurs connexions RTSP concurrentes, cette
    # connexion fantôme entrait en contention avec la connexion de go2rtc —
    # cause racine confirmée des 500 intermittents sur go2rtc `frame.jpeg`,
    # des redémarrages `frame_source` et des coupures d'enregistrement.


@app.on_event("shutdown")
async def on_shutdown():
    # video-engine-v3 · fermeture propre du Video Core + WebRTC gateway
    try:
        from webrtc_gateway import shutdown_all as _webrtc_shutdown
        await _webrtc_shutdown()
        from video_core import VideoCoreManager as _VCM
        _vcm = _VCM.instance()
        for _cid in list(_vcm.list_cameras()):
            await _vcm.stop_camera(_cid)
    except Exception:
        logger.exception("video-engine-v3 shutdown erreur (non bloquant)")
    await stop_all_recorders()
    # Arrêt propre des workers ffmpeg-CUDA persistants (frame_source)
    try:
        from frame_source import stop_all as _fs_stop_all
        _fs_stop_all()
    except Exception:
        pass
    # video-engine-v3 : brokers MJPEG partagés supprimés
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
