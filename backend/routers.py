import os
import re
import uuid
import asyncio
import io
import csv
import base64
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, BackgroundTasks, Response, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database import db
from auth import get_current_user, require_role, require_permission, has_permission, public_user, log_audit, hash_password, ROLES, PERMISSIONS, site_scope, allowed_sites
from notifications import send_notification
from realtime import metrics_snapshot, broadcast_alert, broadcast_camera_status
from plugins import is_enabled

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
    """Séries horaires réelles (agrégation Mongo des dernières 24 h)."""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=24)).isoformat()

    async def hourly_counts(coll) -> dict:
        pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {"_id": {"$substr": ["$timestamp", 0, 13]}, "count": {"$sum": 1}}},
        ]
        return {row["_id"]: row["count"] async for row in coll.aggregate(pipeline)}

    ev, pl, al = await hourly_counts(db.events), await hourly_counts(db.plates), await hourly_counts(db.alerts)
    points = []
    for i in range(24):
        t = now - timedelta(hours=23 - i)
        key = t.strftime("%Y-%m-%dT%H")
        points.append({
            "time": t.strftime("%H:00"),
            "events": ev.get(key, 0),
            "plates": pl.get(key, 0),
            "alerts": al.get(key, 0),
        })
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
    mode: str = "rtsp"  # 'rtsp' ou 'onvif'
    ip: str = ""
    rtsp_port: int = 554
    onvif_port: int = 80
    port: int = 554  # rétro-compatibilité
    protocol: str = "RTSP"
    codec: str = "H264"
    model: str = ""
    manufacturer: str = ""
    firmware: str = ""
    rtsp_url: str = ""
    username: str = ""
    password: str = ""
    # Champs profil (mode ONVIF)
    profile_token: str = ""
    profile_name: str = ""
    # Métadonnées vidéo effectives (informationnelles, mises à jour au probe)
    resolution: str = ""
    fps: Optional[int] = None
    bitrate: Optional[int] = None
    # PTZ / enregistrement / IA
    ptz_enabled: bool = False
    record_enabled: bool = True
    detect_enabled: bool = False
    # Transport RTSP + codec préféré (P0 finalisation)
    rtsp_transport: str = "tcp"  # tcp | udp
    preferred_codec: str = "auto"  # auto | h264 | h265
    allow_rtsp_override: bool = False  # créer même si le test RTSP échoue (mode ONVIF)
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

    payload = data.model_dump()
    # Mode ONVIF : découverte automatique de l'URL RTSP via le service ONVIF
    if data.mode == "onvif":
        if not data.ip:
            raise HTTPException(400, "Mode ONVIF : l'adresse IP est obligatoire")
        from streaming import _onvif_probe, _tcp_check
        if not await asyncio.to_thread(_tcp_check, data.ip, int(data.onvif_port), 3.0):
            raise HTTPException(400, f"Port ONVIF {data.onvif_port} injoignable sur {data.ip}")
        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(_onvif_probe, data.ip, int(data.onvif_port), data.username, data.password),
                timeout=15,
            )
        except asyncio.TimeoutError:
            raise HTTPException(504, "Appareil ONVIF injoignable (délai dépassé)")
        except Exception as e:
            raise HTTPException(400, f"ONVIF injoignable : {type(e).__name__} — vérifiez IP/port/identifiants")
        profiles = info.get("profiles", [])
        # Sélection du profil : utilise `profile_token` si fourni, sinon premier profil avec URI RTSP
        selected = None
        if data.profile_token:
            selected = next((p for p in profiles if p.get("token") == data.profile_token), None)
        if not selected:
            selected = next((p for p in profiles if p.get("rtsp_url")), None)
        if not selected or not selected.get("rtsp_url"):
            raise HTTPException(400, "Aucun profil ONVIF n'a renvoyé d'URL RTSP")
        # Auto-résolution : teste l'URL ONVIF puis ses variantes constructeur (Reolink h264/h265, Hik, Dahua)
        from streaming import _try_ffprobe_variants
        working_url, ffprobe_details, _attempts = await asyncio.to_thread(
            _try_ffprobe_variants, selected["rtsp_url"],
            data.preferred_codec, data.rtsp_transport, data.username, data.password,
        )
        if ffprobe_details:
            payload["rtsp_url"] = working_url
            payload["resolution"] = ffprobe_details.get("resolution", selected.get("resolution", ""))
            payload["fps"] = ffprobe_details.get("fps")
            payload["codec"] = (ffprobe_details.get("codec") or "H264").upper()
            payload["rtsp_transport"] = ffprobe_details.get("transport_used") or data.rtsp_transport
        else:
            payload["rtsp_url"] = selected["rtsp_url"]
            payload["resolution"] = selected.get("resolution") or payload.get("resolution", "")
            payload["codec"] = (selected.get("codec") or payload.get("codec", "H264")).upper().replace("VIDEO", "").strip() or "H264"
        payload["profile_token"] = selected.get("token", "")
        payload["profile_name"] = str(selected.get("name", ""))
        payload["protocol"] = "ONVIF"
        if info.get("model"):
            payload["model"] = payload.get("model") or f"{info.get('manufacturer','')} {info['model']}".strip()
        payload["manufacturer"] = payload.get("manufacturer") or str(info.get("manufacturer") or "")
        payload["firmware"] = payload.get("firmware") or str(info.get("firmware") or "")
        payload["ptz_enabled"] = bool(info.get("ptz_supported")) or payload.get("ptz_enabled", False)
    else:  # mode RTSP pur
        if not (payload.get("rtsp_url") or "").lower().startswith("rtsp://"):
            raise HTTPException(400, "Mode RTSP : l'URL RTSP est obligatoire (rtsp://…)")
        # Validation OBLIGATOIRE ffprobe (sauf allow_rtsp_override=True)
        if not data.allow_rtsp_override:
            from streaming import _try_ffprobe_variants
            working_url, ffprobe_details, _attempts = await asyncio.to_thread(
                _try_ffprobe_variants, payload["rtsp_url"],
                data.preferred_codec, data.rtsp_transport, data.username, data.password,
            )
            if not ffprobe_details:
                raise HTTPException(400,
                    "URL RTSP invalide — aucune variante n'a répondu. "
                    "Utilisez le test de connexion pour diagnostiquer, "
                    "puis cochez « Créer malgré le test RTSP » pour forcer.")
            payload["rtsp_url"] = working_url
            payload["resolution"] = ffprobe_details.get("resolution", payload.get("resolution", ""))
            payload["fps"] = ffprobe_details.get("fps")
            payload["codec"] = (ffprobe_details.get("codec") or "H264").upper()
            payload["rtsp_transport"] = ffprobe_details.get("transport_used") or data.rtsp_transport

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()), "status": "offline", "last_seen": now, "created_at": now,
        "site_name": site["name"],
        "lat": data.lat if data.lat is not None else site["lat"],
        "lng": data.lng if data.lng is not None else site["lng"],
        **payload,
    }
    await db.cameras.insert_one(dict(doc))
    await log_audit(user, "camera_created", data.name, f"Site: {site['name']} · Mode: {data.mode}")
    from streaming import register_camera_stream
    registered = await register_camera_stream(doc)
    if not registered:
        # Si ONVIF a réussi mais go2rtc n'arrive pas à ouvrir le flux, autoriser la création si demandé
        if data.mode == "onvif" and data.allow_rtsp_override:
            await db.cameras.update_one({"id": doc["id"]}, {"$set": {"status": "offline"}})
            await log_audit(user, "camera_created_no_rtsp", data.name,
                            "ONVIF OK, RTSP échoué — création forcée par l'utilisateur")
        else:
            await db.cameras.delete_one({"id": doc["id"]})
            raise HTTPException(400, "Impossible d'enregistrer le flux dans go2rtc "
                                     "(URL RTSP invalide ou service indisponible). "
                                     "Cochez « Créer malgré le test RTSP » pour forcer la création.")
    doc.pop("_id", None); doc.pop("password", None)
    return doc


