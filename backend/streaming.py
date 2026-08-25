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

# ─── MJPEG proxy tuning (fix ERR_INCOMPLETE_CHUNKED_ENCODING) ─────────────
# Cache _ensure_variants par caméra : évite l'appel HTTP go2rtc + resolve_pipeline
# à chaque nouveau consommateur (thundering herd sous forte charge).
_ENSURE_VARIANTS_TTL = 60.0  # secondes
_ensure_variants_cache: dict[str, float] = {}
_ensure_variants_locks: dict[str, asyncio.Lock] = {}

# Politique de reconnexion transparente si le producteur ffmpeg go2rtc meurt.
_MJPEG_RECONNECT_MAX_ATTEMPTS = 5
_MJPEG_RECONNECT_BACKOFF_SEC = 1.5   # 1.5s, 3s, 4.5s, 6s, 7.5s
_MJPEG_UPSTREAM_TIMEOUT = httpx.Timeout(15.0, read=None)  # connect=15, read illimité (stream)

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


def _is_direct_rtsp(cam: dict) -> bool:
    """v1.0-rc4.6 · True si la caméra est en pipeline direct — AUCUNE dépendance Go2RTC."""
    return (cam.get("stream_mode") or "auto").lower() == "direct_rtsp"


def _build_rtsp_url(cam: dict) -> str:
    """Construit l'URL RTSP finale en injectant les identifiants **encodés une seule fois** (RFC 3986).

    - Si l'URL déclare déjà `user:pass@` : ne réencode pas (on considère que l'appelant a déjà encodé).
    - Sinon : encode `username` et `password` avec `urllib.parse.quote(str, safe="")`.
      Exemple : `Rlwt29#+jpf` → `Rlwt29%23%2Bjpf` (jamais `%2523%252B…`).

    NOTE : le fragment `#transport=tcp|udp` a été retiré (retour utilisateur : go2rtc échoue à
    décoder les flux avec ce suffixe — cause identifiée depuis, voir docstring de
    `register_camera_stream` : `#transport=` n'existe côté go2rtc QUE pour tunneliser
    RTSP-sur-WebSocket, pas pour choisir TCP/UDP). Le transport est désormais géré :
    - côté ffprobe : via l'option CLI `-rtsp_transport tcp|udp` dans `_ffprobe`
    - côté go2rtc : `register_camera_stream` préfixe la source par `ffmpeg:` (TCP forcé
      par le template d'entrée par défaut de go2rtc) — PAS de négociation automatique
      fiable côté client RTSP natif, contrairement à ce que ce commentaire affirmait avant.
    """
    url = (cam.get("rtsp_url") or "").strip()
    if not url:
        return ""
    user = (cam.get("username") or "").strip()
    # ── Déchiffrement Fernet du mot de passe (R05 / ADR-06) ──
    # Compat descendante : si password en clair (legacy), retourné tel quel.
    from crypto_utils import decrypt_secret
    pwd = decrypt_secret(cam.get("password") or "")
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


#: Largeur minimale acceptable pour un flux d'aperçu — en dessous, l'image
#: est trop dégradée pour être exploitable dans le mur vidéo.
_PREVIEW_MIN_WIDTH = 320


def _stream_channel_key(url: str) -> Optional[str]:
    """Identifie le CANAL physique auquel appartient une URL RTSP.

    Indispensable pour l'aperçu : un même appareil peut exposer plusieurs
    canaux (caméra multi-capteurs, NVR). Sur la Reolink de test, un seul
    hôte sert `h264Preview_01_*` ET `h264Preview_02_*` — deux objectifs
    DIFFÉRENTS. Choisir « le plus petit flux de l'appareil » sans vérifier
    le canal fait afficher l'image du mauvais objectif dans le mur vidéo
    (bug constaté puis corrigé avant mise en service).

    Retourne ``None`` si le format d'URL n'est pas reconnu.
    """
    u = url or ""
    m = re.search(r"h264preview_(\d+)_(?:main|sub)", u, re.IGNORECASE)   # Reolink
    if m:
        return f"reolink:{int(m.group(1))}"
    m = re.search(r"/streaming/channels/(\d+)", u, re.IGNORECASE)         # Hikvision
    if m:
        d = m.group(1)
        return f"hik:{int(d[:-1] or d)}"                                  # 101/102 → canal 1
    m = re.search(r"[?&]channel=(\d+)", u, re.IGNORECASE)                 # Dahua
    if m:
        return f"dahua:{int(m.group(1))}"
    return None


def _derive_sub_url(main_url: str) -> str:
    """Déduit l'URL du sous-flux à partir de celle du flux principal.

    Utilisé UNIQUEMENT quand la découverte ONVIF n'a pas remonté de
    sous-flux pour ce canal précis — c'est fréquent sur les appareils
    multi-canaux, dont l'ONVIF ne liste souvent que les profils du
    premier canal. Les conventions ci-dessous sont stables chez chaque
    constructeur (vérifié en conditions réelles : `h264Preview_02_sub`
    existe bien en 896×512 H264 alors que l'ONVIF ne le listait pas).

    Retourne "" si aucune convention connue ne s'applique.
    """
    u = main_url or ""
    m = re.search(r"(h264Preview_\d+_)main", u, re.IGNORECASE)            # Reolink
    if m:
        return u.replace(m.group(0), m.group(1) + "sub")
    m = re.search(r"(/Streaming/Channels/)(\d+)", u, re.IGNORECASE)       # Hikvision
    if m:
        d = m.group(2)
        ch = d[:-1] or d
        return u.replace(m.group(0), f"{m.group(1)}{ch}02")
    m = re.search(r"([?&]subtype=)(\d+)", u, re.IGNORECASE)               # Dahua
    if m:
        return u.replace(m.group(0), m.group(1) + "1")
    return ""


def pick_preview_stream(cam: dict) -> Optional[dict]:
    """Choisit le sous-flux le plus léger utilisable pour l'APERÇU live.

    v3.8 · L'aperçu consommait jusqu'ici le flux PRINCIPAL, ce qui est le
    pire choix possible : sur une Reolink RLC-81MA le main est en 4K HEVC
    (3840×2160, 8,3 Mpx/image) alors que le sub est en H264 896×512
    (0,46 Mpx — 18× moins). Mesuré en conditions réelles, ffmpeg seul
    (sans go2rtc dans la boucle) :
        main 4K HEVC : 6–8 images/s reçues sur 10 s (source à 20 fps)
        sub  H264    : 17 images/s, stable
    Le décodage 4K HEVC ne tient donc PAS le temps réel sur ce serveur,
    d'où l'aperçu saccadé et les artefacts « neige » (`Could not find ref
    with POC 0` = images de référence perdues). L'appli constructeur est
    fluide parce qu'elle fait exactement ça : elle prévisualise le
    sous-flux, et décode en matériel côté client.

    Sélection VOLONTAIREMENT basée sur la RÉSOLUTION, pas sur le codec
    annoncé : l'ONVIF de cette caméra déclare `codec=h264` pour un flux
    qui est en réalité du HEVC (vérifié par ffprobe) — se fier au codec
    ONVIF reconduirait le bug. La plus petite résolution est de toute
    façon le sous-flux, et c'est lui qui est en H264 chez tous les
    constructeurs (le sous-flux sert justement à la compatibilité).

    Retourne ``None`` si la caméra n'a pas de `streams_detected` (aucune
    découverte ONVIF encore faite) → l'appelant garde son comportement
    actuel, aucune régression.
    """
    main_url = (cam.get("rtsp_url") or "").strip()
    main_key = _stream_channel_key(main_url)

    streams = cam.get("streams_detected") or []

    # v3.9.2 · Quand l'URL principale ne suit aucun motif connu (certaines
    # caméras annoncent en ONVIF une URI principale sans chemin, ex.
    # `rtsp://<ip>:554/`), on ne peut pas déduire son canal. La règle stricte
    # d'origine refusait alors TOUT sous-flux, y compris quand l'appareil n'en
    # expose manifestement qu'un seul — la caméra restait sur son flux
    # principal 4K sans raison. On autorise donc ce cas à la condition qu'il
    # n'y ait AUCUNE ambiguïté : un seul canal identifiable parmi les flux
    # détectés. Dès qu'il y en a plusieurs (appareil multi-capteurs), on
    # refuse comme avant — c'est ce qui évite d'afficher le mauvais objectif.
    detected_keys = {k for k in (_stream_channel_key(s.get("url") or "")
                                  for s in streams) if k is not None}
    single_channel_device = len(detected_keys) <= 1

    candidates = []
    for s in streams:
        url = (s.get("url") or "").strip()
        if not url.lower().startswith(("rtsp://", "rtsps://")):
            continue
        # Sécurité canal : on n'accepte QUE des flux du même canal physique
        # que le flux principal (voir _stream_channel_key).
        cand_key = _stream_channel_key(url)
        if main_key is not None:
            if cand_key != main_key:
                continue
        elif cand_key is not None and not single_channel_device:
            continue
        res = s.get("resolution") or [0, 0]
        try:
            w, h = int(res[0]), int(res[1])
        except (TypeError, ValueError, IndexError):
            continue
        if w < _PREVIEW_MIN_WIDTH:
            continue
        candidates.append((w * h, w, h, s))

    if candidates:
        candidates.sort(key=lambda c: c[0])
        _px, w, h, best = candidates[0]
        if (best.get("url") or "").strip() != main_url:
            return {"url": best.get("url"), "name": best.get("name") or "sub",
                    "width": w, "height": h, "codec": best.get("codec") or ""}

    # Aucun sous-flux listé pour CE canal (cas courant sur les appareils
    # multi-canaux dont l'ONVIF ne décrit que le canal 1) → on retombe sur
    # la convention constructeur.
    derived = _derive_sub_url(main_url)
    if derived and derived != main_url:
        return {"url": derived, "name": "sub (déduit)",
                "width": 0, "height": 0, "codec": ""}
    return None


