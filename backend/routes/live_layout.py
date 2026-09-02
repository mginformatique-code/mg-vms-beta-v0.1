"""v3.22 · Disposition personnalisée du Mur vidéo (Live).

Demande explicite (02/09) : pouvoir choisir quelles caméras apparaissent
dans quel ordre pour une taille de grille donnée (4, 9, ...), et que ce
choix survive à un `upgrade.sh` — donc en base (Mongo), jamais dans un
fichier local ou le localStorage seul (qui ne partage rien entre postes
et ne survivrait pas à un changement de navigateur).

Portée volontairement simple : une disposition GLOBALE par taille de
grille (pas par utilisateur) — cohérent avec le reste des réglages MG-VMS
(ntp_upstream, llm_config, auto_reboot...), tous stockés de la même
façon dans `db.settings`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_permission, require_role, log_audit
from database import db

live_layout_router = APIRouter(prefix="/api/live/layout", tags=["live-layout"])

_ALLOWED_SIZES = (1, 4, 9, 16, 25, 36, 49, 64)  # doit rester synchro avec LAYOUTS (frontend LiveView.jsx)


def _key(size: int) -> str:
    return f"live_layout_{size}"


@live_layout_router.get("/{size}")
async def get_layout(size: int, user: dict = Depends(require_permission("view_live"))):
    if size not in _ALLOWED_SIZES:
        raise HTTPException(400, "Taille de grille invalide")
    doc = await db.settings.find_one({"key": _key(size)}, {"_id": 0})
    return {"size": size, "camera_ids": (doc or {}).get("value", {}).get("camera_ids") or []}


class LiveLayoutIn(BaseModel):
    camera_ids: list[str] = []


@live_layout_router.put("/{size}")
async def put_layout(size: int, data: LiveLayoutIn, user: dict = Depends(require_role("technician"))):
    if size not in _ALLOWED_SIZES:
        raise HTTPException(400, "Taille de grille invalide")
    value = {"camera_ids": data.camera_ids}
    await db.settings.update_one({"key": _key(size)}, {"$set": {"key": _key(size), "value": value}}, upsert=True)
    await log_audit(user, "live_layout_updated", f"taille={size}, {len(data.camera_ids)} caméra(s)")
    return {"size": size, "camera_ids": data.camera_ids}