@api_router.put("/cameras/{camera_id}")
async def update_camera(camera_id: str, data: CameraInput, user: dict = Depends(require_role("technician"))):
    existing = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Caméra introuvable")

    payload = data.model_dump()
    # Si le mot de passe est vide lors d'un PUT, conserver l'ancien (pratique en édition)
    if not payload.get("password"):
        payload["password"] = existing.get("password", "")
    # Mode ONVIF : redécouverte automatique de l'URL RTSP si IP/port/identifiants changent
    if data.mode == "onvif":
        if not data.ip:
            raise HTTPException(400, "Mode ONVIF : l'adresse IP est obligatoire")
        credentials_changed = (
            existing.get("ip") != data.ip or
            existing.get("onvif_port") != data.onvif_port or
            existing.get("username") != data.username or
            (data.password and existing.get("password") != data.password) or
            (data.profile_token and existing.get("profile_token") != data.profile_token) or
            not (existing.get("rtsp_url") or "").lower().startswith("rtsp://")
        )
        if credentials_changed:
            from streaming import _onvif_probe, _tcp_check
            if not await asyncio.to_thread(_tcp_check, data.ip, int(data.onvif_port), 3.0):
                raise HTTPException(400, f"Port ONVIF {data.onvif_port} injoignable sur {data.ip}")
            try:
                info = await asyncio.wait_for(
                    asyncio.to_thread(_onvif_probe, data.ip, int(data.onvif_port),
                                      data.username, data.password or existing.get("password", "")),
                    timeout=15,
                )
                profiles = info.get("profiles", [])
                selected = None
                if data.profile_token:
                    selected = next((p for p in profiles if p.get("token") == data.profile_token), None)
                if not selected:
                    selected = next((p for p in profiles if p.get("rtsp_url")), None)
                if not selected or not selected.get("rtsp_url"):
                    raise HTTPException(400, "Aucun profil ONVIF n'a renvoyé d'URL RTSP")
                payload["rtsp_url"] = selected["rtsp_url"]
                payload["profile_token"] = selected.get("token", "")
                payload["profile_name"] = str(selected.get("name", ""))
                payload["resolution"] = selected.get("resolution") or payload.get("resolution", "")
                payload["codec"] = (selected.get("codec") or payload.get("codec", "H264")).upper().replace("VIDEO", "").strip() or "H264"
                payload["ptz_enabled"] = bool(info.get("ptz_supported")) or payload.get("ptz_enabled", False)
            except HTTPException:
                raise
            except asyncio.TimeoutError:
                raise HTTPException(504, "Appareil ONVIF injoignable (délai dépassé)")
            except Exception as e:
                raise HTTPException(400, f"ONVIF injoignable : {type(e).__name__} — vérifiez IP/port/identifiants")
        else:
            payload["rtsp_url"] = existing.get("rtsp_url", "")
    else:
        if not (payload.get("rtsp_url") or "").lower().startswith("rtsp://"):
            raise HTTPException(400, "Mode RTSP : l'URL RTSP est obligatoire (rtsp://…)")

    await db.cameras.update_one({"id": camera_id}, {"$set": payload})
    await log_audit(user, "camera_updated", data.name, f"Mode: {data.mode}")
    updated = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    from streaming import register_camera_stream
    registered = await register_camera_stream(updated)
    if not registered and camera_id not in {"demo-cam-001", "demo-cam-002"}:
        raise HTTPException(400, "Impossible de mettre à jour le flux dans go2rtc")
    updated.pop("password", None)
    return updated


