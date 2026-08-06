"""Route module — Map Center / Site Manager (v0.5.2 · Phase 1).

Hiérarchie : Client → Site → Bâtiment → Niveau → Plan → Caméras → Zones.

Modèle de données (Mongo) :

  - `sites` (existante, enrichie côté application via champs
    `client_name`, `phone`, `contact_name`, `notes` — pas de migration
    destructrice, tout est optionnel).

  - `buildings` (nouvelle) — un bâtiment appartient à un site.
      { id, site_id, name, order, notes }

  - `site_plans` (nouvelle) — un plan appartient à un site (et
    optionnellement à un bâtiment + niveau).
      { id, site_id, building_id?, level_name?, name, type,
        image_data_uri, scale_m_per_px?, orientation_deg?, unit,
        order }
    `type` ∈ {"satellite", "rdc", "etage", "parking", "entrepot",
              "exterieur", "drone", "autre"}

  - `cameras` (existante) — extension `map_position` (dict) :
      { plan_id, x, y, rotation, height_m, angle_h, angle_v,
        range_m, color, fixture, lens_mm,
        install_notes, technician, serial, install_date,
        real_height_m, real_angle, install_direction }
    Toutes ces clés sont optionnelles — un nil-plan ⇒ caméra
    non positionnée.

Endpoints (préfixe `/api/site-manager/`) :

  - Bâtiments   : GET / POST / PUT / DELETE `/buildings`
  - Plans       : GET / POST / PUT / DELETE `/plans`
  - Caméras map : GET `/cameras`, PUT `/cameras/{id}/position`

Design évolutif : la couche `site_plans.overlays` (préparée sans
endpoint pour l'instant) pourra héberger câbles, switches, NVR, baies,
Wi-Fi, portes, zones d'intrusion sans refactor Phase 1.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import allowed_sites, get_current_user, require_role
from database import db

site_manager_router = APIRouter(prefix="/api/site-manager", tags=["site-manager"])


# ═══════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════

class BuildingInput(BaseModel):
    site_id: str
    name: str = Field(..., min_length=1, max_length=120)
    order: int = 0
    notes: Optional[str] = None


class BuildingPatch(BaseModel):
    name: Optional[str] = None
    order: Optional[int] = None
    notes: Optional[str] = None


class PlanInput(BaseModel):
    site_id: str
    building_id: Optional[str] = None
    level_name: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=120)
    type: str = Field("autre",
                       pattern="^(satellite|rdc|etage|parking|entrepot|exterieur|drone|autre)$")
    # data URI complet (data:image/png;base64,....) — validation par taille.
    image_data_uri: str
    scale_m_per_px: Optional[float] = None
    orientation_deg: Optional[float] = None
    unit: str = "m"
    order: int = 0
    width: Optional[int] = None
    height: Optional[int] = None


class PlanPatch(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    scale_m_per_px: Optional[float] = None
    orientation_deg: Optional[float] = None
    unit: Optional[str] = None
    order: Optional[int] = None
    building_id: Optional[str] = None
    level_name: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class MapPositionInput(BaseModel):
    plan_id: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    rotation: Optional[float] = None
    height_m: Optional[float] = None
    angle_h: Optional[float] = None
    angle_v: Optional[float] = None
    range_m: Optional[float] = None
    color: Optional[str] = None
    fixture: Optional[str] = None  # wall | ceiling | pole
    lens_mm: Optional[float] = None
    install_notes: Optional[str] = None
    technician: Optional[str] = None
    serial: Optional[str] = None
    install_date: Optional[str] = None
    real_height_m: Optional[float] = None
    real_angle: Optional[float] = None
    install_direction: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _scope(user: dict) -> dict:
    """Retourne un filtre `{site_id: {$in: [...]}}` ou `{}` pour admin/tech."""
    sites = allowed_sites(user)
    if sites is None:
        return {}
    return {"site_id": {"$in": sites}}


async def _assert_site_access(site_id: str, user: dict):
    sites = allowed_sites(user)
    if sites is not None and site_id not in sites:
        raise HTTPException(status_code=403, detail="Accès refusé sur ce site")


# ═══════════════════════════════════════════════════════════════════
# Buildings
# ═══════════════════════════════════════════════════════════════════

@site_manager_router.get("/buildings")
async def list_buildings(
    site_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    q = _scope(user)
    if site_id:
        await _assert_site_access(site_id, user)
        q["site_id"] = site_id
    docs = await db.buildings.find(q, {"_id": 0}).sort("order", 1).to_list(500)
    return docs


@site_manager_router.post("/buildings")
async def create_building(
    payload: BuildingInput,
    user: dict = Depends(require_role("technician")),
):
    await _assert_site_access(payload.site_id, user)
    doc = {
        "id": str(uuid.uuid4()),
        "site_id": payload.site_id,
        "name": payload.name.strip(),
        "order": payload.order,
        "notes": (payload.notes or "").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.buildings.insert_one(doc)
    doc.pop("_id", None)
    return doc


@site_manager_router.put("/buildings/{building_id}")
async def update_building(
    building_id: str,
    patch: BuildingPatch,
    user: dict = Depends(require_role("technician")),
):
    existing = await db.buildings.find_one({"id": building_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Bâtiment introuvable")
    await _assert_site_access(existing["site_id"], user)
    update = {k: v for k, v in patch.model_dump(exclude_none=True).items()}
    if update:
        await db.buildings.update_one({"id": building_id}, {"$set": update})
    doc = await db.buildings.find_one({"id": building_id}, {"_id": 0})
    return doc


@site_manager_router.delete("/buildings/{building_id}")
async def delete_building(
    building_id: str,
    user: dict = Depends(require_role("technician")),
):
    existing = await db.buildings.find_one({"id": building_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Bâtiment introuvable")
    await _assert_site_access(existing["site_id"], user)
    await db.buildings.delete_one({"id": building_id})
    # Détache les plans (garde-fou) et retire building_id sans les supprimer
    await db.site_plans.update_many(
        {"building_id": building_id},
        {"$set": {"building_id": None, "level_name": None}},
    )
    return {"ok": True, "deleted": building_id}


# ═══════════════════════════════════════════════════════════════════
# Plans
# ═══════════════════════════════════════════════════════════════════

@site_manager_router.get("/plans")
async def list_plans(
    site_id: Optional[str] = None,
    building_id: Optional[str] = None,
    include_image: bool = False,
    user: dict = Depends(get_current_user),
):
    q = _scope(user)
    if site_id:
        await _assert_site_access(site_id, user)
        q["site_id"] = site_id
    if building_id:
        q["building_id"] = building_id
    proj = {"_id": 0}
    if not include_image:
        proj["image_data_uri"] = 0
    docs = await db.site_plans.find(q, proj).sort("order", 1).to_list(500)
    return docs


@site_manager_router.get("/plans/{plan_id}")
async def get_plan(plan_id: str, user: dict = Depends(get_current_user)):
    doc = await db.site_plans.find_one({"id": plan_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Plan introuvable")
    await _assert_site_access(doc["site_id"], user)
    return doc


@site_manager_router.post("/plans")
async def create_plan(
    payload: PlanInput,
    user: dict = Depends(require_role("technician")),
):
    await _assert_site_access(payload.site_id, user)
    # Validation image_data_uri : préfixe + taille max ~20 MB base64
    uri = payload.image_data_uri
    if not uri.startswith("data:image/") and not uri.startswith("data:application/pdf"):
        raise HTTPException(status_code=400, detail="image_data_uri invalide")
    if len(uri) > 30_000_000:
        raise HTTPException(status_code=413, detail="Image trop grande (max 22MB)")
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.site_plans.insert_one(doc)
    doc.pop("_id", None)
    return doc


@site_manager_router.put("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    patch: PlanPatch,
    user: dict = Depends(require_role("technician")),
):
    existing = await db.site_plans.find_one({"id": plan_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Plan introuvable")
    await _assert_site_access(existing["site_id"], user)
    update = {k: v for k, v in patch.model_dump(exclude_none=True).items()}
    if update:
        await db.site_plans.update_one({"id": plan_id}, {"$set": update})
    doc = await db.site_plans.find_one({"id": plan_id}, {"_id": 0})
    doc.pop("image_data_uri", None)
    return doc


@site_manager_router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: str,
    user: dict = Depends(require_role("technician")),
):
    existing = await db.site_plans.find_one({"id": plan_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Plan introuvable")
    await _assert_site_access(existing["site_id"], user)
    await db.site_plans.delete_one({"id": plan_id})
    # Désassocier les caméras positionnées sur ce plan
    await db.cameras.update_many(
        {"map_position.plan_id": plan_id},
        {"$unset": {"map_position": ""}},
    )
    return {"ok": True, "deleted": plan_id}


# ═══════════════════════════════════════════════════════════════════
# Camera map positions
# ═══════════════════════════════════════════════════════════════════

@site_manager_router.get("/cameras")
async def list_cameras_map(
    plan_id: Optional[str] = None,
    site_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Renvoie les caméras (position + infos essentielles) pour le canvas."""
    q = _scope(user)
    if site_id:
        await _assert_site_access(site_id, user)
        q["site_id"] = site_id
    if plan_id:
        q["map_position.plan_id"] = plan_id
    proj = {
        "_id": 0, "id": 1, "name": 1, "ip": 1, "brand": 1, "model": 1,
        "driver": 1, "site_id": 1, "site_name": 1, "status": 1,
        "map_position": 1, "enabled_plugins": 1, "detect_enabled": 1,
        "record_enabled": 1, "last_seen_at": 1, "mac": 1, "firmware": 1,
    }
    docs = await db.cameras.find(q, proj).to_list(1000)
    return docs


@site_manager_router.put("/cameras/{camera_id}/position")
async def update_camera_position(
    camera_id: str,
    payload: MapPositionInput,
    user: dict = Depends(require_role("technician")),
):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "site_id": 1, "map_position": 1})
    if not cam:
        raise HTTPException(status_code=404, detail="Caméra introuvable")
    await _assert_site_access(cam["site_id"], user)
    existing = cam.get("map_position") or {}
    patch = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not patch:
        return {"ok": True, "map_position": existing}
    merged = {**existing, **patch}
    await db.cameras.update_one(
        {"id": camera_id}, {"$set": {"map_position": merged}}
    )
    return {"ok": True, "map_position": merged}


@site_manager_router.delete("/cameras/{camera_id}/position")
async def clear_camera_position(
    camera_id: str,
    user: dict = Depends(require_role("technician")),
):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "site_id": 1})
    if not cam:
        raise HTTPException(status_code=404, detail="Caméra introuvable")
    await _assert_site_access(cam["site_id"], user)
    await db.cameras.update_one({"id": camera_id}, {"$unset": {"map_position": ""}})
    return {"ok": True, "cleared": camera_id}
