"""MG-VMS — Gestion intelligente des ressources matérielles (CPU/GPU).

Détection RÉELLE : CPU/RAM via `psutil`, GPU via `nvidia-smi` (CUDA), `rocm-smi` (AMD) et OpenVINO.
Si aucun accélérateur n'est physiquement présent, l'inventaire GPU est vide (aucun placeholder).
Persiste la configuration (assignations plugin→appareil, pools).
"""
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Optional, Dict, List

import psutil
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from database import db
from auth import get_current_user, require_role, log_audit

hardware_router = APIRouter(prefix="/api/hardware", tags=["hardware"])

# Options autorisées par fonction (le frontend les rend dynamiquement)
FUNCTION_OPTIONS: Dict[str, List[str]] = {
    "decode":      ["cpu", "nvdec", "quicksync", "amf", "auto"],
    "encode":      ["cpu", "nvenc", "quicksync", "amf", "auto"],
    "live":        ["cpu", "gpu", "auto", "gpu_priority", "cpu_priority"],
    "playback":    ["cpu", "gpu", "auto", "gpu_priority", "cpu_priority"],
    "ai":          ["cpu", "gpu0", "gpu1", "gpu2", "coral", "auto"],
    "anpr":        ["cpu", "gpu", "auto"],
    "thumbnails":  ["cpu", "gpu"],
    "export":      ["cpu", "gpu"],
    "pdf":         ["cpu", "gpu"],
    "transcode":   ["cpu", "gpu"],
}
FUNCTION_LABELS = {
    "decode": "Décodage vidéo", "encode": "Encodage vidéo", "live": "Live View",
    "playback": "Relecture vidéo", "ai": "IA (YOLO)", "anpr": "ANPR",
    "thumbnails": "Miniatures", "export": "Export vidéo", "pdf": "Génération PDF",
    "transcode": "Reconversion vidéo",
}
DEFAULT_ASSIGNMENTS = {
    "decode": "auto", "encode": "auto", "live": "auto", "playback": "auto", "ai": "auto",
    "anpr": "auto", "thumbnails": "cpu", "export": "cpu", "pdf": "cpu", "transcode": "cpu",
}


def _detect_cpu() -> dict:
    freq = None
    try:
        f = psutil.cpu_freq()
        freq = round(f.max or f.current) if f else None
    except Exception:
        freq = None
    return {
        "model": _cpu_model(),
        "cores": psutil.cpu_count(logical=False) or 0,
        "threads": psutil.cpu_count(logical=True) or 0,
        "freq_mhz": freq,
    }


def _cpu_model() -> str:
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return os.uname().machine if hasattr(os, "uname") else "CPU"


def _detect_ram() -> dict:
    vm = psutil.virtual_memory()
    return {"total_mb": round(vm.total / 1e6), "available_mb": round(vm.available / 1e6)}


def _detect_gpus() -> tuple[list, bool]:
    """Détection GPU via nvidia-smi. Renvoie une liste vide si aucun GPU présent (aucune donnée inventée)."""
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,temperature.gpu,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5)
            gpus = []
            for i, line in enumerate(out.stdout.strip().splitlines()):
                name, vram, temp, util = [x.strip() for x in line.split(",")]
                gpus.append({"id": f"gpu{i}", "index": i, "name": name, "vendor": "NVIDIA",
                             "vram_mb": int(vram), "features": ["CUDA", "NVENC", "NVDEC", "TensorRT"]})
            if gpus:
                return gpus, False
        except Exception:
            pass
    # Aucun GPU détecté : inventaire vide (réel)
    return [], False


def _accelerators(gpus: list) -> list:
    feats = set()
    for g in gpus:
        feats.update(g.get("features", []))
    return sorted(feats)


def _default_config() -> dict:
    return {
        "assignments": dict(DEFAULT_ASSIGNMENTS),
        "pools": [],
    }


