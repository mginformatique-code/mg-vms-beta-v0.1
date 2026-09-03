"""MG-VMS — Configuration RÉELLE des plugins (production).

Endpoints CRUD et paramétrage pour chaque plugin :
- ANPR : config globale (pays, taille plaque, cache) + config par caméra (ROI polygone, listes)
- Tracking (ByteTrack) : thresholds + persistance des IDs
- Face Recognition : base de visages + seuils
- Parking : zones polygonales + capacité par zone
- Access Control : contrôleurs (nom, IP, protocole)
- Thermal / Radar / Drone : ajout manuel d'un capteur matériel

Aucune donnée fictive : ce que l'admin saisit est le seul contenu réel.
"""
import uuid
import io
import csv
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field

from database import db
from auth import get_current_user, require_role, log_audit

plugin_config_router = APIRouter(prefix="/api/plugins", tags=["plugin-config"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# ANPR — Configuration globale + par caméra (ROI polygone, listes)
# ═══════════════════════════════════════════════════════════════════
class AnprGlobalConfig(BaseModel):
    country: str = "fr"  # fr, de, it, es, be, nl, uk, us, eu, other
    min_plate_px: int = 24
    max_plate_px: int = 400
    ocr_confidence: float = 0.55
    cache_seconds: int = 8
    alert_on_blacklist: bool = True
    alert_on_unknown: bool = False  # alerter si plaque inconnue (ni whitelist ni blacklist)


class AnprCameraConfig(BaseModel):
    enabled: bool = True
    roi_polygon: List[List[float]] = Field(default_factory=list)  # points normalisés [[x, y], ...] 0-1
    country_override: str = ""  # vide = utilise la config globale
    whitelist_local: List[str] = Field(default_factory=list)  # plaques autorisées uniquement pour cette cam
    blacklist_local: List[str] = Field(default_factory=list)
    min_confidence: float = 0.5


@plugin_config_router.get("/anpr/config")
async def anpr_config_get(user: dict = Depends(get_current_user)):
    doc = await db.settings.find_one({"key": "anpr_config"}, {"_id": 0})
    val = (doc or {}).get("value", {}) or {}
    return AnprGlobalConfig(**val).model_dump()


@plugin_config_router.put("/anpr/config")
async def anpr_config_put(data: AnprGlobalConfig, user: dict = Depends(require_role("admin"))):
    await db.settings.update_one({"key": "anpr_config"},
                                 {"$set": {"key": "anpr_config", "value": data.model_dump()}}, upsert=True)
    await log_audit(user, "anpr_config_updated", details=str(data.country))
    return data.model_dump()


@plugin_config_router.get("/anpr/cameras/{camera_id}")
async def anpr_camera_get(camera_id: str, user: dict = Depends(get_current_user)):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "anpr_config": 1})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    val = cam.get("anpr_config") or {}
    return AnprCameraConfig(**val).model_dump()


@plugin_config_router.put("/anpr/cameras/{camera_id}")
async def anpr_camera_put(camera_id: str, data: AnprCameraConfig,
                          user: dict = Depends(require_role("technician"))):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "name": 1})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    # Validation polygone : au moins 3 points ou vide
    if data.roi_polygon and len(data.roi_polygon) < 3:
        raise HTTPException(400, "Un polygone ROI doit contenir au moins 3 points ou être vide")
    for pt in data.roi_polygon:
        if len(pt) != 2 or not all(0 <= v <= 1 for v in pt):
            raise HTTPException(400, "Les points du polygone doivent être normalisés entre 0 et 1")
    # Normalise les plaques (uppercase, sans espaces)
    data.whitelist_local = [p.upper().replace(" ", "") for p in data.whitelist_local if p.strip()]
    data.blacklist_local = [p.upper().replace(" ", "") for p in data.blacklist_local if p.strip()]
    await db.cameras.update_one({"id": camera_id},
                                {"$set": {"anpr_config": data.model_dump()}})
    # v0.7.e · Wave A : signal per-cam
    try:
        from ai_engine import signal_camera_config_changed
        signal_camera_config_changed(camera_id)
    except Exception:
        pass
    # v3.29 · Chantier séparation pipeline IA / serveur API — audit
    # complémentaire (au-delà du périmètre 2a-2d, limité aux 4 call sites
    # de routers.py) : l'appel direct ci-dessus mute un ai_engine
    # dormant une fois le pipeline dans son propre conteneur (v3.27) — le
    # vrai process pipeline n'était jamais notifié du changement de
    # config ANPR. Même pattern que routers.py (étape 2c) : publish
    # best-effort en plus de l'appel direct (conservé tel quel, garantie
    # zéro régression en mode monolith).
    try:
        from redis_bus import send_pipeline_signal
        await send_pipeline_signal("camera_config_changed", {"camera_id": camera_id})
    except Exception:
        pass  # best-effort — l'appel direct ci-dessus a déjà fait le travail
    await log_audit(user, "anpr_camera_config_updated", cam["name"],
                    f"ROI={len(data.roi_polygon)} pts · WL={len(data.whitelist_local)} · BL={len(data.blacklist_local)}")
    return data.model_dump()


