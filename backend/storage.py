"""MG-VMS — Gestion multi-disques (stockage RÉEL).

Fournit :
- La détection automatique des points de montage (via `psutil.disk_partitions`).
- L'ajout manuel de chemins (l'admin peut désigner n'importe quel dossier accessible).
- L'affichage capacité / utilisé / libre pour chaque disque.
- Activation d'un disque comme cible d'enregistrement avec quota individuel.
- Récapitulatif par caméra : disque cible + taille consommée.

Persistance : `settings.storage_pools` (liste de pools déclarés par l'admin).
La base des disques auto-détectés n'est pas persistée — recalculée à chaque appel.
"""
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import List, Optional

import psutil
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from auth import get_current_user, require_role, log_audit

storage_router = APIRouter(prefix="/api/storage", tags=["storage"])


# ═══════════════════════════════════════════════════════════════════
# Détection du type de disque (NVMe / SSD / HDD)
# ═══════════════════════════════════════════════════════════════════
def _base_block_device(device: str) -> str:
    """/dev/sda2 -> sda ; /dev/nvme0n1p1 -> nvme0n1 ; /dev/vdb1 -> vdb"""
    name = os.path.basename(device)
    m = re.match(r"^(nvme\d+n\d+)p?\d*$", name)
    if m:
        return m.group(1)
    m = re.match(r"^([a-zA-Z]+)\d*$", name)
    return m.group(1) if m else name


def _disk_type(device: str) -> str:
    """Type physique du disque : 'nvme' | 'ssd' | 'hdd' | 'unknown'.

    Un conteneur partage le noyau de l'hôte, donc /sys/block/<device>/queue/
    rotational reflète l'état RÉEL du disque physique hôte même pour un
    volume bind-mounté. NVMe est identifié par le nom du device (toujours
    un SSD, `rotational` n'est pas fiable pour ce type de contrôleur).
    """
    base = _base_block_device(device)
    if base.startswith("nvme"):
        return "nvme"
    try:
        with open(f"/sys/block/{base}/queue/rotational") as f:
            return "hdd" if f.read().strip() == "1" else "ssd"
    except OSError:
        return "unknown"


# ═══════════════════════════════════════════════════════════════════
# Modèles
# ═══════════════════════════════════════════════════════════════════
class StoragePool(BaseModel):
    id: str = ""
    name: str
    path: str
    enabled: bool = True
    max_size_gb: float = 0  # 0 = illimité (utilise la rétention globale)
    priority: int = 0  # priorité (0=principal). Les enregistrements iront sur les pools par priorité croissante.


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════
def _disk_usage(path: str) -> dict:
    try:
        du = shutil.disk_usage(path)
        return {
            "total_gb": round(du.total / 1e9, 2),
            "used_gb": round(du.used / 1e9, 2),
            "free_gb": round(du.free / 1e9, 2),
            "used_pct": round(100.0 * du.used / du.total, 1) if du.total else 0.0,
        }
    except (OSError, PermissionError):
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "used_pct": 0, "error": "path unreadable"}


def _detect_partitions() -> List[dict]:
    """Liste les disques physiques RÉELS, dédupliqués par device.

    En conteneur Docker, chaque bind-mount (y compris un fichier isolé comme
    /etc/hosts ou une lib NVIDIA individuelle) apparaît comme un point de
    montage séparé dans /proc/mounts — même quand plusieurs partagent le
    même disque physique hôte. Sans dédup, l'admin voyait des dizaines
    d'entrées sans rapport avec un vrai choix de disque. On ignore les
    montages de fichiers isolés (pas des dossiers) et on regroupe le reste
    par device : un seul disque, avec la liste de ses points de montage.
    """
    by_device: dict = {}
    for p in psutil.disk_partitions(all=False):
        if p.fstype in ("", "squashfs", "overlay", "tmpfs", "devtmpfs", "sysfs", "proc", "cgroup", "cgroup2"):
            continue
        if not os.path.isdir(p.mountpoint):
            continue  # bind-mount de fichier isolé — pas un disque
        entry = by_device.get(p.device)
        if entry is None:
            info = _disk_usage(p.mountpoint)
            by_device[p.device] = {
                "device": p.device,
                "type": _disk_type(p.device),
                "mountpoint": p.mountpoint,
                "mountpoints": [p.mountpoint],
                "fstype": p.fstype,
                **info,
            }
        else:
            entry["mountpoints"].append(p.mountpoint)
            # Le point de montage le plus court est le plus représentatif du disque
            if len(p.mountpoint) < len(entry["mountpoint"]):
                entry["mountpoint"] = p.mountpoint

    out = list(by_device.values())
    for entry in out:
        entry["mountpoints"].sort()
    out.sort(key=lambda d: d["mountpoint"])
    return out


