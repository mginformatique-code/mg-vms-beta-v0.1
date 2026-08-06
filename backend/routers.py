import os
import re
import uuid
import asyncio
import io
import csv
import base64
from datetime import datetime, timezone, timedelta
import time
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
# → Extrait vers `routes/dashboard.py` (P1 modularisation, Feb 2026)


# ============ SITES ============
class SiteInput(BaseModel):
    name: str
    type: str
    address: str = ""
    lat: float = 45.764
    lng: float = 4.8357
    # v0.5.2 · Map Center — infos enrichies pour préparation d'installation
    # et audit. Tous ces champs sont optionnels et n'impactent pas l'existant.
    client_name: str = ""
    phone: str = ""
    contact_name: str = ""
    notes: str = ""


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
    # Refonte v0.3 (Feb 2026) : URL RTSP dédiée à l'IA (flux principal HD).
    # Permet d'utiliser un flux différent pour l'IA (haute résolution / faible
    # compression pour meilleure détection & ANPR) et un sous-flux pour le
    # streaming go2rtc (léger, temps réel). Vide → l'IA utilise `rtsp_url`.
    ai_rtsp_url: str = ""
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
    # v0.3 · Config caméra modulaire : liste des plugins IA activés sur cette
    # caméra. Vide → comportement legacy (piloté par detect_enabled). Chaque
    # entrée est un ``name`` de plugin enregistré sur le Plugin Bus (ex :
    # ``["yolo-detection", "bytetrack", "fast-alpr", "fire-detection"]``).
    # 0 → aucune analyse ; 1..N → uniquement les plugins listés seront exécutés
    # pour cette caméra dans ``dispatch_pipeline``.
    enabled_plugins: list[str] = []
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
                timeout=25,
            )
        except asyncio.TimeoutError:
            raise HTTPException(504, "Appareil ONVIF injoignable (délai dépassé)")
        except Exception as e:
            raise HTTPException(400, f"ONVIF injoignable : {type(e).__name__}: {str(e)[:160]} — vérifiez IP/port/identifiants")
        profiles = info.get("profiles", [])
        # Sélection du profil : utilise `profile_token` si fourni, sinon premier profil avec URI RTSP
        selected = None
        if data.profile_token:
            selected = next((p for p in profiles if p.get("token") == data.profile_token), None)
        if not selected:
            selected = next((p for p in profiles if p.get("rtsp_url")), None)
        if not selected or not selected.get("rtsp_url"):
            raise HTTPException(400, "Aucun profil ONVIF n'a renvoyé d'URL RTSP")
        # Validation EXACTE de l'URL du profil choisi (aucune substitution de variante).
        # Le choix explicite du profil (main/sub) doit être respecté : go2rtc utilisera
        # exactement cette URL. Fallback autorisé uniquement entre TCP et UDP.
        from streaming import _ffprobe_validate_exact
        working_url, ffprobe_details, _attempts = await asyncio.to_thread(
            _ffprobe_validate_exact, selected["rtsp_url"],
            data.rtsp_transport, data.username, data.password,
        )
        if ffprobe_details:
            payload["rtsp_url"] = working_url  # == selected["rtsp_url"]
            payload["resolution"] = ffprobe_details.get("resolution", selected.get("resolution", ""))
            payload["fps"] = ffprobe_details.get("fps")
            payload["codec"] = (ffprobe_details.get("codec") or "H264").upper()
            payload["rtsp_transport"] = ffprobe_details.get("transport_used") or data.rtsp_transport
        elif data.allow_rtsp_override:
            payload["rtsp_url"] = selected["rtsp_url"]
            payload["resolution"] = selected.get("resolution") or payload.get("resolution", "")
            payload["codec"] = (selected.get("codec") or payload.get("codec", "H264")).upper().replace("VIDEO", "").strip() or "H264"
        else:
            raise HTTPException(400,
                f"URL RTSP du profil « {selected.get('name','?')} » injoignable — "
                f"choisissez un autre profil ou cochez « Créer malgré le test RTSP ».")
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
    # ── Chiffrement Fernet du mot de passe caméra (R05 / ADR-06) ──
    from crypto_utils import encrypt_secret
    if payload.get("password"):
        payload["password"] = encrypt_secret(payload["password"])
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
    registered = await register_camera_stream(doc, caller=f"POST /api/cameras user={user.get('email','?')}")
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

    # Déchiffre l'ancien mot de passe pour usage interne (ONVIF probe, ffprobe...)
    # sans jamais le renvoyer au client
    from crypto_utils import decrypt_secret
    existing_password_plain = decrypt_secret(existing.get("password", ""))

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
                                      data.username, data.password or existing_password_plain),
                    timeout=25,
                )
                profiles = info.get("profiles", [])
                selected = None
                if data.profile_token:
                    selected = next((p for p in profiles if p.get("token") == data.profile_token), None)
                if not selected:
                    selected = next((p for p in profiles if p.get("rtsp_url")), None)
                if not selected or not selected.get("rtsp_url"):
                    raise HTTPException(400, "Aucun profil ONVIF n'a renvoyé d'URL RTSP")
                # Validation EXACTE de l'URL du profil choisi (pas de substitution)
                from streaming import _ffprobe_validate_exact
                working_url, ffprobe_details, _attempts = await asyncio.to_thread(
                    _ffprobe_validate_exact, selected["rtsp_url"],
                    data.rtsp_transport, data.username, data.password or existing_password_plain,
                )
                payload["rtsp_url"] = selected["rtsp_url"]
                payload["profile_token"] = selected.get("token", "")
                payload["profile_name"] = str(selected.get("name", ""))
                if ffprobe_details:
                    payload["resolution"] = ffprobe_details.get("resolution") or selected.get("resolution") or payload.get("resolution", "")
                    payload["fps"] = ffprobe_details.get("fps")
                    payload["codec"] = (ffprobe_details.get("codec") or "H264").upper()
                    payload["rtsp_transport"] = ffprobe_details.get("transport_used") or data.rtsp_transport
                else:
                    payload["resolution"] = selected.get("resolution") or payload.get("resolution", "")
                    payload["codec"] = (selected.get("codec") or payload.get("codec", "H264")).upper().replace("VIDEO", "").strip() or "H264"
                payload["ptz_enabled"] = bool(info.get("ptz_supported")) or payload.get("ptz_enabled", False)
            except HTTPException:
                raise
            except asyncio.TimeoutError:
                raise HTTPException(504, "Appareil ONVIF injoignable (délai dépassé)")
            except Exception as e:
                raise HTTPException(400, f"ONVIF injoignable : {type(e).__name__}: {str(e)[:160]} — vérifiez IP/port/identifiants")
        else:
            payload["rtsp_url"] = existing.get("rtsp_url", "")
    else:
        if not (payload.get("rtsp_url") or "").lower().startswith("rtsp://"):
            raise HTTPException(400, "Mode RTSP : l'URL RTSP est obligatoire (rtsp://…)")

    # ── Chiffrement Fernet du mot de passe caméra (R05 / ADR-06) ──
    # Idempotent : ne re-chiffre pas si déjà chiffré (utile quand payload garde
    # l'ancien mot de passe existing.password déjà chiffré).
    from crypto_utils import encrypt_secret
    if payload.get("password"):
        payload["password"] = encrypt_secret(payload["password"])

    await db.cameras.update_one({"id": camera_id}, {"$set": payload})
    await log_audit(user, "camera_updated", data.name, f"Mode: {data.mode}")
    updated = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    from streaming import register_camera_stream
    # NOTE: update_camera invoque register_camera_stream qui est désormais idempotent
    # (skip si config identique). Cela évite de déconnecter les consommateurs actifs
    # quand l'utilisateur modifie une prop non-streaming (ex : nom, coordonnées lat/lng).
    registered = await register_camera_stream(updated, caller=f"PUT /api/cameras/{camera_id} user={user.get('email','?')}")
    if not registered and camera_id not in {"demo-cam-001", "demo-cam-002"}:
        raise HTTPException(400, "Impossible de mettre à jour le flux dans go2rtc")
    updated.pop("password", None)
    return updated


