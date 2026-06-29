import os
import uuid
import random
import io
import csv
import base64
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, BackgroundTasks, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database import db
from auth import get_current_user, require_role, public_user, log_audit, hash_password, ROLES, site_scope, allowed_sites
from notifications import send_notification
from realtime import metrics_snapshot, broadcast_alert, broadcast_camera_status

api_router = APIRouter(prefix="/api", tags=["core"])


# ============ DASHBOARD ============
@api_router.get("/dashboard/stats")
async def dashboard_stats(user: dict = Depends(get_current_user)):
    sf = site_scope({}, user)  # {} for admin/tech, {site_id:{$in:[...]}} otherwise
    allowed = allowed_sites(user)
    total_cams = await db.cameras.count_documents(sf)
    online = await db.cameras.count_documents({**sf, "status": "online"})
    sites = await db.sites.count_documents({} if allowed is None else {"id": {"$in": allowed}})
    events_today = await db.events.count_documents({
        **sf, "timestamp": {"$gte": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()}
    })
    alerts_active = await db.alerts.count_documents({**sf, "acknowledged": False})
    plates_today = await db.plates.count_documents({
        **sf, "timestamp": {"$gte": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()}
    })
    return {
        "cameras_total": total_cams,
        "cameras_online": online,
        "cameras_offline": total_cams - online,
        "sites": sites,
        "events_today": events_today,
        "alerts_active": alerts_active,
        "plates_today": plates_today,
        "system": metrics_snapshot(),
    }