async def _get_pools() -> List[dict]:
    doc = await db.settings.find_one({"key": "storage_pools"}, {"_id": 0})
    return list((doc or {}).get("value", []) or [])


async def _save_pools(pools: List[dict]) -> None:
    await db.settings.update_one({"key": "storage_pools"},
                                  {"$set": {"key": "storage_pools", "value": pools}}, upsert=True)


def _partition_for(partitions: List[dict], target_path: str) -> Optional[dict]:
    """Trouve le disque (déjà dédupliqué) dont un des points de montage est
    le préfixe le plus long du chemin donné."""
    if not target_path:
        return None
    best, best_len = None, -1
    for p in partitions:
        for mp in p["mountpoints"]:
            if target_path == mp or target_path.startswith(mp.rstrip("/") + "/"):
                if len(mp) > best_len:
                    best, best_len = p, len(mp)
    return best


def _dir_size_bytes(path: str) -> int:
    total = 0
    try:
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════
@storage_router.get("/overview")
async def storage_overview(user: dict = Depends(get_current_user)):
    """Vue globale : partitions détectées + pools déclarés + volumes enregistrements."""
    partitions = _detect_partitions()
    pools = await _get_pools()
    # Enrichit chaque pool avec l'usage réel de son dossier + le nombre d'enregistrements
    for pool in pools:
        pool["usage"] = _disk_usage(pool["path"])
        disk = _partition_for(partitions, pool["path"])
        pool["disk_type"] = disk["type"] if disk else "unknown"
        recs = await db.recordings.aggregate([
            {"$match": {"file_path": {"$regex": f"^{pool['path'].rstrip('/')}/"}}},
            {"$group": {"_id": None, "count": {"$sum": 1}, "size": {"$sum": "$size_mb"}}},
        ]).to_list(1)
        pool["recordings_count"] = recs[0]["count"] if recs else 0
        pool["recordings_size_gb"] = round((recs[0]["size"] if recs else 0) / 1000, 2)  # size_mb → gb
        pool["dir_size_gb"] = round(_dir_size_bytes(pool["path"]) / 1e9, 2)

    primary_recordings_dir = os.environ.get("RECORDINGS_DIR", "/app/recordings")
    recordings_disk = _partition_for(partitions, primary_recordings_dir)
    # "/app" et "/" ne sont jamais des points de montage distincts en conteneur
    # (racine = overlay, filtrée). /logs est garanti présent (volume compose) et
    # partage le même disque physique que le reste des données applicatives.
    app_disk = _partition_for(partitions, "/logs")

    return {
        "partitions": partitions,
        "pools": pools,
        "primary_recordings_dir": primary_recordings_dir,
        "recordings_disk": recordings_disk,
        "app_disk": app_disk,
    }


@storage_router.post("/pools")
async def create_pool(pool: StoragePool, user: dict = Depends(require_role("admin"))):
    path = os.path.abspath(pool.path)
    # Sécurité : refuse les chemins système sensibles
    forbidden = {"/", "/etc", "/boot", "/proc", "/sys", "/dev", "/root"}
    if path in forbidden or any(path.startswith(p + "/") for p in ("/etc/", "/boot/", "/proc/", "/sys/", "/dev/")):
        raise HTTPException(400, "Chemin interdit")
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(400, f"Impossible de créer/accéder au chemin : {e}")
    if not os.access(path, os.W_OK):
        raise HTTPException(400, "Chemin non accessible en écriture")

    pools = await _get_pools()
    if any(p["path"] == path for p in pools):
        raise HTTPException(400, "Un pool existe déjà pour ce chemin")
    doc = {
        "id": str(uuid.uuid4()), "name": pool.name.strip() or path,
        "path": path, "enabled": pool.enabled,
        "max_size_gb": float(pool.max_size_gb or 0),
        "priority": int(pool.priority or 0),
    }
    pools.append(doc)
    await _save_pools(pools)
    await log_audit(user, "storage_pool_created", doc["name"], f"path={path}")
    return doc


