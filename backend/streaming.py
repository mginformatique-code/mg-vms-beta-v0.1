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
from pathlib import Path
from typing import Optional
from urllib.parse import quote as urlquote

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
    """Construit l'URL RTSP finale en injectant les identifiants **encodés**.
    Encode automatiquement `# @ + : espace /` afin que les mots de passe complexes fonctionnent."""
    url = (cam.get("rtsp_url") or "").strip()
    if not url:
        return ""
    user = (cam.get("username") or "").strip()
    pwd = cam.get("password") or ""
    if user and "@" not in url and url.lower().startswith("rtsp://"):
        # RFC 3986 : n'autoriser dans user:pass que caractères non réservés
        u_enc = urlquote(user, safe="")
        p_enc = urlquote(pwd, safe="")
        url = url.replace("rtsp://", f"rtsp://{u_enc}:{p_enc}@", 1)
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
    """Déclare (ou met à jour) le flux d'une caméra dans go2rtc.
    IMPORTANT : ne pas appeler dans une boucle périodique — la re-registration
    déconnecte tous les consommateurs (live/recorder/IA). Uniquement sur
    create / update / réparation ciblée."""
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
            # UNE seule source RTSP → un seul décodage. Les consommateurs MJPEG
            # obtiennent la conversion à la demande via /api/stream.mjpeg (go2rtc pipeline).
            r = await client.put(f"{GO2RTC_URL}/api/streams",
                                 params=[("name", name), ("src", rtsp_url)])
            r.raise_for_status()
            # Variante SD : produite à la demande, uniquement quand un client la consomme
            r2 = await client.put(f"{GO2RTC_URL}/api/streams",
                                  params=[("name", f"{name}_sd"),
                                          ("src", f"ffmpeg:{name}#video=mjpeg#width=640")])
            r2.raise_for_status()
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
    """Synchronise TOUS les flux caméra + supprime les flux temporaires (`probe_*`).
    Idempotent : appelé au démarrage."""
    # 1) Nettoyage des flux temporaires orphelins (test-connectivity ayant survécu à un restart)
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(f"{GO2RTC_URL}/api/streams")
            if r.status_code == 200:
                for name in (r.json() or {}):
                    if name.startswith("probe_"):
                        try:
                            await client.delete(f"{GO2RTC_URL}/api/streams", params={"src": name})
                            logger.info("go2rtc: flux temporaire nettoyé — %s", name)
                        except httpx.HTTPError:
                            pass
    except httpx.HTTPError:
        pass
    # 2) Garantir la caméra de démonstration
    await _ensure_demo_camera()
    # 3) (Re)-enregistrement des caméras réelles
    cams = await db.cameras.find({}, {"_id": 0}).to_list(1000)
    n = 0
    for cam in cams:
        if cam.get("id") in DEMO_IDS:
            continue
        if await _stream_registered(_stream_name(cam["id"])):
            continue  # déjà présent — ne PAS re-registrer (éviterait le churn)
        if await register_camera_stream(cam):
            n += 1
    logger.info("go2rtc: %d flux caméra (ré)enregistrés au démarrage", n)


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


# ============ Bibliothèque de fabricants (chargée depuis JSON) ============
BRAND_LIB_PATH = Path(os.environ.get("CAMERA_PROFILES_PATH",
                                     str(Path(__file__).parent / "camera_profiles.json")))