@plugin_config_router.get("/anpr/cameras")
async def anpr_cameras_list(user: dict = Depends(get_current_user)):
    """Liste des caméras avec état ANPR (pour la page plugin)."""
    cams = await db.cameras.find({}, {"_id": 0, "id": 1, "name": 1, "site_name": 1,
                                       "detect_enabled": 1, "anpr_config": 1, "status": 1}).to_list(500)
    for c in cams:
        cfg = c.get("anpr_config") or {}
        c["anpr_enabled"] = bool(cfg.get("enabled", True)) and bool(c.get("detect_enabled"))
        c["roi_points"] = len(cfg.get("roi_polygon", []) or [])
        c["wl_count"] = len(cfg.get("whitelist_local", []) or [])
        c["bl_count"] = len(cfg.get("blacklist_local", []) or [])
        c.pop("anpr_config", None)
    return cams


# ═══════════════════════════════════════════════════════════════════
# Import / Export CSV — Watchlist globale + listes locales par caméra
# ═══════════════════════════════════════════════════════════════════
def _normalize_plate(raw: str) -> str:
    """Normalise une plaque : uppercase, sans espace, sans tirets superflus."""
    return (raw or "").upper().replace(" ", "").strip()


def _parse_csv_plates(content: bytes, default_list_type: Optional[str] = None) -> tuple:
    """Parse un CSV. Colonnes acceptées :
      - Ligne 1 = en-têtes optionnelles : `plate,list_type,reason` OU juste `plate`
      - Si list_type est absent : default_list_type est utilisé
    Retourne (rows, errors) : rows = list de dicts prêts à être insérés."""
    rows: list = []
    errors: list = []
    try:
        text = content.decode("utf-8-sig")  # tolère le BOM Excel
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except UnicodeDecodeError as exc:
            return [], [f"Encodage illisible : {exc}"]
    reader = csv.reader(io.StringIO(text))
    header = None
    for i, row in enumerate(reader):
        if not row or all(not (c or "").strip() for c in row):
            continue
        # Détecte l'en-tête
        if i == 0 and any(k in (row[0] or "").lower() for k in ("plate", "plaque", "immatriculation")):
            header = [c.strip().lower() for c in row]
            continue
        plate_raw = row[0] if row else ""
        plate = _normalize_plate(plate_raw)
        if not plate:
            errors.append(f"Ligne {i + 1} : plaque vide")
            continue
        list_type = default_list_type or ""
        reason = ""
        if header:
            idx = {name: n for n, name in enumerate(header)}
            if "list_type" in idx and idx["list_type"] < len(row):
                list_type = (row[idx["list_type"]] or "").strip().lower()
            elif "type" in idx and idx["type"] < len(row):
                list_type = (row[idx["type"]] or "").strip().lower()
            if "reason" in idx and idx["reason"] < len(row):
                reason = (row[idx["reason"]] or "").strip()
            elif "motif" in idx and idx["motif"] < len(row):
                reason = (row[idx["motif"]] or "").strip()
        else:
            if len(row) >= 2:
                list_type = (row[1] or "").strip().lower()
            if len(row) >= 3:
                reason = (row[2] or "").strip()
        list_type = list_type.replace("blanche", "white").replace("noire", "black")
        if list_type not in ("white", "black"):
            errors.append(f"Ligne {i + 1} ({plate}) : list_type invalide '{list_type}' (attendu 'white' ou 'black')")
            continue
        rows.append({"plate": plate, "list_type": list_type, "reason": reason})
    return rows, errors