@api_router.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str, user: dict = Depends(require_role("technician"))):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    await db.cameras.delete_one({"id": camera_id})
    from streaming import unregister_camera_stream
    await unregister_camera_stream(camera_id, caller=f"DELETE /api/cameras user={user.get('email','?')}")
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
async def ptz_command(camera_id: str,
                      command: str = Query(...),
                      speed: float = Query(0.5, ge=0.0, le=1.0),
                      duration: float = Query(0.5, ge=0.0, le=3.0),
                      user: dict = Depends(require_permission("ptz_control"))):
    """Pilotage PTZ ONVIF **réel**.

    Commandes : pan_left, pan_right, tilt_up, tilt_down, zoom_in, zoom_out, stop, home.
    - `speed` [0..1] : vitesse relative
    - `duration` [0..3] : durée en secondes du mouvement continu avant `Stop`
    """
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    if not cam.get("ptz_enabled"):
        raise HTTPException(400, "PTZ non supporté sur cette caméra")
    if (cam.get("mode") or "rtsp") != "onvif" or not cam.get("ip"):
        raise HTTPException(400, "PTZ nécessite une caméra en mode ONVIF avec IP configurée")

    from crypto_utils import decrypt_secret
    from streaming import _ptz_execute
    pwd = decrypt_secret(cam.get("password", ""))
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _ptz_execute,
                cam["ip"], int(cam.get("onvif_port") or 80),
                cam.get("username", ""), pwd,
                command, speed, duration,
            ),
            timeout=15,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, "Timeout PTZ : caméra ne répond pas")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Échec PTZ : {type(e).__name__}: {str(e)[:160]}")

    await log_audit(user, "ptz_command", cam.get("name", camera_id), command)
    return result