def build_preview_rtsp_url(cam: dict) -> str:
    """URL RTSP (identifiants injectés) du flux d'APERÇU.

    Retombe sur le flux principal si aucun sous-flux n'est connu — donc
    strictement identique au comportement d'avant tant que la caméra n'a
    pas été découverte (`streams_detected` absent).
    """
    preview = pick_preview_stream(cam)
    if not preview or not preview.get("url"):
        return _build_rtsp_url(cam)
    # Réutilise l'injection d'identifiants de _build_rtsp_url en lui
    # présentant le sous-flux comme s'il était l'URL principale — même
    # encodage percent, même gestion des credentials déjà présents.
    return _build_rtsp_url({**cam, "rtsp_url": preview["url"]})


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


async def _get_go2rtc_stream_sources(name: str) -> Optional[list[str]]:
    """Récupère les sources go2rtc actuellement enregistrées pour un stream (via
    `GET /api/streams`). Retourne None si l'appel HTTP échoue OU si le stream
    n'existe pas — permet de distinguer les 2 cas côté appelant.
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{GO2RTC_URL}/api/streams")
            if r.status_code != 200:
                return None
            data = r.json() or {}
    except httpx.HTTPError:
        return None
    entry = data.get(name)
    if entry is None:
        return None
    # go2rtc renvoie `{name: [sources]}` (v1.9.x) ou `{name: {producers: [...]}}` (nouvelle version)
    if isinstance(entry, list):
        return [str(s) for s in entry]
    if isinstance(entry, dict):
        prods = entry.get("producers") or entry.get("sources") or []
        return [str(p.get("url") if isinstance(p, dict) else p) for p in prods]
    return []


# ── Probe de statut NON-INVASIF (ne touche jamais la caméra physique) ──────
# Dernier compteur bytes_recv observé par caméra (détection de flux gelé).
_probe_last_bytes: dict[str, int] = {}


async def _stream_bytes_recv(name: str) -> int:
    """Total `bytes_recv` des producteurs ACTIFS d'un stream go2rtc.
    0 si le producteur est idle (aucun consommateur → go2rtc n'est pas connecté
    à la caméra) ou si l'appel échoue. Coût : 1 GET local, aucun décodage."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{GO2RTC_URL}/api/streams", params={"src": name})
            if r.status_code != 200:
                return 0
            data = r.json() or {}
    except (httpx.HTTPError, ValueError):
        return 0
    total = 0
    for prod in (data.get("producers") or []):
        if isinstance(prod, dict):
            try:
                total += int(prod.get("bytes_recv") or 0)
            except (TypeError, ValueError):
                pass
    return total


def _camera_tcp_target(cam: dict) -> Optional[tuple]:
    """(host, port) RTSP de la caméra pour un TCP-check léger.
    Priorité : hôte de l'URL RTSP en base, sinon cam.ip + rtsp_port."""
    url = (cam.get("rtsp_url") or "").strip()
    m = re.match(r"^rtsp://(?:[^@/]*@)?([^:/?#]+)(?::(\d+))?", url, re.IGNORECASE)
    if m:
        return m.group(1), int(m.group(2) or 554)
    host = (cam.get("ip") or "").strip()
    if host:
        try:
            port = int(cam.get("rtsp_port") or cam.get("port") or 554)
        except (TypeError, ValueError):
            port = 554
        return host, port
    return None


async def register_camera_stream(cam: dict, *, caller: str = "unknown",
                                  force: bool = False) -> bool:
    """Déclare (ou met à jour) le flux d'une caméra dans go2rtc.

    IDEMPOTENT : si les 3 variantes existent déjà avec la MÊME config souhaitée,
    n'exécute AUCUN DELETE/PUT (pas de churn côté consommateurs).

    `force=True` force la ré-inscription complète (utilisé par le bouton "Réparer
    ce flux" et par `refresh-stream`). NE PAS UTILISER depuis une boucle périodique.

    Enregistre 3 variantes :
      - `{name}`     : source RTSP brute (H.264/H.265) — utilisée par le recorder + IA
      - `{name}_hd`  : ffmpeg → MJPEG à résolution native (aperçu HD)
      - `{name}_sd`  : ffmpeg → MJPEG width=640 (aperçu SD faible bande passante)
    """
    from lifecycle import record as _lc_record  # import local (évite cycle)

    if cam.get("id") in DEMO_IDS:
        return True  # flux de démonstration défini statiquement dans go2rtc.yaml
    # v1.0-rc4 · Respecter le stream_mode : les caméras en "direct_rtsp"
    # NE SONT PAS inscrites dans Go2RTC (le pipeline IA lit RTSP directement).
    # On retourne True car "l'objectif d'enregistrement" est trivialement
    # satisfait (rien à inscrire). Le caller (create/update) verra registered=True
    # et n'appliquera aucune logique de fallback/refus.
    if (cam.get("stream_mode") or "auto").lower() == "direct_rtsp":
        logger.info("register_camera_stream: skip %s (stream_mode=direct_rtsp)", cam.get("id"))
        return True
    # video-pipeline-v2.1 · URL RTSP dédiée go2rtc (surcharge de rtsp_url).
    # ⚠ go2rtc ne transcode PAS H265→MJPEG : il FAUT un flux H264 en source.
    # Fallback : rtsp_url (avec credentials injectés).
    go2rtc_override = (cam.get("go2rtc_source_url") or "").strip()
    if go2rtc_override.lower().startswith("rtsp://"):
        rtsp_url = go2rtc_override
    else:
        rtsp_url = _build_rtsp_url(cam)
    if not rtsp_url.lower().startswith(("rtsp://", "rtmp://", "http://", "https://")):
        return False
    name = _stream_name(cam["id"])
    cam_id = cam["id"]

    # v3.1.6 · Root cause RÉELLE des artefacts "neige"/paquets perdus (confirmée
    # par log réel : `[rtsp] RTP: PT=60: bad cseq ... expected=...` capturé côté
    # recorder sur un flux relayé par ce chemin) — vérifiée contre la doc source
    # de go2rtc (internal/rtsp/README.md, internal/ffmpeg/README.md) :
    #   - Le client RTSP NATIF de go2rtc (utilisé quand la source est une URL
    #     `rtsp://` brute) n'a AUCUN moyen de forcer le transport RTP en TCP.
    #     Son seul fragment `#transport=...` sert à tunneliser RTSP sur
    #     WebSocket (`#transport=ws://...`), concept sans rapport — d'où
    #     l'échec `Get "tcp": unsupported protocol scheme ""` du fix v1.0-rc4.5
    #     ci-dessous : "tcp" était interprété comme un schéma d'URL à ouvrir,
    #     pas comme un mode de transport RTP. Le comportement par défaut du
    #     client natif n'est donc PAS garanti TCP, contrairement à ce que le
    #     commentaire précédent supposait.
    #   - go2rtc recommande lui-même la source `ffmpeg:` pour un flux caméra
    #     "glitchy" ("It will not add CPU load if you don't use transcoding").
    #     Son template ffmpeg PAR DÉFAUT force déjà `-rtsp_transport tcp`
    #     (doc : `#input=rtsp/udp` "will change RTSP transport from TCP to
    #     UDP+TCP" — donc le défaut, sans override, est bien TCP). Cette source
    #     `ffmpeg:` est déjà utilisée sans problème dans CE MÊME fichier pour
    #     les variantes `_hd`/`_sd` (voir plus bas) — pas une nouvelle capacité
    #     non éprouvée sur ce déploiement.
    # Préfixer la source RTSP par `ffmpeg:` fait donc pull la caméra en TCP
    # forcé, sans toucher au reste de la chaîne (recorder/IA/WebRTC continuent
    # de consommer le flux RE-SERVI par go2rtc en RTSP natif, inchangé).
    rtsp_source = f"ffmpeg:{rtsp_url}"

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

    # v3.8 · Les variantes MJPEG d'APERÇU transcodent désormais depuis le
    # SOUS-FLUX quand il existe, plus depuis le flux principal.
    # Transcoder un 4K HEVC en MJPEG (format SANS compression inter-image :
    # chaque image est un JPEG complet) est le pire cas possible, et c'est
    # fait en logiciel — le conteneur go2rtc n'a pas d'accès GPU. Mesuré :
    # le seul décodage du main tient déjà à peine 6-8 img/s contre 17 pour
    # le sub. On garde le flux principal pour `name` (recorder + IA, qui en
    # ont besoin en pleine résolution) et on n'allège QUE l'aperçu.
    preview = pick_preview_stream(cam)
    preview_source_name = name
    desired = {name: rtsp_source}
    if preview and preview.get("url"):
        preview_url = build_preview_rtsp_url(cam)
        if preview_url and preview_url != rtsp_url:
            preview_source_name = f"{name}_preview"
            desired[preview_source_name] = f"ffmpeg:{preview_url}"
            dims = (f"{preview.get('width')}x{preview.get('height')}"
                    if preview.get("width") else "résolution inconnue")
            logger.info("register_camera_stream %s → aperçu via sous-flux %s (%s)",
                        name, dims, preview.get("name"))
    desired[f"{name}_hd"] = f"ffmpeg:{preview_source_name}#{hd_filter}"
    desired[f"{name}_sd"] = f"ffmpeg:{preview_source_name}#{sd_filter}"

    # ─── Étape 1 : Diff avec la config existante côté go2rtc (idempotence) ───
    if not force:
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                r = await client.get(f"{GO2RTC_URL}/api/streams")
                existing = r.json() if r.status_code == 200 else {}
        except httpx.HTTPError:
            existing = {}
        # Vérifie que les 3 streams existent avec la même source
        all_match = True
        for stream_name, wanted_src in desired.items():
            entry = existing.get(stream_name)
            if entry is None:
                all_match = False
                break
            actual_srcs: list[str] = []
            if isinstance(entry, list):
                actual_srcs = [str(s) for s in entry]
            elif isinstance(entry, dict):
                prods = entry.get("producers") or entry.get("sources") or []
                actual_srcs = [str(p.get("url") if isinstance(p, dict) else p) for p in prods]
            if wanted_src not in actual_srcs:
                all_match = False
                break
        if all_match:
            _lc_record(cam_id, "registered_idempotent",
                       reason="config identical, no go2rtc changes needed",
                       caller=caller,
                       extra={"streams": list(desired.keys())})
            return True

    # ─── Étape 2 : Ré-inscription complète (DELETE + PUT) ───
    _lc_record(cam_id, "registering", reason=f"force={force}", caller=caller,
               extra={"rtsp_url_masked": _mask_url_password(rtsp_url)})
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Supprime les anciens enregistrements (source + variantes) pour repartir propre
            for src in (name, f"{name}_preview", f"{name}_hd", f"{name}_sd"):
                await client.delete(f"{GO2RTC_URL}/api/streams", params={"src": src})
            # v3.8 · Les 3-4 flux sont désormais publiés par la MÊME boucle, via
            # `params=` (encodage httpx), au lieu d'une URL construite à la main
            # pour la source RTSP.
            #
            # L'ancien code insérait `rtsp_source` BRUT dans la query string pour
            # éviter un double encodage supposé. C'était l'inverse du bon
            # comportement, et ça cassait deux choses (vérifié contre le go2rtc
            # réel de production, cf. CHANGELOG v3.8) :
            #   1. le mot de passe percent-encodé était décodé par go2rtc à la
            #      lecture de la query → `Rlwt29%23%2Bjpf` redevenait
            #      `Rlwt29#+jpf`, et ffmpeg tronquait alors le mot de passe au
            #      `#` (séparateur de fragment) → authentification refusée ;
            #   2. tout `&` présent dans l'URL RTSP (ex. `&profile=Profile_1`
            #      chez Hikvision) terminait le paramètre `src` → l'URL
            #      enregistrée était tronquée.
            # Avec `params=`, httpx encode une fois, go2rtc décode une fois, et
            # la chaîne stockée est exactement celle voulue — y compris les
            # identifiants percent-encodés et les query params RTSP.
            for stream_name, src_value in desired.items():
                r = await client.put(f"{GO2RTC_URL}/api/streams",
                                      params=[("name", stream_name), ("src", src_value)])
                r.raise_for_status()
        if not await _stream_registered(name):
            logger.warning("go2rtc: flux %s introuvable après enregistrement", name)
            _lc_record(cam_id, "register_failed", reason="not found in go2rtc after PUT",
                       caller=caller)
            return False
        _lc_record(cam_id, "created",
                   reason=f"{len(desired)} variants PUT to go2rtc", caller=caller,
                   extra={"streams": list(desired.keys())})
        return True
    except httpx.HTTPError as e:
        logger.warning("go2rtc: échec enregistrement %s : %s", name, e)
        _lc_record(cam_id, "register_failed", reason=f"HTTP error: {type(e).__name__}",
                   caller=caller)
        return False