@plugin_config_router.post("/anpr/watchlist/import")
async def anpr_watchlist_import(csv_file: UploadFile = File(...),
                                 default_list_type: Optional[str] = None,
                                 user: dict = Depends(require_role("technician"))):
    """Import CSV de la watchlist GLOBALE (upsert par plaque).
    Formats acceptés : `plate,list_type,reason` (ou `plate` seul + `default_list_type` en query)."""
    if not (csv_file.filename or "").lower().endswith((".csv", ".txt")):
        raise HTTPException(400, "Fichier CSV attendu (.csv)")
    content = await csv_file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(400, "Fichier trop volumineux (max 2 Mo)")
    rows, errors = _parse_csv_plates(content, default_list_type)
    if not rows:
        raise HTTPException(400, f"Aucune plaque valide dans le CSV. {'; '.join(errors[:3])}")
    now = datetime.now(timezone.utc).isoformat()
    inserted, updated = 0, 0
    for row in rows:
        existing = await db.watchlist.find_one({"plate": row["plate"]}, {"_id": 0, "id": 1})
        if existing:
            await db.watchlist.update_one({"id": existing["id"]},
                                           {"$set": {"list_type": row["list_type"],
                                                     "reason": row["reason"], "updated_at": now}})
            updated += 1
        else:
            await db.watchlist.insert_one({
                "id": str(uuid.uuid4()), "created_at": now,
                "plate": row["plate"], "list_type": row["list_type"], "reason": row["reason"],
                "imported_by": user.get("email"),
            })
            inserted += 1
        # Rétro-application : mise à jour du list_status des plaques déjà lues
        await db.plates.update_many({"plate": row["plate"]},
                                     {"$set": {"list_status": row["list_type"]}})
    await log_audit(user, "anpr_watchlist_imported",
                    csv_file.filename, f"inserted={inserted} updated={updated} errors={len(errors)}")
    return {"ok": True, "inserted": inserted, "updated": updated,
            "total": inserted + updated, "errors": errors[:20]}


@plugin_config_router.get("/anpr/watchlist/export")
async def anpr_watchlist_export(user: dict = Depends(get_current_user)):
    """Export CSV de la watchlist globale."""
    rows = await db.watchlist.find({}, {"_id": 0}).sort("plate", 1).to_list(10000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["plate", "list_type", "reason"])
    for r in rows:
        writer.writerow([r.get("plate", ""), r.get("list_type", ""), r.get("reason", "")])
    return Response(content=buf.getvalue(), media_type="text/csv",
                     headers={"Content-Disposition": 'attachment; filename="mgvms_watchlist.csv"'})


@plugin_config_router.post("/anpr/cameras/{camera_id}/lists/import")
async def anpr_camera_lists_import(camera_id: str,
                                    csv_file: UploadFile = File(...),
                                    target: str = "whitelist",  # "whitelist" ou "blacklist"
                                    user: dict = Depends(require_role("technician"))):
    """Import CSV des plaques dans la liste LOCALE (whitelist ou blacklist) d'une caméra.
    Format : une plaque par ligne. Les entrées existantes sont conservées (union)."""
    if target not in ("whitelist", "blacklist"):
        raise HTTPException(400, "target doit être 'whitelist' ou 'blacklist'")
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "name": 1, "anpr_config": 1})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    if not (csv_file.filename or "").lower().endswith((".csv", ".txt")):
        raise HTTPException(400, "Fichier CSV attendu")
    content = await csv_file.read()
    if len(content) > 512 * 1024:
        raise HTTPException(400, "Fichier trop volumineux (max 512 Ko)")
    # Parse en forçant le type (whitelist → 'white' pour compatibilité) — on n'utilise
    # que la 1re colonne, les autres champs sont ignorés
    default = "white" if target == "whitelist" else "black"
    rows, errors = _parse_csv_plates(content, default)
    plates = list({r["plate"] for r in rows})
    if not plates:
        raise HTTPException(400, f"Aucune plaque valide. {'; '.join(errors[:3])}")
    field = "whitelist_local" if target == "whitelist" else "blacklist_local"
    current = set((cam.get("anpr_config") or {}).get(field, []) or [])
    merged = sorted(current.union(plates))
    await db.cameras.update_one({"id": camera_id},
                                 {"$set": {f"anpr_config.{field}": merged}})
    added = len(merged) - len(current)
    await log_audit(user, "anpr_camera_list_imported", cam["name"],
                    f"target={target} added={added} total={len(merged)}")
    return {"ok": True, "target": target, "added": added,
            "total": len(merged), "errors": errors[:10]}