def _load_brand_lib() -> dict:
    try:
        return json.loads(BRAND_LIB_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("camera_profiles.json illisible : %s", e)
        return {"brands": []}


def _resolve_rtsp_template(brand_id: str, model_idx: int, stream_key: str) -> Optional[str]:
    lib = _load_brand_lib()
    for b in lib.get("brands", []):
        if b.get("id") == brand_id:
            models = b.get("models", [])
            if not (0 <= model_idx < len(models)):
                return None
            return models[model_idx].get("streams", {}).get(stream_key)
    return None


def _format_rtsp_from_template(template: str, ip: str, port: int,
                                username: str, password: str, channel: int = 1) -> str:
    """Remplit un template RTSP en encodant les identifiants."""
    return template.format(
        user=urlquote(username or "", safe=""),
        pass_=urlquote(password or "", safe=""),
        **{"pass": urlquote(password or "", safe="")},
        ip=ip, port=port, channel=channel,
    )


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
    mode: str = "rtsp"  # 'rtsp' ou 'onvif'
    ip: str
    rtsp_port: int = 554
    onvif_port: int = 80
    rtsp_url: str = ""
    username: str = ""
    password: str = ""


async def test_connectivity(data: ConnectivityTestInput) -> dict:
    """Test de connexion RÉEL, mode-aware, retourne un tableau `steps[]` de statuts détaillés.
       Chaque étape a: {name, status: 'ok'|'warn'|'error'|'skip', message}."""
    ip = (data.ip or "").strip()
    steps: list[dict] = []
    onvif_info = None
    rtsp_details = None
    rtsp_final_url = ""

    def add(name: str, status: str, message: str, **extra):
        steps.append({"name": name, "status": status, "message": message, **extra})

    if not ip:
        add("ip", "error", "Adresse IP obligatoire")
        return {"success": False, "mode": data.mode, "steps": steps, "message": "Adresse IP obligatoire"}

    # 1) Ping ICMP ou fallback TCP sur port cible (rapide)
    tgt_port = int(data.onvif_port if data.mode == "onvif" else data.rtsp_port)
    ping_ok = await asyncio.to_thread(_tcp_check, ip, tgt_port, 3.0)
    add("ping", "ok" if ping_ok else "error",
        f"IP {ip} joignable sur port {tgt_port}" if ping_ok else f"IP {ip} injoignable (port {tgt_port} fermé)")

    if data.mode == "onvif":
        # 2) Port ONVIF (déjà testé au ping si mode=onvif, on garde une étape claire)
        add("onvif_port", "ok" if ping_ok else "error",
            f"Port ONVIF {data.onvif_port} ouvert" if ping_ok else "Port ONVIF fermé — vérifiez le port")

        # 3) Authentification ONVIF
        if ping_ok:
            try:
                onvif_info = await asyncio.wait_for(
                    asyncio.to_thread(_onvif_probe, ip, int(data.onvif_port), data.username, data.password),
                    timeout=12,
                )
                n_prof = len(onvif_info.get("profiles", []))
                add("onvif_auth", "ok",
                    f"{onvif_info.get('manufacturer','?')} {onvif_info.get('model','?')} · {n_prof} profil(s)",
                    manufacturer=onvif_info.get("manufacturer"),
                    model=onvif_info.get("model"),
                    firmware=onvif_info.get("firmware"),
                    ptz_supported=onvif_info.get("ptz_supported"),
                    profiles=onvif_info.get("profiles", []))
            except asyncio.TimeoutError:
                add("onvif_auth", "error", "Service ONVIF ne répond pas (délai dépassé)")
            except Exception as e:
                add("onvif_auth", "error", f"Auth ONVIF refusée — {type(e).__name__}")
        else:
            add("onvif_auth", "skip", "Ignoré (port ONVIF fermé)")

        # 4) Port RTSP (déduction de l'URI RTSP découverte)
        discovered_rtsp = next((p.get("rtsp_url") for p in (onvif_info or {}).get("profiles", []) if p.get("rtsp_url")), None)
        if discovered_rtsp:
            m = re.match(r"rtsp://[^/]*?([\d.]+)(?::(\d+))?", discovered_rtsp)
            rtsp_host = m.group(1) if m else ip
            rtsp_port = int(m.group(2)) if m and m.group(2) else 554
            rtsp_port_ok = await asyncio.to_thread(_tcp_check, rtsp_host, rtsp_port, 3.0)
            add("rtsp_port", "ok" if rtsp_port_ok else "error",
                f"Port RTSP {rtsp_port} ouvert" if rtsp_port_ok else f"Port RTSP {rtsp_port} fermé")
            # 5) Ouverture RTSP (ffprobe)
            rtsp_final_url = _build_rtsp_url({
                "rtsp_url": discovered_rtsp, "username": data.username, "password": data.password})
            rtsp_details = await asyncio.to_thread(_ffprobe, rtsp_final_url)
            if rtsp_details:
                add("rtsp_open", "ok",
                    f"Flux RTSP OK · {rtsp_details.get('resolution')} @ {rtsp_details.get('fps','?')}fps {rtsp_details.get('codec','')}",
                    **rtsp_details, rtsp_url=discovered_rtsp)
            else:
                add("rtsp_open", "error", "Ouverture RTSP impossible (ffprobe)")
        else:
            add("rtsp_port", "skip", "Ignoré (aucune URI RTSP découverte)")
            add("rtsp_open", "skip", "Ignoré")
    else:
        # Mode RTSP pur
        add("onvif_port", "skip", "Ignoré (mode RTSP)")
        add("onvif_auth", "skip", "Ignoré (mode RTSP)")
        add("rtsp_port", "ok" if ping_ok else "error",
            f"Port RTSP {data.rtsp_port} ouvert" if ping_ok else "Port RTSP fermé")
        rtsp_final_url = _build_rtsp_url({
            "rtsp_url": data.rtsp_url, "username": data.username, "password": data.password})
        if rtsp_final_url.lower().startswith("rtsp://") and ping_ok:
            rtsp_details = await asyncio.to_thread(_ffprobe, rtsp_final_url)
            if rtsp_details:
                add("rtsp_open", "ok",
                    f"Flux RTSP OK · {rtsp_details.get('resolution')} @ {rtsp_details.get('fps','?')}fps {rtsp_details.get('codec','')}",
                    **rtsp_details, rtsp_url=data.rtsp_url)
            else:
                add("rtsp_open", "error", "Ouverture RTSP impossible — URL/identifiants ?")
        else:
            add("rtsp_open", "skip", "Ignoré (URL RTSP invalide ou port fermé)")

    # 6) Test go2rtc : enregistre temporairement le flux et récupère une frame
    go2rtc_ok = False
    preview_url = None
    if rtsp_final_url.lower().startswith("rtsp://") and any(s["name"] == "rtsp_open" and s["status"] == "ok" for s in steps):
        tmp_name = f"probe_{int(time.time()*1000)}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.put(f"{GO2RTC_URL}/api/streams",
                                     params=[("name", tmp_name), ("src", rtsp_final_url)])
                r.raise_for_status()
                # Attend jusqu'à 6 s qu'une frame soit produite
                for _ in range(6):
                    fr = await client.get(f"{GO2RTC_URL}/api/frame.jpeg", params={"src": tmp_name})
                    if fr.status_code == 200 and fr.content[:3] == b"\xff\xd8\xff":
                        go2rtc_ok = True
                        preview_url = f"/api/stream/preview.jpeg?name={tmp_name}"
                        break
                    await asyncio.sleep(1)
        except httpx.HTTPError:
            pass
        finally:
            # nettoie l'enregistrement de test après quelques secondes
            async def _cleanup(n: str) -> None:
                await asyncio.sleep(30)
                try:
                    async with httpx.AsyncClient(timeout=5) as c:
                        await c.delete(f"{GO2RTC_URL}/api/streams", params={"src": n})
                except httpx.HTTPError:
                    pass
            asyncio.create_task(_cleanup(tmp_name))
        add("go2rtc", "ok" if go2rtc_ok else "warn",
            "go2rtc ouvre le flux et fournit une image" if go2rtc_ok
            else "go2rtc n'a pas réussi à décoder — mais l'URL RTSP est valide",
            preview_url=preview_url, temp_stream=tmp_name)
    else:
        add("go2rtc", "skip", "Ignoré (aucun flux RTSP valide)")

    # 7) Aperçu vidéo (identique à go2rtc.preview_url si dispo)
    add("preview", "ok" if preview_url else "skip",
        "Aperçu vidéo disponible" if preview_url else "Aperçu indisponible",
        preview_url=preview_url)

    critical_ok = all(s["status"] in ("ok", "skip") for s in steps
                      if s["name"] in ("ping", "onvif_auth" if data.mode == "onvif" else "rtsp_open"))
    success = critical_ok

    return {
        "success": success, "mode": data.mode, "steps": steps,
        "manufacturer": (onvif_info or {}).get("manufacturer") if onvif_info else None,
        "model": (onvif_info or {}).get("model") if onvif_info else None,
        "firmware": (onvif_info or {}).get("firmware") if onvif_info else None,
        "profiles": (onvif_info or {}).get("profiles", []) if onvif_info else [],
        "ptz_supported": (onvif_info or {}).get("ptz_supported") if onvif_info else None,
        "resolution": (rtsp_details or {}).get("resolution"),
        "fps": (rtsp_details or {}).get("fps"),
        "codec": (rtsp_details or {}).get("codec"),
        "message": (
            f"Tous les tests {data.mode.upper()} sont passés" if success else
            "Un ou plusieurs tests ont échoué — voir détails"
        ),
    }