@api_router.get("/cameras/{camera_id}/ptz/presets")
async def ptz_list_presets(camera_id: str, user: dict = Depends(require_permission("ptz_control"))):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    if not cam.get("ptz_enabled") or (cam.get("mode") or "rtsp") != "onvif":
        raise HTTPException(400, "PTZ ONVIF requis")
    from crypto_utils import decrypt_secret
    from streaming import _ptz_list_presets
    pwd = decrypt_secret(cam.get("password", ""))
    try:
        presets = await asyncio.wait_for(
            asyncio.to_thread(_ptz_list_presets, cam["ip"], int(cam.get("onvif_port") or 80),
                              cam.get("username", ""), pwd),
            timeout=10,
        )
    except Exception as e:
        raise HTTPException(502, f"Échec ONVIF: {type(e).__name__}: {str(e)[:160]}")
    return {"presets": presets}


@api_router.post("/cameras/{camera_id}/ptz/preset/{preset_token}")
async def ptz_goto_preset(camera_id: str, preset_token: str,
                          speed: float = Query(0.6, ge=0.0, le=1.0),
                          user: dict = Depends(require_permission("ptz_control"))):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    if not cam.get("ptz_enabled") or (cam.get("mode") or "rtsp") != "onvif":
        raise HTTPException(400, "PTZ ONVIF requis")
    from crypto_utils import decrypt_secret
    from streaming import _ptz_goto_preset
    pwd = decrypt_secret(cam.get("password", ""))
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_ptz_goto_preset, cam["ip"], int(cam.get("onvif_port") or 80),
                              cam.get("username", ""), pwd, preset_token, speed),
            timeout=15,
        )
    except Exception as e:
        raise HTTPException(502, f"Échec PTZ preset: {type(e).__name__}: {str(e)[:160]}")
    await log_audit(user, "ptz_goto_preset", cam.get("name", camera_id), preset_token)
    return result


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
    # Vérifie l'état go2rtc réel (source + variantes _hd/_sd)
    from streaming import _stream_name, _stream_registered
    name = _stream_name(camera_id)
    go2rtc_ok = await _stream_registered(name)
    hd_ok = await _stream_registered(f"{name}_hd")
    sd_ok = await _stream_registered(f"{name}_sd")
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
            "go2rtc_hd_registered": hd_ok,
            "go2rtc_sd_registered": sd_ok,
            "camera_online": cam.get("status") == "online",
            "rtsp_transport_used": cam.get("rtsp_transport") or "tcp",
            "stream_urls": {
                "live_mjpeg": f"/api/stream/{camera_id}/live.mjpeg",
                "live_mjpeg_hd": f"/api/stream/{camera_id}/live.mjpeg?hd=1",
                "frame_jpeg": f"/api/stream/{camera_id}/frame.jpeg",
                "frame_jpeg_hd": f"/api/stream/{camera_id}/frame.jpeg?hd=1",
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


@api_router.post("/cameras/{camera_id}/refresh-stream")
async def refresh_camera_stream(camera_id: str, user: dict = Depends(require_role("technician"))):
    """Force la (ré)-registration complète du flux caméra dans go2rtc.
    Utile quand :
      - la caméra a été créée avant l'upgrade v2.13.0 (variantes _hd/_sd manquantes),
      - go2rtc a été redémarré et le flux n'a pas encore été (ré)-enregistré,
      - l'URL RTSP en base a été mise à jour (nouveau profil ONVIF) mais go2rtc a
        gardé l'ancienne config.

    Recrée les 3 flux : source RTSP + variante MJPEG HD (native) + variante MJPEG SD (640).
    """
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    from streaming import register_camera_stream, _mask_url_password
    # force=True car c'est l'action explicite "Réparer" — l'utilisateur veut le DELETE+PUT
    ok = await register_camera_stream(cam, caller=f"refresh-stream user={user.get('email','?')}",
                                       force=True)
    if not ok:
        raise HTTPException(502, "Impossible d'enregistrer le flux dans go2rtc")
    await log_audit(user, "camera_stream_refreshed", cam.get("name", camera_id),
                    f"URL: {_mask_url_password(cam.get('rtsp_url',''))}")
    return {"success": True, "camera_id": camera_id,
             "rtsp_url_masked": _mask_url_password(cam.get("rtsp_url", ""))}


# ============ DIAGNOSTIC CAMÉRA (Phase 1) ============
@api_router.get("/diagnostics/journal")
async def diagnostics_journal(camera_id: Optional[str] = None, cause: Optional[str] = None,
                                event_type: Optional[str] = None, limit: int = 100, offset: int = 0,
                                user: dict = Depends(require_permission("view_live"))):
    """Journal global des incidents caméra — filtrable par caméra, cause probable, ou type d'événement.
    Les caméras hors des sites autorisés sont filtrées.
    """
    q: dict = {}
    if camera_id:
        q["camera_id"] = camera_id
    if cause:
        q["cause"] = cause
    if event_type:
        q["event_type"] = event_type
    # Filtrage multi-site
    allowed = allowed_sites(user)
    if allowed is not None:
        q["site_id"] = {"$in": list(allowed)}
    total = await db.camera_diagnostics.count_documents(q)
    docs = await db.camera_diagnostics.find(q, {"_id": 0}).sort("timestamp", -1).skip(offset).limit(limit).to_list(limit)
    return {"total": total, "items": docs}


@api_router.get("/diagnostics/camera/{camera_id}/summary")
async def diagnostics_camera_summary(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    """Résumé d'exploitation (uptime, MTBF, moyenne reconnexion, top causes) — 30 j."""
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    from diagnostics import camera_diagnostic_summary
    return await camera_diagnostic_summary(camera_id)


@api_router.get("/diagnostics/stream-lifecycle/{camera_id}")
async def diagnostics_stream_lifecycle(camera_id: str, limit: int = 100,
                                         user: dict = Depends(require_permission("view_live"))):
    """Journal circulaire en mémoire du cycle de vie du stream d'une caméra.

    Retourne les N dernières transitions (max 100) avec pour chaque entrée :
      - ts       : timestamp UTC ISO 8601
      - action   : created / registered_idempotent / destroyed / consumer_attached /
                   consumer_detached / status_probe_ok / status_probe_fail /
                   status_offline_confirmed / status_online_restored /
                   webrtc_negotiation / variants_ensured / stream_absent_from_go2rtc / ...
      - reason   : texte libre explicatif
      - caller   : qui a déclenché l'action (endpoint + user, ou processus interne)
      - extra    : dict optionnel avec détails structurés

    Utilisé pour diagnostiquer les cycles de déconnexion/reconnexion : si une caméra
    subit un cycle, ce journal montre EXACTEMENT quel composant démonte/remonte
    le stream et pourquoi.
    """
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "id": 1, "name": 1})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    from lifecycle import get_journal, get_probe_counter
    return {
        "camera_id": camera_id,
        "camera_name": cam.get("name", ""),
        "consecutive_probe_failures": get_probe_counter(camera_id),
        "entries": get_journal(camera_id, limit=limit),
    }