@plugin_config_router.get("/anpr/cameras/{camera_id}/lists/export")
async def anpr_camera_lists_export(camera_id: str,
                                    target: str = "whitelist",
                                    user: dict = Depends(get_current_user)):
    """Export CSV d'une liste locale (whitelist ou blacklist) d'une caméra."""
    if target not in ("whitelist", "blacklist"):
        raise HTTPException(400, "target invalide")
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "name": 1, "anpr_config": 1})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    field = "whitelist_local" if target == "whitelist" else "blacklist_local"
    plates = (cam.get("anpr_config") or {}).get(field, []) or []
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["plate"])
    for p in plates:
        writer.writerow([p])
    return Response(content=buf.getvalue(), media_type="text/csv",
                     headers={"Content-Disposition": f'attachment; filename="cam_{camera_id}_{target}.csv"'})


# ═══════════════════════════════════════════════════════════════════
# Tracking (ByteTrack)
# ═══════════════════════════════════════════════════════════════════
class ByteTrackConfig(BaseModel):
    enabled: bool = True
    track_thresh: float = 0.25  # 0.1-0.9 — bas = accepte plus de détections faibles pour maintenir l'ID
    match_thresh: float = 0.85  # 0.5-0.95 — haut = matching plus strict, moins de swap d'IDs
    track_buffer: int = 60  # frames avant perte d'ID (60 = ~30s à 2 FPS)
    min_box_area: int = 100  # pixels²
    id_persist_seconds: int = 120  # combien de temps garder un ID en mémoire après disparition


@plugin_config_router.get("/tracking/config")
async def tracking_config_get(user: dict = Depends(get_current_user)):
    doc = await db.settings.find_one({"key": "bytetrack_config"}, {"_id": 0})
    val = (doc or {}).get("value", {}) or {}
    return ByteTrackConfig(**val).model_dump()


@plugin_config_router.put("/tracking/config")
async def tracking_config_put(data: ByteTrackConfig, user: dict = Depends(require_role("admin"))):
    data.track_thresh = max(0.1, min(0.9, data.track_thresh))
    data.match_thresh = max(0.5, min(0.95, data.match_thresh))
    data.track_buffer = max(5, min(300, data.track_buffer))
    data.id_persist_seconds = max(5, min(600, data.id_persist_seconds))
    await db.settings.update_one({"key": "bytetrack_config"},
                                 {"$set": {"key": "bytetrack_config", "value": data.model_dump()}}, upsert=True)
    # v0.4 · Sync runtime — recharge immédiatement _bytetrack_cfg dans ai_engine
    # sinon le PUT met à jour la DB mais le pipeline continue avec l'ancienne
    # config (bug remonté par audit : "ByteTrack=False dans le monitoring").
    # v0.7.e · Wave A : plutôt qu'un appel synchrone + import cyclique on
    # POSE UN SIGNAL — la boucle IA rechargera au prochain cycle (défaut < 150ms).
    try:
        from ai_engine import signal_config_changed
        signal_config_changed()
    except Exception:
        pass
    # v3.29 · Chantier séparation pipeline IA / serveur API — audit
    # complémentaire (au-delà du périmètre 2a-2d) : même raison que le
    # site ANPR ci-dessus — ai_engine dormant côté conteneur API (v3.27),
    # le vrai pipeline ne rechargeait plus jamais _bytetrack_cfg sur un
    # PUT. Publish best-effort en plus de l'appel direct (conservé).
    try:
        from redis_bus import send_pipeline_signal
        await send_pipeline_signal("config_changed")
    except Exception:
        pass  # best-effort — l'appel direct ci-dessus a déjà fait le travail
    await log_audit(user, "bytetrack_config_updated",
                    f"enabled={data.enabled} thresh={data.track_thresh}")
    return data.model_dump()