async def unregister_camera_stream(camera_id: str, *, caller: str = "unknown") -> None:
    from lifecycle import record as _lc_record
    if camera_id in DEMO_IDS:
        return
    name = _stream_name(camera_id)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # `_preview` : nouvelle variante v3.8, à retirer comme les autres.
            for stream in (name, f"{name}_preview", f"{name}_hd", f"{name}_sd"):
                await client.delete(f"{GO2RTC_URL}/api/streams", params={"src": stream})
        _lc_record(camera_id, "destroyed", reason="DELETE from go2rtc", caller=caller)
    except httpx.HTTPError as e:
        # v3.8 · On journalise au lieu d'avaler silencieusement. Un flux
        # orphelin (`cam_b65c469f…`) a été trouvé en production, tirant encore
        # une session RTSP sur une caméra supprimée de la base depuis longtemps
        # — sur un appareil qui n'accepte que quelques sessions simultanées.
        # La cause exacte n'a pas pu être établie a posteriori, justement
        # parce que cet échec ne laissait aucune trace.
        logger.warning("go2rtc: échec du retrait des flux de %s : %s", camera_id, e)


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
        # v1.0-rc4.6 · Garde mode-aware : une caméra direct_rtsp ne reçoit JAMAIS
        # de variantes Go2RTC (cam_xxx n'y existe pas → `Error opening input file`).
        if cam and _is_direct_rtsp(cam):
            logger.info("_ensure_variants: skip %s (stream_mode=direct_rtsp)", name)
            return
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


async def _ensure_variants_cached(name: str) -> None:
    """Version cachée de `_ensure_variants` — throttle par caméra (TTL 60 s).

    Fix pour `ERR_INCOMPLETE_CHUNKED_ENCODING` sous forte charge : évite d'exécuter
    resolve_pipeline() + un aller-retour HTTP vers go2rtc à CHAQUE requête MJPEG.
    Un verrou par caméra empêche N appelants parallèles de faire le même travail.
    """
    now = time.monotonic()
    last = _ensure_variants_cache.get(name, 0.0)
    if now - last < _ENSURE_VARIANTS_TTL:
        return
    lock = _ensure_variants_locks.setdefault(name, asyncio.Lock())
    async with lock:
        # Re-check après acquisition du verrou (double-checked locking)
        if time.monotonic() - _ensure_variants_cache.get(name, 0.0) < _ENSURE_VARIANTS_TTL:
            return
        await _ensure_variants(name)
        _ensure_variants_cache[name] = time.monotonic()


async def sync_all_streams() -> None:
    """P0-fix · Solution B (Go2RTC + MJPEG) : réconcilie DB ↔ Go2RTC.

    Utile après un restart de Go2RTC (les flux enregistrés dynamiquement via
    `PUT /api/streams` ne sont PAS persistés dans go2rtc.yaml — seules les
    démos le sont) : ré-enregistre chaque caméra "auto"/go2rtc, purge les
    résidus des caméras stream_mode=direct_rtsp ou supprimées. Remplace les
    3 anciennes fonctions (NO-OP + 2 versions mortes) laissées par la
    migration "video-engine-v3", qui référençaient encore video_pipelines
    (module supprimé).
    """
    await _ensure_demo_camera()
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(f"{GO2RTC_URL}/api/streams")
            go2rtc_names = set((r.json() or {}).keys()) if r.status_code == 200 else set()
    except httpx.HTTPError:
        go2rtc_names = set()
    cams = await db.cameras.find({}, {"_id": 0}).to_list(1000)
    n_registered = 0
    n_purged = 0
    for cam in cams:
        if cam.get("id") in DEMO_IDS:
            await _ensure_variants(_stream_name(cam["id"]))
            continue
        name = _stream_name(cam["id"])
        if _is_direct_rtsp(cam):
            if go2rtc_names & {name, f"{name}_hd", f"{name}_sd"}:
                await unregister_camera_stream(cam["id"], caller="sync_all_streams@direct_rtsp_purge")
                n_purged += 1
            continue
        if await register_camera_stream(cam, caller="sync_all_streams"):
            n_registered += 1
    logger.info("sync_all_streams: %d caméra(s) réconciliée(s) avec go2rtc, %d résidu(s) purgé(s)",
                n_registered, n_purged)