@api_router.get("/dashboard/timeseries")
async def dashboard_timeseries(user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    points = []
    for i in range(24):
        t = now - timedelta(hours=23 - i)
        rnd = random.Random(int(t.timestamp() / 3600))
        points.append({
            "time": t.strftime("%H:00"),
            "events": rnd.randint(2, 28),
            "plates": rnd.randint(1, 18),
            "alerts": rnd.randint(0, 6),
        })
    # detection breakdown
    breakdown = []
    cursor = db.events.aggregate([{"$group": {"_id": "$type", "count": {"$sum": 1}}}])
    async for row in cursor:
        breakdown.append({"name": row["_id"], "value": row["count"]})
    return {"hourly": points, "breakdown": breakdown}


# ============ SITES ============
class SiteInput(BaseModel):
    name: str
    type: str
    address: str = ""
    lat: float = 45.764
    lng: float = 4.8357


@api_router.get("/sites")
async def list_sites(user: dict = Depends(get_current_user)):
    allowed = allowed_sites(user)
    q = {} if allowed is None else {"id": {"$in": allowed}}
    sites = await db.sites.find(q, {"_id": 0}).to_list(500)
    for s in sites:
        s["camera_count"] = await db.cameras.count_documents({"site_id": s["id"]})
    return sites


@api_router.post("/sites")
async def create_site(data: SiteInput, user: dict = Depends(require_role("technician"))):
    doc = {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(), "camera_count": 0, **data.model_dump()}
    await db.sites.insert_one(dict(doc))
    await log_audit(user, "site_created", data.name)
    doc.pop("_id", None)
    return doc


@api_router.put("/sites/{site_id}")
async def update_site(site_id: str, data: SiteInput, user: dict = Depends(require_role("technician"))):
    res = await db.sites.update_one({"id": site_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(404, "Site introuvable")
    await log_audit(user, "site_updated", data.name)
    return await db.sites.find_one({"id": site_id}, {"_id": 0})


@api_router.delete("/sites/{site_id}")
async def delete_site(site_id: str, user: dict = Depends(require_role("admin"))):
    await db.cameras.delete_many({"site_id": site_id})
    await db.sites.delete_one({"id": site_id})
    await log_audit(user, "site_deleted", site_id)
    return {"ok": True}


# ============ CAMERAS ============
class CameraInput(BaseModel):
    name: str
    site_id: str
    ip: str = ""
    port: int = 554
    protocol: str = "RTSP"
    codec: str = "H264"
    model: str = ""
    rtsp_url: str = ""
    username: str = ""
    password: str = ""
    ptz_enabled: bool = False
    lat: Optional[float] = None
    lng: Optional[float] = None


@api_router.get("/cameras")
async def list_cameras(site_id: Optional[str] = None, status: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {}
    if site_id:
        q["site_id"] = site_id
    if status:
        q["status"] = status
    site_scope(q, user)
    cams = await db.cameras.find(q, {"_id": 0, "password": 0}).to_list(1000)
    return cams


@api_router.get("/cameras/{camera_id}")
async def get_camera(camera_id: str, user: dict = Depends(get_current_user)):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "password": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    return cam


@api_router.post("/cameras")
async def create_camera(data: CameraInput, user: dict = Depends(require_role("technician"))):
    site = await db.sites.find_one({"id": data.site_id}, {"_id": 0})
    if not site:
        raise HTTPException(400, "Site invalide")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()), "status": "offline", "last_seen": now, "created_at": now,
        "site_name": site["name"],
        "lat": data.lat if data.lat is not None else site["lat"],
        "lng": data.lng if data.lng is not None else site["lng"],
        **data.model_dump(),
    }
    await db.cameras.insert_one(dict(doc))
    await log_audit(user, "camera_created", data.name, f"Site: {site['name']}")
    doc.pop("_id", None); doc.pop("password", None)
    return doc


@api_router.put("/cameras/{camera_id}")
async def update_camera(camera_id: str, data: CameraInput, user: dict = Depends(require_role("technician"))):
    res = await db.cameras.update_one({"id": camera_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(404, "Caméra introuvable")
    await log_audit(user, "camera_updated", data.name)
    return await db.cameras.find_one({"id": camera_id}, {"_id": 0, "password": 0})


@api_router.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str, user: dict = Depends(require_role("technician"))):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    await db.cameras.delete_one({"id": camera_id})
    await log_audit(user, "camera_deleted", cam["name"] if cam else camera_id)
    return {"ok": True}


@api_router.post("/cameras/{camera_id}/test")
async def test_camera(camera_id: str, user: dict = Depends(get_current_user)):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    # Simulated connection test
    success = random.random() > 0.15
    status = "online" if success else "offline"
    await db.cameras.update_one({"id": camera_id}, {"$set": {"status": status, "last_seen": datetime.now(timezone.utc).isoformat()}})
    await log_audit(user, "camera_tested", cam["name"], f"Résultat: {status}")
    await broadcast_camera_status({**cam, "status": status})
    return {
        "success": success,
        "status": status,
        "latency_ms": random.randint(8, 120) if success else None,
        "resolution": "1920x1080" if success else None,
        "fps": random.choice([15, 25, 30]) if success else None,
        "message": "Connexion établie" if success else "Délai dépassé - vérifiez l'URL/RTSP",
    }


@api_router.post("/cameras/{camera_id}/snapshot")
async def snapshot_camera(camera_id: str, user: dict = Depends(get_current_user)):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    await log_audit(user, "snapshot_captured", cam["name"])
    imgs = [
        "https://images.unsplash.com/photo-1707829248830-578d2b0cbe65?w=800&q=80",
        "https://images.unsplash.com/photo-1693541684739-e714db2637e2?w=800&q=80",
    ]
    return {"snapshot_url": random.choice(imgs), "captured_at": datetime.now(timezone.utc).isoformat()}


@api_router.post("/cameras/{camera_id}/ptz")
async def ptz_command(camera_id: str, command: str = Query(...), user: dict = Depends(require_role("client"))):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    if not cam.get("ptz_enabled"):
        raise HTTPException(400, "PTZ non supporté sur cette caméra")
    return {"ok": True, "command": command}


# ============ EVENTS ============
@api_router.get("/events")
async def list_events(response: Response, type: Optional[str] = None, site_id: Optional[str] = None,
                      camera_id: Optional[str] = None, limit: int = 100, offset: int = 0,
                      user: dict = Depends(get_current_user)):
    q = {}
    if type:
        q["type"] = type
    if site_id:
        q["site_id"] = site_id
    if camera_id:
        q["camera_id"] = camera_id
    site_scope(q, user)
    total = await db.events.count_documents(q)
    response.headers["X-Total-Count"] = str(total)
    events = await db.events.find(q, {"_id": 0}).sort("timestamp", -1).skip(offset).limit(limit).to_list(limit)
    return events


# ============ ANPR / PLATES ============
@api_router.get("/plates")
async def search_plates(response: Response, plate: Optional[str] = None, color: Optional[str] = None,
                        make: Optional[str] = None, vtype: Optional[str] = None,
                        site_id: Optional[str] = None, camera_id: Optional[str] = None,
                        direction: Optional[str] = None, list_status: Optional[str] = None,
                        date_from: Optional[str] = None, date_to: Optional[str] = None,
                        limit: int = 50, offset: int = 0, user: dict = Depends(get_current_user)):
    q = {}
    if plate:
        q["plate"] = {"$regex": plate.upper().replace(" ", ""), "$options": "i"}
    if color:
        q["vehicle_color"] = color
    if make:
        q["vehicle_make"] = make
    if vtype:
        q["vehicle_type"] = vtype
    if site_id:
        q["site_id"] = site_id
    if camera_id:
        q["camera_id"] = camera_id
    if direction:
        q["direction"] = direction
    if list_status:
        q["list_status"] = list_status
    if date_from or date_to:
        rng = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["timestamp"] = rng
    site_scope(q, user)
    total = await db.plates.count_documents(q)
    response.headers["X-Total-Count"] = str(total)
    plates = await db.plates.find(q, {"_id": 0}).sort("timestamp", -1).skip(offset).limit(limit).to_list(limit)
    return plates


@api_router.get("/plates/export")
async def export_plates(user: dict = Depends(get_current_user)):
    plates = await db.plates.find({}, {"_id": 0}).sort("timestamp", -1).to_list(2000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Plaque", "Date", "Caméra", "Site", "Couleur", "Marque", "Modèle", "Type", "Direction", "Confiance", "Liste"])
    for p in plates:
        writer.writerow([p["plate"], p["timestamp"], p["camera_name"], p["site_name"], p["vehicle_color"],
                         p["vehicle_make"], p["vehicle_model"], p["vehicle_type"], p["direction"], p["confidence"], p["list_status"]])
    output.seek(0)
    await log_audit(user, "plates_exported", "CSV")
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=anpr_export.csv"})


# ============ WATCHLIST ============
class WatchInput(BaseModel):
    plate: str
    list_type: str = "black"
    reason: str = ""


@api_router.get("/watchlist")
async def list_watchlist(user: dict = Depends(get_current_user)):
    return await db.watchlist.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)


@api_router.post("/watchlist")
async def add_watchlist(data: WatchInput, user: dict = Depends(require_role("technician"))):
    doc = {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
           "plate": data.plate.upper(), "list_type": data.list_type, "reason": data.reason}
    await db.watchlist.insert_one(dict(doc))
    await db.plates.update_many({"plate": data.plate.upper()}, {"$set": {"list_status": data.list_type}})
    await log_audit(user, "watchlist_added", data.plate, data.list_type)
    doc.pop("_id", None)
    return doc


@api_router.delete("/watchlist/{wid}")
async def delete_watchlist(wid: str, user: dict = Depends(require_role("technician"))):
    w = await db.watchlist.find_one({"id": wid}, {"_id": 0})
    await db.watchlist.delete_one({"id": wid})
    if w:
        await db.plates.update_many({"plate": w["plate"]}, {"$set": {"list_status": "none"}})
    await log_audit(user, "watchlist_removed", w["plate"] if w else wid)
    return {"ok": True}


# ============ ALERTS ============
@api_router.get("/alerts")
async def list_alerts(response: Response, acknowledged: Optional[bool] = None, limit: int = 100, offset: int = 0, user: dict = Depends(get_current_user)):
    q = {}
    if acknowledged is not None:
        q["acknowledged"] = acknowledged
    site_scope(q, user)
    total = await db.alerts.count_documents(q)
    response.headers["X-Total-Count"] = str(total)
    return await db.alerts.find(q, {"_id": 0}).sort("timestamp", -1).skip(offset).limit(limit).to_list(limit)


@api_router.post("/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str, user: dict = Depends(require_role("client"))):
    res = await db.alerts.update_one({"id": alert_id}, {"$set": {"acknowledged": True}})
    if res.matched_count == 0:
        raise HTTPException(404, "Alerte introuvable")
    await log_audit(user, "alert_acknowledged", alert_id)
    return {"ok": True}


class AlertCreate(BaseModel):
    message: str
    severity: str = "warning"
    camera_id: str = ""
    site_id: str = ""


@api_router.post("/alerts")
async def create_alert(data: AlertCreate, background: BackgroundTasks, user: dict = Depends(require_role("technician"))):
    cam = await db.cameras.find_one({"id": data.camera_id}, {"_id": 0}) if data.camera_id else await db.cameras.find_one({}, {"_id": 0})
    doc = {
        "id": str(uuid.uuid4()), "type": "manual", "severity": data.severity, "message": data.message,
        "camera_id": cam["id"] if cam else "", "camera_name": cam["name"] if cam else "—",
        "site_id": cam["site_id"] if cam else "", "site_name": cam["site_name"] if cam else "—",
        "acknowledged": False, "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await db.alerts.insert_one(dict(doc))
    await log_audit(user, "alert_created", data.message, data.severity)
    doc.pop("_id", None)
    await broadcast_alert(doc)
    if data.severity == "critical":
        body = f"Alerte: {data.message}\nCaméra: {doc['camera_name']} · Site: {doc['site_name']}\nHorodatage: {doc['timestamp']}"
        background.add_task(send_notification, "ALERTE CRITIQUE", body)
    return {**doc, "dispatched": data.severity == "critical"}


# ============ AUDIT ============
@api_router.get("/audit")
async def list_audit(response: Response, limit: int = 100, offset: int = 0, user: dict = Depends(require_role("technician"))):
    total = await db.audit_logs.count_documents({})
    response.headers["X-Total-Count"] = str(total)
    return await db.audit_logs.find({}, {"_id": 0}).sort("timestamp", -1).skip(offset).limit(limit).to_list(limit)


# ============ USERS (admin) ============
class UserCreate(BaseModel):
    email: str
    password: str
    name: str
    role: str = "client"


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    site_ids: Optional[List[str]] = None


@api_router.get("/users")
async def list_users(user: dict = Depends(require_role("admin"))):
    users = await db.users.find({}, {"_id": 0, "password_hash": 0, "twofa_secret": 0}).to_list(500)
    return [public_user(u) for u in users]


@api_router.post("/users")
async def create_user(data: UserCreate, user: dict = Depends(require_role("admin"))):
    email = data.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email déjà utilisé")
    role = data.role if data.role in ROLES else "client"
    doc = {
        "id": str(uuid.uuid4()), "email": email, "password_hash": hash_password(data.password),
        "name": data.name, "role": role, "twofa_enabled": False, "twofa_secret": None,
        "active": True, "site_ids": [], "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(dict(doc))
    await log_audit(user, "user_created", email, role)
    return public_user(doc)


@api_router.put("/users/{user_id}")
async def update_user(user_id: str, data: UserUpdate, user: dict = Depends(require_role("admin"))):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if "role" in update and update["role"] not in ROLES:
        raise HTTPException(400, "Rôle invalide")
    res = await db.users.update_one({"id": user_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Utilisateur introuvable")
    await log_audit(user, "user_updated", user_id, str(update))
    u = await db.users.find_one({"id": user_id}, {"_id": 0})
    return public_user(u)


@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_role("admin"))):
    if user_id == user["id"]:
        raise HTTPException(400, "Impossible de supprimer votre propre compte")
    await db.users.delete_one({"id": user_id})
    await log_audit(user, "user_deleted", user_id)
    return {"ok": True}


# ============ AI IMAGE ANALYSIS (ANPR) ============
@api_router.post("/ai/analyze-plate")
async def analyze_plate(file: UploadFile = File(...), user: dict = Depends(require_role("client"))):
    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(400, "Image trop volumineuse (max 8MB)")
    b64 = base64.b64encode(content).decode("utf-8")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
        chat = LlmChat(
            api_key=os.environ["EMERGENT_LLM_KEY"],
            session_id=f"anpr-{uuid.uuid4()}",
            system_message=(
                "Tu es un moteur ANPR (lecture automatique de plaques) et d'analyse de véhicule. "
                "Analyse l'image et réponds UNIQUEMENT en JSON valide avec les clés: "
                "plate (string, plaque lue ou ''), country (string), vehicle_color (string en français), "
                "vehicle_make (string), vehicle_model (string), vehicle_type (Voiture/Camion/Moto/Bus/Utilitaire/Inconnu), "
                "confidence (nombre 0-1). Aucun texte hors JSON."
            ),
        ).with_model("openai", "gpt-5.4")
        msg = UserMessage(text="Analyse cette image et extrais la plaque et les attributs du véhicule.",
                          file_contents=[ImageContent(image_base64=b64)])
        result = await chat.send_message(msg)
        import json, re
        text = result if isinstance(result, str) else str(result)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(match.group(0)) if match else {}
    except Exception as e:
        raise HTTPException(500, f"Erreur analyse IA: {str(e)}")

    await log_audit(user, "ai_plate_analysis", data.get("plate", ""))

    # Persist as a plate record
    if data.get("plate"):
        cam = await db.cameras.find_one({}, {"_id": 0})
        wl = await db.watchlist.find_one({"plate": data["plate"].upper()}, {"_id": 0})
        rec = {
            "id": str(uuid.uuid4()), "plate": data.get("plate", "").upper(),
            "camera_id": cam["id"] if cam else "upload", "camera_name": "Analyse manuelle",
            "site_id": cam["site_id"] if cam else "upload", "site_name": cam["site_name"] if cam else "Upload",
            "confidence": float(data.get("confidence", 0.9)),
            "vehicle_color": data.get("vehicle_color", ""), "vehicle_make": data.get("vehicle_make", ""),
            "vehicle_model": data.get("vehicle_model", ""), "vehicle_type": data.get("vehicle_type", "Inconnu"),
            "country": data.get("country", ""), "direction": "—",
            "lat": cam["lat"] if cam else 0, "lng": cam["lng"] if cam else 0,
            "list_status": wl["list_type"] if wl else "none",
            "vehicle_crop": f"data:{file.content_type};base64,{b64}",
            "plate_crop": "", "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await db.plates.insert_one(dict(rec))
    return data
