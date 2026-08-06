"""Route module — Welcome Center (v0.5.1.a).

Le Welcome Center est l'écran d'accueil officiel de MG-VMS (route "/") :
il agrège en une requête légère (< 200 ms) toutes les informations qu'un
administrateur veut voir en 3 secondes après connexion :

  - **Health score** : score global 0-100 + statut de chaque brique (GPU,
    Mongo, pipeline, go2rtc, disque, caméras, plugins).
  - **Version** : version installée, dernière version connue, alerte MAJ.
  - **Changelog** : versions publiées depuis la dernière consultée par
    l'utilisateur (préférences).
  - **Alertes système** : disque faible, Mongo KO, GPU absent, go2rtc HS,
    version obsolète, sauvegarde absente.
  - **Stats express** : caméras, plugins actifs, workflows, events du jour,
    plaques du jour, occupation disque.
  - **Tips** : conseils contextuels dépendant de l'état système.
  - **News** : annonces administrateur (collection `welcome_news`).
  - **Préférences** : Ne plus afficher pour cette version, mode nouveautés
    uniquement, etc. — stockées per-user dans `welcome_prefs`.

Toutes les routes sont préfixées `/api/welcome/` et protégées par JWT.
Les endpoints d'écriture (news) requièrent le rôle admin.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user, require_role, site_scope, allowed_sites
from database import db

logger = logging.getLogger("routes.welcome")

welcome_router = APIRouter(prefix="/api/welcome", tags=["welcome"])

# Version courante de MG-VMS — pilotée par CHANGELOG.md (première entrée).
# En production, une CI peut injecter `MG_VMS_VERSION` dans l'env pour
# refléter la version réellement buildée dans l'image Docker.
_CHANGELOG_PATH = Path("/app/CHANGELOG.md")
_VERSION_HEADING_RE = re.compile(r"^##\s+\[([^\]]+)\]\s+—?\s*([\d-]+)?\s*—?\s*(.*)$")

# ── Health score & thresholds ─────────────────────────────────────────
# Poids par composant (somme = 100). Ajustable selon la criticité perçue.
_HEALTH_WEIGHTS = {
    "gpu": 15,
    "mongo": 15,
    "pipeline": 15,
    "go2rtc": 10,
    "disk": 15,
    "cpu": 5,
    "ram": 5,
    "cameras": 10,
    "plugins": 10,
}
_DISK_WARN_PCT = 80
_DISK_CRIT_PCT = 92
_CPU_WARN_PCT = 80
_RAM_WARN_PCT = 85


class NewsInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=4000)
    severity: str = Field("info", pattern="^(info|warning|critical)$")
    pinned: bool = False


class PrefsInput(BaseModel):
    last_seen_version: Optional[str] = None
    hide_until_next_version: Optional[bool] = None
    always_show: Optional[bool] = None
    important_only: Optional[bool] = None


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _parse_changelog(limit_entries: int = 30) -> list[dict]:
    """Parse `CHANGELOG.md` → liste d'entrées `{version, date, title, body}`.

    Le body est la première section d'une entrée (jusqu'à la prochaine
    entrée ou la fin du fichier). Version-tolérant, ne casse jamais si le
    fichier est absent — retourne une liste vide.
    """
    if not _CHANGELOG_PATH.exists():
        return []
    lines = _CHANGELOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    entries: list[dict] = []
    current: Optional[dict] = None
    buf: list[str] = []
    for line in lines:
        m = _VERSION_HEADING_RE.match(line)
        if m:
            if current is not None:
                current["body"] = "\n".join(buf).strip()
                entries.append(current)
                if len(entries) >= limit_entries:
                    return entries
                buf = []
            current = {
                "version": m.group(1).strip(),
                "date": (m.group(2) or "").strip(),
                "title": (m.group(3) or "").strip(),
                "body": "",
            }
        elif current is not None:
            buf.append(line)
    if current is not None:
        current["body"] = "\n".join(buf).strip()
        entries.append(current)
    return entries


def _current_version() -> str:
    """Version courante = première entrée du CHANGELOG (ou fallback env)."""
    import os
    env = os.environ.get("MG_VMS_VERSION")
    if env:
        return env
    entries = _parse_changelog(limit_entries=1)
    return entries[0]["version"] if entries else "unknown"


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


async def _quick_system() -> dict:
    """Snapshot système léger (psutil) — < 150 ms."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        du = psutil.disk_usage("/")
        return {
            "cpu": psutil.cpu_percent(interval=0.05),
            "ram_percent": vm.percent,
            "ram_used_gb": round(vm.used / (1024 ** 3), 2),
            "ram_total_gb": round(vm.total / (1024 ** 3), 2),
            "disk_percent": du.percent,
            "disk_used_gb": round(du.used / (1024 ** 3), 1),
            "disk_total_gb": round(du.total / (1024 ** 3), 1),
        }
    except Exception as e:
        return {"error": str(e)}


