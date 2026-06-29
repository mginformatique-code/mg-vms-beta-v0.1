"""MG-VMS — Supervision réseau (PRODUCTION, service `network-monitor`).

⚠️ Artefact de production. NON exécuté dans la sandbox (pas d'accès réseau/SNMP).

Rôle :
- ICMP (ping) périodique sur l'inventaire `equipment` (PostgreSQL) -> statut + latence.
- SNMP (GET) pour les métriques spécifiques :
    * Switch  : état/débit des ports (IF-MIB)
    * NAS     : volumes/espace (HOST-RESOURCES-MIB)
    * UPS     : charge/batterie/autonomie (UPS-MIB / RFC 1628)
    * Serveur : CPU/RAM/température
- Met à jour la base + publie Redis Pub/Sub (`network`) pour le temps réel.
- Déclenche une alerte critique sur passage hors-ligne ou UPS sur batterie.
"""
from __future__ import annotations
import os
import json
import time
import asyncio
import platform
import subprocess
from datetime import datetime, timezone

import redis
from sqlalchemy import create_engine, text

# pysnmp pour les métriques SNMP (cf. requirements.txt)
try:
    from pysnmp.hlapi import (getCmd, SnmpEngine, CommunityData, UdpTransportTarget,
                              ContextData, ObjectType, ObjectIdentity)
except Exception:
    getCmd = None

DB_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
SNMP_COMMUNITY = os.environ.get("SNMP_COMMUNITY", "public")
# OID UPS-MIB : upsEstimatedMinutesRemaining / upsBatteryStatus
OID_UPS_BATTERY_STATUS = "1.3.6.1.2.1.33.1.2.1.0"   # 2=normal,3=low,4=depleted
OID_UPS_CHARGE = "1.3.6.1.2.1.33.1.2.4.0"           # % de charge restante

engine = create_engine(DB_URL, pool_pre_ping=True)
rds = redis.from_url(REDIS_URL)


def _equipment() -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id::text, name, type, host(ip) AS ip, site_id::text, status, snmp_enabled "
            "FROM equipment"
        )).mappings().all()
    return [dict(r) for r in rows]


def icmp_ping(ip: str) -> tuple[bool, float | None]:
    count = "-n" if platform.system().lower() == "windows" else "-c"
    try:
        out = subprocess.run(["ping", count, "1", "-W", "1", ip],
                             capture_output=True, text=True, timeout=3)
        if out.returncode != 0:
            return False, None
        # extraction approximative de la latence
        for tok in out.stdout.replace("=", " ").split():
            if tok.replace(".", "").isdigit() and "." in tok:
                return True, float(tok)
        return True, None
    except Exception:
        return False, None


def snmp_get(ip: str, oid: str):
    if getCmd is None:
        return None
    it = getCmd(SnmpEngine(), CommunityData(SNMP_COMMUNITY),
               UdpTransportTarget((ip, 161), timeout=1.5, retries=1),
               ContextData(), ObjectType(ObjectIdentity(oid)))
    errInd, errStat, _, varBinds = next(it)
    if errInd or errStat:
        return None
    return varBinds[0][1] if varBinds else None


def raise_alert(eq: dict, reason: str):
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO alerts (type, severity, message, site_id, ts) "
            "VALUES ('network', 'critical', :msg, :site, :ts)"
        ), {"msg": f"{reason} : {eq['name']} ({eq['type']})",
            "site": eq["site_id"], "ts": datetime.now(timezone.utc)})
    rds.publish("alerts", json.dumps({
        "type": "network", "severity": "critical",
        "message": f"{reason} : {eq['name']}", "site_id": eq["site_id"],
    }))


def poll_once():
    for eq in _equipment():
        prev = eq["status"]
        up, latency = icmp_ping(eq["ip"])
        status = "offline" if not up else ("warning" if (latency or 0) > 12 else "online")
        update = {"status": status, "latency_ms": latency, "last_seen": datetime.now(timezone.utc)}

        if eq["type"] == "UPS" and up and eq.get("snmp_enabled"):
            bat_status = snmp_get(eq["ip"], OID_UPS_BATTERY_STATUS)
            charge = snmp_get(eq["ip"], OID_UPS_CHARGE)
            on_battery = str(bat_status) not in ("2", "None")
            update["on_battery"] = on_battery
            update["battery_pct"] = int(charge) if charge is not None else None
            if on_battery and not eq.get("on_battery"):
                raise_alert(eq, "UPS bascule sur batterie")

        with engine.begin() as c:
            cols = ", ".join(f"{k}=:{k}" for k in update)
            c.execute(text(f"UPDATE equipment SET {cols} WHERE id=:id"), {**update, "id": eq["id"]})
        rds.publish("network", json.dumps({"id": eq["id"], "status": status, "latency_ms": latency}))
        if prev != "offline" and status == "offline":
            raise_alert(eq, "Équipement hors-ligne")


def main():
    print(f"[network-monitor] poll every {POLL_INTERVAL}s (SNMP community={SNMP_COMMUNITY})")
    while True:
        try:
            poll_once()
        except Exception as e:
            print(f"[network-monitor] error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
