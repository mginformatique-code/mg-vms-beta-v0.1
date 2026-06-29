"""MG-VMS — Supervision réseau (SNMP/ICMP) — sandbox MongoDB.

⚠️ Sandbox : pas d'accès SNMP/ICMP réel → le ping/poll est SIMULÉ.
Le poller de production réel se trouve dans /deploy/network-monitor/.
Équipements : switches, NAS, UPS, routeurs, serveurs, NVR, génériques.
Métriques : statut (online/offline/warning) + latence (ICMP). UPS : batterie.
Alerte critique automatique sur passage hors-ligne ou UPS sur batterie.
"""
import uuid
import random
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

from database import db
from auth import get_current_user, require_role, log_audit, site_scope, allowed_sites
from notifications import send_notification
from realtime import broadcast_alert

network_router = APIRouter(prefix="/api/network", tags=["network"])

EQUIPMENT_TYPES = ["Switch", "Routeur", "NAS", "UPS", "Serveur", "NVR", "Caméra", "Générique"]


class EquipmentInput(BaseModel):
    name: str
    type: str = "Switch"
    site_id: str
    ip: str = ""
    model: str = ""
    vendor: str = ""
    parent_id: Optional[str] = None


def _public(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


async def _raise_equipment_alert(eq: dict, reason: str, background: BackgroundTasks):
    """Alerte critique + diffusion + notification quand un équipement tombe / UPS sur batterie."""
    alert = {
        "id": str(uuid.uuid4()), "type": "network", "severity": "critical",
        "message": f"{reason} : {eq['name']} ({eq['type']})",
        "camera_id": "", "camera_name": eq["name"],
        "site_id": eq.get("site_id", ""), "site_name": eq.get("site_name", "—"),
        "acknowledged": False, "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await db.alerts.insert_one(dict(alert))
    alert.pop("_id", None)
    await broadcast_alert(alert)
    body = (f"{reason}\nÉquipement : {eq['name']} ({eq['type']}) · IP {eq.get('ip', '—')}\n"
            f"Site : {alert['site_name']}\nHorodatage : {alert['timestamp']}")
    background.add_task(send_notification, "ALERTE RÉSEAU", body)
    return alert


def _simulate_ping(eq: dict) -> dict:
    """Simule une réponse ICMP/SNMP et renvoie les champs mis à jour."""
    up = random.random() > 0.12
    update = {"last_seen": datetime.now(timezone.utc).isoformat()}
    if up:
        latency = round(random.uniform(0.4, 18.0), 1)
        update["status"] = "warning" if latency > 12 else "online"
        update["latency_ms"] = latency
        update["uptime_sec"] = eq.get("uptime_sec", 0) + random.randint(30, 300)
    else:
        update["status"] = "offline"
        update["latency_ms"] = None
    if eq.get("type") == "UPS":
        on_battery = (not up) or random.random() > 0.85
        update["on_battery"] = on_battery
        update["battery_pct"] = random.randint(35, 100) if not on_battery else random.randint(8, 60)
        update["autonomy_min"] = round(update["battery_pct"] * 0.9) if on_battery else None
    return update


# ============ CRUD ============
@network_router.get("/equipment")
async def list_equipment(type: Optional[str] = None, site_id: Optional[str] = None,
                         status: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {}
    if type:
        q["type"] = type
    if site_id:
        q["site_id"] = site_id
    if status:
        q["status"] = status
    site_scope(q, user)
    return await db.equipment.find(q, {"_id": 0}).sort("name", 1).to_list(1000)


@network_router.get("/stats")
async def network_stats(user: dict = Depends(get_current_user)):
    q = {}
    site_scope(q, user)
    total = await db.equipment.count_documents(q)
    online = await db.equipment.count_documents({**q, "status": "online"})
    warning = await db.equipment.count_documents({**q, "status": "warning"})
    offline = await db.equipment.count_documents({**q, "status": "offline"})
    on_battery = await db.equipment.count_documents({**q, "type": "UPS", "on_battery": True})
    return {"total": total, "online": online, "warning": warning, "offline": offline, "ups_on_battery": on_battery}


@network_router.get("/topology")
async def topology(site_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {}
    if site_id:
        q["site_id"] = site_id
    site_scope(q, user)
    nodes = await db.equipment.find(q, {"_id": 0}).to_list(1000)
    ids = {n["id"] for n in nodes}
    edges = []
    for n in nodes:
        pid = n.get("parent_id")
        if pid and pid in ids:
            parent = next((x for x in nodes if x["id"] == pid), None)
            up = n["status"] != "offline" and parent and parent["status"] != "offline"
            edges.append({"source": pid, "target": n["id"], "status": "up" if up else "down"})
    return {"nodes": nodes, "edges": edges}


@network_router.get("/equipment/{eq_id}")
async def get_equipment(eq_id: str, user: dict = Depends(get_current_user)):
    eq = await db.equipment.find_one({"id": eq_id}, {"_id": 0})
    if not eq:
        raise HTTPException(404, "Équipement introuvable")
    allowed = allowed_sites(user)
    if allowed is not None and eq.get("site_id") not in allowed:
        raise HTTPException(403, "Accès refusé")
    return eq


@network_router.post("/equipment")
async def create_equipment(data: EquipmentInput, user: dict = Depends(require_role("technician"))):
    if data.type not in EQUIPMENT_TYPES:
        raise HTTPException(400, "Type invalide")
    site = await db.sites.find_one({"id": data.site_id}, {"_id": 0})
    if not site:
        raise HTTPException(400, "Site invalide")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()), "status": "offline", "latency_ms": None, "uptime_sec": 0,
        "on_battery": False, "battery_pct": None, "autonomy_min": None,
        "site_name": site["name"], "last_seen": now, "created_at": now,
        **data.model_dump(),
    }
    await db.equipment.insert_one(dict(doc))
    await log_audit(user, "equipment_created", data.name, data.type)
    return _public(doc)


@network_router.put("/equipment/{eq_id}")
async def update_equipment(eq_id: str, data: EquipmentInput, user: dict = Depends(require_role("technician"))):
    if data.type not in EQUIPMENT_TYPES:
        raise HTTPException(400, "Type invalide")
    update = data.model_dump()
    site = await db.sites.find_one({"id": data.site_id}, {"_id": 0})
    if site:
        update["site_name"] = site["name"]
    res = await db.equipment.update_one({"id": eq_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Équipement introuvable")
    await log_audit(user, "equipment_updated", data.name)
    return await db.equipment.find_one({"id": eq_id}, {"_id": 0})


@network_router.delete("/equipment/{eq_id}")
async def delete_equipment(eq_id: str, user: dict = Depends(require_role("technician"))):
    eq = await db.equipment.find_one({"id": eq_id}, {"_id": 0})
    await db.equipment.delete_many({"parent_id": eq_id})  # détache/supprime les enfants
    await db.equipment.delete_one({"id": eq_id})
    await log_audit(user, "equipment_deleted", eq["name"] if eq else eq_id)
    return {"ok": True}


# ============ ICMP/SNMP (simulé) ============
@network_router.post("/equipment/{eq_id}/ping")
async def ping_equipment(eq_id: str, background: BackgroundTasks, user: dict = Depends(get_current_user)):
    eq = await db.equipment.find_one({"id": eq_id}, {"_id": 0})
    if not eq:
        raise HTTPException(404, "Équipement introuvable")
    prev_status = eq.get("status")
    prev_battery = eq.get("on_battery", False)
    update = _simulate_ping(eq)
    await db.equipment.update_one({"id": eq_id}, {"$set": update})
    merged = {**eq, **update}
    if prev_status != "offline" and update.get("status") == "offline":
        await _raise_equipment_alert(merged, "Équipement hors-ligne", background)
    if eq.get("type") == "UPS" and not prev_battery and update.get("on_battery"):
        await _raise_equipment_alert(merged, "UPS bascule sur batterie", background)
    return {"equipment": merged, "result": "ok" if update.get("status") != "offline" else "timeout"}


@network_router.post("/poll")
async def poll_all(background: BackgroundTasks, site_id: Optional[str] = None,
                   user: dict = Depends(require_role("technician"))):
    q = {}
    if site_id:
        q["site_id"] = site_id
    site_scope(q, user)
    equipment = await db.equipment.find(q, {"_id": 0}).to_list(1000)
    alerts_raised = 0
    for eq in equipment:
        prev_status = eq.get("status")
        prev_battery = eq.get("on_battery", False)
        update = _simulate_ping(eq)
        await db.equipment.update_one({"id": eq["id"]}, {"$set": update})
        merged = {**eq, **update}
        if prev_status != "offline" and update.get("status") == "offline":
            await _raise_equipment_alert(merged, "Équipement hors-ligne", background)
            alerts_raised += 1
        if eq.get("type") == "UPS" and not prev_battery and update.get("on_battery"):
            await _raise_equipment_alert(merged, "UPS bascule sur batterie", background)
            alerts_raised += 1
    await log_audit(user, "network_poll", f"{len(equipment)} équipements", f"{alerts_raised} alertes")
    return {"polled": len(equipment), "alerts_raised": alerts_raised}


# ============ Seed (idempotent) ============
async def seed_equipment():
    if await db.equipment.count_documents({}) > 0:
        return
    sites = await db.sites.find({}, {"_id": 0}).to_list(50)
    if not sites:
        return
    VENDORS = {"Switch": ["Cisco", "Aruba", "Netgear"], "Routeur": ["MikroTik", "Cisco", "Ubiquiti"],
               "NAS": ["Synology", "QNAP"], "UPS": ["APC", "Eaton"], "Serveur": ["Dell", "HPE"],
               "NVR": ["Hikvision", "Dahua"]}
    now = datetime.now(timezone.utc).isoformat()
    docs = []

    def mk(name, typ, site, parent_id, idx):
        up = random.random() > 0.18
        st = "offline" if not up else ("warning" if random.random() > 0.8 else "online")
        d = {
            "id": str(uuid.uuid4()), "name": name, "type": typ,
            "site_id": site["id"], "site_name": site["name"],
            "ip": f"10.{idx}.{random.randint(1, 20)}.{random.randint(2, 254)}",
            "model": f"{random.choice(VENDORS.get(typ, ['Generic']))} {random.randint(100, 9999)}",
            "vendor": random.choice(VENDORS.get(typ, ["Generic"])),
            "parent_id": parent_id,
            "status": st,
            "latency_ms": None if st == "offline" else round(random.uniform(0.4, 16.0), 1),
            "uptime_sec": 0 if st == "offline" else random.randint(3600, 8_000_000),
            "on_battery": False, "battery_pct": None, "autonomy_min": None,
            "last_seen": now, "created_at": now,
        }
        if typ == "UPS":
            on_bat = random.random() > 0.8
            d["on_battery"] = on_bat
            d["battery_pct"] = random.randint(15, 60) if on_bat else random.randint(70, 100)
            d["autonomy_min"] = round(d["battery_pct"] * 0.9) if on_bat else None
            d["status"] = "warning" if on_bat else d["status"]
        return d

    for si, site in enumerate(sites):
        router = mk(f"GW-{site['type'][:3].upper()}", "Routeur", site, None, si + 30)
        docs.append(router)
        ups = mk(f"UPS-{site['type'][:3].upper()}", "UPS", site, router["id"], si + 30)
        docs.append(ups)
        sw1 = mk(f"SW-{site['type'][:3].upper()}-01", "Switch", site, router["id"], si + 30)
        docs.append(sw1)
        if random.random() > 0.5:
            sw2 = mk(f"SW-{site['type'][:3].upper()}-02", "Switch", site, sw1["id"], si + 30)
            docs.append(sw2)
        docs.append(mk(f"NAS-{site['type'][:3].upper()}", "NAS", site, sw1["id"], si + 30))
        docs.append(mk(f"NVR-{site['type'][:3].upper()}", "NVR", site, sw1["id"], si + 30))
        docs.append(mk(f"SRV-{site['type'][:3].upper()}", "Serveur", site, sw1["id"], si + 30))

    await db.equipment.insert_many([dict(d) for d in docs])