@storage_router.put("/pools/{pool_id}")
async def update_pool(pool_id: str, pool: StoragePool, user: dict = Depends(require_role("admin"))):
    pools = await _get_pools()
    idx = next((i for i, p in enumerate(pools) if p["id"] == pool_id), -1)
    if idx < 0:
        raise HTTPException(404, "Pool introuvable")
    existing = pools[idx]
    # Ne permet pas de changer le path (créer un nouveau pool si besoin) — évite la casse d'index
    pools[idx] = {
        **existing,
        "name": pool.name.strip() or existing["name"],
        "enabled": pool.enabled,
        "max_size_gb": float(pool.max_size_gb or 0),
        "priority": int(pool.priority or 0),
    }
    await _save_pools(pools)
    await log_audit(user, "storage_pool_updated", pools[idx]["name"])
    return pools[idx]


@storage_router.delete("/pools/{pool_id}")
async def delete_pool(pool_id: str, user: dict = Depends(require_role("admin"))):
    pools = await _get_pools()
    pool = next((p for p in pools if p["id"] == pool_id), None)
    if not pool:
        raise HTTPException(404, "Pool introuvable")
    # Vérifie qu'aucune caméra n'est encore assignée à ce pool
    assigned = await db.cameras.count_documents({"storage_pool_id": pool_id})
    if assigned > 0:
        raise HTTPException(400, f"{assigned} caméra(s) assignée(s) à ce pool — retirez l'assignation d'abord")
    pools = [p for p in pools if p["id"] != pool_id]
    await _save_pools(pools)
    await log_audit(user, "storage_pool_removed", pool["name"])
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════
# Assignation d'une caméra à un pool (config par caméra)
# ═══════════════════════════════════════════════════════════════════
class CameraStorageAssign(BaseModel):
    storage_pool_id: str = ""  # vide = utilise le RECORDINGS_DIR par défaut
    max_size_gb: float = 0     # 0 = illimité (utilise la rétention globale du pool)
    record_mode: str = "continuous"  # continuous | motion | ai | schedule
    profile_token: str = ""    # canal ONVIF (Main / Sub / autre)


@storage_router.get("/cameras/{camera_id}/assignment")
async def get_assignment(camera_id: str, user: dict = Depends(get_current_user)):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "storage_pool_id": 1,
                                                          "storage_max_size_gb": 1,
                                                          "record_mode": 1, "profile_token": 1})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    return {
        "storage_pool_id": cam.get("storage_pool_id", ""),
        "max_size_gb": float(cam.get("storage_max_size_gb", 0) or 0),
        "record_mode": cam.get("record_mode", "continuous"),
        "profile_token": cam.get("profile_token", ""),
    }


@storage_router.put("/cameras/{camera_id}/assignment")
async def set_assignment(camera_id: str, data: CameraStorageAssign,
                         user: dict = Depends(require_role("technician"))):
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "name": 1})
    if not cam:
        raise HTTPException(404, "Caméra introuvable")
    if data.record_mode not in ("continuous", "motion", "ai", "off"):
        raise HTTPException(400, "Mode d'enregistrement invalide")
    # Valide que le pool existe (sauf pour vide = défaut)
    if data.storage_pool_id:
        pools = await _get_pools()
        if not any(p["id"] == data.storage_pool_id for p in pools):
            raise HTTPException(400, "Pool de stockage introuvable")
    await db.cameras.update_one({"id": camera_id}, {"$set": {
        "storage_pool_id": data.storage_pool_id,
        "storage_max_size_gb": float(data.max_size_gb or 0),
        "record_mode": data.record_mode,
        "profile_token": data.profile_token or "",
    }})
    await log_audit(user, "camera_storage_assigned", cam["name"],
                    f"pool={data.storage_pool_id or 'default'} mode={data.record_mode}")
    return {"ok": True}