async def reconcile_streams_with_go2rtc() -> dict:
    """Phase 2 (v2.22.0) — Diagnostic de réconciliation DB ↔ go2rtc.

    Compare la vérité DB (MongoDB `cameras` collection) avec l'état réel go2rtc
    (`GET /api/streams`) et retourne :
      - `in_sync` : caméras présentes des 2 côtés avec toutes les variantes attendues
      - `missing_in_go2rtc` : caméras en DB mais absentes du moteur vidéo
        → il FAUT re-push (probablement après un restart go2rtc / reset du conteneur)
      - `orphan_in_go2rtc` : flux dans go2rtc sans caméra DB correspondante
        → à supprimer (résidus d'une caméra supprimée en DB pendant que go2rtc était HS)
      - `variant_drift` : caméras avec producteur OK mais variantes `_hd`/`_sd` manquantes
        → réparable via `_ensure_variants(name)`
      - `demo_names` : liste des flux démo (traités séparément, jamais dans "orphans")

    N'écrit RIEN. C'est un diagnostic pur, utilisé par `GET /api/diagnostics/streams-sync`.
    La réparation se fait via l'endpoint `POST /api/diagnostics/streams-sync/repair` qui
    appelle `sync_all_streams()`.
    """
    result = {
        "in_sync": [], "missing_in_go2rtc": [], "orphan_in_go2rtc": [],
        "variant_drift": [], "demo_names": [],
        "go2rtc_reachable": False, "go2rtc_error": None,
        "db_cameras_count": 0, "go2rtc_streams_count": 0,
    }
    # ── Récupérer l'état go2rtc ─────────────────────────────────────────
    go2rtc_streams: dict = {}
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(f"{GO2RTC_URL}/api/streams")
            r.raise_for_status()
            go2rtc_streams = r.json() or {}
            result["go2rtc_reachable"] = True
    except httpx.HTTPError as e:
        result["go2rtc_error"] = f"{type(e).__name__}: {str(e)[:180]}"
        return result
    result["go2rtc_streams_count"] = len(go2rtc_streams)

    # ── Récupérer la vérité DB ─────────────────────────────────────────
    cams = await db.cameras.find({}, {"_id": 0}).to_list(1000)
    result["db_cameras_count"] = len(cams)
    expected_names: set[str] = set()
    for cam in cams:
        cam_id = cam.get("id", "")
        if not cam_id:
            continue
        name = _stream_name(cam_id)
        expected_names.add(name)
        is_demo = cam_id in DEMO_IDS
        if is_demo:
            result["demo_names"].append(name)
        present = name in go2rtc_streams
        hd_present = f"{name}_hd" in go2rtc_streams
        sd_present = f"{name}_sd" in go2rtc_streams
        if not present:
            result["missing_in_go2rtc"].append({
                "camera_id": cam_id,
                "name": cam.get("name", ""),
                "stream_name": name,
                "is_demo": is_demo,
                "status": cam.get("status", ""),
            })
        elif not (hd_present and sd_present):
            result["variant_drift"].append({
                "camera_id": cam_id,
                "name": cam.get("name", ""),
                "stream_name": name,
                "hd_present": hd_present,
                "sd_present": sd_present,
            })
        else:
            result["in_sync"].append({
                "camera_id": cam_id,
                "name": cam.get("name", ""),
                "stream_name": name,
            })

    # ── Orphelins go2rtc (flux sans caméra DB) ────────────────────────
    # Exclut : variantes _hd/_sd (déjà comptées via leur producteur),
    # flux temporaires probe_*, et les caméras démo statiques du yaml.
    for stream_name in go2rtc_streams:
        if stream_name.endswith("_hd") or stream_name.endswith("_sd"):
            continue
        if stream_name.startswith("probe_"):
            continue
        if not stream_name.startswith("cam_"):
            continue
        if stream_name in expected_names:
            continue
        result["orphan_in_go2rtc"].append({"stream_name": stream_name})

    return result


async def _ensure_demo_camera() -> None:
    """Caméras de démonstration : vrais flux H.264 générés localement (pipeline réel).

    Skip conditions :
        - MGVMS_SEED_DEMOS=false → jamais de démos
        - au moins une caméra réelle en base (non-démo) → on ne re-sème pas les démos
          (le client a demandé un setup propre avec sa vraie caméra uniquement)
    """
    if (os.environ.get("MGVMS_SEED_DEMOS", "auto") or "").lower() in ("false", "0", "no"):
        return
    real_count = await db.cameras.count_documents({"id": {"$nin": list(DEMO_IDS)}})
    if real_count > 0:
        return
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


# ─── Transcodage à la volée HEVC → H264 pour lecture navigateur ───────────
# v3.1.1 · Les navigateurs ne décodent pas HEVC nativement en <video>. Les
# enregistrements sont servis tels quels (recorder.py fait `-c copy`, jamais
# de ré-encodage à l'écriture) : une caméra HEVC produit des fichiers HEVC
# sur disque. Plutôt que d'exiger un sous-flux H264 dédié pour l'enregistrement
# (dégraderait la qualité stockée), on transcode UNIQUEMENT à la lecture — coût
# borné par le nombre de lectures simultanées (typiquement 1-3 personnes qui
# consultent des clips), pas par le nombre de caméras de la flotte. Utilisé par
# GET /api/recordings/{id}/media (routers.py) — recordings ET aperçus vidéo
# d'événements/alertes (EventViewer.jsx) passent tous par cette même route.
_HAS_NVENC_H264: Optional[bool] = None


def _ffmpeg_supports_nvenc_h264() -> bool:
    """Vérifie une fois (résultat caché en mémoire) que ffmpeg a l'encodeur
    h264_nvenc. Indépendant de la détection NVDEC (décodage) de frame_source.py
    — décoder et encoder sur GPU sont deux capacités distinctes."""
    global _HAS_NVENC_H264
    if _HAS_NVENC_H264 is not None:
        return _HAS_NVENC_H264
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                              capture_output=True, text=True, timeout=5)
        text = (out.stdout or "") + (out.stderr or "")
        _HAS_NVENC_H264 = "h264_nvenc" in text
    except Exception:
        _HAS_NVENC_H264 = False
    logger.info("recording-transcode: h264_nvenc %s",
                "disponible ✅" if _HAS_NVENC_H264 else "indisponible — fallback CPU (libx264)")
    return _HAS_NVENC_H264


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_RANGE_CHUNK = 256 * 1024


