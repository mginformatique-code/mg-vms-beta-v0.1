"""MG-VMS — Gestion intelligente des ressources matérielles (CPU/GPU) — Phase 1.

Sandbox : CPU/RAM détectés réellement (psutil). GPU détectés si présents
(nvidia-smi), sinon **inventaire simulé** clairement étiqueté pour piloter l'UI.
La détection/accélération matérielle réelle (CUDA/NVENC/OpenVINO/Coral) vit
dans /deploy. Persiste la configuration (assignations, profil, priorités, pools).
"""
import os
import random
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Optional, Dict, List

import psutil
from fastapi import APIRouter, Depends, HTTPException
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
PRIORITY_LEVELS = ["realtime", "normal", "low"]
PRIORITY_ENGINES = ["live", "playback", "ai", "anpr", "encode", "decode", "export", "thumbnails"]
PROFILES = ["economy", "balanced", "performance", "ultra", "custom"]

PROFILE_ASSIGNMENTS = {
    "economy":     {"decode": "cpu", "encode": "cpu", "live": "cpu", "playback": "cpu", "ai": "cpu",
                    "anpr": "cpu", "thumbnails": "cpu", "export": "cpu", "pdf": "cpu", "transcode": "cpu"},
    "balanced":    {"decode": "auto", "encode": "auto", "live": "auto", "playback": "auto", "ai": "auto",
                    "anpr": "auto", "thumbnails": "cpu", "export": "cpu", "pdf": "cpu", "transcode": "cpu"},
    "performance": {"decode": "nvdec", "encode": "nvenc", "live": "gpu", "playback": "gpu", "ai": "gpu0",
                    "anpr": "gpu", "thumbnails": "gpu", "export": "gpu", "pdf": "cpu", "transcode": "gpu"},
    "ultra":       {"decode": "nvdec", "encode": "nvenc", "live": "gpu_priority", "playback": "gpu", "ai": "gpu0",
                    "anpr": "gpu", "thumbnails": "gpu", "export": "gpu", "pdf": "gpu", "transcode": "gpu"},
}
PROFILE_PRIORITIES = {
    "economy":     {"live": "normal", "playback": "low", "ai": "low", "anpr": "low", "encode": "low",
                    "decode": "normal", "export": "low", "thumbnails": "low"},
    "balanced":    {"live": "realtime", "playback": "normal", "ai": "normal", "anpr": "normal", "encode": "normal",
                    "decode": "normal", "export": "low", "thumbnails": "low"},
    "performance": {"live": "realtime", "playback": "normal", "ai": "realtime", "anpr": "realtime", "encode": "normal",
                    "decode": "normal", "export": "normal", "thumbnails": "normal"},
    "ultra":       {"live": "realtime", "playback": "realtime", "ai": "realtime", "anpr": "realtime", "encode": "realtime",
                    "decode": "realtime", "export": "normal", "thumbnails": "normal"},
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
    """Tente nvidia-smi ; sinon renvoie un inventaire simulé (sandbox)."""
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
    # Inventaire simulé (sandbox)
    sim = [
        {"id": "gpu0", "index": 0, "name": "NVIDIA GeForce RTX 4070", "vendor": "NVIDIA",
         "vram_mb": 12288, "features": ["CUDA", "NVENC", "NVDEC", "TensorRT", "Vulkan", "OpenCL"]},
        {"id": "gpu1", "index": 1, "name": "NVIDIA RTX A2000", "vendor": "NVIDIA",
         "vram_mb": 6144, "features": ["CUDA", "NVENC", "NVDEC", "TensorRT"]},
        {"id": "igpu", "index": 2, "name": "Intel UHD Graphics 770", "vendor": "Intel",
         "vram_mb": 2048, "features": ["QuickSync", "OpenVINO", "OpenCL", "DirectML"]},
        {"id": "coral", "index": 3, "name": "Google Coral Edge TPU", "vendor": "Google",
         "vram_mb": 0, "features": ["EdgeTPU"]},
    ]
    return sim, True


def _accelerators(gpus: list) -> list:
    feats = set()
    for g in gpus:
        feats.update(g.get("features", []))
    return sorted(feats)


def _default_config() -> dict:
    return {
        "profile": "balanced",
        "assignments": dict(PROFILE_ASSIGNMENTS["balanced"]),
        "priorities": dict(PROFILE_PRIORITIES["balanced"]),
        "auto_optimize": True,
        "pools": [],
    }


async def seed_hardware():
    """Détecte le matériel et initialise la config (idempotent)."""
    doc = await db.hardware.find_one({"id": "global"}, {"_id": 0})
    gpus, simulated = _detect_gpus()
    info = {
        "cpu": _detect_cpu(), "ram": _detect_ram(),
        "gpus": gpus, "accelerators": _accelerators(gpus), "simulated_gpu": simulated,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
    if not doc:
        await db.hardware.insert_one({"id": "global", **info, "config": _default_config()})
    else:
        # rafraîchit la détection matérielle, conserve la config existante
        await db.hardware.update_one({"id": "global"}, {"$set": info})


async def _load() -> dict:
    doc = await db.hardware.find_one({"id": "global"}, {"_id": 0})
    if not doc:
        await seed_hardware()
        doc = await db.hardware.find_one({"id": "global"}, {"_id": 0})
    return doc


# ---------- Monitoring temps réel ----------
def _gpu_monitor(gpus: list) -> list:
    res = []
    for g in gpus:
        coral = g["vendor"] == "Google"
        util = random.randint(5, 40) if coral else random.randint(20, 92)
        vram_used = 0 if g["vram_mb"] == 0 else round(g["vram_mb"] * random.uniform(0.25, 0.85))
        res.append({
            "id": g["id"], "name": g["name"], "vendor": g["vendor"],
            "util_pct": util, "vram_mb": g["vram_mb"], "vram_used_mb": vram_used,
            "temp_c": random.randint(38, 78), "power_w": 0 if coral else random.randint(40, 220),
            "fan_pct": 0 if coral else random.randint(20, 75),
        })
    return res


async def _monitor_snapshot() -> dict:
    doc = await _load()
    from realtime import metrics_snapshot
    sys = metrics_snapshot()
    streams = await db.cameras.count_documents({"status": "online"})
    gpus = _gpu_monitor(doc.get("gpus", []))
    return {
        "cpu_pct": sys["cpu"], "ram_pct": sys["ram"],
        "cpu_temp_c": sys.get("temperature", 0) or random.randint(40, 70),
        "bandwidth_mbps": sys.get("bandwidth_mbps", 0),
        "streams": streams,
        "fps": streams * random.randint(20, 30),
        "ai_load_pct": random.randint(10, 80),
        "ffmpeg_load_pct": random.randint(10, 70),
        "power_total_w": sum(g["power_w"] for g in gpus) + random.randint(40, 120),
        "gpus": gpus,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------- Schemas ----------
class ConfigUpdate(BaseModel):
    assignments: Optional[Dict[str, str]] = None
    priorities: Optional[Dict[str, str]] = None
    auto_optimize: Optional[bool] = None


# ---------- Endpoints ----------
@hardware_router.get("/info")
async def hardware_info(user: dict = Depends(get_current_user)):
    doc = await _load()
    return {
        "cpu": doc["cpu"], "ram": doc["ram"], "gpus": doc["gpus"],
        "accelerators": doc["accelerators"], "simulated_gpu": doc.get("simulated_gpu", True),
        "detected_at": doc.get("detected_at"),
    }


@hardware_router.get("/config")
async def get_config(user: dict = Depends(get_current_user)):
    doc = await _load()
    cfg = doc.get("config") or _default_config()
    return {
        **cfg,
        "options": FUNCTION_OPTIONS, "labels": FUNCTION_LABELS,
        "priority_levels": PRIORITY_LEVELS, "priority_engines": PRIORITY_ENGINES,
        "profiles": PROFILES,
    }


@hardware_router.put("/config")
async def update_config(data: ConfigUpdate, user: dict = Depends(require_role("admin"))):
    doc = await _load()
    cfg = doc.get("config") or _default_config()
    if data.assignments is not None:
        for k, v in data.assignments.items():
            if k in FUNCTION_OPTIONS and v in FUNCTION_OPTIONS[k]:
                cfg["assignments"][k] = v
        cfg["profile"] = "custom"   # toute modification manuelle -> profil personnalisé
    if data.priorities is not None:
        for k, v in data.priorities.items():
            if k in PRIORITY_ENGINES and v in PRIORITY_LEVELS:
                cfg["priorities"][k] = v
        cfg["profile"] = "custom"
    if data.auto_optimize is not None:
        cfg["auto_optimize"] = data.auto_optimize
    await db.hardware.update_one({"id": "global"}, {"$set": {"config": cfg}})
    await log_audit(user, "hardware_config_updated", cfg["profile"])
    return cfg


@hardware_router.post("/profile/{profile}")
async def apply_profile(profile: str, user: dict = Depends(require_role("admin"))):
    if profile not in PROFILES:
        raise HTTPException(400, "Profil inconnu")
    doc = await _load()
    cfg = doc.get("config") or _default_config()
    cfg["profile"] = profile
    if profile != "custom":
        cfg["assignments"] = dict(PROFILE_ASSIGNMENTS[profile])
        cfg["priorities"] = dict(PROFILE_PRIORITIES[profile])
    await db.hardware.update_one({"id": "global"}, {"$set": {"config": cfg}})
    await log_audit(user, "hardware_profile_applied", profile)
    return cfg


@hardware_router.get("/monitor")
async def monitor(user: dict = Depends(get_current_user)):
    return await _monitor_snapshot()