async def _quick_mongo() -> dict:
    try:
        t = time.perf_counter()
        await db.command("ping")
        return {"status": "ok", "ping_ms": int((time.perf_counter() - t) * 1000)}
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}


def _quick_gpu() -> dict:
    try:
        from ai_engine import get_ai_health
        h = get_ai_health()
        return {
            "yolo_loaded": bool(h.get("yolo_loaded")),
            "device": h.get("device", "cpu"),
            "cuda": bool(h.get("cuda_available")),
        }
    except Exception as e:
        return {"error": str(e)[:200], "yolo_loaded": False, "cuda": False}


def _quick_plugins() -> dict:
    try:
        from plugin_manager import bus
        entries = bus.summary()
        errors = [e for e in entries if e.get("state") in ("error", "missing_dependency")]
        return {
            "total": len(entries),
            "dispatchable": sum(1 for e in entries if e.get("dispatchable")),
            "errors": len(errors),
        }
    except Exception as e:
        return {"error": str(e)[:200], "total": 0, "dispatchable": 0, "errors": 0}


def _quick_pipeline() -> dict:
    try:
        from pipeline_v2.registry import registry
        s = registry.stats()
        return {
            "cameras_tracked": s.get("cameras_tracked", 0),
            "active": s.get("with_active_plugins", 0),
        }
    except Exception as e:
        return {"error": str(e)[:200], "cameras_tracked": 0, "active": 0}


async def _quick_go2rtc() -> dict:
    import os
    import httpx
    url = os.environ.get("GO2RTC_URL", "http://localhost:1984")
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(f"{url}/api/streams")
            return {"reachable": r.status_code == 200, "streams": len(r.json() or {}) if r.status_code == 200 else 0}
    except Exception as e:
        return {"reachable": False, "error": str(e)[:120]}


def _score_component(name: str, value: dict) -> tuple[float, str]:
    """Retourne (score 0-1, statut ok|warn|crit) pour un composant."""
    if name == "mongo":
        return (1.0, "ok") if value.get("status") == "ok" else (0.0, "crit")
    if name == "gpu":
        if value.get("cuda") and value.get("yolo_loaded"):
            return 1.0, "ok"
        if value.get("yolo_loaded"):
            return 0.6, "warn"  # CPU only
        return 0.0, "crit"
    if name == "pipeline":
        if value.get("error"):
            return 0.0, "crit"
        return (1.0, "ok") if value.get("active", 0) > 0 else (0.7, "warn")
    if name == "go2rtc":
        return (1.0, "ok") if value.get("reachable") else (0.3, "warn")
    if name == "disk":
        p = value.get("disk_percent", 0)
        if p >= _DISK_CRIT_PCT:
            return 0.0, "crit"
        if p >= _DISK_WARN_PCT:
            return 0.5, "warn"
        return 1.0, "ok"
    if name == "cpu":
        p = value.get("cpu", 0)
        return (0.5, "warn") if p >= _CPU_WARN_PCT else (1.0, "ok")
    if name == "ram":
        p = value.get("ram_percent", 0)
        return (0.5, "warn") if p >= _RAM_WARN_PCT else (1.0, "ok")
    if name == "cameras":
        total = value.get("total", 0)
        online = value.get("online", 0)
        if total == 0:
            return 0.8, "warn"  # No cameras configured yet
        ratio = online / total
        if ratio >= 0.9:
            return 1.0, "ok"
        if ratio >= 0.5:
            return 0.6, "warn"
        return 0.2, "crit"
    if name == "plugins":
        if value.get("errors", 0) > 0:
            return 0.5, "warn"
        return 1.0, "ok"
    return 1.0, "ok"


async def _compute_health(user: dict) -> dict:
    """Calcule le score global + le détail par composant."""
    system = await _quick_system()
    mongo = await _quick_mongo()
    gpu = _quick_gpu()
    plugins = _quick_plugins()
    pipeline = _quick_pipeline()
    go2rtc = await _quick_go2rtc()

    sf = site_scope({}, user)
    total_cams = await db.cameras.count_documents(sf)
    online_cams = await db.cameras.count_documents({**sf, "status": "online"})
    cameras = {"total": total_cams, "online": online_cams, "offline": total_cams - online_cams}

    components = {
        "gpu": _score_component("gpu", gpu),
        "mongo": _score_component("mongo", mongo),
        "pipeline": _score_component("pipeline", pipeline),
        "go2rtc": _score_component("go2rtc", go2rtc),
        "disk": _score_component("disk", system),
        "cpu": _score_component("cpu", system),
        "ram": _score_component("ram", system),
        "cameras": _score_component("cameras", cameras),
        "plugins": _score_component("plugins", plugins),
    }

    total_weight = sum(_HEALTH_WEIGHTS.values())
    weighted = sum(_HEALTH_WEIGHTS[k] * s for k, (s, _st) in components.items())
    score = int(round(_clamp(weighted / total_weight * 100)))

    detail = {
        k: {"score": round(s * 100), "status": st}
        for k, (s, st) in components.items()
    }
    return {
        "score": score,
        "components": detail,
        "system": system,
        "mongo": mongo,
        "gpu": gpu,
        "plugins": plugins,
        "pipeline": pipeline,
        "go2rtc": go2rtc,
        "cameras": cameras,
    }