@api_router.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str, user: dict = Depends(require_role("technician"))):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    await db.cameras.delete_one({"id": camera_id})
    from streaming import unregister_camera_stream
    await unregister_camera_stream(camera_id)
    await log_audit(user, "camera_deleted", cam["name"] if cam else camera_id)
    return {"ok": True}


@api_router.post("/cameras/{camera_id}/test")
async def test_camera(camera_id: str, user: dict = Depends(get_current_user)):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    from streaming import probe_camera
    result = await probe_camera(cam)
    await db.cameras.update_one({"id": camera_id}, {"$set": {"status": result["status"], "last_seen": datetime.now(timezone.utc).isoformat()}})
    await log_audit(user, "camera_tested", cam["name"], f"Résultat: {result['status']}")
    await broadcast_camera_status({**cam, "status": result["status"]})
    return result


@api_router.post("/cameras/{camera_id}/snapshot")
async def snapshot_camera(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    await log_audit(user, "snapshot_captured", cam["name"])
    # Image réelle extraite du flux via le proxy authentifié (le frontend ajoute le token)
    return {"snapshot_url": f"/stream/{camera_id}/frame.jpeg", "captured_at": datetime.now(timezone.utc).isoformat()}


@api_router.post("/cameras/{camera_id}/ptz")
async def ptz_command(camera_id: str, command: str = Query(...), user: dict = Depends(require_permission("ptz_control"))):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    if not cam.get("ptz_enabled"):
        raise HTTPException(400, "PTZ non supporté sur cette caméra")
    return {"ok": True, "command": command}


@api_router.get("/cameras/{camera_id}/stream")
async def camera_stream(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    """Renvoie l'URL de flux live ; la qualité (HD/SD) dépend de la permission `stream_hd`."""
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "password": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    allowed = allowed_sites(user)
    if allowed is not None and cam.get("site_id") not in allowed:
        raise HTTPException(403, "Accès refusé à cette caméra")
    hd = has_permission(user, "stream_hd")
    return {
        "camera_id": cam["id"], "name": cam["name"],
        "quality": "HD" if hd else "SD",
        "stream_url": f"/stream/{cam['id']}/live.mjpeg",
        "frame_url": f"/stream/{cam['id']}/frame.jpeg",
        "engine": "go2rtc",
    }


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


@api_router.get("/events/{event_id}/recording")
async def event_recording(event_id: str, user: dict = Depends(get_current_user)):
    """Retourne l'enregistrement vidéo qui contient l'événement + l'offset (en secondes)
    pour se caler autour, ou 404 si aucun enregistrement ne couvre le timestamp."""
    ev = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not ev:
        # Peut aussi être une plaque ou une alerte
        ev = await db.plates.find_one({"id": event_id}, {"_id": 0})
    if not ev:
        ev = await db.alerts.find_one({"id": event_id}, {"_id": 0})
    if not ev:
        raise HTTPException(404, "Événement introuvable")
    return await _lookup_recording_for(ev, user)


@api_router.get("/recording-context")
async def recording_context(camera_id: str, at: str, user: dict = Depends(get_current_user)):
    """Trouve l'enregistrement couvrant un instant précis (camera_id + timestamp ISO).
    Utilisé pour les alertes ou tout item sans id d'événement direct."""
    return await _lookup_recording_for({"camera_id": camera_id, "timestamp": at, "site_id": None}, user)


async def _lookup_recording_for(ev: dict, user: dict) -> dict:
    allowed = allowed_sites(user)
    if allowed is not None and ev.get("site_id") and ev.get("site_id") not in allowed:
        raise HTTPException(403, "Accès refusé")
    ts = ev.get("timestamp")
    if not ts:
        raise HTTPException(404, "Événement sans horodatage")
    rec = await db.recordings.find_one(
        {"camera_id": ev.get("camera_id"),
         "start": {"$lte": ts},
         "end": {"$gte": ts}},
        {"_id": 0},
    )
    if not rec:
        raise HTTPException(404, "Aucun enregistrement ne couvre cet événement")
    try:
        ev_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        rec_start_dt = datetime.fromisoformat(rec["start"].replace("Z", "+00:00"))
        offset_sec = max(0, int((ev_dt - rec_start_dt).total_seconds()) - 5)  # 5 s avant
    except (ValueError, KeyError):
        offset_sec = 0
    return {
        "recording": rec,
        "event_timestamp": ts,
        "offset_sec": offset_sec,
        "stream_url": f"/recordings/{rec['id']}/media",
    }


# ============ ANPR / PLATES ============
@api_router.get("/plates")
async def search_plates(response: Response, plate: Optional[str] = None, color: Optional[str] = None,
                        make: Optional[str] = None, vtype: Optional[str] = None,
                        site_id: Optional[str] = None, camera_id: Optional[str] = None,
                        direction: Optional[str] = None, list_status: Optional[str] = None,
                        date_from: Optional[str] = None, date_to: Optional[str] = None,
                        limit: int = 50, offset: int = 0, user: dict = Depends(require_permission("read_plates"))):
    q = {}
    if plate:
        q["plate"] = {"$regex": plate.upper().replace(" ", ""), "$options": "i"}
    if color:
        import re as _re
        q["vehicle_color"] = {"$regex": f"^{_re.escape(color)}$", "$options": "i"}
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
async def export_plates(user: dict = Depends(require_permission("export_files"))):
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


# ============ CONFIG IA RUNTIME + DEBUG ALPR (P1) ============
class AIConfigUpdate(BaseModel):
    interval_seconds: Optional[float] = None
    confidence: Optional[float] = None
    min_plate_px: Optional[int] = None
    plate_cache_seconds: Optional[int] = None
    device: Optional[str] = None  # cpu | cuda | auto


@api_router.get("/ai/config")
async def ai_config_get(user: dict = Depends(get_current_user)):
    from ai_engine import get_runtime_config
    return get_runtime_config()


@api_router.put("/ai/config")
async def ai_config_put(data: AIConfigUpdate, user: dict = Depends(require_role("admin"))):
    from ai_engine import update_runtime_config, get_runtime_config
    patch = {k: v for k, v in data.model_dump().items() if v is not None}
    if "interval_seconds" in patch:
        patch["interval_seconds"] = max(0.2, min(60.0, float(patch["interval_seconds"])))
    if "confidence" in patch:
        patch["confidence"] = max(0.1, min(0.95, float(patch["confidence"])))
    if "min_plate_px" in patch:
        patch["min_plate_px"] = max(8, min(200, int(patch["min_plate_px"])))
    if "plate_cache_seconds" in patch:
        patch["plate_cache_seconds"] = max(0, min(300, int(patch["plate_cache_seconds"])))
    if "device" in patch and patch["device"] not in {"cpu", "cuda", "auto"}:
        raise HTTPException(400, "device doit être cpu, cuda ou auto")
    await update_runtime_config(patch)
    await log_audit(user, "ai_config_updated", str(patch))
    return get_runtime_config()


@api_router.get("/ai/debug/{camera_id}")
async def ai_debug(camera_id: str, user: dict = Depends(require_role("technician"))):
    """Dernier snapshot IA de la caméra : frame analysée, véhicules, plaques tentées, timings."""
    from ai_engine import get_debug_snapshot
    snap = get_debug_snapshot(camera_id)
    if not snap:
        return {"available": False, "message": "Aucune analyse récente pour cette caméra"}
    return {"available": True, "camera_id": camera_id, **snap}


def _mask_rtsp(url: str) -> str:
    """Masque les identifiants dans une URL RTSP pour affichage."""
    if not url:
        return ""
    return re.sub(r"(rtsp://)([^:@]+):([^@]+)@", r"\1\2:****@", url, flags=re.IGNORECASE)


@api_router.get("/cameras/{camera_id}/diagnostic")
async def camera_diagnostic(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    """Diagnostic complet caméra : flux + IA + dernières détections.
    Utilisé par la page Diagnostic (bouton "Diagnostic" dans la fiche caméra)."""
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "password": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    # Vérifie l'état go2rtc réel
    from streaming import _stream_name, _stream_registered
    name = _stream_name(camera_id)
    go2rtc_ok = await _stream_registered(name)
    # Dernier événement + dernière plaque + dernier objet
    latest_event = await db.events.find_one({"camera_id": camera_id}, {"_id": 0},
                                             sort=[("timestamp", -1)])
    latest_plate = await db.plates.find_one({"camera_id": camera_id}, {"_id": 0},
                                             sort=[("timestamp", -1)])
    # Compteurs 24h
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    events_24h = await db.events.count_documents({"camera_id": camera_id, "timestamp": {"$gte": since}})
    plates_24h = await db.plates.count_documents({"camera_id": camera_id, "timestamp": {"$gte": since}})
    from ai_engine import get_debug_snapshot
    ai_snap = get_debug_snapshot(camera_id) or {}
    return {
        "camera": {
            "id": cam["id"], "name": cam["name"], "status": cam.get("status", "offline"),
            "site_name": cam.get("site_name"),
            "mode": cam.get("mode"), "manufacturer": cam.get("manufacturer"), "model": cam.get("model"),
            "resolution": cam.get("resolution"), "fps": cam.get("fps"), "codec": cam.get("codec"),
            "rtsp_transport": cam.get("rtsp_transport") or "tcp",
            "preferred_codec": cam.get("preferred_codec") or "auto",
            "profile_token": cam.get("profile_token"),
            "profile_name": cam.get("profile_name"),
            "rtsp_url_masked": _mask_rtsp(cam.get("rtsp_url")),
            "record_enabled": cam.get("record_enabled", True),
            "record_mode": cam.get("record_mode", "continuous"),
            "detect_enabled": cam.get("detect_enabled", False),
            "last_seen": cam.get("last_seen"),
        },
        "flux": {
            "go2rtc_registered": go2rtc_ok,
            "camera_online": cam.get("status") == "online",
            "rtsp_transport_used": cam.get("rtsp_transport") or "tcp",
            "stream_urls": {
                "live_mjpeg": f"/api/stream/{camera_id}/live.mjpeg",
                "frame_jpeg": f"/api/stream/{camera_id}/frame.jpeg",
            },
        },
        "ai": {
            "detect_enabled": bool(cam.get("detect_enabled")),
            "last_analysis_at": ai_snap.get("timestamp"),
            "last_detections_count": len(ai_snap.get("detections", []) or []),
            "last_yolo_ms": ai_snap.get("yolo_ms"),
            "last_alpr_ms": ai_snap.get("alpr_ms"),
            "motion_pct": ai_snap.get("motion_pct"),
            "detections": (ai_snap.get("detections") or [])[:10],
            "plates_debug": ai_snap.get("plate_debug", [])[:10],
        },
        "stats_24h": {"events": events_24h, "plates": plates_24h},
        "last_event": latest_event,
        "last_plate": latest_plate,
    }


# ============ RECORDING RETENTION (P2.a) ============
class RetentionInput(BaseModel):
    retention_days: int = 7
    min_free_gb: float = 5.0
    max_disk_pct: float = 85.0


@api_router.get("/settings/retention")
async def retention_get(user: dict = Depends(require_role("admin"))):
    from recorder import get_retention_status
    return await get_retention_status()


@api_router.put("/settings/retention")
async def retention_put(data: RetentionInput, user: dict = Depends(require_role("admin"))):
    data.retention_days = max(1, min(365, data.retention_days))
    data.min_free_gb = max(0.5, min(10000, float(data.min_free_gb)))
    data.max_disk_pct = max(10.0, min(99.0, float(data.max_disk_pct)))
    await db.settings.update_one({"key": "retention"},
                                 {"$set": {"key": "retention", "value": data.model_dump()}}, upsert=True)
    await log_audit(user, "retention_config_updated",
                    f"days={data.retention_days} free={data.min_free_gb}Go pct={data.max_disk_pct}%")
    from recorder import get_retention_status
    return await get_retention_status()


@api_router.post("/settings/retention/run")
async def retention_run(user: dict = Depends(require_role("admin"))):
    from recorder import _apply_retention
    report = await _apply_retention()
    await log_audit(user, "retention_purge_manual",
                    f"deleted_age={report['deleted_by_age']} deleted_quota={report['deleted_by_quota']} freed={report['freed_gb']}Go")
    return report



class MqttConfig(BaseModel):
    host: str = ""
    port: int = 1883
    username: str = ""
    password: str = ""
    topic_prefix: str = "mgvms"
    tls: bool = False


@api_router.get("/settings/mqtt")
async def mqtt_get(user: dict = Depends(require_role("admin"))):
    doc = await db.settings.find_one({"key": "mqtt_broker"}, {"_id": 0})
    val = (doc or {}).get("value", {}) or {}
    return MqttConfig(**val).model_dump()


@api_router.put("/settings/mqtt")
async def mqtt_put(data: MqttConfig, user: dict = Depends(require_role("admin"))):
    await db.settings.update_one({"key": "mqtt_broker"},
                                 {"$set": {"key": "mqtt_broker", "value": data.model_dump()}}, upsert=True)
    await log_audit(user, "mqtt_config_updated", data.host)
    return data.model_dump()


async def maybe_blacklist_alert(plate_doc: dict, background: BackgroundTasks):
    """Crée une alerte critique + diffuse + notifie si la plaque est en liste noire."""
    if plate_doc.get("list_status") != "black":
        return None
    alert = {
        "id": str(uuid.uuid4()), "type": "anpr_blacklist", "severity": "critical",
        "message": f"Plaque en liste noire détectée : {plate_doc['plate']}",
        "camera_id": plate_doc.get("camera_id", ""), "camera_name": plate_doc.get("camera_name", "—"),
        "site_id": plate_doc.get("site_id", ""), "site_name": plate_doc.get("site_name", "—"),
        "acknowledged": False, "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await db.alerts.insert_one(dict(alert))
    alert.pop("_id", None)
    await broadcast_alert(alert)
    frontend = os.environ.get("CORS_ORIGINS", "").split(",")[0].strip().rstrip("/")
    cam_id = plate_doc.get("camera_id", "")
    link_url = f"{frontend}/recordings?camera={cam_id}" if frontend and cam_id else None
    image_url = plate_doc.get("vehicle_crop") or plate_doc.get("plate_crop") or None
    body = (f"Plaque en liste noire détectée : {plate_doc['plate']}\n"
            f"Caméra : {alert['camera_name']} · Site : {alert['site_name']}\n"
            f"Horodatage : {alert['timestamp']}")
    background.add_task(send_notification, "PLAQUE LISTE NOIRE", body, image_url, link_url)
    return alert


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
@api_router.get("/ai/arming")
async def get_arming(user: dict = Depends(require_role("technician"))):
    from ai_engine import get_arming_config, _is_armed
    cfg = await get_arming_config()
    cfg["armed_now"] = await _is_armed(datetime.now(timezone.utc))
    return cfg


@api_router.put("/ai/arming")
async def update_arming(cfg: dict, user: dict = Depends(require_role("admin"))):
    from ai_engine import DEFAULT_ARMING, get_arming_config, _is_armed
    clean = {k: cfg[k] for k in DEFAULT_ARMING if k in cfg}
    if clean.get("mode") not in ("always", "schedule", "off"):
        clean.pop("mode", None)
    await db.settings.update_one({"key": "arming_schedule"},
                                 {"$set": {"key": "arming_schedule", "value": clean}}, upsert=True)
    await log_audit(user, "arming_updated", details=str(clean))
    out = await get_arming_config()
    out["armed_now"] = await _is_armed(datetime.now(timezone.utc))
    return out


@api_router.get("/ai/alert-rules")
async def get_ai_alert_rules(user: dict = Depends(require_role("technician"))):
    from ai_engine import _get_scenario_rules
    return await _get_scenario_rules()


@api_router.put("/ai/alert-rules")
async def update_ai_alert_rules(rules: Dict[str, dict], user: dict = Depends(require_role("admin"))):
    from ai_engine import DEFAULT_SCENARIOS
    clean = {k: v for k, v in rules.items() if k in DEFAULT_SCENARIOS and isinstance(v, dict)}
    await db.settings.update_one({"key": "ai_alert_rules"}, {"$set": {"key": "ai_alert_rules", "value": clean}}, upsert=True)
    await log_audit(user, "ai_rules_updated", details=str(list(clean.keys())))
    from ai_engine import _get_scenario_rules
    return await _get_scenario_rules()


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
    cam = None
    if data.camera_id:
        cam = await db.cameras.find_one({"id": data.camera_id}, {"_id": 0})
    elif data.site_id:
        cam = await db.cameras.find_one({"site_id": data.site_id}, {"_id": 0})
    if cam is None and not data.site_id:
        cam = await db.cameras.find_one({}, {"_id": 0})
    site = None
    if data.site_id:
        site = await db.sites.find_one({"id": data.site_id}, {"_id": 0})
    site_id = (cam["site_id"] if cam else "") or data.site_id
    site_name = (cam["site_name"] if cam else "") or (site["name"] if site else "—")
    doc = {
        "id": str(uuid.uuid4()), "type": "manual", "severity": data.severity, "message": data.message,
        "camera_id": cam["id"] if cam else "", "camera_name": cam["name"] if cam else "—",
        "site_id": site_id, "site_name": site_name,
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


# ============ RECORDINGS / TIMELINE ============
@api_router.get("/recordings/timeline")
async def recordings_timeline(camera_id: str, date: Optional[str] = None, user: dict = Depends(require_permission("view_recordings"))):
    """Segments enregistrés d'une caméra pour une journée (date ISO AAAA-MM-JJ).
    Lit les vraies vidéos MP4 (recorder ffmpeg → /data/recordings/<camera_id>/...)."""
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "password": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    allowed = allowed_sites(user)
    if allowed is not None and cam.get("site_id") not in allowed:
        raise HTTPException(403, "Accès refusé à cette caméra")
    if date:
        try:
            day_start = datetime.fromisoformat(date).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(400, "Date invalide")
    else:
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    q = {"camera_id": camera_id, "start": {"$gte": day_start.isoformat(), "$lt": day_end.isoformat()}}
    segments = await db.recordings.find(q, {"_id": 0}).sort("start", 1).to_list(500)
    total_sec = sum(s.get("duration_sec", 0) for s in segments)
    total_mb = round(sum(s.get("size_mb", 0) for s in segments), 1)
    return {
        "camera": {"id": cam["id"], "name": cam["name"], "site_name": cam.get("site_name", "")},
        "date": day_start.date().isoformat(),
        "segments": segments,
        "coverage_sec": total_sec,
        "total_size_mb": total_mb,
        "event_count": sum(1 for s in segments if s.get("has_event")),
    }


@api_router.get("/recordings/{recording_id}/playback")
async def recordings_playback(recording_id: str, user: dict = Depends(require_permission("view_recordings"))):
    rec = await db.recordings.find_one({"id": recording_id}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "Enregistrement introuvable")
    allowed = allowed_sites(user)
    if allowed is not None and rec.get("site_id") not in allowed:
        raise HTTPException(403, "Accès refusé")
    await log_audit(user, "recording_playback", rec["camera_name"], rec["start"])
    has_file = bool(rec.get("file_path")) and os.path.exists(rec.get("file_path", ""))
    return {
        "recording": rec,
        "poster": None,
        "stream_url": f"/recordings/{recording_id}/media" if has_file else None,
        "message": None if has_file else "Fichier introuvable sur le disque.",
    }


@api_router.get("/recordings/{recording_id}/media")
async def recordings_media(recording_id: str, request: Request):
    """Fichier MP4 réel (lecture <video> — token accepté en query)."""
    from streaming import stream_user
    from fastapi.responses import FileResponse
    user = await stream_user(request, request.query_params.get("token"))
    if not has_permission(user, "view_recordings"):
        raise HTTPException(403, "Permission requise : view_recordings")
    rec = await db.recordings.find_one({"id": recording_id}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "Enregistrement introuvable")
    allowed = allowed_sites(user)
    if allowed is not None and rec.get("site_id") not in allowed:
        raise HTTPException(403, "Accès refusé")
    path = rec.get("file_path")
    if not path or not os.path.exists(path):
        raise HTTPException(404, "Fichier vidéo introuvable")
    return FileResponse(path, media_type="video/mp4", filename=os.path.basename(path))


# ============ EXPORT DE SÉQUENCE ============
class ExportRequest(BaseModel):
    camera_id: str
    start: str   # ISO datetime
    end: str     # ISO datetime
    format: str = "zip"   # zip | mp4


@api_router.post("/recordings/export")
async def create_export(data: ExportRequest, user: dict = Depends(require_permission("export_files"))):
    cam = await db.cameras.find_one({"id": data.camera_id}, {"_id": 0, "password": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    allowed = allowed_sites(user)
    if allowed is not None and cam.get("site_id") not in allowed:
        raise HTTPException(403, "Accès refusé à cette caméra")
    try:
        start_dt = datetime.fromisoformat(data.start)
        end_dt = datetime.fromisoformat(data.end)
    except ValueError:
        raise HTTPException(400, "Plage horaire invalide")
    if end_dt <= start_dt:
        raise HTTPException(400, "La fin doit être après le début")
    fmt = data.format if data.format in ("zip", "mp4") else "zip"
    # Segments chevauchant la plage
    segs = await db.recordings.find(
        {"camera_id": data.camera_id, "start": {"$lt": data.end}, "end": {"$gt": data.start}},
        {"_id": 0}
    ).sort("start", 1).to_list(500)
    duration_sec = int((end_dt - start_dt).total_seconds())
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()), "user_id": user["id"],
        "camera_id": cam["id"], "camera_name": cam["name"], "site_name": cam.get("site_name", ""),
        "start": data.start, "end": data.end, "format": fmt,
        "segment_count": len(segs), "duration_sec": duration_sec,
        "segment_ids": [s["id"] for s in segs],
        "created_at": now,
    }
    if fmt == "zip":
        doc["status"] = "ready"
        doc["message"] = "Archive ZIP prête (clips MP4 réels + manifeste)."
    else:  # mp4 : concaténation réelle FFmpeg (sans réencodage)
        files = [s.get("file_path") for s in segs if s.get("file_path") and os.path.exists(s.get("file_path", ""))]
        if not files:
            raise HTTPException(400, "Aucun segment vidéo sur disque dans cette plage")
        export_dir = os.path.join(os.environ.get("RECORDINGS_DIR", "/app/recordings"), "exports")
        os.makedirs(export_dir, exist_ok=True)
        out_path = os.path.join(export_dir, f"{doc['id']}.mp4")
        list_path = os.path.join(export_dir, f"{doc['id']}.txt")
        with open(list_path, "w") as lf:
            lf.write("\n".join(f"file '{f}'" for f in files))
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", list_path, "-c", "copy", out_path)
        await proc.wait()
        os.unlink(list_path)
        if proc.returncode != 0 or not os.path.exists(out_path):
            raise HTTPException(500, "Échec de l'assemblage FFmpeg")
        doc["status"] = "ready"
        doc["file_path"] = out_path
        doc["size_mb"] = round(os.path.getsize(out_path) / 1e6, 1)
        doc["message"] = "Clip MP4 assemblé (FFmpeg, copie sans réencodage)."
    await db.exports.insert_one(dict(doc))
    doc.pop("_id", None)
    await log_audit(user, "recording_export", cam["name"], f"{fmt} · {len(segs)} segments")
    return doc


@api_router.get("/recordings/exports")
async def list_exports(user: dict = Depends(get_current_user)):
    return await db.exports.find({"user_id": user["id"]}, {"_id": 0, "segment_ids": 0}).sort("created_at", -1).to_list(50)


@api_router.get("/recordings/exports/{export_id}/download")
async def download_export(export_id: str, user: dict = Depends(require_permission("export_files"))):
    exp = await db.exports.find_one({"id": export_id, "user_id": user["id"]}, {"_id": 0})
    if not exp:
        raise HTTPException(404, "Export introuvable")
    if exp["status"] != "ready":
        raise HTTPException(400, "Export non prêt")
    await log_audit(user, "export_downloaded", exp["camera_name"], exp["id"])
    if exp["format"] == "mp4":
        from fastapi.responses import FileResponse
        path = exp.get("file_path")
        if not path or not os.path.exists(path):
            raise HTTPException(404, "Fichier d'export introuvable")
        fname = f"mgvms_export_{exp['camera_name']}_{exp['id'][:8]}.mp4".replace(" ", "_")
        return FileResponse(path, media_type="video/mp4", filename=fname)
    # ZIP : clips MP4 réels + manifeste
    import zipfile
    segs = await db.recordings.find({"id": {"$in": exp.get("segment_ids", [])}}, {"_id": 0}).sort("start", 1).to_list(500)
    manifest = {
        "camera": exp["camera_name"], "site": exp["site_name"],
        "range": {"start": exp["start"], "end": exp["end"]},
        "duration_sec": exp["duration_sec"], "segment_count": len(segs),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "segments": [{"start": s["start"], "end": s["end"], "mode": s.get("mode"),
                      "size_mb": s.get("size_mb"), "file": os.path.basename(s.get("file_path") or "")} for s in segs],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", __import__("json").dumps(manifest, ensure_ascii=False, indent=2))
        for i, s in enumerate(segs):
            path = s.get("file_path")
            if path and os.path.exists(path):
                zf.write(path, arcname=f"clips/{i+1:03d}_{os.path.basename(path)}")
    buf.seek(0)
    fname = f"mgvms_export_{exp['camera_name']}_{exp['id'][:8]}.zip".replace(" ", "_")
    return StreamingResponse(iter([buf.getvalue()]), media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename={fname}"})


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
    site_ids: Optional[List[str]] = None
    permissions: Optional[Dict[str, bool]] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    site_ids: Optional[List[str]] = None
    permissions: Optional[Dict[str, bool]] = None


def _clean_permissions(perms: Optional[Dict[str, bool]]) -> Dict[str, bool]:
    if not perms:
        return {}
    return {k: bool(v) for k, v in perms.items() if k in PERMISSIONS}


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
        "active": True, "site_ids": data.site_ids or [],
        "permissions": _clean_permissions(data.permissions),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(dict(doc))
    await log_audit(user, "user_created", email, role)
    return public_user(doc)


@api_router.put("/users/{user_id}")
async def update_user(user_id: str, data: UserUpdate, user: dict = Depends(require_role("admin"))):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if "role" in update and update["role"] not in ROLES:
        raise HTTPException(400, "Rôle invalide")
    if "permissions" in update:
        update["permissions"] = _clean_permissions(update["permissions"])
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


# ============ AI IMAGE ANALYSIS (ANPR) — LOCAL (fast-alpr), aucune dépendance cloud ============
@api_router.post("/ai/analyze-plate")
async def analyze_plate(background: BackgroundTasks, file: UploadFile = File(...), user: dict = Depends(require_role("client"))):
    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(400, "Image trop volumineuse (max 8MB)")
    b64 = base64.b64encode(content).decode("utf-8")
    try:
        from ai_engine import analyze_image_local
        data = await asyncio.to_thread(analyze_image_local, content)
    except Exception as e:
        raise HTTPException(500, f"Erreur analyse IA (fast-alpr) : {str(e)}")

    await log_audit(user, "ai_plate_analysis", data.get("plate", ""))
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
            "plate_crop": data.get("plate_crop", ""), "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await db.plates.insert_one(dict(rec))
        rec.pop("_id", None)
        await maybe_blacklist_alert(rec, background)
    return data
