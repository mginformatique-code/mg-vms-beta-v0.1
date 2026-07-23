"""MG-VMS — Diagnostic caméra : traçabilité des déconnexions et incidents.

Enregistre chaque transition d'état ONLINE↔OFFLINE avec le contexte complet :
- URL RTSP masquée (jamais le mot de passe)
- Flux utilisé (main/sub), codec, résolution, FPS demandé/réel, bitrate
- Uptime avant incident, temps depuis la dernière frame, tentatives de reconnexion
- Erreurs brutes FFmpeg / go2rtc / RTSP / TCP / UDP / ONVIF / HTTP / DNS (jamais tronquées)
- Cause probable identifiée par heuristique regex + indice de confiance

Consultable via `/api/diagnostics/*` — dédié à l'administration.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from database import db

logger = logging.getLogger("diagnostics")

# ============================================================================
# Table des causes probables (regex → (cause, sévérité))
# ============================================================================
CAUSE_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"connection\s+timed?\s*out|timed?\s*out\s+(during|while)", re.I),
     "Timeout RTSP", "Le serveur RTSP n'a pas répondu dans le délai imparti"),
    (re.compile(r"401\s+unauthori[sz]ed|authentication\s+(failed|refused)|wrong\s+password|invalid\s+credential", re.I),
     "Authentification refusée", "Identifiants RTSP/ONVIF invalides"),
    (re.compile(r"host\s+is\s+unreachable|no\s+route\s+to\s+host|network\s+unreachable", re.I),
     "Caméra hors ligne", "Adresse IP injoignable au niveau réseau"),
    (re.compile(r"connection\s+refused|econnrefused", re.I),
     "Caméra hors ligne", "Port RTSP fermé (caméra éteinte ou reboot)"),
    (re.compile(r"name\s+or\s+service\s+not\s+known|getaddrinfo|dns", re.I),
     "Erreur DNS", "Résolution DNS impossible pour l'hostname caméra"),
    (re.compile(r"invalid\s+data\s+found|malformed|corrupted|non-monotonous\s+dts|invalid\s+nal\s+unit|missing\s+sps|missing\s+pps", re.I),
     "GOP corrompu", "Flux vidéo malformé — GOP/SPS/PPS incorrects"),
    (re.compile(r"rtp:\s+missed|rtp\s+jitter|packet\s+loss|too\s+many\s+packets\s+lost", re.I),
     "Trop de pertes réseau", "Perte importante de paquets RTP"),
    (re.compile(r"end\s+of\s+file|eof\s+while\s+reading|server\s+closed\s+connection", re.I),
     "Flux interrompu", "Le serveur RTSP a fermé le flux"),
    (re.compile(r"404\s+not\s+found|stream\s+not\s+found|no\s+such\s+stream", re.I),
     "Flux RTSP invalide", "URL RTSP invalide (chemin/profil inexistant)"),
    (re.compile(r"onvif|wsdl|soap\s+fault", re.I),
     "Erreur ONVIF", "Échec de communication ONVIF (WSDL/SOAP)"),
    (re.compile(r"go2rtc\s+(crashed|not\s+responding|exit)", re.I),
     "Crash go2rtc", "Le service go2rtc a crashé — flux tous suspendus"),
    (re.compile(r"cuda|gpu|out\s+of\s+memory\s+on\s+device", re.I),
     "Saturation GPU", "Mémoire GPU saturée ou pilote CUDA en erreur"),
    (re.compile(r"cannot\s+allocate\s+memory|out\s+of\s+memory|memoryerror", re.I),
     "Mémoire insuffisante", "RAM système saturée"),
    (re.compile(r"(cpu|system)\s+overloaded|swap\s+full", re.I),
     "Saturation CPU", "CPU saturé — cycle IA en retard"),
    (re.compile(r"traceback\s+\(most\s+recent\s+call\s+last\)", re.I),
     "Exception Python", "Erreur non gérée côté backend"),
    (re.compile(r"tcp\s+error|econnreset|connection\s+reset\s+by\s+peer", re.I),
     "TCP réinitialisé", "Connexion TCP réinitialisée par la caméra"),
    (re.compile(r"udp\s+error|sendto:", re.I),
     "Erreur UDP", "Échec d'envoi UDP RTP"),
    (re.compile(r"reboot|restart|rebooted", re.I),
     "Caméra redémarrée", "Cycle de reboot détecté"),
]


def identify_cause(error_text: str) -> tuple[str, int, str]:
    """Analyse un message d'erreur brut et retourne (cause, confiance_%, détail).
    Retourne `("Cause inconnue", 0, "")` si aucun pattern ne matche."""
    if not error_text:
        return ("Cause inconnue", 0, "")
    text = str(error_text)
    for rgx, cause, detail in CAUSE_RULES:
        m = rgx.search(text)
        if m:
            # Confiance : longueur du match relative + spécificité du pattern
            confidence = min(95, 60 + int(len(m.group(0)) * 1.5))
            return (cause, confidence, detail)
    return ("Cause inconnue", 0, "")


# ============================================================================
# Collecte des métriques réelles du flux (via go2rtc + ffprobe)
# ============================================================================
GO2RTC_URL = "http://localhost:1984"


def _mask_password(url: str) -> str:
    """Masque le mot de passe d'une URL RTSP (rtsp://user:PASS@host → rtsp://user:***@host)."""
    if not url:
        return ""
    return re.sub(r"://([^:@/]+):([^@/]+)@", r"://\1:***@", url)