@api_router.get("/diagnostics/stream-lifecycle")
async def diagnostics_stream_lifecycle_summary(user: dict = Depends(require_permission("view_live"))):
    """Résumé du journal lifecycle pour toutes les caméras (nb entrées + dernière action).
    Utile pour repérer d'un coup d'œil les caméras qui subissent un cycle anormal."""
    from lifecycle import get_all_journal_summary
    return {"summary": get_all_journal_summary()}


@api_router.get("/diagnostics/frame-source")
async def diagnostics_frame_source(user: dict = Depends(require_permission("view_live"))):
    """État des workers FFmpeg-CUDA persistants (frame_source module).

    Retourne pour chaque worker actif :
      - codec, résolution, mode GPU actif
      - restart_count : nombre de redémarrages depuis le boot (≥ 1 = crash upstream)
      - last_frame_age_s : âge de la dernière frame produite (None si aucune)
      - alive : le thread reader tourne toujours
      - last_error : dernière ligne stderr ffmpeg (utile pour diag RTSP timeout / codec issue)

    Utilisé par la page Diagnostics pour vérifier que l'IA reçoit bien des frames GPU.
    """
    from frame_source import status
    return status()


@api_router.get("/diagnostics/ai-health")
async def diagnostics_ai_health(user: dict = Depends(require_permission("view_live"))):
    """État exhaustif du pipeline IA (Phase 0 RCA v2.21.0).

    Utile en prod pour comprendre POURQUOI l'IA ne détecte rien :
      - `yolo_loaded` / `yolo_error` : YOLO chargé ? sinon message d'erreur
      - `alpr_loaded` / `alpr_error` : fast-alpr chargé ?
      - `torch_available` / `torch_cuda_available` / `torch_version` : état PyTorch
      - `ultralytics_version` : version ultralytics
      - `device_effective` : GPU ou CPU réellement utilisé
      - `cycles_total` / `last_cycle_ts` / `last_cycle_error` : la boucle tourne-t-elle ?
      - `loop_alive` : la coroutine ai_loop est-elle démarrée ?
      - `force_cpu_env` : la var d'env `MGVMS_AI_FORCE_CPU` est-elle active ?

    Astuce prod : si `yolo_loaded=false` ET `torch_available=true`, l'erreur exacte
    est dans `yolo_error` (ex. modèle introuvable, incompat CUDA↔driver, VRAM saturée).
    """
    from ai_engine import get_ai_health
    return get_ai_health()