# ═══════════════════════════════════════════════════════════════════
# Face Recognition
# ═══════════════════════════════════════════════════════════════════
class FaceRecoConfig(BaseModel):
    enabled: bool = False
    distance_threshold: float = 0.6  # plus bas = plus strict
    model_name: str = "hog"  # hog (CPU) ou cnn (GPU requis)
    alert_on_unknown: bool = False
    alert_on_watchlist: bool = True


class FaceEntry(BaseModel):
    name: str
    watchlist: bool = False
    notes: str = ""


@plugin_config_router.get("/face_recognition/config")
async def face_config_get(user: dict = Depends(get_current_user)):
    doc = await db.settings.find_one({"key": "face_recognition_config"}, {"_id": 0})
    return FaceRecoConfig(**((doc or {}).get("value", {}) or {})).model_dump()


@plugin_config_router.put("/face_recognition/config")
async def face_config_put(data: FaceRecoConfig, user: dict = Depends(require_role("admin"))):
    await db.settings.update_one({"key": "face_recognition_config"},
                                 {"$set": {"key": "face_recognition_config", "value": data.model_dump()}}, upsert=True)
    await log_audit(user, "face_config_updated", details=data.model_name)
    return data.model_dump()


@plugin_config_router.get("/face_recognition/faces")
async def face_list(user: dict = Depends(get_current_user)):
    return await db.faces.find({}, {"_id": 0, "encoding": 0}).sort("created_at", -1).to_list(1000)


@plugin_config_router.get("/face_recognition/availability")
async def face_availability(user: dict = Depends(get_current_user)):
    """Statut d'installation d'InsightFace + instructions d'installation."""
    from face_recognition_engine import availability
    return availability()


@plugin_config_router.post("/face_recognition/faces")
async def face_add(entry: FaceEntry, user: dict = Depends(require_role("technician"))):
    doc = {
        "id": str(uuid.uuid4()), "name": entry.name.strip(), "watchlist": entry.watchlist,
        "notes": entry.notes, "created_at": _now_iso(), "created_by": user.get("email"),
        "encoding": None, "thumbnail": None, "photo_meta": None,
    }
    if not doc["name"]:
        raise HTTPException(400, "Nom requis")
    await db.faces.insert_one(dict(doc))
    doc.pop("_id", None); doc.pop("encoding", None)
    await log_audit(user, "face_added", doc["name"])
    return doc


@plugin_config_router.post("/face_recognition/faces/{face_id}/photo")
async def face_upload_photo(face_id: str, photo: UploadFile = File(...),
                             user: dict = Depends(require_role("technician"))):
    """Upload une photo, extrait l'embedding via InsightFace et le persiste."""
    face = await db.faces.find_one({"id": face_id}, {"_id": 0})
    if not face:
        raise HTTPException(404, "Visage introuvable")
    if not (photo.content_type or "").startswith("image/"):
        raise HTTPException(400, "Le fichier doit être une image")
    content = await photo.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(400, "Photo trop volumineuse (max 8 Mo)")
    from face_recognition_engine import extract_embedding, image_to_thumbnail
    embedding, meta = extract_embedding(content)
    if embedding is None:
        raise HTTPException(400, meta.get("error", "Extraction échouée"))
    thumbnail = image_to_thumbnail(content)
    await db.faces.update_one({"id": face_id}, {"$set": {
        "encoding": embedding, "photo_meta": meta,
        "thumbnail": thumbnail, "photo_uploaded_at": _now_iso(),
    }})
    await log_audit(user, "face_photo_uploaded", face["name"],
                    f"det_score={meta.get('det_score', 0):.2f}")
    return {"ok": True, "name": face["name"], "meta": meta,
            "has_thumbnail": bool(thumbnail), "embedding_dim": len(embedding)}


@plugin_config_router.delete("/face_recognition/faces/{face_id}")
async def face_delete(face_id: str, user: dict = Depends(require_role("technician"))):
    f = await db.faces.find_one({"id": face_id}, {"_id": 0, "name": 1})
    if not f:
        raise HTTPException(404, "Visage introuvable")
    await db.faces.delete_one({"id": face_id})
    await log_audit(user, "face_removed", f["name"])
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════
# Parking — zones polygonales
# ═══════════════════════════════════════════════════════════════════
class ParkingZone(BaseModel):
    name: str
    camera_id: str
    site_id: str = ""
    polygon: List[List[float]] = Field(default_factory=list)  # normalisé 0-1
    capacity: int = 1
    occupied: int = 0