async def range_file_response(path: str, request: Request, media_type: str = "video/mp4",
                               background=None) -> Response:
    """FileResponse avec vrai support HTTP Range (206 Partial Content).

    v3.4 · Starlette 0.36.3 (version pinnée ici) ne gère PAS les requêtes
    Range dans FileResponse — confirmé en lisant sa source, elle renvoie
    toujours 200 avec le fichier entier quel que soit le header `Range`
    envoyé par le `<video>` du navigateur. Ça forçait des rechargements
    complets à chaque lecture d'événement (20-30 Mo à chaque fois). Implémenté
    manuellement ici plutôt que de monter de version Starlette/FastAPI (risque
    de régression trop large sur le reste de l'app pour ce correctif ciblé).
    """
    file_size = os.path.getsize(path)
    range_header = request.headers.get("range")

    if not range_header:
        async def _stream_full():
            # NB : un fichier ouvert par open() est un objet SYNCHRONE — pas
            # de support de "async with" (pas de __aenter__). Fermeture
            # manuelle via to_thread, comme _stream_range juste en dessous.
            f = await asyncio.to_thread(open, path, "rb")
            try:
                while True:
                    chunk = await asyncio.to_thread(f.read, _RANGE_CHUNK)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await asyncio.to_thread(f.close)
            if background:
                await background()
        return StreamingResponse(_stream_full(), media_type=media_type, headers={
            "Content-Length": str(file_size), "Accept-Ranges": "bytes",
        })

    m = _RANGE_RE.match(range_header)
    if not m:
        raise HTTPException(416, "Range invalide", headers={"Content-Range": f"bytes */{file_size}"})
    start = int(m.group(1)) if m.group(1) else 0
    end = int(m.group(2)) if m.group(2) else file_size - 1
    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        raise HTTPException(416, "Range non satisfiable", headers={"Content-Range": f"bytes */{file_size}"})
    length = end - start + 1

    async def _stream_range():
        f = await asyncio.to_thread(open, path, "rb")
        try:
            await asyncio.to_thread(f.seek, start)
            remaining = length
            while remaining > 0:
                chunk = await asyncio.to_thread(f.read, min(_RANGE_CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            await asyncio.to_thread(f.close)
        if background:
            await background()

    return StreamingResponse(_stream_range(), status_code=206, media_type=media_type, headers={
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
    })


def needs_transcode_for_browser(path: str) -> bool:
    """True si le fichier local est dans un codec que <video> HTML5 ne décode
    pas (HEVC/H265). Sonde le FICHIER réel via ffprobe plutôt que de faire
    confiance au champ `codec` Mongo (peut être stale si la caméra a changé
    d'encodage après l'enregistrement)."""
    details = _ffprobe(path)
    return (details or {}).get("codec", "") in ("HEVC", "H265")


async def transcode_to_temp_mp4(path: str, start_sec: float = 0.0) -> str:
    """Transcode HEVC→H264 vers un fichier temporaire COMPLET, pas un flux
    streamé en direct.

    v3.1.3 · Fix : la première version streamait le MP4 fragmenté
    (`frag_keyframe+empty_moov`) au fur et à mesure via un pipe, sans fichier
    sur disque. Repéré en usage réel : `<video>` HTML5 standard ne gère pas
    de façon fiable la durée/le seek sur ce genre de flux "live" — lecture
    qui semblait s'arrêter après ~2s au lieu des 2 min réelles du segment
    (aucun `moov` connu à l'avance = durée non déterminable proprement côté
    navigateur). Un fichier complet, une fois le transcodage terminé, se
    comporte comme un vrai MP4 (Range HTTP natif via FileResponse, durée/
    seek fiables) — coût : attend la fin du transcodage avant de répondre
    (rapide sur un segment de 2 min avec accélération GPU) plutôt que de
    streamer au fur et à mesure.

    `start_sec` : seek AVANT décodage (rapide, par keyframe) — utilisé pour
    caler le début du fichier généré sur l'instant précis d'un événement.
    L'appelant est responsable de supprimer le fichier retourné après usage
    (voir `BackgroundTask` dans la route qui consomme cette fonction).
    """
    import tempfile
    use_gpu_decode = False
    try:
        from frame_source import _use_gpu  # réutilise la détection NVDEC existante
        use_gpu_decode = _use_gpu()
    except Exception:
        pass
    use_gpu_encode = _ffmpeg_supports_nvenc_h264()

    fd, out_path = tempfile.mkstemp(suffix=".mp4", prefix="mgvms_transcode_")
    os.close(fd)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-nostdin"]
    if start_sec > 0:
        cmd += ["-ss", str(max(0.0, start_sec))]
    if use_gpu_decode:
        cmd += ["-hwaccel", "cuda", "-c:v", "hevc_cuvid"]
    cmd += ["-i", path]
    if use_gpu_encode:
        cmd += ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
    # +faststart : réordonne le moov en tête de fichier une fois l'encodage
    # terminé — démarrage rapide côté lecteur, mais fichier COMPLET normal
    # (à ne pas confondre avec le MP4 fragmenté abandonné ci-dessus).
    cmd += ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-f", "mp4", out_path]

    logger.info("recording-transcode: start (gpu_decode=%s gpu_encode=%s ss=%s) %s → %s",
                use_gpu_decode, use_gpu_encode, start_sec, os.path.basename(path), out_path)
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        logger.warning("recording-transcode: échec (rc=%s) %s", proc.returncode,
                        (stderr or b"")[:300].decode(errors="replace"))
        raise RuntimeError("transcodage HEVC→H264 échoué")
    logger.info("recording-transcode: terminé (%d octets) %s",
                os.path.getsize(out_path), os.path.basename(out_path))
    return out_path


async def probe_camera(cam: dict) -> dict:
    """Test de connexion réel : frame via go2rtc + ffprobe sur l'URL RTSP."""
    await register_camera_stream(cam, caller="probe_camera(explicit test)")
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
                    timeout=25,
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
                add("onvif_auth", "error",
                    f"Auth ONVIF refusée — {type(e).__name__}: {str(e)[:160]}")
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

    # 6) Décodage vidéo — capture ffmpeg one-shot (décode H264 ET H265).
    #    video-pipeline-v2 : l'aperçu d'ajout de caméra ne dépend PLUS de Go2RTC.
    decode_ok = False
    preview_url = None
    if rtsp_final_url.lower().startswith("rtsp://") and any(s["name"] == "rtsp_open" and s["status"] == "ok" for s in steps):
        tmp_name = f"probe_{int(time.time()*1000)}"
        jpeg = await _oneshot_probe_jpeg(rtsp_final_url,
                                          (validated_transport or "tcp") if rtsp_url_validated else "tcp")
        if jpeg:
            _PROBE_PREVIEWS[tmp_name] = (time.monotonic(), jpeg)
            decode_ok = True
            preview_url = f"/api/stream/preview.jpeg?name={tmp_name}"
        add("decode", "ok" if decode_ok else "warn",
            "Décodage vidéo OK (ffmpeg) — aperçu généré" if decode_ok
            else "Capture d'image impossible — mais l'URL RTSP est valide",
            preview_url=preview_url, temp_stream=tmp_name)
    else:
        add("decode", "skip", "Ignoré (aucun flux RTSP valide)")

    # 7) Aperçu vidéo
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
async def _probe_status_once(cam: dict) -> tuple[str, str, bool]:
    """Probe non-invasif du statut d'une caméra. NE JAMAIS réenregistrer ici
    (source du bug historique de cycles déconnexion/reconnexion).

    Retourne `(status, error_text, stream_missing)` :
      - `status`         : "online" | "offline" (basé sur l'existence go2rtc + probe frame léger)
      - `error_text`     : raison précise si offline (vide si online)
      - `stream_missing` : True si go2rtc a PERDU le stream (situation anormale à remonter,
                            NON auto-réparée — l'admin doit cliquer "Réparer" manuellement)

    Le status offline n'est confirmé qu'après N échecs CONSECUTIFS (hystérésis) —
    voir `lifecycle.record_probe_result`. Les blips HTTP transitoires n'entraînent
    plus de flip online→offline.
    """
    from lifecycle import record as _lc_record
    name = _stream_name(cam["id"])
    cam_id = cam["id"]
    is_demo = cam_id in DEMO_IDS

    # ── Étape 0 (v0.7.c P0-1) : SOURCE DE VÉRITÉ PRIORITAIRE ──
    # Une caméra dont le worker frame_source produit des frames fraîches
    # alimente le pipeline IA — elle ne peut JAMAIS être marquée offline,
    # quel que soit le résultat des probes go2rtc/TCP en aval.
    try:
        import frame_source as _fs
        if _fs.get_latest_frame(cam_id, max_age_sec=10.0) is not None:
            return ("online", "", False)
    except Exception:
        pass

    # P0-fix · Solution B (Go2RTC + MJPEG) : statut basé sur Go2RTC pour toute
    # caméra go2rtc (réelle ou démo) ; stream_mode=direct_rtsp dépend uniquement
    # de frame_source (déjà vérifié plus haut). Remplace video_pipelines.status
    # — module inexistant, qui faisait planter TOUT le cycle de camera_status_loop
    # (except Exception englobant tout le `for cam in cams`) dès la 1re caméra réelle.
    if not is_demo and _is_direct_rtsp(cam):
        # Pas de frame_source récente (IA/détection désactivée ou pas encore
        # démarrée) ne veut pas dire caméra injoignable — probe TCP réel sur
        # le port RTSP avant de conclure "offline" (évite un faux NO SIGNAL
        # alors que le pont MJPEG direct fonctionne très bien).
        ip = (cam.get("ip") or "").strip()
        port = int(cam.get("rtsp_port") or 554)
        if ip and await asyncio.to_thread(_tcp_check, ip, port, 3.0):
            return ("online", "", False)
        return ("offline_transient", "aucune frame récente et port RTSP injoignable (direct_rtsp)", False)
    # v3.9 · On sonde la variante `_preview` (sous-flux H264) AVANT le flux
    # principal. `/api/frame.jpeg` doit produire un JPEG : go2rtc n'y arrive
    # pas depuis une source HEVC et renvoie HTTP 500 — la caméra était donc
    # affichée « NO SIGNAL » alors que son flux fonctionnait parfaitement
    # (constaté en prod sur la Reolink 4K HEVC : main → 500, _preview → 200).
    # Le sous-flux est en H264 chez tous les constructeurs, donc toujours
    # convertible en JPEG.
    last_err = ""
    for candidate in (f"{name}_preview", name):
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(f"{GO2RTC_URL}/api/frame.jpeg", params={"src": candidate})
            if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
                return ("online", "", False)
            last_err = f"go2rtc frame HTTP {r.status_code} ({candidate})"
        except httpx.HTTPError as e:
            last_err = f"HTTP client error: {type(e).__name__} ({candidate})"
    return ("offline_transient", last_err, False)


async def camera_status_loop() -> None:
    """Sonde périodiquement chaque caméra ; met à jour le statut réel en base +
    enregistre les transitions online↔offline dans le journal diagnostic.

    HYSTÉRÉSIS : 3 échecs consécutifs de probe avant de flipper online→offline
    (évite les faux positifs sur blip HTTP transitoire vers go2rtc).

    NE FAIT PLUS JAMAIS de register_camera_stream — c'était la source du bug
    historique de churn qui déconnectait tous les consommateurs actifs.
    """
    from datetime import datetime, timezone
    from diagnostics import record_disconnect, record_reconnect
    from lifecycle import (
        record as _lc_record,
        record_probe_result,
        reset_probe_counter,
        get_probe_counter,
    )
    await asyncio.sleep(15)  # laisser go2rtc / seeding démarrer
    reconnect_attempts: dict = {}
    while True:
        try:
            cams = await db.cameras.find({}, {"_id": 0}).to_list(1000)
            for cam in cams:
                cam_id = cam["id"]
                raw_status, error_text, stream_missing = await _probe_status_once(cam)
                # Résout le status effectif avec hystérésis
                probe_ok = (raw_status == "online")
                should_offline, fail_count = record_probe_result(cam_id, probe_ok, error_text)
                if probe_ok:
                    status = "online"
                    _lc_record(cam_id, "status_probe_ok",
                               reason="producteur actif ou caméra joignable (probe non-invasif)",
                               caller="camera_status_loop")
                elif should_offline:
                    status = "offline"
                    _lc_record(cam_id, "status_offline_confirmed",
                               reason=f"{fail_count} consecutive probe failures: {error_text}",
                               caller="camera_status_loop",
                               extra={"stream_missing": stream_missing})
                else:
                    # Blip transitoire — conserve l'ancien status en base
                    status = cam.get("status", "unknown")
                    _lc_record(cam_id, "status_probe_fail",
                               reason=f"attempt {fail_count}/{3}: {error_text}",
                               caller="camera_status_loop")
                now = datetime.now(timezone.utc).isoformat()
                previous = cam.get("status", "unknown")
                changes = {"status": status}
                if status == "online":
                    changes["last_seen"] = now
                await db.cameras.update_one({"id": cam_id}, {"$set": changes})
                # Détecte les transitions et logue dans le journal diagnostic
                if previous == "online" and status == "offline":
                    try:
                        await record_disconnect(cam, error_text=error_text, source="camera_status_loop")
                        reconnect_attempts[cam_id] = 0
                    except Exception:
                        logger.exception("record_disconnect a échoué (non bloquant)")
                elif previous == "offline" and status == "offline":
                    reconnect_attempts[cam_id] = reconnect_attempts.get(cam_id, 0) + 1
                elif previous == "offline" and status == "online":
                    try:
                        attempts = reconnect_attempts.pop(cam_id, 1) or 1
                        await record_reconnect(cam_id, attempts=attempts)
                        _lc_record(cam_id, "status_online_restored",
                                   reason="probe OK after N failures", caller="camera_status_loop")
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
def _parse_mjpeg_boundary(content_type: str) -> bytes:
    """Extrait le boundary MJPEG depuis le header content-type upstream (fallback = 'frame')."""
    m = re.search(r"boundary=([^;\s]+)", content_type or "", re.IGNORECASE)
    return (m.group(1) if m else "frame").encode("latin-1")


async def _open_mjpeg_upstream(src: str) -> tuple[httpx.AsyncClient, httpx.Response]:
    """Ouvre une connexion streaming vers go2rtc pour la source MJPEG demandée.

    Retourne `(client, response)`. Le caller est responsable de leur fermeture.
    Lève `HTTPException(502)` si go2rtc renvoie un statut != 200.
    """
    client = httpx.AsyncClient(timeout=_MJPEG_UPSTREAM_TIMEOUT)
    req = client.build_request("GET", f"{GO2RTC_URL}/api/stream.mjpeg", params={"src": src})
    upstream = await client.send(req, stream=True)
    if upstream.status_code != 200:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(502, "Flux indisponible")
    return client, upstream


# ============ Pont vidéo direct_rtsp (ZÉRO Go2RTC) ============
# Aperçus du test de connexion (capture ffmpeg one-shot en mémoire, TTL 3 min)
_PROBE_PREVIEWS: dict = {}


async def _oneshot_probe_jpeg(rtsp_url: str, transport: str = "tcp"):
    """Capture 1 frame JPEG (640px) — décode H264 ET H265, zéro Go2RTC."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-rtsp_transport", transport if transport in ("tcp", "udp") else "tcp",
           "-skip_frame", "nokey",
           "-i", rtsp_url, "-frames:v", "1", "-vf", "scale=640:-2",
           "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"]
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=12)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return None
    return out if out[:3] == b"\xff\xd8\xff" else None


def _direct_live_mjpeg_response(cam: dict, want_hd: bool, request: Request, user: dict):
    """Pont vidéo pour stream_mode=direct_rtsp : RTSP → ffmpeg local → MJPEG
    multipart HTTP (lisible par <img>). Réutilise le générateur éprouvé de
    routes/mjpeg_direct.py. AUCUN appel Go2RTC (ni variantes, ni frame.jpeg).
    Le mur vidéo consomme la même URL /api/stream/{id}/live.mjpeg — inchangée.
    """
    from routes.mjpeg_direct import (_BOUNDARY, _build_ffmpeg_cmd as _direct_cmd,
                                      _mjpeg_stream_generator)
    rtsp_url = (cam.get("ai_rtsp_url") or "").strip() or _build_rtsp_url(cam)
    if not rtsp_url.lower().startswith("rtsp://"):
        raise HTTPException(502, "Aucune URL RTSP valide pour cette caméra (mode direct_rtsp)")
    transport = (cam.get("rtsp_transport") or "tcp").lower()
    if transport not in ("tcp", "udp"):
        transport = "tcp"
    # SD : limite la largeur à 640px (faible bande passante mur multi-caméras)
    cmd = _direct_cmd(rtsp_url, transport, target_fps=10 if want_hd else 8,
                      quality=4 if want_hd else 6,
                      max_width=0 if want_hd else 640,
                      codec=cam.get("codec") or "")
    from lifecycle import record as _lc_record
    client_ip = request.client.host if request.client else "?"
    _lc_record(cam["id"], "consumer_attached",
               reason=f"live.mjpeg direct_rtsp hd={1 if want_hd else 0}",
               caller=f"{user.get('email','?')}@{client_ip}",
               extra={"src": "direct-ffmpeg"})
    return StreamingResponse(
        _mjpeg_stream_generator(cmd),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
        headers={"Cache-Control": "no-store, no-cache",
                 "X-Accel-Buffering": "no",
                 "X-Preview-Source": "direct-ffmpeg"})


async def _direct_frame_jpeg(cam: dict, want_hd: bool) -> bytes:
    """Snapshot JPEG pour stream_mode=direct_rtsp — ZÉRO Go2RTC.

    1. Worker frame_source actif (pipeline IA direct) → réutilise la dernière
       frame en mémoire (aucune session RTSP supplémentaire vers la caméra).
    2. Sinon capture ffmpeg one-shot (-frames:v 1) sur le flux RTSP direct.
    """
    cam_id = cam["id"]
    try:
        import frame_source
        frame = frame_source.get_latest_frame(cam_id, max_age_sec=10.0)
        if frame is not None:
            import cv2
            if not want_hd and frame.shape[1] > 640:
                h = max(1, int(frame.shape[0] * 640 / frame.shape[1]))
                frame = cv2.resize(frame, (640, h))
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ok:
                return buf.tobytes()
    except Exception:
        logger.debug("frame_jpeg direct: frame_source indisponible pour %s", cam_id, exc_info=True)
    # P0-fix · Solution B : pas de mediamtx ni de broker video_pipelines
    # (module inexistant) — capture directement l'URL RTSP de la caméra.
    rtsp_url = (cam.get("ai_rtsp_url") or "").strip() or _build_rtsp_url(cam)
    if not rtsp_url.lower().startswith("rtsp://"):
        raise HTTPException(502, "Aucune URL RTSP valide pour cette caméra (mode direct_rtsp)")
    transport = (cam.get("rtsp_transport") or "tcp").lower()
    if transport not in ("tcp", "udp"):
        transport = "tcp"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-rtsp_transport", transport, "-skip_frame", "nokey",
           "-i", rtsp_url, "-frames:v", "1"]
    if not want_hd:
        cmd += ["-vf", "scale=640:-2"]
    cmd += ["-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=12)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise HTTPException(502, "Flux direct indisponible (timeout capture RTSP)")
    if out[:3] == b"\xff\xd8\xff":
        return out
    raise HTTPException(502, "Flux direct indisponible (capture ffmpeg vide)")


@stream_router.get("/stream/{camera_id}/live.mjpeg")
async def live_mjpeg(camera_id: str, request: Request,
                     hd: int = 0, user: dict = Depends(stream_user)):
    """Flux vidéo MJPEG temps réel (transcodé par go2rtc via `{name}_hd` ou `{name}_sd`).

    Query param `hd=1` → variante HD (résolution native). Nécessite la permission
    `stream_hd` ; sinon rétrogradation silencieuse vers SD.

    Robustesse (fix `ERR_INCOMPLETE_CHUNKED_ENCODING`) :
    - Cache `_ensure_variants` (throttle 60 s par caméra).
    - Attrape les erreurs upstream (ffmpeg producer mort, go2rtc restart…) et
      **reconnecte de façon transparente** au flux go2rtc jusqu'à
      `_MJPEG_RECONNECT_MAX_ATTEMPTS` tentatives avec backoff progressif.
    - Termine silencieusement quand le client browser ferme la connexion
      (`CancelledError`), sans stack trace parasite.
    - Distingue disconnection client vs upstream mort dans les logs (diagnostic).
    """
    cam_doc = await _authorize_camera(user, camera_id)
    want_hd = bool(int(hd or 0)) and has_permission(user, "stream_hd")
    # P0-fix · Solution B (Go2RTC + MJPEG) : seule stream_mode=direct_rtsp
    # contourne Go2RTC (pont ffmpeg local). Tout le reste passe par le
    # chemin Go2RTC éprouvé ci-dessous. (Remplace l'ancien dispatch
    # video_pipelines.base.resolve_pipeline — module inexistant, ModuleNotFoundError.)
    if camera_id not in DEMO_IDS and _is_direct_rtsp(cam_doc):
        return _direct_live_mjpeg_response(cam_doc, want_hd, request, user)
    src = _mjpeg_stream(camera_id, hd=want_hd)
    # Garantit la variante côté go2rtc (throttled → 1 appel par caméra / 60 s)
    await _ensure_variants_cached(_stream_name(camera_id))

    # Première connexion upstream (peut lever 502 si go2rtc down → réponse propre)
    client, upstream = await _open_mjpeg_upstream(src)
    upstream_content_type = upstream.headers.get(
        "content-type", "multipart/x-mixed-replace;boundary=frame")
    client_ip = (request.client.host if request.client else "?")
    # Trace du cycle de vie : ce consommateur vient de se connecter
    from lifecycle import record as _lc_record
    _lc_record(camera_id, "consumer_attached",
               reason=f"live.mjpeg?hd={1 if want_hd else 0}",
               caller=f"{user.get('email','?')}@{client_ip}",
               extra={"src": src})

    async def relay():
        nonlocal client, upstream
        attempt = 0
        total_bytes = 0
        started_at = time.monotonic()
        detach_reason = "unknown"
        try:
            while True:
                try:
                    async for chunk in upstream.aiter_bytes():
                        total_bytes += len(chunk)
                        yield chunk
                    # aiter_bytes est terminé sans exception → upstream a fermé
                    # proprement (EOF). Tenter une reconnexion : le producer go2rtc
                    # a peut-être été redémarré.
                    logger.info("mjpeg %s: upstream EOF après %d octets (client=%s)",
                                src, total_bytes, client_ip)
                    raise httpx.RemoteProtocolError("Upstream EOF")
                except (asyncio.CancelledError, GeneratorExit):
                    # Client browser a fermé la connexion — silencieux, normal.
                    detach_reason = "client disconnect"
                    logger.debug("mjpeg %s: client %s parti (relayed %d octets en %.1fs)",
                                 src, client_ip, total_bytes, time.monotonic() - started_at)
                    raise
                except (httpx.ReadError, httpx.RemoteProtocolError,
                        httpx.ReadTimeout, httpx.ConnectError,
                        httpx.WriteError, ConnectionResetError) as exc:
                    # Upstream go2rtc/ffmpeg mort. Tenter reconnexion transparente.
                    attempt += 1
                    if attempt > _MJPEG_RECONNECT_MAX_ATTEMPTS:
                        detach_reason = f"upstream lost, {attempt-1} retries exhausted ({type(exc).__name__})"
                        logger.warning(
                            "mjpeg %s: upstream perdu %d fois, abandon (client=%s, relayed=%d octets, err=%s)",
                            src, attempt, client_ip, total_bytes, type(exc).__name__)
                        return
                    backoff = _MJPEG_RECONNECT_BACKOFF_SEC * attempt
                    logger.warning(
                        "mjpeg %s: upstream perdu (%s) — reconnexion #%d dans %.1fs",
                        src, type(exc).__name__, attempt, backoff)
                    # Ferme l'ancien couple client/upstream
                    try:
                        await upstream.aclose()
                    except Exception:
                        pass
                    try:
                        await client.aclose()
                    except Exception:
                        pass
                    await asyncio.sleep(backoff)
                    # Rouvre une nouvelle connexion vers go2rtc
                    try:
                        client, upstream = await _open_mjpeg_upstream(src)
                    except HTTPException as http_exc:
                        logger.warning(
                            "mjpeg %s: reconnexion #%d refusée par go2rtc (HTTP %s)",
                            src, attempt, http_exc.status_code)
                        continue  # retry (jusqu'à MAX_ATTEMPTS)
                    # MJPEG frame-based : la concaténation d'un nouveau flux
                    # est transparente pour le browser (le boundary aligne).
                    logger.info("mjpeg %s: reconnexion #%d réussie", src, attempt)
        finally:
            try:
                await upstream.aclose()
            except Exception:
                pass
            try:
                await client.aclose()
            except Exception:
                pass
            _lc_record(camera_id, "consumer_detached", reason=detach_reason,
                       caller=f"{user.get('email','?')}@{client_ip}",
                       extra={"bytes_relayed": total_bytes,
                              "duration_s": round(time.monotonic() - started_at, 1)})

    # IMPORTANT : le boundary retourné par go2rtc doit être transmis intact au navigateur
    # (sinon Chrome/Firefox refusent d'afficher le MJPEG). On retransmet donc l'en-tête complet.
    return StreamingResponse(relay(), media_type=upstream_content_type,
                              headers={"Cache-Control": "no-store, no-cache",
                                       "X-Accel-Buffering": "no"})


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
    cam_doc = await _authorize_camera(user, camera_id)
    want_hd = bool(int(hd or 0)) and has_permission(user, "stream_hd")
    # P0-fix · Solution B (Go2RTC + MJPEG) : même logique que live_mjpeg —
    # seul stream_mode=direct_rtsp contourne Go2RTC.
    if camera_id not in DEMO_IDS and _is_direct_rtsp(cam_doc):
        data = await _direct_frame_jpeg(cam_doc, want_hd)
        return Response(content=data, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store",
                                 "X-Preview-Source": "direct-ffmpeg"})
    name = _stream_name(camera_id)
    # Garantit que les variantes HD/SD existent (auto-migration après upgrade, throttled)
    await _ensure_variants_cached(name)
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

    # v3.7.2 · Repli automatique sur les autres ports ONVIF courants.
    # Le port ONVIF n'est pas normalisé : 80 chez Hikvision/Axis, 8000 chez
    # Reolink, 2020 chez certains Dahua/Uniview. Le formulaire propose une
    # valeur par défaut qui ne peut pas être juste pour tout le monde, et
    # une erreur de port produit un message trompeur : sur une Hikvision
    # DS-2CD2086G2-I, le port 8000 sert le SDK propriétaire et coupe la
    # connexion ONVIF — l'utilisateur voit "vérifiez identifiants" alors
    # que les identifiants sont bons (constaté en conditions réelles).
    # On essaie donc le port demandé d'abord, puis les autres candidats.
    candidates = [int(body.onvif_port)]
    for p in (80, 8000, 2020, 8899):
        if p not in candidates:
            candidates.append(p)

    info = None
    used_port = int(body.onvif_port)
    last_error = None
    reachable_any = False
    for port in candidates:
        if not await asyncio.to_thread(_tcp_check, ip, port, 2.0):
            continue
        reachable_any = True
        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(_onvif_probe, ip, port, body.username, body.password),
                timeout=25,
            )
            used_port = port
            if port != int(body.onvif_port):
                logger.info("auto-detect %s : ONVIF trouvé sur le port %s (port demandé : %s)",
                            ip, port, body.onvif_port)
            break
        except asyncio.TimeoutError:
            last_error = "délai dépassé"
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)[:160]}"

    if info is None:
        if not reachable_any:
            raise HTTPException(400, f"Aucun port ONVIF joignable sur {ip} "
                                      f"(essayés : {', '.join(str(p) for p in candidates)})")
        raise HTTPException(400, f"ONVIF injoignable sur {ip} (ports essayés : "
                                  f"{', '.join(str(p) for p in candidates)}) — {last_error} — "
                                  f"vérifiez les identifiants, et que le protocole ONVIF est activé "
                                  f"sur la caméra (avec un compte ONVIF dédié chez Hikvision)")
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
    # `onvif_port` renvoyé = le port RÉELLEMENT retenu, pour que le formulaire
    # se corrige tout seul si le repli ci-dessus a joué.
    return {"ip": ip, "onvif_port": used_port, **info}


# ============ Aperçu vidéo depuis un flux temporaire (utilisé par Test Connexion) ============
@stream_router.get("/stream/preview.jpeg")
async def stream_preview(name: str = Query(...), user: dict = Depends(require_role("technician"))):
    """Aperçu du test de connexion — capture ffmpeg en mémoire (zéro Go2RTC)."""
    if not re.match(r"^probe_[0-9a-z_-]+$", name):
        raise HTTPException(400, "Nom de flux temporaire invalide")
    # purge des aperçus expirés (> 3 min)
    now = time.monotonic()
    for k in [k for k, (ts, _) in _PROBE_PREVIEWS.items() if now - ts > 180]:
        _PROBE_PREVIEWS.pop(k, None)
    hit = _PROBE_PREVIEWS.get(name)
    if not hit:
        raise HTTPException(404, "Aperçu expiré — relancez le test de connexion")
    return Response(content=hit[1], media_type="image/jpeg", headers={"Cache-Control": "no-store"})


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
    hint = None
    if not devices:
        hint = ("Aucun appareil détecté. La découverte WS-Discovery utilise du multicast UDP qui ne "
                "traverse PAS un réseau Docker bridge : si MG-VMS tourne en Docker, ajoutez la caméra "
                "par IP directe (bouton « Auto-détection ONVIF » du formulaire), ou passez le service "
                "backend en network_mode: host dans docker-compose.")
    return {"devices": devices, "count": len(devices), "hint": hint}


class OnvifProbeInput(BaseModel):
    ip: str
    port: int = 80
    username: str = ""
    password: str = ""


def _onvif_probe(ip: str, port: int, username: str, password: str) -> dict:
    """Interroge un appareil ONVIF : infos + profils + URI RTSP (bloquant).

    v1.0-rc4.5 · Audit ONVIF · Tolérance aux capacités secondaires manquantes :
    - Le service Media est essentiel pour les profils/RTSP. Si absent → erreur claire.
    - PTZ est OPTIONNEL — jamais bloquant.
    - Chaque étape est loggée pour permettre au technicien d'identifier la
      première étape en échec dans les logs backend (aucune UI de diagnostic).
    """
    from wsdl_path import onvif_camera
    logger.info("onvif_probe: connexion %s:%s user=%s", ip, port, username or "(anonyme)")
    cam = onvif_camera(ip, port, username, password)

    # 1. devicemgmt : identité de l'appareil (OBLIGATOIRE)
    try:
        device = cam.create_devicemgmt_service()
    except Exception as e:
        logger.warning("onvif_probe %s: create_devicemgmt_service échec — %s: %s",
                       ip, type(e).__name__, str(e)[:200])
        raise
    try:
        info = device.GetDeviceInformation()
    except Exception as e:
        logger.warning("onvif_probe %s: GetDeviceInformation échec — %s: %s",
                       ip, type(e).__name__, str(e)[:200])
        raise
    logger.info("onvif_probe %s: identité OK — %s %s (fw=%s)",
                ip, info.Manufacturer, info.Model, info.FirmwareVersion)

    # 2. Media service : profils + RTSP (OBLIGATOIRE pour ajout caméra)
    media = None
    profiles: list = []
    result_profiles: list = []
    try:
        media = cam.create_media_service()
        logger.info("onvif_probe %s: media service créé", ip)
    except Exception as e:
        logger.warning("onvif_probe %s: create_media_service échec — %s: %s",
                       ip, type(e).__name__, str(e)[:200])
        # On continue quand même avec media=None → profiles vide → 400 côté routeur
        # avec message plus explicite ("aucun profil ONVIF"). L'admin peut saisir
        # manuellement l'URL RTSP via le mode RTSP direct.

    if media is not None:
        try:
            profiles = media.GetProfiles() or []
            logger.info("onvif_probe %s: %d profil(s) ONVIF détecté(s)",
                        ip, len(profiles))
        except Exception as e:
            logger.warning("onvif_probe %s: GetProfiles échec — %s: %s",
                           ip, type(e).__name__, str(e)[:200])
            profiles = []

        for profile in profiles:
            rtsp_uri = None
            try:
                uri = media.GetStreamUri({
                    "StreamSetup": {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}},
                    "ProfileToken": profile.token,
                })
                rtsp_uri = uri.Uri
                logger.info("onvif_probe %s: profil %s → RTSP %s",
                            ip, profile.token, rtsp_uri[:80])
            except Exception as e:
                # Un profil sans RTSP n'est pas bloquant tant qu'un autre profil marche
                logger.info("onvif_probe %s: profil %s sans RTSP (%s) — profil skippé",
                            ip, profile.token, type(e).__name__)
            enc = getattr(profile, "VideoEncoderConfiguration", None)
            result_profiles.append({
                "token": profile.token,
                "name": str(profile.Name),
                "rtsp_url": rtsp_uri,
                "codec": str(getattr(enc, "Encoding", "")) if enc else None,
                "resolution": (f"{enc.Resolution.Width}x{enc.Resolution.Height}"
                               if enc and getattr(enc, "Resolution", None) else None),
            })

    # 3. PTZ : capacité OPTIONNELLE (jamais bloquante)
    ptz = False
    try:
        if profiles:
            ptz = bool(getattr(profiles[0], "PTZConfiguration", None))
    except Exception as e:
        logger.debug("onvif_probe %s: PTZ probe échec (optionnel) — %s", ip, type(e).__name__)
    logger.info("onvif_probe %s: PTZ=%s · profils avec RTSP=%d/%d",
                ip, ptz, sum(1 for p in result_profiles if p.get("rtsp_url")),
                len(result_profiles))
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
            timeout=25,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, "Appareil ONVIF injoignable (délai dépassé)")
    except Exception as e:
        raise HTTPException(502, f"Échec ONVIF : {type(e).__name__}: {str(e)[:160]} — vérifiez IP/port/identifiants")
    await log_audit(user, "onvif_probe", target=body.ip)
    return result


# ============ PTZ ONVIF (RÉEL) ============
# Commandes supportées côté client :
#   pan_left, pan_right, tilt_up, tilt_down,
#   zoom_in, zoom_out, stop,
#   home (goto home preset si dispo)
_PTZ_VECTORS = {
    "pan_left":   (-0.5, 0.0, 0.0),
    "pan_right":  (0.5,  0.0, 0.0),
    "tilt_up":    (0.0,  0.5, 0.0),
    "tilt_down":  (0.0, -0.5, 0.0),
    "zoom_in":    (0.0,  0.0, 0.5),
    "zoom_out":   (0.0,  0.0, -0.5),
}


def _ptz_execute(ip: str, port: int, username: str, password: str,
                 command: str, speed: float = 0.5, duration: float = 0.5) -> dict:
    """Exécute une commande PTZ ONVIF réelle (bloquant, à appeler via to_thread).

    Utilise ContinuousMove + attente `duration` + Stop, ce qui donne un déplacement
    court et prévisible depuis un simple clic UI. Pour `stop` on n'attend pas.
    """
    from wsdl_path import onvif_camera
    cmd = (command or "").strip().lower()
    if cmd not in _PTZ_VECTORS and cmd not in ("stop", "home"):
        raise ValueError(f"Commande PTZ inconnue: {command}")

    cam = onvif_camera(ip, port, username, password)
    media = cam.create_media_service()
    ptz = cam.create_ptz_service()
    profiles = media.GetProfiles()
    if not profiles:
        raise RuntimeError("Aucun profil média ONVIF disponible")
    # Choisir le premier profil ayant une PTZConfiguration
    profile = None
    for p in profiles:
        if getattr(p, "PTZConfiguration", None):
            profile = p
            break
    if profile is None:
        raise RuntimeError("Aucun profil ONVIF n'expose de PTZConfiguration")
    token = profile.token

    if cmd == "stop":
        req = ptz.create_type("Stop")
        req.ProfileToken = token
        req.PanTilt = True
        req.Zoom = True
        ptz.Stop(req)
        return {"ok": True, "command": cmd}

    if cmd == "home":
        try:
            req = ptz.create_type("GotoHomePosition")
            req.ProfileToken = token
            ptz.GotoHomePosition(req)
            return {"ok": True, "command": cmd}
        except Exception as e:
            raise RuntimeError(f"GotoHomePosition non supporté: {type(e).__name__}: {e}")

    dx, dy, dz = _PTZ_VECTORS[cmd]
    s = max(0.0, min(1.0, float(speed)))
    req = ptz.create_type("ContinuousMove")
    req.ProfileToken = token
    req.Velocity = {
        "PanTilt": {"x": dx * s, "y": dy * s},
        "Zoom":    {"x": dz * s},
    }
    ptz.ContinuousMove(req)
    # Bref déplacement puis stop pour éviter que la caméra parte à l'infini
    if duration and duration > 0:
        time.sleep(min(float(duration), 3.0))
    stop_req = ptz.create_type("Stop")
    stop_req.ProfileToken = token
    stop_req.PanTilt = True
    stop_req.Zoom = True
    try:
        ptz.Stop(stop_req)
    except Exception:
        pass
    return {"ok": True, "command": cmd, "duration": duration}


def _ptz_goto_preset(ip: str, port: int, username: str, password: str,
                     preset_token: str, speed: float = 0.6) -> dict:
    """Déplace la caméra vers un preset ONVIF."""
    from wsdl_path import onvif_camera
    cam = onvif_camera(ip, port, username, password)
    media = cam.create_media_service()
    ptz = cam.create_ptz_service()
    profiles = media.GetProfiles()
    profile = next((p for p in profiles if getattr(p, "PTZConfiguration", None)), None)
    if profile is None:
        raise RuntimeError("Aucun profil ONVIF PTZ")
    req = ptz.create_type("GotoPreset")
    req.ProfileToken = profile.token
    req.PresetToken = preset_token
    s = max(0.1, min(1.0, float(speed)))
    req.Speed = {"PanTilt": {"x": s, "y": s}, "Zoom": {"x": s}}
    ptz.GotoPreset(req)
    return {"ok": True, "preset": preset_token}


def _ptz_list_presets(ip: str, port: int, username: str, password: str) -> list:
    from wsdl_path import onvif_camera
    cam = onvif_camera(ip, port, username, password)
    media = cam.create_media_service()
    ptz = cam.create_ptz_service()
    profiles = media.GetProfiles()
    profile = next((p for p in profiles if getattr(p, "PTZConfiguration", None)), None)
    if profile is None:
        return []
    presets = ptz.GetPresets({"ProfileToken": profile.token}) or []
    return [
        {"token": str(getattr(p, "token", "")), "name": str(getattr(p, "Name", ""))}
        for p in presets
    ]