# ============ Sonde périodique du statut des caméras (online/offline réel) ============
async def _probe_status_once(cam: dict) -> str:
    """Extrait une image depuis go2rtc pour vérifier que le flux est réellement lisible.
    NE JAMAIS re-enregistrer ici (déconnecterait les consommateurs live/recorder/IA)."""
    name = _stream_name(cam["id"])
    if cam.get("id") not in DEMO_IDS and not await _stream_registered(name):
        # Le flux n'existe pas côté go2rtc (probablement effacé par un restart go2rtc) :
        # une SEULE ré-inscription ciblée, pas de churn.
        if not await register_camera_stream(cam):
            return "offline"
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


# ============ Bibliothèque de fabricants — endpoints ============
@stream_router.get("/cameras/brands")
async def cameras_brands(user: dict = Depends(require_role("technician"))):
    """Renvoie la bibliothèque de fabricants + modèles (JSON extensible côté serveur)."""
    lib = _load_brand_lib()
    return {"brands": [
        {"id": b["id"], "name": b["name"], "default_port": b.get("default_port", 554),
         "models": [{"name": m["name"], "streams": list(m.get("streams", {}).keys()),
                     "help": m.get("help")} for m in b.get("models", [])]}
        for b in lib.get("brands", [])
    ]}


class GenerateRtspInput(BaseModel):
    brand: str
    model_idx: int = 0
    stream: str = "main"  # clé dans models[].streams
    ip: str
    port: int = 554
    channel: int = 1
    username: str = ""
    password: str = ""