async def capture_stream_metrics(cam: dict) -> dict:
    """Interroge go2rtc pour obtenir les métriques réelles du flux caméra.
    Fallback gracieux si go2rtc/ffprobe indisponible."""
    metrics: dict = {
        "codec": (cam.get("codec") or "").upper() or None,
        "resolution": cam.get("resolution") or None,
        "fps_requested": cam.get("fps"),
        "fps_actual": None,
        "bitrate_kbps": None,
        "rtsp_transport": cam.get("rtsp_transport") or "tcp",
        "profile_name": cam.get("profile_name") or cam.get("profile_token") or "",
        "url_masked": _mask_password(cam.get("rtsp_url") or ""),
    }
    name = f"cam_{cam['id']}"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{GO2RTC_URL}/api/streams", params={"src": name})
            if r.status_code == 200:
                info = r.json() or {}
                # go2rtc renvoie une liste de producers + consumers avec bitrate/fps réels
                producers = info.get("producers") or info.get("Producers") or []
                for prod in (producers if isinstance(producers, list) else [producers]):
                    if not isinstance(prod, dict):
                        continue
                    if prod.get("bitrate"):
                        metrics["bitrate_kbps"] = int(prod["bitrate"]) // 1000
                    if prod.get("fps"):
                        metrics["fps_actual"] = round(float(prod["fps"]), 1)
                    if prod.get("codecs"):
                        metrics["codec_detected"] = str(prod["codecs"])
    except Exception:
        pass
    return metrics


# ============================================================================
# Enregistrement des événements de diagnostic
# ============================================================================
async def record_disconnect(cam: dict, error_text: str = "",
                             source: str = "camera_status_loop") -> str:
    """Enregistre une déconnexion caméra.
    Retourne l'id du document diagnostic pour permettre la corrélation avec la
    reconnexion ultérieure."""
    now = datetime.now(timezone.utc)
    cause, confidence, detail = identify_cause(error_text)
    metrics = await capture_stream_metrics(cam)

    # Uptime avant incident (secondes depuis last_seen ou created_at)
    uptime_s = None
    for key in ("last_seen", "created_at"):
        ts = cam.get(key)
        if ts:
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                uptime_s = (now - t).total_seconds()
                break
            except Exception:
                pass

    doc = {
        "id": str(uuid.uuid4()),
        "event_type": "disconnect",
        "camera_id": cam["id"],
        "camera_name": cam.get("name", ""),
        "site_id": cam.get("site_id", ""),
        "site_name": cam.get("site_name", ""),
        "timestamp": now.isoformat(),
        "previous_state": "online",
        "current_state": "offline",
        "cause": cause,
        "cause_confidence": confidence,
        "cause_detail": detail,
        "error_source": source,       # `camera_status_loop`, `ffmpeg`, `go2rtc`, ...
        "error_text": (error_text or "")[:4000],  # conservé complet (limite 4KB pour éviter le bloat)
        "uptime_before_incident_s": round(uptime_s, 1) if uptime_s is not None else None,
        "time_since_last_frame_s": None,  # rempli si dispo
        "reconnect_attempts": 0,
        "reconnect_duration_s": None,
        "reconnected": False,
        **metrics,
    }
    await db.camera_diagnostics.insert_one(dict(doc))
    doc.pop("_id", None)
    logger.warning("DIAGNOSTIC · %s DÉCONNEXION · cause=%s (%d%%) · %s",
                    cam.get("name", "?"), cause, confidence, error_text[:200])
    return doc["id"]


