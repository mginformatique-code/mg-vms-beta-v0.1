"""MG-VMS — Streaming vidéo RÉEL (go2rtc) + découverte ONVIF réelle.

- Chaque caméra avec une URL RTSP est enregistrée dynamiquement dans go2rtc
  (source native + source de transcodage MJPEG + variante SD 640px).
- Le navigateur lit les flux via les proxys authentifiés /api/stream/...
- La découverte ONVIF utilise WS-Discovery (multicast UDP) + onvif-zeep.
"""
import asyncio
import json
import logging
import os
import re
import socket
import subprocess
import time
from typing import Optional

import httpx
import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from auth import (
    JWT_ALGORITHM, allowed_sites, get_current_user, get_jwt_secret,
    has_permission, log_audit, require_role,
)
from database import db

logger = logging.getLogger("streaming")
stream_router = APIRouter(prefix="/api")

GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://localhost:1984")
DEMO_CAMERA_ID = "demo-cam-001"
DEMO_CAMERAS = [
    {"id": "demo-cam-001", "name": "Caméra Démo (mire réelle)", "model": "MG-VMS TestSource",
     "detect_enabled": False, "record_enabled": True},
    {"id": "demo-cam-002", "name": "Caméra Démo Trafic (IA + LAPI)", "model": "MG-VMS TrafficSource",
     "detect_enabled": True, "record_enabled": True},
]
DEMO_IDS = {c["id"] for c in DEMO_CAMERAS}


# ============ Enregistrement des flux dans go2rtc ============
def _stream_name(camera_id: str) -> str:
    return f"cam_{camera_id}"


def _build_rtsp_url(cam: dict) -> str:
    """Construit l'URL RTSP en injectant identifiants + port si nécessaire."""
    url = (cam.get("rtsp_url") or "").strip()
    if not url:
        return ""
    user = (cam.get("username") or "").strip()
    pwd = cam.get("password") or ""
    if user and "@" not in url and url.lower().startswith("rtsp://"):
        url = url.replace("rtsp://", f"rtsp://{user}:{pwd}@", 1)
    return url


async def _stream_registered(name: str) -> bool:
    """Vérifie que le flux est bien présent côté go2rtc."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{GO2RTC_URL}/api/streams")
            r.raise_for_status()
            return name in (r.json() or {})
    except httpx.HTTPError:
        return False


async def register_camera_stream(cam: dict) -> bool:
    """Déclare (ou met à jour) le flux d'une caméra dans go2rtc."""
    if cam.get("id") in DEMO_IDS:
        return True  # flux de démonstration défini statiquement dans go2rtc.yaml
    rtsp_url = _build_rtsp_url(cam)
    if not rtsp_url.lower().startswith(("rtsp://", "rtmp://", "http://", "https://")):
        return False
    name = _stream_name(cam["id"])
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Supprime l'ancien enregistrement pour repartir propre (évite les producteurs en doublon)
            await client.delete(f"{GO2RTC_URL}/api/streams", params={"src": name})
            await client.delete(f"{GO2RTC_URL}/api/streams", params={"src": f"{name}_sd"})
            r = await client.put(f"{GO2RTC_URL}/api/streams",
                                 params=[("name", name), ("src", rtsp_url),
                                         ("src", f"ffmpeg:{name}#video=mjpeg")])
            r.raise_for_status()
            r2 = await client.put(f"{GO2RTC_URL}/api/streams",
                                  params=[("name", f"{name}_sd"),
                                          ("src", f"ffmpeg:{name}#video=mjpeg#width=640")])
            r2.raise_for_status()
        # Vérifie que go2rtc a bien enregistré le flux
        if not await _stream_registered(name):
            logger.warning("go2rtc: flux %s introuvable après enregistrement", name)
            return False
        return True
    except httpx.HTTPError as e:
        logger.warning("go2rtc: échec enregistrement %s : %s", name, e)
        return False


async def unregister_camera_stream(camera_id: str) -> None:
    if camera_id in DEMO_IDS:
        return
    name = _stream_name(camera_id)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            for stream in (name, f"{name}_sd"):
                await client.delete(f"{GO2RTC_URL}/api/streams", params={"src": stream})
    except httpx.HTTPError:
        pass