def _derive_alerts(health: dict) -> list[dict]:
    """Alertes système déduites automatiquement du snapshot health."""
    out: list[dict] = []
    sys_ = health.get("system", {})
    if sys_.get("disk_percent", 0) >= _DISK_CRIT_PCT:
        out.append({
            "id": "disk-critical",
            "severity": "critical",
            "title": "Espace disque critique",
            "message": f"Disque à {sys_['disk_percent']}% — libérer de l'espace immédiatement.",
        })
    elif sys_.get("disk_percent", 0) >= _DISK_WARN_PCT:
        out.append({
            "id": "disk-warning",
            "severity": "warning",
            "title": "Espace disque faible",
            "message": f"Disque à {sys_['disk_percent']}% — planifier une purge des enregistrements.",
        })
    if health.get("mongo", {}).get("status") != "ok":
        out.append({
            "id": "mongo-down",
            "severity": "critical",
            "title": "MongoDB indisponible",
            "message": "Base de données injoignable — vérifier le service mongod.",
        })
    gpu = health.get("gpu", {})
    if not gpu.get("cuda") and not gpu.get("yolo_loaded"):
        out.append({
            "id": "gpu-missing",
            "severity": "warning",
            "title": "GPU absent",
            "message": "Aucun GPU CUDA détecté — MG-VMS tourne en mode CPU (dégradé).",
        })
    if not health.get("go2rtc", {}).get("reachable"):
        out.append({
            "id": "go2rtc-down",
            "severity": "warning",
            "title": "go2rtc arrêté",
            "message": "Le proxy streaming go2rtc ne répond pas — flux WebRTC indisponibles.",
        })
    if health.get("plugins", {}).get("errors", 0) > 0:
        n = health["plugins"]["errors"]
        out.append({
            "id": "plugin-errors",
            "severity": "warning",
            "title": f"{n} plugin(s) en erreur",
            "message": "Consulter le Plugin Center pour diagnostiquer.",
        })
    cams = health.get("cameras", {})
    if cams.get("total", 0) > 0 and cams.get("offline", 0) > 0:
        out.append({
            "id": "cameras-offline",
            "severity": "warning" if cams["offline"] < cams["total"] / 2 else "critical",
            "title": f"{cams['offline']} caméra(s) hors ligne",
            "message": "Vérifier réseau, alimentation ou URL RTSP.",
        })
    return out


def _derive_tips(health: dict) -> list[str]:
    """Conseils contextuels selon l'état système."""
    tips: list[str] = []
    if health.get("cameras", {}).get("total", 0) == 0:
        tips.append("Ajoutez votre première caméra depuis le Camera Center pour démarrer.")
    if health.get("plugins", {}).get("dispatchable", 0) == 0:
        tips.append("Activez au moins un plugin dans le Plugin Center pour enrichir la détection.")
    if not health.get("gpu", {}).get("cuda"):
        tips.append("Un GPU NVIDIA (CUDA) améliore drastiquement le FPS ANPR/YOLO.")
    tips.append("Utilisez le Camera Center pour détecter les capacités matérielles réelles d'une caméra.")
    tips.append("Utilisez le Pipeline Center pour diagnostiquer les FPS et goulets d'étranglement par caméra.")
    tips.append("Pour l'ANPR de nuit, privilégiez une caméra spécialisée (Dahua ITC, Hikvision DeepInView) plutôt qu'une caméra classique.")
    tips.append("Un téléobjectif dédié améliore fortement le taux OCR par rapport à une caméra grand-angle.")
    return tips[:5]