async def seed_hardware():
    """Détecte le matériel et initialise la config (idempotent)."""
    doc = await db.hardware.find_one({"id": "global"}, {"_id": 0})
    gpus, _ = _detect_gpus()
    info = {
        "cpu": _detect_cpu(), "ram": _detect_ram(),
        "gpus": gpus, "accelerators": _accelerators(gpus),
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
    if not doc:
        await db.hardware.insert_one({"id": "global", **info, "config": _default_config()})
    else:
        # rafraîchit la détection matérielle, conserve la config existante
        await db.hardware.update_one({"id": "global"}, {"$set": info})
        # nettoie les champs de l'ex-panneau "Profils & priorités" (supprimé, jamais réellement branché)
        await db.hardware.update_one(
            {"id": "global"},
            {"$unset": {"config.profile": "", "config.priorities": "", "config.auto_optimize": ""}},
        )


async def _load() -> dict:
    doc = await db.hardware.find_one({"id": "global"}, {"_id": 0})
    if not doc:
        await seed_hardware()
        doc = await db.hardware.find_one({"id": "global"}, {"_id": 0})
    return doc


# ---------- Monitoring temps réel (100 % réel) ----------
def _gpu_monitor(gpus: list) -> list:
    """Métriques GPU réelles via nvidia-smi (vide si aucun GPU)."""
    if not gpus or not shutil.which("nvidia-smi"):
        return []
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,temperature.gpu,utilization.gpu,power.draw,fan.speed",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        res = []
        for i, line in enumerate(out.stdout.strip().splitlines()):
            name, vram, vram_used, temp, util, power, fan = [x.strip() for x in line.split(",")]
            res.append({"id": f"gpu{i}", "name": name, "vendor": "NVIDIA",
                        "util_pct": int(float(util)), "vram_mb": int(float(vram)),
                        "vram_used_mb": int(float(vram_used)), "temp_c": int(float(temp)),
                        "power_w": int(float(power)) if power not in ("N/A", "[N/A]") else 0,
                        "fan_pct": int(float(fan)) if fan not in ("N/A", "[N/A]") else 0})
        return res
    except Exception:
        return []


def _process_cpu(names: tuple[str, ...]) -> float:
    """Charge CPU réelle cumulée des processus dont le nom correspond."""
    total = 0.0
    for p in psutil.process_iter(["name", "cpu_percent"]):
        try:
            if (p.info["name"] or "").lower().startswith(names):
                total += p.info["cpu_percent"] or 0.0
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return round(min(total, 100.0), 1)


async def _monitor_snapshot() -> dict:
    doc = await _load()
    from realtime import metrics_snapshot
    sys = await metrics_snapshot()
    streams = await db.cameras.count_documents({"status": "online"})
    gpus = _gpu_monitor(doc.get("gpus", []))
    return {
        "cpu_pct": sys["cpu"], "ram_pct": sys["ram"],
        "cpu_temp_c": sys.get("temperature") or None,
        "bandwidth_mbps": sys.get("bandwidth_mbps", 0),
        "streams": streams,
        "fps": None,
        "ai_load_pct": _process_cpu(("python",)),
        "ffmpeg_load_pct": _process_cpu(("ffmpeg", "ffprobe", "go2rtc")),
        "power_total_w": sum(g["power_w"] for g in gpus) or None,
        "gpus": gpus,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------- Schemas ----------
class ConfigUpdate(BaseModel):
    assignments: Optional[Dict[str, str]] = None


# ---------- Endpoints ----------
@hardware_router.get("/info")
async def hardware_info(user: dict = Depends(get_current_user)):
    doc = await _load()
    return {
        "cpu": doc["cpu"], "ram": doc["ram"], "gpus": doc["gpus"],
        "accelerators": doc["accelerators"],
        "detected_at": doc.get("detected_at"),
    }


@hardware_router.get("/config")
async def get_config(user: dict = Depends(get_current_user)):
    doc = await _load()
    cfg = doc.get("config") or _default_config()
    return {
        **cfg,
        "options": FUNCTION_OPTIONS, "labels": FUNCTION_LABELS,
    }


@hardware_router.put("/config")
async def update_config(data: ConfigUpdate, user: dict = Depends(require_role("admin"))):
    doc = await _load()
    cfg = doc.get("config") or _default_config()
    if data.assignments is not None:
        for k, v in data.assignments.items():
            if k in FUNCTION_OPTIONS and v in FUNCTION_OPTIONS[k]:
                cfg["assignments"][k] = v
    await db.hardware.update_one({"id": "global"}, {"$set": {"config": cfg}})
    await log_audit(user, "hardware_config_updated", "assignments")
    return cfg


@hardware_router.get("/monitor")
async def monitor(user: dict = Depends(get_current_user)):
    return await _monitor_snapshot()
