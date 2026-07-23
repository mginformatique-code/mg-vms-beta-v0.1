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
    """Construit l'URL RTSP finale en injectant les identifiants **encodés une seule fois** (RFC 3986).

    - Si l'URL déclare déjà `user:pass@` : ne réencode pas (on considère que l'appelant a déjà encodé).
    - Sinon : encode `username` et `password` avec `urllib.parse.quote(str, safe="")`.
      Exemple : `Rlwt29#+jpf` → `Rlwt29%23%2Bjpf` (jamais `%2523%252B…`).

    NOTE : le fragment `#transport=tcp|udp` a été retiré (retour utilisateur : go2rtc échoue à
    décoder les flux avec ce suffixe). Le transport est désormais géré :
    - côté ffprobe : via l'option CLI `-rtsp_transport tcp|udp` dans `_ffprobe`
    - côté go2rtc : négociation automatique (TCP par défaut pour la plupart des caméras IP)
    """
    url = (cam.get("rtsp_url") or "").strip()
    if not url:
        return ""
    user = (cam.get("username") or "").strip()
    pwd = cam.get("password") or ""
    if user and url.lower().startswith("rtsp://"):
        # Détection stricte de la présence de credentials dans l'URL (avant le premier /)
        after_scheme = url[7:]
        host_part = after_scheme.split("/", 1)[0]
        if "@" not in host_part:
            u_enc = urlquote(str(user), safe="")
            p_enc = urlquote(str(pwd), safe="")
            url = url.replace("rtsp://", f"rtsp://{u_enc}:{p_enc}@", 1)
    # Nettoyage : retire tout fragment `#transport=…` déjà présent (au cas où l'URL viendrait
    # avec cette syntaxe historique)
    if "#transport=" in url:
        idx = url.find("#transport=")
        url = url[:idx]
    return url