@api_router.get("/plugins/registry")
async def list_plugins_registry(user: dict = Depends(require_permission("view_live"))):
    """Registre déclaratif du bundle NG (Preview NG v2.30 · chantier A).

    **Note** : différent du legacy `GET /api/plugins` (`plugins.py`) qui liste
    les plugins actifs de l'ancien modèle. Cet endpoint expose le nouveau
    catalogue Plugin Manager (chapitre 11) synchronisé avec `_ai_health`.
    """
    from plugin_manager import registry
    from ai_engine import get_ai_health
    registry.sync_from_ai_health(get_ai_health())
    return {
        "plugins": registry.list_plugins(),
        "core_version": "2.30.0-preview-ng",
        "plugin_manager_version": "0.1.0",
    }


@api_router.get("/plugins/registry/{name}")
async def get_plugin_registry(name: str, user: dict = Depends(require_permission("view_live"))):
    """Détail d'un plugin du registre NG (Preview NG v2.30)."""
    from plugin_manager import registry
    from ai_engine import get_ai_health
    registry.sync_from_ai_health(get_ai_health())
    info = registry.get(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' introuvable")
    return info.to_dict()


@api_router.get("/diagnostics/streams-sync")
async def diagnostics_streams_sync(user: dict = Depends(require_permission("technician"))):
    """Phase 2 (v2.22.0) — Réconciliation DB ↔ go2rtc.

    Diagnostic pur (aucune écriture) qui expose :
      - `in_sync[]` : caméras alignées des 2 côtés
      - `missing_in_go2rtc[]` : caméras en DB mais absentes du moteur → nécessite un
        `sync_all_streams()` (bouton "Resynchroniser go2rtc")
      - `orphan_in_go2rtc[]` : flux orphelins dans go2rtc (caméra supprimée en DB
        pendant que go2rtc était HS)
      - `variant_drift[]` : producteur OK mais variantes `_hd`/`_sd` manquantes
      - `go2rtc_reachable` / `go2rtc_error` : le moteur vidéo répond-il ?

    Utile après un `docker restart go2rtc` ou un reset de conteneur pour vérifier
    que tous les flux sont bien re-provisionnés côté moteur vidéo.
    """
    from streaming import reconcile_streams_with_go2rtc
    return await reconcile_streams_with_go2rtc()


@api_router.post("/diagnostics/streams-sync/repair")
async def diagnostics_streams_sync_repair(user: dict = Depends(require_permission("technician"))):
    """Phase 2 (v2.22.0) — Force la resynchronisation complète DB → go2rtc.

    Appelle `sync_all_streams()` qui :
      1. Nettoie les flux temporaires `probe_*` orphelins
      2. Garantit les caméras démo
      3. (Re)-enregistre les caméras réelles absentes de go2rtc
      4. Ajoute les variantes `_hd`/`_sd` manquantes sur les producteurs existants

    Idempotent : n'écrase pas les flux déjà présents avec la bonne config.
    Après appel, refaire un `GET /diagnostics/streams-sync` pour vérifier `missing_in_go2rtc == []`.

    Auditté : `stream_sync_repair` par l'utilisateur `{user.email}`.
    """
    from streaming import sync_all_streams, reconcile_streams_with_go2rtc
    from auth import log_audit
    await log_audit(user, "stream_sync_repair", details="manual")
    await sync_all_streams()
    # Retourne le nouvel état pour affichage immédiat
    return await reconcile_streams_with_go2rtc()


@api_router.get("/diagnostics/camera/{camera_id}/logs")
async def diagnostics_camera_logs(camera_id: str, lines: int = 100,
                                    user: dict = Depends(require_permission("view_live"))):
    """Récupère les dernières lignes de logs (backend + go2rtc) mentionnant cette caméra."""
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    from diagnostics import camera_recent_errors
    return await camera_recent_errors(camera_id, camera_name=cam.get("name", ""), lines=max(1, min(500, lines)))


@api_router.get("/diagnostics/camera/{camera_id}/report")
async def diagnostics_camera_report(camera_id: str, user: dict = Depends(require_permission("view_live"))):
    """Rapport complet téléchargeable (JSON) — configuration caméra + résumé + historique + logs."""
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    from streaming import _mask_url_password, _stream_registered, _stream_name
    from diagnostics import camera_diagnostic_summary, camera_recent_errors
    name = _stream_name(camera_id)
    incidents = await db.camera_diagnostics.find(
        {"camera_id": camera_id}, {"_id": 0},
    ).sort("timestamp", -1).limit(200).to_list(200)
    summary = await camera_diagnostic_summary(camera_id)
    logs = await camera_recent_errors(camera_id, camera_name=cam.get("name", ""), lines=200)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "camera": {
            "id": camera_id,
            "name": cam.get("name"),
            "site_name": cam.get("site_name"),
            "manufacturer": cam.get("manufacturer"),
            "model": cam.get("model"),
            "mode": cam.get("mode"),
            "profile_name": cam.get("profile_name"),
            "resolution": cam.get("resolution"),
            "fps": cam.get("fps"),
            "codec": cam.get("codec"),
            "rtsp_transport": cam.get("rtsp_transport"),
            "rtsp_url_masked": _mask_url_password(cam.get("rtsp_url", "")),
            "status": cam.get("status"),
            "last_seen": cam.get("last_seen"),
            "detect_enabled": cam.get("detect_enabled"),
        },
        "go2rtc": {
            "source_registered": await _stream_registered(name),
            "hd_registered": await _stream_registered(f"{name}_hd"),
            "sd_registered": await _stream_registered(f"{name}_sd"),
        },
        "summary": summary,
        "recent_incidents": incidents,
        "recent_logs": logs,
    }
    return report