@stream_router.post("/cameras/generate-rtsp-url")
async def cameras_generate_rtsp(body: GenerateRtspInput, user: dict = Depends(require_role("technician"))):
    """Génère une URL RTSP à partir d'un fabricant + modèle + type de flux.
       Les identifiants sont automatiquement URL-encodés."""
    tpl = _resolve_rtsp_template(body.brand, body.model_idx, body.stream)
    if not tpl:
        raise HTTPException(400, "Fabricant / modèle / flux inconnu")
    try:
        url = _format_rtsp_from_template(tpl, body.ip, int(body.port),
                                          body.username, body.password, int(body.channel))
    except (KeyError, IndexError, ValueError) as e:
        raise HTTPException(400, f"Template invalide : {e}")
    return {"rtsp_url": url, "template": tpl}


# ============ Détection automatique (ONVIF + probe en une seule opération) ============
class AutoDetectInput(BaseModel):
    ip: str
    onvif_port: int = 80
    username: str = ""
    password: str = ""


@stream_router.post("/cameras/auto-detect")
async def cameras_auto_detect(body: AutoDetectInput, user: dict = Depends(require_role("technician"))):
    """Détection AUTOMATIQUE d'une caméra à partir de son IP :
       - Ouvre ONVIF, récupère fabricant / modèle / firmware / profils / URI RTSP.
       - Renvoie tout ce qu'il faut pour pré-remplir le formulaire (aucune saisie manuelle)."""
    ip = (body.ip or "").strip()
    if not ip:
        raise HTTPException(400, "IP requise")
    if not await asyncio.to_thread(_tcp_check, ip, int(body.onvif_port), 3.0):
        raise HTTPException(400, f"Port ONVIF {body.onvif_port} injoignable sur {ip}")
    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(_onvif_probe, ip, int(body.onvif_port), body.username, body.password),
            timeout=15,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, "Appareil ONVIF injoignable (délai dépassé)")
    except Exception as e:
        raise HTTPException(400, f"ONVIF injoignable : {type(e).__name__} — vérifiez identifiants")
    # ffprobe le premier flux pour enrichir la résolution effective
    profiles = info.get("profiles", [])
    if profiles and profiles[0].get("rtsp_url"):
        details = await asyncio.to_thread(_ffprobe, _build_rtsp_url(
            {"rtsp_url": profiles[0]["rtsp_url"], "username": body.username, "password": body.password}))
        if details:
            info["live_resolution"] = details.get("resolution")
            info["live_fps"] = details.get("fps")
            info["live_codec"] = details.get("codec")
    await log_audit(user, "onvif_auto_detect", target=ip)
    return {"ip": ip, "onvif_port": body.onvif_port, **info}


# ============ Aperçu vidéo depuis un flux temporaire (utilisé par Test Connexion) ============
@stream_router.get("/stream/preview.jpeg")
async def stream_preview(name: str = Query(...), user: dict = Depends(require_role("technician"))):
    """Récupère une image d'un flux temporaire enregistré via l'endpoint test-connectivity."""
    if not re.match(r"^probe_[0-9a-z_-]+$", name):
        raise HTTPException(400, "Nom de flux temporaire invalide")
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(f"{GO2RTC_URL}/api/frame.jpeg", params={"src": name})
    except httpx.HTTPError:
        raise HTTPException(502, "Aperçu indisponible")
    if r.status_code != 200:
        raise HTTPException(502, "Aperçu indisponible")
    return Response(content=r.content, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


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
