"""Route module — Public status (unauthenticated, minimal info for login page).

Expose des chiffres agrégés uniquement — jamais de noms de caméras, de sites,
ou d'infos sensibles. But : afficher un badge de santé sur la page de login.
"""
from fastapi import APIRouter

from database import db

public_router = APIRouter(prefix="/api", tags=["public"])


@public_router.get("/system/public-status")
async def public_status():
    """Retourne un snapshot public agrégé pour l'écran de login.

    - `cameras_online` : nombre de caméras dont `status == "online"`
    - `anpr_active` : au moins un plugin ANPR est dispatchable
    - `ai_engine` : au moins un FrameAnalyzer est dispatchable
    """
    try:
        online = await db.cameras.count_documents({"status": "online"})
    except Exception:
        online = 0

    anpr_active = False
    ai_engine = False
    try:
        from plugin_manager.bus import bus
        anpr_active = any(e.is_dispatchable() for e in bus.list_entries("PlateRecognizer"))
        ai_engine = any(e.is_dispatchable() for e in bus.list_entries("FrameAnalyzer"))
    except Exception:
        pass

    return {
        "cameras_online": int(online),
        "anpr_active": bool(anpr_active),
        "ai_engine": bool(ai_engine),
    }