class ManualIncidentInput(BaseModel):
    error_text: str
    source: str = "manual"


@api_router.post("/diagnostics/camera/{camera_id}/test-cause")
async def diagnostics_test_cause(camera_id: str, data: ManualIncidentInput,
                                    user: dict = Depends(require_role("admin"))):
    """Utilitaire : teste l'heuristique de cause probable sur un texte d'erreur brut.
    Pratique pour valider les patterns après ajout de nouveaux logs constructeur."""
    from diagnostics import identify_cause
    cause, confidence, detail = identify_cause(data.error_text)
    return {"cause": cause, "confidence": confidence, "detail": detail,
             "input_preview": data.error_text[:200]}


# ============ GPU / ACCÉLÉRATION MATÉRIELLE (Phase 3) ============
@api_router.get("/system/gpu/summary")
async def system_gpu_summary(user: dict = Depends(get_current_user)):
    """Snapshot compact du GPU pour le header web (poll ~5-10s).
    Retourne `{available, vendor, name, gpu_util_pct, vram_*, temperature_c}`.
    Sans GPU NVIDIA : `available=False` + `error` explicite."""
    from gpu import gpu_summary
    return gpu_summary()


@api_router.get("/system/gpu")
async def system_gpu_full(user: dict = Depends(require_role("technician"))):
    """Rapport complet GPU + runtimes CUDA/TensorRT/ONNX/OpenCV + pipeline actif.
    Pour la page /gpu (accélération matérielle)."""
    from gpu import gpu_full_info
    return gpu_full_info()


# ============ MOTEUR VIDÉO — Config, statut, WebRTC (Phase 4) ============
@api_router.get("/pipeline/config")
async def pipeline_config_get(user: dict = Depends(require_permission("view_live"))):
    """Config actuelle du moteur vidéo (modes globaux + prévisualisation)."""
    from video_engine import get_config, _ffmpeg_capabilities, has_cuda_pipeline
    return {"config": await get_config(),
             "capabilities": _ffmpeg_capabilities(),
             "cuda_pipeline_ready": has_cuda_pipeline()}