async def sync_all_streams() -> None:
    """Au démarrage : (ré)enregistre toutes les caméras + garantit la caméra de démo."""
    await _ensure_demo_camera()
    cams = await db.cameras.find({}, {"_id": 0}).to_list(1000)
    count = 0
    for cam in cams:
        if await register_camera_stream(cam):
            count += 1
    logger.info("go2rtc: %s flux caméra enregistrés", count)


async def _ensure_demo_camera() -> None:
    """Caméras de démonstration : vrais flux H.264 générés localement (pipeline réel)."""
    site = await db.sites.find_one({}, {"_id": 0})
    if not site:
        return
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    for demo in DEMO_CAMERAS:
        if await db.cameras.find_one({"id": demo["id"]}):
            continue
        await db.cameras.insert_one({
            **demo,
            "site_id": site["id"], "site_name": site["name"],
            "ip": "127.0.0.1", "port": 8554, "protocol": "RTSP", "codec": "H264",
            "username": "", "password": "",
            "rtsp_url": f"rtsp://127.0.0.1:8554/cam_{demo['id']}",
            "ptz_enabled": False, "lat": site.get("lat"), "lng": site.get("lng"),
            "status": "online", "last_seen": now, "created_at": now,
        })
        logger.info("Caméra de démonstration créée : %s", demo["name"])


# ============ Test / sonde réels ============
def _tcp_check(host: str, port: int, timeout: float = 3.0) -> bool:
    """TCP connect réel : renvoie True si le port est atteignable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ffprobe(rtsp_url: str) -> Optional[dict]:
    """Sonde ffprobe réelle (résolution, fps, codec)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-rtsp_transport", "tcp",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height,avg_frame_rate,codec_name",
             "-of", "json", rtsp_url],
            capture_output=True, timeout=12,
        )
        info = json.loads(out.stdout or "{}").get("streams", [])
        if not info:
            return None
        s = info[0]
        fps = None
        if s.get("avg_frame_rate") and s["avg_frame_rate"] != "0/0":
            num, _, den = s["avg_frame_rate"].partition("/")
            fps = round(int(num) / int(den or 1))
        return {"resolution": f"{s.get('width')}x{s.get('height')}",
                "fps": fps, "codec": (s.get("codec_name") or "").upper()}
    except Exception:
        return None


async def probe_camera(cam: dict) -> dict:
    """Test de connexion réel : frame via go2rtc + ffprobe sur l'URL RTSP."""
    await register_camera_stream(cam)
    name = _stream_name(cam["id"])
    # Laisse à go2rtc/ffmpeg quelques secondes pour ouvrir le flux
    start = time.monotonic()
    success = False
    for _ in range(6):
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(f"{GO2RTC_URL}/api/frame.jpeg", params={"src": name})
            if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
                success = True
                break
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)
    latency_ms = int((time.monotonic() - start) * 1000)
    details = None
    rtsp = _build_rtsp_url(cam)
    if success and rtsp.lower().startswith("rtsp://"):
        details = await asyncio.to_thread(_ffprobe, rtsp)
    return {
        "success": success,
        "status": "online" if success else "offline",
        "latency_ms": latency_ms if success else None,
        "resolution": (details or {}).get("resolution"),
        "fps": (details or {}).get("fps"),
        "codec": (details or {}).get("codec"),
        "message": "Connexion établie (flux vérifié)" if success
                   else "Flux injoignable — vérifiez l'URL RTSP / identifiants / réseau",
    }


class ConnectivityTestInput(BaseModel):
    ip: str
    rtsp_port: int = 554
    onvif_port: int = 80
    rtsp_url: str = ""
    username: str = ""
    password: str = ""


async def test_connectivity(data: ConnectivityTestInput) -> dict:
    """Test de connectivité RÉEL avant sauvegarde d'une caméra :
       1) IP joignable (TCP sur port RTSP)  2) service ONVIF (TCP sur port ONVIF)  3) flux RTSP accessible."""
    ip = (data.ip or "").strip()
    ip_ok = False
    onvif_ok = False
    rtsp_ok = False
    rtsp_details = None
    if ip:
        ip_ok = await asyncio.to_thread(_tcp_check, ip, data.rtsp_port, 3.0)
        onvif_ok = await asyncio.to_thread(_tcp_check, ip, data.onvif_port, 3.0)
    rtsp_url = _build_rtsp_url({
        "rtsp_url": data.rtsp_url, "username": data.username, "password": data.password})
    if rtsp_url.lower().startswith("rtsp://"):
        rtsp_details = await asyncio.to_thread(_ffprobe, rtsp_url)
        rtsp_ok = rtsp_details is not None
    success = ip_ok and rtsp_ok  # ONVIF signalé mais non bloquant (certaines caméras désactivent ONVIF)
    return {
        "success": success,
        "ip_reachable": ip_ok,
        "onvif_reachable": onvif_ok,
        "rtsp_reachable": rtsp_ok,
        "resolution": (rtsp_details or {}).get("resolution"),
        "fps": (rtsp_details or {}).get("fps"),
        "codec": (rtsp_details or {}).get("codec"),
        "message": (
            "Tous les tests réussis" if success else
            "IP injoignable sur le port RTSP" if not ip_ok else
            "Flux RTSP inaccessible — vérifiez l'URL / identifiants"
        ),
    }