async def _quick_stats(user: dict) -> dict:
    """Compteurs rapides pour l'affichage du Welcome Center."""
    sf = site_scope({}, user)
    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    total_cams = await db.cameras.count_documents(sf)
    online_cams = await db.cameras.count_documents({**sf, "status": "online"})
    events_today = await db.events.count_documents({**sf, "timestamp": {"$gte": since_24h}})
    plates_today = await db.plates.count_documents({**sf, "timestamp": {"$gte": since_24h}})
    alerts_active = await db.alerts.count_documents({**sf, "acknowledged": False})
    workflows_active = 0
    try:
        workflows_active = await db.workflows.count_documents({"enabled": True})
    except Exception:
        pass
    allowed = allowed_sites(user)
    sites = await db.sites.count_documents({} if allowed is None else {"id": {"$in": allowed}})
    return {
        "cameras_total": total_cams,
        "cameras_online": online_cams,
        "cameras_offline": total_cams - online_cams,
        "sites": sites,
        "events_today": events_today,
        "plates_today": plates_today,
        "alerts_active": alerts_active,
        "workflows_active": workflows_active,
    }


async def _load_prefs(user_id: str) -> dict:
    doc = await db.welcome_prefs.find_one({"user_id": user_id}, {"_id": 0})
    return doc or {
        "user_id": user_id,
        "last_seen_version": None,
        "hide_until_next_version": False,
        "always_show": False,
        "important_only": False,
    }


async def _news_active() -> list[dict]:
    """Annonces publiées, épinglées en premier, plus récentes ensuite."""
    docs = await db.welcome_news.find(
        {}, {"_id": 0}
    ).sort([("pinned", -1), ("created_at", -1)]).to_list(50)
    return docs


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════


@welcome_router.get("/summary")
async def welcome_summary(user: dict = Depends(get_current_user)):
    """Réponse agrégée pour l'écran d'accueil MG-VMS.

    Un seul call ⇒ health score + version + alertes + tips + stats + prefs +
    news + changelog (nouveautés depuis la dernière version consultée).
    """
    health = await _compute_health(user)
    stats = await _quick_stats(user)
    version = _current_version()
    prefs = await _load_prefs(user["id"])
    news = await _news_active()

    # Changelog : nouveautés depuis last_seen_version
    all_entries = _parse_changelog(limit_entries=30)
    last_seen = prefs.get("last_seen_version")
    new_entries: list[dict] = []
    for e in all_entries:
        if e["version"] == last_seen:
            break
        new_entries.append(e)
    has_new_version = last_seen is not None and last_seen != version and len(new_entries) > 0

    return {
        "version": {
            "installed": version,
            "latest_known": version,  # même moteur pour l'instant (pas de call externe)
            "has_update": False,
            "build_date": all_entries[0]["date"] if all_entries else None,
        },
        "health": health,
        "stats": stats,
        "alerts": _derive_alerts(health),
        "tips": _derive_tips(health),
        "news": news,
        "prefs": prefs,
        "changelog": {
            "current_version": version,
            "new_since_last_seen": new_entries[:10],
            "has_new_version": has_new_version,
        },
    }


@welcome_router.get("/changelog")
async def welcome_changelog(
    since_version: Optional[str] = None,
    limit: int = 30,
    user: dict = Depends(get_current_user),
):
    """Changelog complet ou depuis une version donnée."""
    entries = _parse_changelog(limit_entries=max(1, min(limit, 100)))
    if since_version:
        cut: list[dict] = []
        for e in entries:
            if e["version"] == since_version:
                break
            cut.append(e)
        entries = cut
    return {
        "current_version": _current_version(),
        "entries": entries,
        "count": len(entries),
    }


@welcome_router.get("/preferences")
async def welcome_get_prefs(user: dict = Depends(get_current_user)):
    return await _load_prefs(user["id"])


@welcome_router.put("/preferences")
async def welcome_put_prefs(patch: PrefsInput, user: dict = Depends(get_current_user)):
    update = {k: v for k, v in patch.model_dump(exclude_none=True).items()}
    if not update:
        return await _load_prefs(user["id"])
    update["user_id"] = user["id"]
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.welcome_prefs.update_one(
        {"user_id": user["id"]}, {"$set": update}, upsert=True,
    )
    return await _load_prefs(user["id"])


@welcome_router.get("/news")
async def welcome_list_news(user: dict = Depends(get_current_user)):
    return {"items": await _news_active()}


@welcome_router.post("/news")
async def welcome_create_news(
    payload: NewsInput,
    user: dict = Depends(require_role("admin")),
):
    doc = {
        "id": str(uuid.uuid4()),
        "title": payload.title.strip(),
        "body": payload.body.strip(),
        "severity": payload.severity,
        "pinned": payload.pinned,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user.get("email"),
    }
    await db.welcome_news.insert_one(doc)
    doc.pop("_id", None)
    return doc


@welcome_router.delete("/news/{news_id}")
async def welcome_delete_news(
    news_id: str,
    user: dict = Depends(require_role("admin")),
):
    r = await db.welcome_news.delete_one({"id": news_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Annonce introuvable")
    return {"ok": True, "deleted": news_id}