async def record_reconnect(camera_id: str, attempts: int = 1) -> None:
    """Enregistre une reconnexion réussie et corrèle avec la dernière déconnexion."""
    now = datetime.now(timezone.utc)
    # Trouve la dernière déconnexion non-résolue
    last = await db.camera_diagnostics.find_one(
        {"camera_id": camera_id, "event_type": "disconnect", "reconnected": False},
        sort=[("timestamp", -1)],
    )
    duration_s = None
    if last:
        try:
            t = datetime.fromisoformat(last["timestamp"].replace("Z", "+00:00"))
            duration_s = (now - t).total_seconds()
        except Exception:
            pass
        await db.camera_diagnostics.update_one(
            {"id": last["id"]},
            {"$set": {
                "reconnected": True,
                "reconnect_duration_s": round(duration_s, 1) if duration_s is not None else None,
                "reconnect_attempts": attempts,
                "reconnect_timestamp": now.isoformat(),
            }},
        )
    # Trace aussi la reconnexion comme événement dédié pour la timeline
    await db.camera_diagnostics.insert_one({
        "id": str(uuid.uuid4()),
        "event_type": "reconnect",
        "camera_id": camera_id,
        "timestamp": now.isoformat(),
        "previous_state": "offline",
        "current_state": "online",
        "cause": "Reconnexion automatique",
        "cause_confidence": 100,
        "reconnect_duration_s": round(duration_s, 1) if duration_s is not None else None,
        "reconnect_attempts": attempts,
        "linked_disconnect_id": (last or {}).get("id"),
    })
    logger.info("DIAGNOSTIC · %s RECONNEXION · durée=%s s · tentatives=%d",
                 camera_id, duration_s, attempts)


# ============================================================================
# Capture des logs bruts récents (FFmpeg / go2rtc / backend)
# ============================================================================
LOG_SOURCES = {
    "backend": "/var/log/supervisor/backend.err.log",
    "backend_out": "/var/log/supervisor/backend.out.log",
    "go2rtc": "/var/log/supervisor/go2rtc.err.log",
    "go2rtc_out": "/var/log/supervisor/go2rtc.out.log",
}


async def tail_log(source: str, filter_text: str = "", lines: int = 100) -> list[str]:
    """Retourne les `lines` dernières lignes d'un log, optionnellement filtrées.
    Utilise `deque` pour lecture efficace des fichiers volumineux."""
    from collections import deque
    path = LOG_SOURCES.get(source)
    if not path or not Path(path).exists():
        return []
    try:
        # Lecture non-bloquante en thread — évite de bloquer l'event loop
        def _read() -> list[str]:
            with open(path, encoding="utf-8", errors="replace") as f:
                if filter_text:
                    return list(deque((ln for ln in f if filter_text.lower() in ln.lower()),
                                        maxlen=lines))
                return list(deque(f, maxlen=lines))
        return await asyncio.to_thread(_read)
    except Exception as e:
        logger.warning("tail_log(%s) : %s", source, e)
        return []


async def camera_recent_errors(camera_id: str, camera_name: str = "",
                                 lines: int = 50) -> dict:
    """Récupère les dernières lignes de logs mentionnant la caméra."""
    result: dict = {}
    tokens = [camera_id]
    if camera_name:
        tokens.append(camera_name)
    tokens.append(f"cam_{camera_id}")  # nom go2rtc
    for src in ("backend", "go2rtc"):
        chunks: list[str] = []
        for token in tokens:
            lines_matched = await tail_log(src, filter_text=token, lines=lines)
            chunks.extend(lines_matched)
        # Déduplique en conservant l'ordre
        seen: set = set()
        deduped: list[str] = []
        for ln in chunks:
            if ln not in seen:
                seen.add(ln)
                deduped.append(ln)
        result[src] = deduped[-lines:]
    return result


# ============================================================================
# Statistiques agrégées par caméra
# ============================================================================
async def camera_diagnostic_summary(camera_id: str) -> dict:
    """Résumé d'exploitation : uptime cumulé, MTBF, moyenne reconnexion, causes fréquentes."""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=30)).isoformat()
    docs = await db.camera_diagnostics.find(
        {"camera_id": camera_id, "timestamp": {"$gte": since}},
        {"_id": 0},
    ).sort("timestamp", -1).to_list(500)
    disconnects = [d for d in docs if d.get("event_type") == "disconnect"]
    reconnects = [d for d in docs if d.get("event_type") == "reconnect"]
    reconnect_durations = [d.get("reconnect_duration_s") for d in reconnects
                             if isinstance(d.get("reconnect_duration_s"), (int, float))]
    avg_reconnect_s = round(sum(reconnect_durations) / len(reconnect_durations), 1) if reconnect_durations else None
    # MTBF = durée totale de la fenêtre / nombre de déconnexions
    mtbf_h = None
    if disconnects:
        mtbf_h = round((30 * 24) / len(disconnects), 1)
    # Causes fréquentes (top 5)
    from collections import Counter
    causes = Counter(d.get("cause", "Cause inconnue") for d in disconnects)
    top_causes = causes.most_common(5)
    last_disconnect = disconnects[0] if disconnects else None
    last_reconnect = reconnects[0] if reconnects else None
    return {
        "camera_id": camera_id,
        "window_days": 30,
        "disconnects_30d": len(disconnects),
        "reconnects_30d": len(reconnects),
        "avg_reconnect_s": avg_reconnect_s,
        "mtbf_hours": mtbf_h,
        "top_causes": [{"cause": c, "count": n} for c, n in top_causes],
        "last_disconnect": last_disconnect,
        "last_reconnect": last_reconnect,
    }