# ============ Sonde périodique du statut des caméras (online/offline réel) ============
async def _probe_status_once(cam: dict) -> str:
    """Extrait une image depuis go2rtc pour vérifier que le flux est réellement lisible."""
    if cam.get("id") in DEMO_IDS:
        name = _stream_name(cam["id"])
    else:
        if not await register_camera_stream(cam):
            return "offline"
        name = _stream_name(cam["id"])
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{GO2RTC_URL}/api/frame.jpeg", params={"src": name})
        if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
            return "online"
    except httpx.HTTPError:
        pass
    return "offline"


async def camera_status_loop() -> None:
    """Sonde périodiquement chaque caméra ; met à jour le statut réel en base."""
    from datetime import datetime, timezone
    await asyncio.sleep(15)  # laisser go2rtc / seeding démarrer
    while True:
        try:
            cams = await db.cameras.find({}, {"_id": 0}).to_list(1000)
            for cam in cams:
                status = await _probe_status_once(cam)
                now = datetime.now(timezone.utc).isoformat()
                changes = {"status": status}
                if status == "online":
                    changes["last_seen"] = now
                await db.cameras.update_one({"id": cam["id"]}, {"$set": changes})
        except Exception:
            logger.exception("camera_status_loop : erreur, reprise dans 30s")
        await asyncio.sleep(30)