class PipelineConfigInput(BaseModel):
    pipeline_mode: Optional[str] = None   # auto | gpu | cpu | direct
    preview_mode: Optional[str] = None    # auto | webrtc | mjpeg | mse
    ai_pipeline: Optional[str] = None     # auto | gpu | cpu
    recorder_mode: Optional[str] = None   # auto | copy | reencode
    hd_preview_width: Optional[int] = None
    sd_preview_width: Optional[int] = None
    sd_preview_fps: Optional[int] = None
    low_latency: Optional[bool] = None


@api_router.put("/pipeline/config")
async def pipeline_config_set(data: PipelineConfigInput, user: dict = Depends(require_role("admin"))):
    """Met à jour la config du moteur vidéo. Force la ré-création des variantes go2rtc."""
    from video_engine import set_config
    payload = {k: v for k, v in data.dict().items() if v is not None}
    allowed_vals = {
        "pipeline_mode": ("auto", "gpu", "cpu", "direct"),
        "preview_mode": ("auto", "webrtc", "mjpeg", "mse"),
        "ai_pipeline": ("auto", "gpu", "cpu"),
        "recorder_mode": ("auto", "copy", "reencode"),
    }
    for k, allowed in allowed_vals.items():
        if k in payload and payload[k] not in allowed:
            raise HTTPException(400, f"{k}: valeurs autorisées {allowed}")
    new = await set_config(payload)
    await log_audit(user, "pipeline_config_updated", "video_engine",
                     f"nouvelle config: {payload}")
    return {"success": True, "config": new,
             "note": "Les nouveaux paramètres s'appliqueront au prochain (re)enregistrement des flux — utilisez /refresh-stream par caméra pour forcer."}


@api_router.get("/pipeline/status")
async def pipeline_status(user: dict = Depends(require_permission("view_live"))):
    """Rapport global : config + capacités FFmpeg + pipeline effectif par caméra."""
    from video_engine import engine_status
    return await engine_status()


@api_router.get("/pipeline/webrtc/offer/{camera_id}")
async def pipeline_webrtc_url(camera_id: str, user: dict = Depends(get_current_user)):
    """URL du WebRTC signaling go2rtc pour cette caméra.
    Le frontend utilise `RTCPeerConnection` avec cette URL comme signaling websocket.
    go2rtc gère la négociation SDP et streaming H.264 en pass-through (aucun transcodage).
    """
    from streaming import _stream_name, _authorize_camera
    await _authorize_camera(user, camera_id)
    name = _stream_name(camera_id)
    # URL relative (le frontend construit l'URL WS en préfixant REACT_APP_BACKEND_URL)
    return {"ws_url": f"/webrtc/api/ws?src={name}", "src": name}


class WebRTCOfferInput(BaseModel):
    type: str
    sdp: str


@api_router.post("/pipeline/webrtc/{camera_id}")
async def pipeline_webrtc_offer(camera_id: str, offer: WebRTCOfferInput,
                                  user: dict = Depends(get_current_user)):
    """Proxy WebRTC signaling — le frontend POST son SDP offer ici, on relaie à
    go2rtc `/api/webrtc?src={name}` et on renvoie la SDP answer. Aucun WS ni
    reverse-proxy custom nécessaire : la communication passe uniquement par
    `/api/pipeline/webrtc/*` (donc par le backend authentifié).

    Le média (RTP DTLS-SRTP) est ensuite négocié en direct navigateur↔go2rtc
    via ICE — go2rtc utilise typiquement les ports 8555 (WebRTC) + un range UDP.
    """
    from streaming import _stream_name, _authorize_camera, GO2RTC_URL, _ensure_variants_cached
    await _authorize_camera(user, camera_id)
    name = _stream_name(camera_id)
    # Vérifie que le flux source existe côté go2rtc (throttled)
    await _ensure_variants_cached(name)
    from lifecycle import record as _lc_record
    _lc_record(camera_id, "webrtc_negotiation",
               reason="SDP offer received",
               caller=f"{user.get('email','?')}")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{GO2RTC_URL}/api/webrtc",
                params={"src": name},
                json={"type": offer.type, "sdp": offer.sdp},
            )
        if r.status_code != 200:
            _lc_record(camera_id, "webrtc_failed",
                       reason=f"go2rtc HTTP {r.status_code}", caller="webrtc_offer")
            raise HTTPException(502, f"go2rtc WebRTC signaling échec: HTTP {r.status_code} · {r.text[:400]}")
        _lc_record(camera_id, "webrtc_answered", reason="SDP answer relayed to browser",
                   caller="webrtc_offer")
        return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"go2rtc unreachable: {type(e).__name__}: {e}")