def _mask_url_password(url: str) -> str:
    """Masque le mot de passe dans une URL rtsp:// pour affichage sûr côté frontend."""
    if not url:
        return ""
    return re.sub(r"(rtsp://[^:@/]+):([^@/]+)@", lambda m: f"{m.group(1)}:******@", url, count=1, flags=re.IGNORECASE)


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
    create / update / réparation ciblée.

    Enregistre 3 variantes :
      - `{name}`     : source RTSP brute (H.264/H.265) — utilisée par le recorder + IA
      - `{name}_hd`  : ffmpeg → MJPEG à résolution native (aperçu HD)
      - `{name}_sd`  : ffmpeg → MJPEG width=640 (aperçu SD faible bande passante)
    """
    if cam.get("id") in DEMO_IDS:
        return True  # flux de démonstration défini statiquement dans go2rtc.yaml
    rtsp_url = _build_rtsp_url(cam)
    if not rtsp_url.lower().startswith(("rtsp://", "rtmp://", "http://", "https://")):
        return False
    name = _stream_name(cam["id"])
    # Résolution du pipeline effectif (auto/GPU/CPU) — construit les filtres ffmpeg optimisés
    try:
        from video_engine import resolve_pipeline
        pipe = await resolve_pipeline(cam)
        hd_filter = pipe["mjpeg_filter_hd"]
        sd_filter = pipe["mjpeg_filter_sd"]
        logger.info("register_camera_stream %s → mode=%s decoder=%s preview=%s rec=%s ai=%s",
                     name, pipe["mode"], pipe["decoder"], pipe["preview"], pipe["recorder"], pipe["ai"])
    except Exception as e:
        logger.warning("video_engine.resolve_pipeline échec (fallback SW) : %s", e)
        hd_filter = "video=mjpeg"
        sd_filter = "video=mjpeg#width=640"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Supprime les anciens enregistrements (source + variantes) pour repartir propre
            for src in (name, f"{name}_hd", f"{name}_sd"):
                await client.delete(f"{GO2RTC_URL}/api/streams", params={"src": src})
            # 1) Source unique RTSP (un seul décodage) — utilisée par le recorder et l'IA
            r = await client.put(f"{GO2RTC_URL}/api/streams",
                                 params=[("name", name), ("src", rtsp_url)])
            r.raise_for_status()
            # 2) Variante HD : MJPEG à résolution native (avec accel matérielle si dispo)
            r_hd = await client.put(f"{GO2RTC_URL}/api/streams",
                                     params=[("name", f"{name}_hd"),
                                             ("src", f"ffmpeg:{name}#{hd_filter}")])
            r_hd.raise_for_status()
            # 3) Variante SD : MJPEG 640 (avec accel matérielle si dispo)
            r_sd = await client.put(f"{GO2RTC_URL}/api/streams",
                                     params=[("name", f"{name}_sd"),
                                             ("src", f"ffmpeg:{name}#{sd_filter}")])
            r_sd.raise_for_status()
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
            for stream in (name, f"{name}_hd", f"{name}_sd"):
                await client.delete(f"{GO2RTC_URL}/api/streams", params={"src": stream})
    except httpx.HTTPError:
        pass


async def _ensure_variants(name: str) -> None:
    """Garantit que les variantes `{name}_hd` et `{name}_sd` sont enregistrées dans go2rtc.
    Ne touche PAS au producteur principal `{name}` (évite le churn côté recorder/IA).
    Utile lors d'un upgrade de la plateforme : les caméras existantes qui n'avaient
    que la variante SD (ancien code) reçoivent maintenant la variante HD à la volée.
    Reconstruit avec les filtres optimisés du moteur vidéo (NVDEC + scale_cuda si dispo).
    """
    # Récupère la config de la caméra pour construire les bons filtres ffmpeg
    hd_filter = "video=mjpeg"
    sd_filter = "video=mjpeg#width=640"
    try:
        # extraction du camera_id depuis le nom `cam_{id}`
        camera_id = name[4:] if name.startswith("cam_") else name
        cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
        if cam:
            from video_engine import resolve_pipeline
            pipe = await resolve_pipeline(cam)
            hd_filter = pipe["mjpeg_filter_hd"]
            sd_filter = pipe["mjpeg_filter_sd"]
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{GO2RTC_URL}/api/streams")
            existing = set((r.json() or {}).keys()) if r.status_code == 200 else set()
            if f"{name}_hd" not in existing:
                await client.put(f"{GO2RTC_URL}/api/streams",
                                  params=[("name", f"{name}_hd"),
                                          ("src", f"ffmpeg:{name}#{hd_filter}")])
                logger.info("go2rtc: variante HD ajoutée à la volée pour %s (filter=%s)", name, hd_filter)
            if f"{name}_sd" not in existing:
                await client.put(f"{GO2RTC_URL}/api/streams",
                                  params=[("name", f"{name}_sd"),
                                          ("src", f"ffmpeg:{name}#{sd_filter}")])
                logger.info("go2rtc: variante SD ajoutée à la volée pour %s (filter=%s)", name, sd_filter)
    except httpx.HTTPError as e:
        logger.warning("go2rtc: échec ensure_variants(%s) : %s", name, e)


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
    n_new = 0
    n_upgraded = 0
    for cam in cams:
        if cam.get("id") in DEMO_IDS:
            # Les démos : variantes _hd et _sd déjà déclarées statiquement dans go2rtc.yaml,
            # mais on garantit qu'elles existent quand même (utile après upgrade).
            await _ensure_variants(_stream_name(cam["id"]))
            continue
        name = _stream_name(cam["id"])
        if await _stream_registered(name):
            # Producteur principal déjà présent → on ajoute uniquement les variantes manquantes
            # (migration transparente depuis les versions antérieures à v2.13.0 qui n'avaient
            # pas la variante _hd).
            await _ensure_variants(name)
            n_upgraded += 1
            continue
        if await register_camera_stream(cam):
            n_new += 1
    logger.info("go2rtc: %d flux caméra enregistrés (nouveaux) · %d variantes HD/SD garanties (existants)",
                n_new, n_upgraded)


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


def _strip_go2rtc_fragments(url: str) -> str:
    """Retire les fragments spécifiques go2rtc (`#transport=tcp`, `#video=...`) qui ne sont
    PAS des fragments RTSP standards. ffprobe interprète le # comme partie du chemin et
    retourne '404 Stream Not Found'. Cette fonction sanitise l'URL avant l'appel ffprobe."""
    if not url:
        return url
    # Retire tout après le premier #
    idx = url.find("#")
    return url[:idx] if idx >= 0 else url


def _ffprobe(rtsp_url: str, transport: str = "tcp") -> Optional[dict]:
    """Sonde ffprobe réelle (résolution, fps, codec, bitrate).
    Applique le transport RTSP demandé (TCP par défaut) via -rtsp_transport CLI.
    IMPORTANT : retire les fragments `#transport=...` de l'URL avant l'appel — ffprobe
    ne connaît pas ces fragments (spécifiques go2rtc) et répond 404."""
    tr = "tcp" if (transport or "tcp").lower() != "udp" else "udp"
    # Fix critique : ffprobe interprète #transport=tcp comme partie du path → 404
    clean_url = _strip_go2rtc_fragments(rtsp_url)
    masked = _mask_url_password(clean_url)
    logger.info("FFPROBE URL=%s (transport=%s)", masked, tr)
    cmd = ["ffprobe", "-v", "error", "-rtsp_transport", tr,
           "-select_streams", "v:0",
           "-show_entries", "stream=width,height,avg_frame_rate,codec_name,bit_rate",
           "-of", "json", clean_url]
    logger.info("FFPROBE CMD=%s", ["ffprobe", "-rtsp_transport", tr, "…", masked])
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=12)
        logger.info("FFPROBE RC=%s stderr=%r", out.returncode,
                    (out.stderr or b"")[:200].decode(errors="replace"))
        info = json.loads(out.stdout or "{}").get("streams", [])
        if not info:
            logger.info("FFPROBE : aucun stream trouvé (URL invalide ou codec inconnu)")
            return None
        s = info[0]
        fps = None
        if s.get("avg_frame_rate") and s["avg_frame_rate"] != "0/0":
            num, _, den = s["avg_frame_rate"].partition("/")
            fps = round(int(num) / int(den or 1))
        br = None
        try:
            br = int(s.get("bit_rate")) if s.get("bit_rate") else None
        except (ValueError, TypeError):
            br = None
        result = {"resolution": f"{s.get('width')}x{s.get('height')}",
                   "fps": fps, "codec": (s.get("codec_name") or "").upper(),
                   "bitrate": br, "transport": tr}
        logger.info("FFPROBE OK → %s", result)
        return result
    except subprocess.TimeoutExpired:
        logger.warning("FFPROBE TIMEOUT après 12s pour %s", masked)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.exception("FFPROBE crash sur %s : %s", masked, exc)
        return None


# ═══════════════════════════════════════════════════════════════════
# Fallback RTSP — variantes constructeurs (Reolink, Hikvision, Dahua…)
# ═══════════════════════════════════════════════════════════════════
def _rtsp_variants(base_url: str, preferred_codec: str = "auto") -> list:
    """Génère les variantes RTSP à tester selon le codec préféré.
    Priorité 1 : URL d'origine · Priorité 2 : variantes du même flux avec codec préféré ·
    Priorité 3 : autres codecs/streams. Utile quand ONVIF ment (retourne h264Preview
    alors que la caméra encode réellement en H.265)."""
    if not base_url or not base_url.lower().startswith("rtsp://"):
        return [base_url] if base_url else []
    variants = [base_url]  # priorité 1 : URL déclarée par ONVIF

    # Extrait hôte/port (identifiants gérés séparément par _build_rtsp_url)
    m = re.match(r"^(rtsp://)([^/?#]+)(/.*)?$", base_url, re.IGNORECASE)
    if not m:
        return variants
    scheme, host_port, path = m.group(1), m.group(2), m.group(3) or "/"

    # Détecte le pattern Reolink (h264Preview / h265Preview)
    reolink = re.search(r"h26[45]Preview_\d+_(main|sub)", path or "", re.IGNORECASE)
    if reolink:
        # Génère toutes les combinaisons attendues
        combos = [
            "/h264Preview_01_main", "/h265Preview_01_main",
            "/h264Preview_01_sub",  "/h265Preview_01_sub",
            "/h264Preview_02_main", "/h265Preview_02_main",
        ]
        # Ordonne selon codec préféré
        if preferred_codec == "h264":
            combos.sort(key=lambda p: (0 if "h264" in p else 1, 0 if "main" in p else 1))
        elif preferred_codec == "h265":
            combos.sort(key=lambda p: (0 if "h265" in p else 1, 0 if "main" in p else 1))
        else:
            # Auto : main d'abord (H.264 préféré pour compatibilité live/IA)
            combos.sort(key=lambda p: (0 if "main" in p else 1, 0 if "h264" in p else 1))
        for c in combos:
            u = f"{scheme}{host_port}{c}"
            if u not in variants:
                variants.append(u)
        return variants

    # Hikvision : /Streaming/Channels/101 (main) / 102 (sub)
    hik = re.search(r"/Streaming/Channels/(\d+)", path or "", re.IGNORECASE)
    if hik:
        for ch in ("101", "102", "201", "202"):
            u = f"{scheme}{host_port}/Streaming/Channels/{ch}"
            if u not in variants:
                variants.append(u)
        return variants

    # Dahua : /cam/realmonitor?channel=1&subtype=0 (main) / subtype=1 (sub)
    if "realmonitor" in (path or "").lower():
        for ch in (1, 2):
            for st in (0, 1):
                u = f"{scheme}{host_port}/cam/realmonitor?channel={ch}&subtype={st}"
                if u not in variants:
                    variants.append(u)
        return variants

    return variants


def _try_ffprobe_variants(base_url: str, preferred_codec: str, transport: str,
                          username: str = "", password: str = "") -> tuple:
    """Teste chaque URL possible avec l'ordre demandé par l'utilisateur :
       1) H.264 TCP   2) H.265 TCP   3) H.264 UDP   4) H.265 UDP
    (Si `preferred_codec` est forcé h264 ou h265, on ne teste que ce codec sur les 2 transports.)

    Retourne un tuple `(working_url, ffprobe_details, debug_attempts)`."""
    pref = (preferred_codec or "auto").lower()
    variants = _rtsp_variants(base_url, pref)
    logger.info("TRY_VARIANTS base=%s pref=%s transport=%s → %d variante(s) : %s",
                base_url, pref, transport, len(variants),
                [_strip_go2rtc_fragments(v) for v in variants])

    def _variant_codec(u: str) -> str:
        low = u.lower()
        if "h265preview" in low or "hevc" in low:
            return "h265"
        if "h264preview" in low or "avc" in low:
            return "h264"
        return "unknown"

    # Ordre demandé : H264 TCP → H265 TCP → H264 UDP → H265 UDP
    if pref == "h264":
        codecs_seq = ["h264"]
    elif pref == "h265":
        codecs_seq = ["h265"]
    else:
        codecs_seq = ["h264", "h265"]
    # Si le transport user est UDP, on inverse la préférence (UDP en premier)
    tr_seq = ["tcp", "udp"] if (transport or "tcp").lower() != "udp" else ["udp", "tcp"]

    attempts: list = []
    ordered_pairs = []  # (variant_url, transport)
    for tr in tr_seq:
        for cd in codecs_seq:
            # Priorité aux variantes qui correspondent au codec attendu (par nom URL), puis autres
            for v in variants:
                vc = _variant_codec(v)
                if vc == cd or (vc == "unknown" and cd == "h264"):
                    pair = (v, tr)
                    if pair not in ordered_pairs:
                        ordered_pairs.append(pair)

    for variant_url, tr in ordered_pairs:
        full = _build_rtsp_url({"rtsp_url": variant_url, "username": username,
                                 "password": password, "rtsp_transport": tr})
        masked = _mask_url_password(full)
        logger.info("VARIANT_TEST transport=%s url=%s", tr.upper(), masked)
        details = _ffprobe(full, transport=tr)
        attempt = {"url_masked": masked, "transport": tr.upper(),
                    "ok": bool(details),
                    "codec": (details or {}).get("codec"),
                    "resolution": (details or {}).get("resolution"),
                    "fps": (details or {}).get("fps")}
        attempts.append(attempt)
        if not details:
            continue
        codec_up = (details.get("codec") or "").upper()
        if pref == "h264" and codec_up not in ("H264", "AVC"):
            logger.info("VARIANT_TEST skip : codec=%s ≠ preferred=h264", codec_up)
            continue
        if pref == "h265" and codec_up not in ("H265", "HEVC"):
            logger.info("VARIANT_TEST skip : codec=%s ≠ preferred=h265", codec_up)
            continue
        details["rtsp_url_used"] = variant_url
        details["transport_used"] = tr
        logger.info("VARIANT_TEST MATCH → %s (transport=%s, codec=%s)", masked, tr, codec_up)
        return variant_url, details, attempts

    logger.info("VARIANT_TEST : aucune variante n'a répondu (%d tentative(s))", len(attempts))
    return base_url, None, attempts


def _ffprobe_validate_exact(base_url: str, transport: str,
                             username: str = "", password: str = "") -> tuple:
    """Valide EXACTEMENT l'URL fournie (aucune substitution de variante).
    Essaie le transport demandé d'abord, puis l'autre en fallback (tcp↔udp).
    Retourne `(base_url, details, attempts)` — `base_url` reste inchangé.
    Utilisé quand l'utilisateur a explicitement choisi un profil ONVIF (main/sub).
    """
    tr_pref = (transport or "tcp").lower()
    tr_seq = ["tcp", "udp"] if tr_pref != "udp" else ["udp", "tcp"]
    attempts: list = []
    logger.info("EXACT_VALIDATE base=%s pref_transport=%s", base_url, tr_pref)
    for tr in tr_seq:
        full = _build_rtsp_url({"rtsp_url": base_url, "username": username,
                                 "password": password, "rtsp_transport": tr})
        masked = _mask_url_password(full)
        logger.info("EXACT_VALIDATE transport=%s url=%s", tr.upper(), masked)
        details = _ffprobe(full, transport=tr)
        attempt = {"url_masked": masked, "transport": tr.upper(),
                    "ok": bool(details),
                    "codec": (details or {}).get("codec"),
                    "resolution": (details or {}).get("resolution"),
                    "fps": (details or {}).get("fps")}
        attempts.append(attempt)
        if details:
            details["rtsp_url_used"] = base_url
            details["transport_used"] = tr
            logger.info("EXACT_VALIDATE MATCH → %s (transport=%s, codec=%s, res=%s)",
                        masked, tr, details.get("codec"), details.get("resolution"))
            return base_url, details, attempts
    logger.info("EXACT_VALIDATE : URL injoignable sur tcp+udp (%d tentative(s))", len(attempts))
    return base_url, None, attempts


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
        details = await asyncio.to_thread(_ffprobe, rtsp, cam.get("rtsp_transport") or "tcp")
    return {
        "success": success,
        "status": "online" if success else "offline",
        "latency_ms": latency_ms if success else None,
        "resolution": (details or {}).get("resolution"),
        "fps": (details or {}).get("fps"),
        "codec": (details or {}).get("codec"),
        "rtsp_transport": cam.get("rtsp_transport") or "tcp",
        "preferred_codec": cam.get("preferred_codec") or "auto",
        "go2rtc_stream_registered": await _stream_registered(name),
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
    rtsp_transport: str = "tcp"      # tcp | udp
    preferred_codec: str = "auto"    # auto | h264 | h265
    profile_token: str = ""          # profil ONVIF explicite (main/sub) — pas de substitution de variante si fourni


async def test_connectivity(data: ConnectivityTestInput) -> dict:
    """Test de connexion RÉEL, mode-aware, retourne un tableau `steps[]` de statuts détaillés.
       Chaque étape a: {name, status: 'ok'|'warn'|'error'|'skip', message}."""
    logger.info("TEST_CONNECTIVITY start mode=%s ip=%s transport=%s codec_pref=%s",
                data.mode, data.ip, data.rtsp_transport, data.preferred_codec)
    ip = (data.ip or "").strip()
    steps: list[dict] = []
    onvif_info = None
    rtsp_details = None
    rtsp_final_url = ""
    rtsp_url_validated = False
    validated_url_masked = ""
    validated_transport = ""
    debug_attempts: list = []

    def add(name: str, status: str, message: str, **extra):
        steps.append({"name": name, "status": status, "message": message, **extra})

    if not ip:
        logger.info("TEST_CONNECTIVITY early return : IP vide")
        add("ip", "error", "Adresse IP obligatoire")
        return {"success": False, "mode": data.mode, "steps": steps, "message": "Adresse IP obligatoire"}

    # 1) Ping ICMP ou fallback TCP sur port cible (rapide)
    tgt_port = int(data.onvif_port if data.mode == "onvif" else data.rtsp_port)
    ping_ok = await asyncio.to_thread(_tcp_check, ip, tgt_port, 3.0)
    logger.info("TEST_CONNECTIVITY ping %s:%s → %s", ip, tgt_port, ping_ok)
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
        # Si l'utilisateur a explicitement choisi un profil, on utilise SON URL (pas la première).
        onvif_profiles = (onvif_info or {}).get("profiles", [])
        selected_profile = None
        if data.profile_token:
            selected_profile = next((p for p in onvif_profiles if p.get("token") == data.profile_token and p.get("rtsp_url")), None)
        if not selected_profile:
            selected_profile = next((p for p in onvif_profiles if p.get("rtsp_url")), None)
        discovered_rtsp = selected_profile.get("rtsp_url") if selected_profile else None
        selected_profile_name = selected_profile.get("name") if selected_profile else ""
        if discovered_rtsp:
            m = re.match(r"rtsp://[^/]*?([\d.]+)(?::(\d+))?", discovered_rtsp)
            rtsp_host = m.group(1) if m else ip
            rtsp_port = int(m.group(2)) if m and m.group(2) else 554
            rtsp_port_ok = await asyncio.to_thread(_tcp_check, rtsp_host, rtsp_port, 3.0)
            add("rtsp_port", "ok" if rtsp_port_ok else "error",
                f"Port RTSP {rtsp_port} ouvert" if rtsp_port_ok else f"Port RTSP {rtsp_port} fermé")
            # 5) Ouverture RTSP
            # - Si profile_token fourni : validation EXACTE de l'URL du profil (aucune substitution)
            # - Sinon : essai de variantes constructeur (Reolink main/sub, Hik, Dahua) en fallback
            transport = (data.rtsp_transport or "tcp").lower()
            pref = (data.preferred_codec or "auto").lower()
            if data.profile_token:
                working_url, rtsp_details, attempts = await asyncio.to_thread(
                    _ffprobe_validate_exact, discovered_rtsp, transport, data.username, data.password
                )
            else:
                working_url, rtsp_details, attempts = await asyncio.to_thread(
                    _try_ffprobe_variants, discovered_rtsp, pref, transport, data.username, data.password
                )
            if rtsp_details:
                rtsp_final_url = _build_rtsp_url({
                    "rtsp_url": working_url, "username": data.username,
                    "password": data.password,
                    "rtsp_transport": rtsp_details.get("transport_used") or transport})
                profile_label = f" · profil « {selected_profile_name} »" if selected_profile_name else ""
                add("rtsp_open", "ok",
                    f"Flux RTSP OK{profile_label} · {rtsp_details.get('resolution')} @ {rtsp_details.get('fps','?')}fps {rtsp_details.get('codec','')} (transport {(rtsp_details.get('transport_used') or transport).upper()})",
                    **{k: v for k, v in rtsp_details.items() if k not in ("transport_used", "rtsp_url_used")},
                    rtsp_url=working_url, rtsp_url_used=working_url,
                    validated_url_masked=_mask_url_password(rtsp_final_url),
                    transport_used=rtsp_details.get("transport_used"),
                    profile_token=(selected_profile or {}).get("token", ""),
                    profile_name=selected_profile_name,
                    attempts=attempts)
                rtsp_url_validated = True
                validated_url_masked = _mask_url_password(rtsp_final_url)
                validated_transport = rtsp_details.get("transport_used") or transport
                debug_attempts = attempts
            else:
                # Ajoute le contexte : quelles variantes ont été essayées (mode debug)
                add("rtsp_open", "error",
                    f"Ouverture RTSP impossible (ffprobe) — {len(attempts)} tentative(s). "
                    f"Vérifiez identifiants ou essayez UDP/l'autre codec.",
                    rtsp_url=discovered_rtsp, attempts=attempts, allow_override=True)
                rtsp_url_validated = False
                debug_attempts = attempts
        else:
            add("rtsp_port", "skip", "Ignoré (aucune URI RTSP découverte)")
            add("rtsp_open", "skip", "Ignoré")
    else:
        # Mode RTSP pur
        add("onvif_port", "skip", "Ignoré (mode RTSP)")
        add("onvif_auth", "skip", "Ignoré (mode RTSP)")
        add("rtsp_port", "ok" if ping_ok else "error",
            f"Port RTSP {data.rtsp_port} ouvert" if ping_ok else "Port RTSP fermé")
        transport = (data.rtsp_transport or "tcp").lower()
        pref = (data.preferred_codec or "auto").lower()
        if (data.rtsp_url or "").lower().startswith("rtsp://") and ping_ok:
            working_url, rtsp_details, attempts = await asyncio.to_thread(
                _try_ffprobe_variants, data.rtsp_url, pref, transport, data.username, data.password
            )
            rtsp_final_url = _build_rtsp_url({
                "rtsp_url": working_url, "username": data.username,
                "password": data.password,
                "rtsp_transport": (rtsp_details or {}).get("transport_used") or transport})
            if rtsp_details:
                add("rtsp_open", "ok",
                    f"Flux RTSP OK · {rtsp_details.get('resolution')} @ {rtsp_details.get('fps','?')}fps {rtsp_details.get('codec','')} (transport {(rtsp_details.get('transport_used') or transport).upper()})",
                    **{k: v for k, v in rtsp_details.items() if k not in ("transport_used", "rtsp_url_used")},
                    rtsp_url=working_url, rtsp_url_used=working_url,
                    validated_url_masked=_mask_url_password(rtsp_final_url),
                    transport_used=rtsp_details.get("transport_used"),
                    attempts=attempts)
                rtsp_url_validated = True
                validated_url_masked = _mask_url_password(rtsp_final_url)
                validated_transport = rtsp_details.get("transport_used") or transport
                debug_attempts = attempts
            else:
                add("rtsp_open", "error",
                    f"Ouverture RTSP impossible — {len(attempts)} tentative(s). "
                    f"Vérifiez URL/identifiants ou essayez UDP.",
                    rtsp_url=data.rtsp_url, attempts=attempts, allow_override=True)
                rtsp_url_validated = False
                debug_attempts = attempts
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
    logger.info("TEST_CONNECTIVITY end mode=%s success=%s rtsp_validated=%s attempts=%d",
                data.mode, success, rtsp_url_validated, len(debug_attempts))

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
        "rtsp_url_validated": rtsp_url_validated,
        "validated_url": validated_url_masked,
        "validated_transport": validated_transport,
        "debug_attempts": debug_attempts,
        "message": (
            f"Tous les tests {data.mode.upper()} sont passés" if success else
            "Un ou plusieurs tests ont échoué — voir détails"
        ),
    }


# ============ Sonde périodique du statut des caméras (online/offline réel) ============
async def _probe_status_once(cam: dict) -> tuple[str, str]:
    """Retourne (status, error_text). `error_text` est vide si online.
    NE JAMAIS re-enregistrer ici (déconnecterait les consommateurs live/recorder/IA)."""
    name = _stream_name(cam["id"])
    if cam.get("id") not in DEMO_IDS and not await _stream_registered(name):
        # Le flux n'existe pas côté go2rtc (probablement effacé par un restart go2rtc) :
        # une SEULE ré-inscription ciblée, pas de churn.
        if not await register_camera_stream(cam):
            return ("offline", "go2rtc: ré-enregistrement échoué (flux introuvable après tentative)")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{GO2RTC_URL}/api/frame.jpeg", params={"src": name})
        if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
            return ("online", "")
        return ("offline", f"go2rtc HTTP {r.status_code}: {r.text[:800]}")
    except httpx.HTTPError as e:
        return ("offline", f"HTTP client error: {type(e).__name__}: {e}")


async def camera_status_loop() -> None:
    """Sonde périodiquement chaque caméra ; met à jour le statut réel en base +
    enregistre les transitions online↔offline dans le journal diagnostic."""
    from datetime import datetime, timezone
    from diagnostics import record_disconnect, record_reconnect
    await asyncio.sleep(15)  # laisser go2rtc / seeding démarrer
    # Compteur de tentatives par caméra (pour la reconnect chain)
    reconnect_attempts: dict = {}
    while True:
        try:
            cams = await db.cameras.find({}, {"_id": 0}).to_list(1000)
            for cam in cams:
                status, error_text = await _probe_status_once(cam)
                now = datetime.now(timezone.utc).isoformat()
                previous = cam.get("status", "unknown")
                changes = {"status": status}
                if status == "online":
                    changes["last_seen"] = now
                await db.cameras.update_one({"id": cam["id"]}, {"$set": changes})
                # Détecte les transitions et logue dans le journal diagnostic
                if previous == "online" and status == "offline":
                    try:
                        await record_disconnect(cam, error_text=error_text, source="camera_status_loop")
                        reconnect_attempts[cam["id"]] = 0
                    except Exception:
                        logger.exception("record_disconnect a échoué (non bloquant)")
                elif previous == "offline" and status == "offline":
                    reconnect_attempts[cam["id"]] = reconnect_attempts.get(cam["id"], 0) + 1
                elif previous == "offline" and status == "online":
                    try:
                        attempts = reconnect_attempts.pop(cam["id"], 1) or 1
                        await record_reconnect(cam["id"], attempts=attempts)
                    except Exception:
                        logger.exception("record_reconnect a échoué (non bloquant)")
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
    """Retourne le nom de flux go2rtc à utiliser.

    Note : pour MJPEG (proxy live.mjpeg), le stream `_sd` est OBLIGATOIRE car il contient le
    transcodage ffmpeg → MJPEG (`video=mjpeg`). go2rtc 1.9.8 ne convertit plus H.264 → MJPEG
    automatiquement sur l'endpoint /api/stream.mjpeg pour les producteurs H.264 purs.
    """
    name = _stream_name(camera_id)
    return name if has_permission(user, "stream_hd") else f"{name}_sd"


def _mjpeg_stream(camera_id: str, hd: bool = False) -> str:
    """Retourne la variante MJPEG à consommer.

    - `hd=True`  → `{name}_hd`  (résolution native, transcodée MJPEG)
    - `hd=False` → `{name}_sd`  (width=640, transcodée MJPEG, faible bande passante)

    Les 2 variantes sont enregistrées dans go2rtc par `register_camera_stream`.
    Elles utilisent le producteur brut `{name}` en amont (un seul décodage RTSP).
    """
    name = _stream_name(camera_id)
    return f"{name}_hd" if hd else f"{name}_sd"


# ============ Proxys de flux authentifiés ============
@stream_router.get("/stream/{camera_id}/live.mjpeg")
async def live_mjpeg(camera_id: str, request: Request,
                     hd: int = 0, user: dict = Depends(stream_user)):
    """Flux vidéo MJPEG temps réel (transcodé par go2rtc via `{name}_hd` ou `{name}_sd`).

    Query param `hd=1` → variante HD (résolution native). Nécessite la permission
    `stream_hd` ; sinon rétrogradation silencieuse vers SD.

    Si la variante demandée n'est pas encore enregistrée dans go2rtc (caméra créée
    avant l'upgrade v2.13.0), elle est créée à la volée via `_ensure_variants`.
    """
    await _authorize_camera(user, camera_id)
    want_hd = bool(int(hd or 0)) and has_permission(user, "stream_hd")
    src = _mjpeg_stream(camera_id, hd=want_hd)
    # Garantit que la variante HD/SD existe côté go2rtc (auto-migration)
    await _ensure_variants(_stream_name(camera_id))
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

    # IMPORTANT : le boundary retourné par go2rtc doit être transmis intact au navigateur
    # (sinon Chrome/Firefox refusent d'afficher le MJPEG). On retransmet donc l'en-tête complet.
    content_type = upstream.headers.get("content-type", "multipart/x-mixed-replace;boundary=frame")
    return StreamingResponse(relay(), media_type=content_type,
                              headers={"Cache-Control": "no-store, no-cache"})


@stream_router.get("/stream/{camera_id}/frame.jpeg")
async def frame_jpeg(camera_id: str, hd: int = 1, user: dict = Depends(stream_user)):
    """Image instantanée réelle extraite du flux.

    - `hd=1` (défaut) : tente le flux source brut (résolution native, HD) puis
      les variantes `{name}_hd` / `{name}_sd` en fallback si go2rtc ne peut pas
      extraire un JPEG du producteur H.264/H.265 direct.
    - `hd=0` : force la variante SD (rapide, 640px).
    Nécessite la permission `stream_hd` pour obtenir la version HD ; sinon
    rétrogradation silencieuse vers SD.
    """
    await _authorize_camera(user, camera_id)
    want_hd = bool(int(hd or 0)) and has_permission(user, "stream_hd")
    name = _stream_name(camera_id)
    # Garantit que les variantes HD/SD existent (auto-migration après upgrade)
    await _ensure_variants(name)
    if want_hd:
        # Priorité au flux natif (résolution originale). Fallback sur variante
        # MJPEG HD transcodée, puis SD en dernier recours.
        sources = [name, f"{name}_hd", f"{name}_sd"]
    else:
        sources = [f"{name}_sd"]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for src in sources:
                r = await client.get(f"{GO2RTC_URL}/api/frame.jpeg", params={"src": src})
                if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
                    return Response(content=r.content, media_type="image/jpeg",
                                     headers={"Cache-Control": "no-store"})
    except httpx.HTTPError:
        raise HTTPException(502, "Flux indisponible")
    raise HTTPException(502, "Flux indisponible")


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