# ============ Auth des flux (token en query pour <img>/<video>) ============
async def stream_user(request: Request, token: Optional[str] = Query(None)) -> dict:
    raw = token
    if not raw:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            raw = auth_header[7:]
    if not raw:
        raw = request.cookies.get("access_token")
    if not raw:
        raise HTTPException(401, "Non authentifié")
    try:
        payload = pyjwt.decode(raw, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(401, "Type de jeton invalide")
    except pyjwt.PyJWTError:
        raise HTTPException(401, "Jeton invalide ou expiré")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
    if not user:
        raise HTTPException(401, "Utilisateur introuvable")
    return user


async def _authorize_camera(user: dict, camera_id: str) -> dict:
    if not has_permission(user, "view_live"):
        raise HTTPException(403, "Permission requise : view_live")
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    allowed = allowed_sites(user)
    if allowed is not None and cam.get("site_id") not in allowed:
        raise HTTPException(403, "Accès refusé à cette caméra")
    return cam


def _quality_stream(user: dict, camera_id: str) -> str:
    name = _stream_name(camera_id)
    return name if has_permission(user, "stream_hd") else f"{name}_sd"


# ============ Proxys de flux authentifiés ============
@stream_router.get("/stream/{camera_id}/live.mjpeg")
async def live_mjpeg(camera_id: str, request: Request, user: dict = Depends(stream_user)):
    """Flux vidéo MJPEG temps réel (transcodé par go2rtc depuis le H.264 caméra)."""
    await _authorize_camera(user, camera_id)
    src = _quality_stream(user, camera_id)
    client = httpx.AsyncClient(timeout=httpx.Timeout(15, read=None))
    req = client.build_request("GET", f"{GO2RTC_URL}/api/stream.mjpeg", params={"src": src})
    upstream = await client.send(req, stream=True)
    if upstream.status_code != 200:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(502, "Flux indisponible")

    async def relay():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(relay(), media_type=upstream.headers.get("content-type", "multipart/x-mixed-replace"))


@stream_router.get("/stream/{camera_id}/frame.jpeg")
async def frame_jpeg(camera_id: str, user: dict = Depends(stream_user)):
    """Image instantanée réelle extraite du flux."""
    await _authorize_camera(user, camera_id)
    src = _quality_stream(user, camera_id)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{GO2RTC_URL}/api/frame.jpeg", params={"src": src})
    except httpx.HTTPError:
        raise HTTPException(502, "Flux indisponible")
    if r.status_code != 200:
        raise HTTPException(502, "Flux indisponible")
    return Response(content=r.content, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


# ============ Découverte ONVIF réelle ============
@stream_router.post("/cameras/test-connectivity")
async def cameras_test_connectivity(body: ConnectivityTestInput, user: dict = Depends(require_role("technician"))):
    """Test réel de connectivité AVANT sauvegarde d'une caméra (IP, ONVIF, RTSP)."""
    return await test_connectivity(body)


def _ws_discovery(timeout: int = 4) -> list[dict]:
    """WS-Discovery multicast (bloquant, exécuté dans un thread)."""
    from wsdiscovery.discovery import ThreadedWSDiscovery
    wsd = ThreadedWSDiscovery()
    found: list[dict] = []
    try:
        wsd.start()
        services = wsd.searchServices(timeout=timeout)
        for svc in services:
            xaddrs = svc.getXAddrs()
            types = " ".join(str(t) for t in svc.getTypes())
            if not xaddrs or ("onvif" not in types.lower() and "NetworkVideoTransmitter" not in types):
                continue
            xaddr = xaddrs[0]
            m = re.search(r"https?://([\d.]+)(?::(\d+))?", xaddr)
            found.append({
                "xaddr": xaddr,
                "ip": m.group(1) if m else None,
                "port": int(m.group(2)) if m and m.group(2) else 80,
                "types": types,
            })
    finally:
        wsd.stop()
    return found


@stream_router.post("/cameras/discover")
async def discover_cameras(user: dict = Depends(require_role("technician"))):
    """Découverte ONVIF réelle sur le réseau local (WS-Discovery)."""
    devices = await asyncio.to_thread(_ws_discovery)
    known_ips = {c.get("ip") for c in await db.cameras.find({}, {"_id": 0, "ip": 1}).to_list(1000)}
    for device in devices:
        device["already_added"] = device.get("ip") in known_ips
    await log_audit(user, "onvif_discovery", details=f"{len(devices)} appareil(s) trouvé(s)")
    return {"devices": devices, "count": len(devices)}


class OnvifProbeInput(BaseModel):
    ip: str
    port: int = 80
    username: str = ""
    password: str = ""


def _onvif_probe(ip: str, port: int, username: str, password: str) -> dict:
    """Interroge un appareil ONVIF : infos + profils + URI RTSP (bloquant)."""
    from onvif import ONVIFCamera
    cam = ONVIFCamera(ip, port, username, password)
    device = cam.create_devicemgmt_service()
    info = device.GetDeviceInformation()
    media = cam.create_media_service()
    profiles = media.GetProfiles()
    result_profiles = []
    for profile in profiles:
        try:
            uri = media.GetStreamUri({
                "StreamSetup": {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}},
                "ProfileToken": profile.token,
            })
            rtsp_uri = uri.Uri
        except Exception:
            rtsp_uri = None
        enc = getattr(profile, "VideoEncoderConfiguration", None)
        result_profiles.append({
            "token": profile.token,
            "name": str(profile.Name),
            "rtsp_url": rtsp_uri,
            "codec": str(getattr(enc, "Encoding", "")) if enc else None,
            "resolution": (f"{enc.Resolution.Width}x{enc.Resolution.Height}"
                           if enc and getattr(enc, "Resolution", None) else None),
        })
    ptz = False
    try:
        ptz = bool(getattr(profiles[0], "PTZConfiguration", None))
    except Exception:
        pass
    return {
        "manufacturer": str(info.Manufacturer), "model": str(info.Model),
        "firmware": str(info.FirmwareVersion), "serial": str(info.SerialNumber),
        "ptz_supported": ptz, "profiles": result_profiles,
    }


@stream_router.post("/cameras/onvif-probe")
async def onvif_probe(body: OnvifProbeInput, user: dict = Depends(require_role("technician"))):
    """Connexion ONVIF réelle à un appareil : renvoie modèle, profils et URL RTSP."""
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_onvif_probe, body.ip, body.port, body.username, body.password),
            timeout=20,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, "Appareil ONVIF injoignable (délai dépassé)")
    except Exception as e:
        raise HTTPException(502, f"Échec ONVIF : {type(e).__name__} — vérifiez IP/port/identifiants")
    await log_audit(user, "onvif_probe", target=body.ip)
    return result