# ============ COMPARAISON PERFORMANCE ANPR (Phase 3 - section 12) ============
@api_router.post("/system/anpr-benchmark")
async def anpr_benchmark(camera_id: Optional[str] = None,
                          iterations: int = 5,
                          user: dict = Depends(require_role("technician"))):
    """Mesure la performance du pipeline ANPR sur un frame réel (ou test pattern).
    Utile pour comparer 2 versions de MG-VMS et diagnostiquer un ralentissement.

    Retourne :
      - `resolution_analyzed` : taille du frame utilisé
      - `avg_yolo_ms` : temps moyen de détection YOLO
      - `avg_alpr_ms` : temps moyen d'OCR plaque
      - `avg_total_ms` : cycle IA complet (fetch+yolo+alpr+encode)
      - `plates_detected` : nombre de plaques trouvées (agrégé sur les itérations)
      - `plates_ocr_success` : plaques dont l'OCR retourne au moins 4 caractères
      - `plates_ocr_failed` : YOLO a trouvé mais OCR incapable
      - `estimated_fps` : 1000 / avg_total_ms
      - `gpu_active` : le pipeline utilise-t-il le GPU
      - `models_info` : version + backend YOLO / ALPR
    """
    from gpu import is_gpu_active_for_pipeline, _runtime_pytorch
    from ai_engine import _analyze_frame, _fetch_frame, _model_name, _alpr_model_name
    if iterations < 1 or iterations > 30:
        raise HTTPException(400, "iterations doit être entre 1 et 30")
    # Choix du frame source
    cam_id = camera_id
    if not cam_id:
        # Prend n'importe quelle caméra online (préfère demo-cam-002 qui a de vrais véhicules)
        cam = await db.cameras.find_one({"status": "online"}, sort=[("id", 1)])
        if not cam:
            raise HTTPException(400, "Aucune caméra online — impossible de récupérer un frame")
        cam_id = cam["id"]
    frame_bytes = await _fetch_frame(cam_id)
    if not frame_bytes:
        raise HTTPException(502, f"Impossible de récupérer un frame de la caméra {cam_id}")
    # Décode UNE fois pour connaître la résolution
    import cv2
    import numpy as np
    arr = np.frombuffer(frame_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    resolution = f"{img.shape[1]}x{img.shape[0]}" if img is not None else "unknown"
    # Warm-up (compile CUDA kernels + charge modèles) — 1 passe non comptée
    await asyncio.to_thread(_analyze_frame, cam_id, frame_bytes)
    # N itérations mesurées
    samples: list[dict] = []
    plates_ok = 0
    plates_ko = 0
    plates_total = 0
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = await asyncio.to_thread(_analyze_frame, cam_id, frame_bytes)
        total_ms = (time.perf_counter() - t0) * 1000.0
        tim = result.get("timings", {})
        plates = result.get("plates", [])
        plates_total += len(plates)
        for p in plates:
            plate = p.get("plate", "") or ""
            if len(plate.strip()) >= 4:
                plates_ok += 1
            else:
                plates_ko += 1
        samples.append({
            "total_ms": round(total_ms, 1),
            "yolo_ms": round(tim.get("yolo_ms", 0), 1),
            "alpr_ms": round(tim.get("alpr_ms", 0), 1),
            "detections": len(result.get("detections", [])),
            "plates": len(plates),
        })
    avg = lambda k: round(sum(s[k] for s in samples) / len(samples), 1)  # noqa: E731
    avg_total = avg("total_ms")
    return {
        "camera_id": cam_id,
        "iterations": iterations,
        "resolution_analyzed": resolution,
        "avg_total_ms": avg_total,
        "avg_yolo_ms": avg("yolo_ms"),
        "avg_alpr_ms": avg("alpr_ms"),
        "estimated_fps": round(1000.0 / avg_total, 2) if avg_total > 0 else 0,
        "plates_detected_total": plates_total,
        "plates_ocr_success": plates_ok,
        "plates_ocr_failed": plates_ko,
        "ocr_success_rate": round(plates_ok / plates_total * 100, 1) if plates_total else 0,
        "avg_detections_per_frame": round(sum(s["detections"] for s in samples) / len(samples), 1),
        "gpu_active": is_gpu_active_for_pipeline(),
        "torch_backend": "cuda" if _runtime_pytorch().get("available") else "cpu",
        "torch_version": _runtime_pytorch().get("version"),
        "cuda_version": _runtime_pytorch().get("cuda_version"),
        "yolo_model": _model_name(),
        "alpr_model": _alpr_model_name(),
        "samples": samples,
        "run_at": datetime.now(timezone.utc).isoformat(),
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
# → Extrait vers `routes/audit.py`


# ============ USERS (admin) ============
# → Extrait vers `routes/users.py`


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