@plugin_config_router.get("/parking/zones")
async def parking_list(user: dict = Depends(get_current_user)):
    return await db.parking_zones.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)


@plugin_config_router.post("/parking/zones")
async def parking_create(zone: ParkingZone, user: dict = Depends(require_role("technician"))):
    if not zone.name.strip():
        raise HTTPException(400, "Nom requis")
    cam = await db.cameras.find_one({"id": zone.camera_id}, {"_id": 0, "name": 1, "site_id": 1, "site_name": 1})
    if not cam:
        raise HTTPException(400, "Caméra invalide")
    if len(zone.polygon) < 3:
        raise HTTPException(400, "Zone : au moins 3 points requis")
    doc = {
        "id": str(uuid.uuid4()), "created_at": _now_iso(),
        **zone.model_dump(),
        "site_id": cam.get("site_id", ""), "site_name": cam.get("site_name", ""),
        "camera_name": cam["name"], "occupied": 0,
    }
    await db.parking_zones.insert_one(dict(doc))
    doc.pop("_id", None)
    await log_audit(user, "parking_zone_created", zone.name)
    return doc


@plugin_config_router.put("/parking/zones/{zone_id}")
async def parking_update(zone_id: str, zone: ParkingZone, user: dict = Depends(require_role("technician"))):
    existing = await db.parking_zones.find_one({"id": zone_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Zone introuvable")
    if len(zone.polygon) < 3:
        raise HTTPException(400, "Zone : au moins 3 points requis")
    await db.parking_zones.update_one({"id": zone_id},
                                       {"$set": {k: v for k, v in zone.model_dump().items() if k != "occupied"}})
    updated = await db.parking_zones.find_one({"id": zone_id}, {"_id": 0})
    await log_audit(user, "parking_zone_updated", zone.name)
    return updated


@plugin_config_router.delete("/parking/zones/{zone_id}")
async def parking_delete(zone_id: str, user: dict = Depends(require_role("technician"))):
    z = await db.parking_zones.find_one({"id": zone_id}, {"_id": 0, "name": 1})
    if not z:
        raise HTTPException(404, "Zone introuvable")
    await db.parking_zones.delete_one({"id": zone_id})
    await log_audit(user, "parking_zone_removed", z["name"])
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════
# Access Control — contrôleurs (barrières, portes, lecteurs)
# ═══════════════════════════════════════════════════════════════════
class AccessController(BaseModel):
    name: str
    kind: str = "gate"  # gate | door | barrier | reader
    ip: str = ""
    port: int = 80
    protocol: str = "http"  # http | wiegand | osdp | mqtt
    site_id: str = ""
    linked_camera_id: str = ""
    notes: str = ""


@plugin_config_router.get("/access_control/controllers")
async def ac_list(user: dict = Depends(get_current_user)):
    return await db.access_controllers.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)


@plugin_config_router.post("/access_control/controllers")
async def ac_add(ctrl: AccessController, user: dict = Depends(require_role("technician"))):
    if not ctrl.name.strip():
        raise HTTPException(400, "Nom requis")
    doc = {"id": str(uuid.uuid4()), "created_at": _now_iso(), "status": "unknown", **ctrl.model_dump()}
    await db.access_controllers.insert_one(dict(doc))
    doc.pop("_id", None)
    await log_audit(user, "access_controller_added", ctrl.name)
    return doc


@plugin_config_router.put("/access_control/controllers/{ctrl_id}")
async def ac_update(ctrl_id: str, ctrl: AccessController, user: dict = Depends(require_role("technician"))):
    if not await db.access_controllers.find_one({"id": ctrl_id}, {"_id": 1}):
        raise HTTPException(404, "Contrôleur introuvable")
    await db.access_controllers.update_one({"id": ctrl_id}, {"$set": ctrl.model_dump()})
    updated = await db.access_controllers.find_one({"id": ctrl_id}, {"_id": 0})
    await log_audit(user, "access_controller_updated", ctrl.name)
    return updated


@plugin_config_router.delete("/access_control/controllers/{ctrl_id}")
async def ac_delete(ctrl_id: str, user: dict = Depends(require_role("technician"))):
    c = await db.access_controllers.find_one({"id": ctrl_id}, {"_id": 0, "name": 1})
    if not c:
        raise HTTPException(404, "Contrôleur introuvable")
    await db.access_controllers.delete_one({"id": ctrl_id})
    await log_audit(user, "access_controller_removed", c["name"])
    return {"ok": True}


@plugin_config_router.post("/access_control/controllers/{ctrl_id}/test")
async def ac_test(ctrl_id: str, user: dict = Depends(require_role("technician"))):
    """Test TCP réel du contrôleur (ping IP:port)."""
    c = await db.access_controllers.find_one({"id": ctrl_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Contrôleur introuvable")
    import socket
    try:
        with socket.create_connection((c["ip"], int(c.get("port", 80))), timeout=3):
            status = "online"
    except (OSError, ValueError):
        status = "offline"
    await db.access_controllers.update_one({"id": ctrl_id},
                                            {"$set": {"status": status, "last_check": _now_iso()}})
    return {"ip": c["ip"], "port": c.get("port"), "status": status}


# ═══════════════════════════════════════════════════════════════════
# Capteurs matériels manuels (Thermal / Radar / Drone)
# ═══════════════════════════════════════════════════════════════════
class SensorInput(BaseModel):
    name: str
    kind: str  # forcé dans l'endpoint (thermal|radar|drone)
    ip: str = ""
    port: int = 0
    protocol: str = "http"
    site_id: str = ""
    linked_camera_id: str = ""
    notes: str = ""


def _sensors_router(kind: str, coll_name: str):
    """Génère les endpoints CRUD pour un type de capteur matériel."""
    async def _list(user: dict = Depends(get_current_user)):
        return await db[coll_name].find({}, {"_id": 0}).sort("created_at", -1).to_list(500)

    async def _add(sensor: SensorInput, user: dict = Depends(require_role("technician"))):
        if not sensor.name.strip():
            raise HTTPException(400, "Nom requis")
        doc = {"id": str(uuid.uuid4()), "created_at": _now_iso(), "status": "unknown",
               **sensor.model_dump(), "kind": kind}
        await db[coll_name].insert_one(dict(doc))
        doc.pop("_id", None)
        await log_audit(user, f"{kind}_sensor_added", sensor.name)
        return doc

    async def _remove(sensor_id: str, user: dict = Depends(require_role("technician"))):
        s = await db[coll_name].find_one({"id": sensor_id}, {"_id": 0, "name": 1})
        if not s:
            raise HTTPException(404, "Capteur introuvable")
        await db[coll_name].delete_one({"id": sensor_id})
        await log_audit(user, f"{kind}_sensor_removed", s["name"])
        return {"ok": True}

    plugin_config_router.get(f"/{kind}/sensors")(_list)
    plugin_config_router.post(f"/{kind}/sensors")(_add)
    plugin_config_router.delete(f"/{kind}/sensors/{{sensor_id}}")(_remove)


_sensors_router("thermal", "thermal_sensors")
_sensors_router("radar", "radar_sensors")
_sensors_router("drone", "drones")


# ═══════════════════════════════════════════════════════════════════
# Snapshot d'une caméra (utilisé pour dessiner ROI / polygones dans l'UI)
# Route publique authentifiée qui délivre une image JPEG fraîche
# ═══════════════════════════════════════════════════════════════════
@plugin_config_router.get("/_helpers/camera-snapshot/{camera_id}")
async def helper_snapshot(camera_id: str, user: dict = Depends(get_current_user)):
    """Retourne une frame JPEG live (via go2rtc) pour servir de fond au polygon editor."""
    import httpx
    import os
    from fastapi.responses import Response
    go2rtc = os.environ.get("GO2RTC_URL", "http://localhost:1984")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{go2rtc}/api/frame.jpeg", params={"src": f"cam_{camera_id}"})
            if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
                return Response(content=r.content, media_type="image/jpeg",
                                headers={"Cache-Control": "no-store"})
    except httpx.HTTPError:
        pass
    raise HTTPException(404, "Snapshot indisponible (caméra offline)")
