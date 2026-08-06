"""Route module — Découverte réseau avancée (v0.5.5).

Assistant de découverte ONVIF étendu pour le bouton « Recherche ONVIF »
du formulaire d'ajout de caméra. Objectifs :

  1. Lister les interfaces réseau détectées (physiques + virtuelles).
  2. Permettre à l'utilisateur de choisir les réseaux à scanner et/ou
     d'ajouter des CIDR personnalisés (ex. `192.168.50.0/24`).
  3. Lancer un scan asynchrone, annulable, non bloquant.
  4. Émettre en temps réel via SSE (Server-Sent Events) :
       - `log`     : ligne horodatée pour la console noire
       - `progress`: progression (%, IP testées, ETA)
       - `device`  : appareil trouvé (caméra ou équipement générique)
       - `summary` : résumé final
       - `done`    : fin de scan (avec statut cancelled ou completed)

Contraintes :
  - Aucune modification de l'API existante `/api/cameras/discover`
    (rétro-compatibilité stricte).
  - Endpoints préfixés `/api/discovery/*` — nouveau namespace dédié.
  - Tous les endpoints protégés par le rôle `technician` (comme le
    scan ONVIF actuel).

Le scan combine :
  - **WS-Discovery multicast** (via `wsdiscovery`) : rapide et couvre
    les caméras compatibles (Reolink, Hikvision, Axis, Uniview…).
  - **Scan CIDR ciblé** : TCP-connect sur les ports 80/554/8000/2020
    pour repérer les équipements « qui répondent » puis probe ONVIF
    (`GetDeviceInformation`) sur ceux qui écoutent en 80. Les autres
    sont rapportés comme « équipement détecté mais non compatible ».
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import psutil
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth import log_audit, require_role
from database import db

logger = logging.getLogger("mgvms.discovery")

discovery_router = APIRouter(prefix="/api/discovery", tags=["discovery"])

# Ports usuels pour détecter des équipements réseau (caméras + NVR, imprimantes,
# switches, NAS…). Ordre = probabilité décroissante côté caméras IP.
_DEFAULT_PROBE_PORTS = [80, 554, 8000, 8080, 8899, 2020, 8081]
_ONVIF_PORTS = [80, 8080, 8000, 8899]  # ports fréquents pour ONVIF

# Interfaces considérées « virtuelles » et masquées par défaut côté UI.
_VIRTUAL_PREFIXES = ("docker", "br-", "veth", "tailscale", "wg", "tun", "tap",
                     "vmnet", "vboxnet", "cni", "flannel", "kube", "cali",
                     "virbr")


# ═════════════════════════════════════════════════════════════════════════
# Interfaces réseau
# ═════════════════════════════════════════════════════════════════════════
def _is_virtual_iface(name: str) -> bool:
    n = name.lower()
    if n == "lo":
        return True
    return any(n.startswith(p) for p in _VIRTUAL_PREFIXES)


def _iface_speed_state(name: str) -> tuple[Optional[int], str]:
    """Retourne (vitesse Mbps ou None, état 'up'/'down')."""
    try:
        stats = psutil.net_if_stats().get(name)
        if not stats:
            return None, "unknown"
        speed = stats.speed if stats.speed and stats.speed > 0 else None
        state = "up" if stats.isup else "down"
        return speed, state
    except Exception:  # pragma: no cover
        return None, "unknown"


def _default_gateways() -> dict[str, str]:
    """Renvoie {iface_name: gateway_ipv4} d'après /proc/net/route."""
    gws: dict[str, str] = {}
    try:
        with open("/proc/net/route", "r", encoding="ascii") as f:
            next(f)  # skip header
            for line in f:
                parts = line.split()
                if len(parts) < 4:
                    continue
                iface, dest_hex, gw_hex, flags_hex = parts[0], parts[1], parts[2], parts[3]
                if dest_hex != "00000000":  # non default route
                    continue
                try:
                    gw_bytes = bytes.fromhex(gw_hex)
                    gw_ip = ".".join(str(b) for b in gw_bytes[::-1])
                    gws[iface] = gw_ip
                except ValueError:
                    continue
    except FileNotFoundError:  # pragma: no cover — non-linux env
        pass
    return gws


def _list_network_interfaces() -> list[dict[str, Any]]:
    """Retourne la liste des interfaces réseau IPv4 détectées.

    Chaque item : {name, ip, netmask, cidr, gateway, speed_mbps, state,
                   virtual, mac}
    """
    result: list[dict[str, Any]] = []
    gws = _default_gateways()
    for name, addrs in psutil.net_if_addrs().items():
        ipv4 = None
        netmask = None
        mac = None
        for a in addrs:
            if a.family == socket.AF_INET and not ipv4:
                ipv4 = a.address
                netmask = a.netmask
            elif getattr(socket, "AF_PACKET", None) and a.family == socket.AF_PACKET:
                mac = a.address
        if not ipv4:
            continue
        try:
            net = ipaddress.IPv4Network(f"{ipv4}/{netmask}", strict=False)
            cidr = str(net)
        except (ValueError, TypeError):
            cidr = None
        speed, state = _iface_speed_state(name)
        result.append({
            "name": name,
            "ip": ipv4,
            "netmask": netmask,
            "cidr": cidr,
            "gateway": gws.get(name),
            "speed_mbps": speed,
            "state": state,
            "virtual": _is_virtual_iface(name),
            "mac": mac,
        })
    # Tri : interfaces physiques UP d'abord.
    result.sort(key=lambda i: (i["virtual"], i["state"] != "up", i["name"]))
    return result


@discovery_router.get("/interfaces")
async def list_interfaces(user: dict = Depends(require_role("technician"))):
    """Liste toutes les interfaces réseau détectées."""
    ifaces = await asyncio.to_thread(_list_network_interfaces)
    return {
        "interfaces": ifaces,
        "count": len(ifaces),
        "count_physical": sum(1 for i in ifaces if not i["virtual"]),
    }


# ═════════════════════════════════════════════════════════════════════════
# Task registry (in-memory)
# ═════════════════════════════════════════════════════════════════════════
@dataclass
class ScanTask:
    task_id: str
    user_id: str
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    total_ips: int = 0
    tested_ips: int = 0
    cameras: list[dict] = field(default_factory=list)
    other_devices: list[dict] = field(default_factory=list)
    interfaces_scanned: list[str] = field(default_factory=list)
    networks_scanned: list[str] = field(default_factory=list)
    errors: int = 0
    status: str = "running"  # running | completed | cancelled | error
    cancelled: bool = False
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    bg_task: Optional[asyncio.Task] = None


# Registry mémoire : {task_id: ScanTask}. Nettoyage automatique après 15 min.
_TASKS: dict[str, ScanTask] = {}
_TASK_TTL_SEC = 900


def _purge_old_tasks() -> None:
    now = time.time()
    stale = [tid for tid, t in _TASKS.items()
             if t.ended_at and (now - t.ended_at) > _TASK_TTL_SEC]
    for tid in stale:
        _TASKS.pop(tid, None)


async def _emit(task: ScanTask, event: str, data: dict) -> None:
    """Ajoute un événement à la file SSE du task."""
    payload = {"event": event, "data": data, "ts": time.time()}
    try:
        task.queue.put_nowait(payload)
    except asyncio.QueueFull:  # pragma: no cover
        pass


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


async def _log(task: ScanTask, line: str) -> None:
    await _emit(task, "log", {"time": _now_hms(), "line": line})


# ═════════════════════════════════════════════════════════════════════════
# Probing helpers (bloquants → exécutés dans un thread)
# ═════════════════════════════════════════════════════════════════════════
def _tcp_probe(ip: str, port: int, timeout: float = 0.4) -> bool:
    """Test TCP-connect rapide."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((ip, port)) == 0
    except OSError:
        return False


def _http_banner(ip: str, port: int, timeout: float = 0.6) -> str:
    """Récupère la première ligne d'une réponse HTTP (best-effort)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((ip, port))
            s.sendall(b"GET / HTTP/1.0\r\nHost: " + ip.encode() + b"\r\n\r\n")
            data = s.recv(2048).decode("utf-8", errors="ignore")
            return data
    except OSError:
        return ""


def _onvif_probe(ip: str, port: int, timeout: float = 2.5) -> Optional[dict]:
    """Probe ONVIF GetDeviceInformation sans authentification (best-effort).
    Retourne un dict {manufacturer, model, firmware, serial} si OK, sinon None.

    On tente sans credentials — pour la plupart des caméras ce sera un 401
    mais on peut quand même extraire les headers/faults pour reconnaître un
    endpoint ONVIF valide.
    """
    import urllib.request
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:tds="http://www.onvif.org/ver10/device/wsdl">'
        '<s:Body><tds:GetDeviceInformation/></s:Body></s:Envelope>'
    )
    url = f"http://{ip}:{port}/onvif/device_service"
    req = urllib.request.Request(
        url, data=envelope.encode("utf-8"),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return _parse_device_info(body, onvif_confirmed=True)
    except urllib.error.HTTPError as e:
        # 401/403 = ONVIF présent mais auth requise → on renvoie un stub
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        if e.code in (400, 401, 403) and ("onvif" in body.lower() or "soap" in body.lower() or e.code in (401, 403)):
            return {"onvif": True, "auth_required": True}
        return None
    except Exception:
        return None


def _parse_device_info(xml: str, onvif_confirmed: bool = False) -> Optional[dict]:
    """Extrait Manufacturer/Model/Firmware/Serial d'une réponse ONVIF SOAP."""
    if not xml:
        return None
    fields = {}
    for key, tag in (("manufacturer", "Manufacturer"), ("model", "Model"),
                     ("firmware", "FirmwareVersion"),
                     ("serial", "SerialNumber")):
        m = re.search(rf"<[a-zA-Z0-9]*:?{tag}>([^<]+)</", xml)
        if m:
            fields[key] = m.group(1).strip()
    if fields:
        fields["onvif"] = True
        return fields
    if onvif_confirmed and "Envelope" in xml:
        return {"onvif": True}
    return None


def _guess_manufacturer(banner: str, ip: str) -> str:
    """Devine le fabricant à partir d'un banner HTTP."""
    b = banner.lower()
    if "hikvision" in b or "webserver" in b and "app-webs" in b:
        return "Hikvision"
    if "reolink" in b or "netwave" in b:
        return "Reolink"
    if "dahua" in b:
        return "Dahua"
    if "axis" in b:
        return "Axis"
    if "uniview" in b or "univiewip" in b:
        return "Uniview"
    if "hanwha" in b or "wisenet" in b or "samsung" in b:
        return "Hanwha"
    if "synology" in b:
        return "Synology (NAS)"
    if "qnap" in b:
        return "QNAP (NAS)"
    if "printer" in b or "cups" in b or "hp-" in b or "canon" in b:
        return "Printer"
    if "mikrotik" in b or "routeros" in b:
        return "MikroTik (Switch/Router)"
    if "ubnt" in b or "ubiquiti" in b:
        return "Ubiquiti"
    return "Unknown"


def _device_type(manufacturer: str, has_onvif: bool, has_554: bool) -> str:
    """Classifie l'équipement : camera / nvr / printer / switch / other."""
    m = manufacturer.lower()
    if has_onvif or (has_554 and manufacturer in ("Hikvision", "Reolink",
                                                    "Dahua", "Axis", "Uniview",
                                                    "Hanwha")):
        return "camera"
    if "nas" in m:
        return "nas"
    if "printer" in m:
        return "printer"
    if "switch" in m or "router" in m or "mikrotik" in m or "ubiquiti" in m:
        return "network"
    if has_554:
        return "camera"
    return "other"


# ═════════════════════════════════════════════════════════════════════════
# Scan pipeline
# ═════════════════════════════════════════════════════════════════════════
async def _probe_ip(task: ScanTask, ip: str, semaphore: asyncio.Semaphore,
                    known_ips: set[str]) -> None:
    """Sonde une IP et émet les événements adéquats."""
    async with semaphore:
        if task.cancelled:
            return
        # 1) Ports ouverts ?
        open_ports = []
        for port in _DEFAULT_PROBE_PORTS:
            if task.cancelled:
                return
            ok = await asyncio.to_thread(_tcp_probe, ip, port, 0.35)
            if ok:
                open_ports.append(port)
        task.tested_ips += 1
        # Émettre le progress régulièrement (mais pas à chaque IP pour éviter le bruit).
        if task.tested_ips % 5 == 0 or task.tested_ips == task.total_ips:
            elapsed = time.time() - task.started_at
            ratio = task.tested_ips / max(task.total_ips, 1)
            eta = (elapsed / ratio - elapsed) if ratio > 0 else 0
            await _emit(task, "progress", {
                "tested": task.tested_ips, "total": task.total_ips,
                "cameras_found": len(task.cameras),
                "others_found": len(task.other_devices),
                "percent": round(ratio * 100, 1),
                "elapsed_sec": round(elapsed, 1),
                "eta_sec": round(max(eta, 0), 1),
            })
        if not open_ports:
            return

        # 2) Banner HTTP + probe ONVIF si port 80/8080/8000/8899 ouvert.
        banner = ""
        for p in open_ports:
            if p in (80, 8080, 8000, 8899):
                banner = await asyncio.to_thread(_http_banner, ip, p, 0.6)
                if banner:
                    break

        onvif_info = None
        onvif_port = None
        for p in open_ports:
            if p in _ONVIF_PORTS:
                info = await asyncio.to_thread(_onvif_probe, ip, p, 2.0)
                if info:
                    onvif_info = info
                    onvif_port = p
                    break

        manufacturer = (onvif_info or {}).get("manufacturer") or _guess_manufacturer(banner, ip)
        model = (onvif_info or {}).get("model")
        has_onvif = bool(onvif_info)
        has_554 = 554 in open_ports
        dtype = _device_type(manufacturer, has_onvif, has_554)

        device = {
            "ip": ip,
            "ports": open_ports,
            "manufacturer": manufacturer,
            "model": model,
            "firmware": (onvif_info or {}).get("firmware"),
            "serial": (onvif_info or {}).get("serial"),
            "onvif": has_onvif,
            "onvif_port": onvif_port,
            "type": dtype,
            "already_added": ip in known_ips,
            "auth_required": (onvif_info or {}).get("auth_required", False),
        }

        if dtype == "camera":
            task.cameras.append(device)
            await _log(task, f"{ip}  Camera detected")
            if manufacturer != "Unknown":
                await _log(task, f"          Manufacturer : {manufacturer}")
            if model:
                await _log(task, f"          Model        : {model}")
            if has_onvif:
                await _log(task, f"          ONVIF port   : {onvif_port}")
            if device["auth_required"]:
                await _log(task, "          (authentication required)")
            await _log(task, "          Done.")
            await _log(task, "--------------------------------")
            await _emit(task, "device", device)
        else:
            task.other_devices.append(device)
            await _log(task, f"{ip}  Device detected ({manufacturer})")
            await _log(task, f"          Not a supported camera (ports: {open_ports})")
            await _log(task, "--------------------------------")
            await _emit(task, "device", device)


async def _ws_discovery_multicast(task: ScanTask, iface_ip: Optional[str],
                                  known_ips: set[str]) -> None:
    """Lance WS-Discovery (multicast) et enregistre les résultats trouvés."""
    from wsdiscovery.discovery import ThreadedWSDiscovery

    def _run() -> list[dict]:
        wsd = ThreadedWSDiscovery()
        found: list[dict] = []
        try:
            wsd.start()
            services = wsd.searchServices(timeout=3)
            for svc in services:
                xaddrs = svc.getXAddrs()
                types = " ".join(str(t) for t in svc.getTypes())
                if not xaddrs:
                    continue
                if "onvif" not in types.lower() and "NetworkVideoTransmitter" not in types:
                    continue
                xaddr = xaddrs[0]
                m = re.search(r"https?://([\d.]+)(?::(\d+))?", xaddr)
                if not m:
                    continue
                found.append({
                    "ip": m.group(1),
                    "port": int(m.group(2)) if m.group(2) else 80,
                    "xaddr": xaddr,
                    "types": types,
                })
        finally:
            wsd.stop()
        return found

    await _log(task, "Searching WS-Discovery (multicast)...")
    try:
        results = await asyncio.to_thread(_run)
    except Exception as e:  # pragma: no cover
        await _log(task, f"WS-Discovery error: {type(e).__name__}: {e}")
        task.errors += 1
        return
    await _log(task, f"WS-Discovery: {len(results)} response(s)")
    for r in results:
        # Enrichir avec un probe ONVIF si possible.
        info = await asyncio.to_thread(_onvif_probe, r["ip"], r["port"], 2.0)
        manufacturer = (info or {}).get("manufacturer") or "ONVIF Device"
        # Dédup avec ce qui a été trouvé par le scan CIDR.
        if any(c["ip"] == r["ip"] for c in task.cameras):
            continue
        device = {
            "ip": r["ip"],
            "ports": [r["port"]],
            "manufacturer": manufacturer,
            "model": (info or {}).get("model"),
            "firmware": (info or {}).get("firmware"),
            "serial": (info or {}).get("serial"),
            "onvif": True,
            "onvif_port": r["port"],
            "type": "camera",
            "already_added": r["ip"] in known_ips,
            "source": "ws-discovery",
            "auth_required": (info or {}).get("auth_required", False),
        }
        task.cameras.append(device)
        await _log(task, f"{r['ip']}  Camera detected (WS-Discovery)")
        await _log(task, f"          Manufacturer : {manufacturer}")
        await _log(task, "--------------------------------")
        await _emit(task, "device", device)


async def _run_scan(task: ScanTask, networks: list[str],
                    interfaces: list[str], max_hosts_per_net: int) -> None:
    """Boucle principale du scan."""
    try:
        known_ips = {c.get("ip") for c in
                     await db.cameras.find({}, {"_id": 0, "ip": 1}).to_list(2000)}
        known_ips.discard(None)

        # Précalcule le total d'IP à tester (bornée).
        total = 0
        parsed: list[tuple[str, list[str]]] = []
        for cidr in networks:
            try:
                net = ipaddress.IPv4Network(cidr, strict=False)
                hosts = [str(h) for h in net.hosts()][:max_hosts_per_net]
                parsed.append((cidr, hosts))
                total += len(hosts)
            except ValueError:
                await _log(task, f"Invalid network: {cidr}")
                task.errors += 1
        task.total_ips = total

        await _log(task, "Starting discovery...")
        await _log(task, "--------------------------------")
        await _log(task, f"Networks   : {len(parsed)}  (IP total: {total})")
        if interfaces:
            await _log(task, f"Interfaces : {', '.join(interfaces)}")
        await _log(task, "--------------------------------")

        # 1) WS-Discovery global (une seule fois, tous les réseaux joignables).
        await _ws_discovery_multicast(task, None, known_ips)

        # 2) Scan CIDR ciblé.
        semaphore = asyncio.Semaphore(64)
        for cidr, hosts in parsed:
            if task.cancelled:
                break
            await _log(task, f"Interface  : {cidr}")
            await _log(task, "Searching ONVIF...")
            await _log(task, "Broadcast sent...")
            await _log(task, "Waiting responses...")
            await _log(task, "--------------------------------")
            task.networks_scanned.append(cidr)
            tasks = [_probe_ip(task, ip, semaphore, known_ips) for ip in hosts]
            for chunk_start in range(0, len(tasks), 128):
                if task.cancelled:
                    break
                await asyncio.gather(*tasks[chunk_start:chunk_start + 128],
                                     return_exceptions=True)

        task.status = "cancelled" if task.cancelled else "completed"
    except asyncio.CancelledError:
        task.status = "cancelled"
        task.cancelled = True
    except Exception as e:  # pragma: no cover
        task.status = "error"
        task.errors += 1
        await _log(task, f"Fatal error: {type(e).__name__}: {e}")
        logger.exception("Discovery scan crashed")
    finally:
        task.ended_at = time.time()
        by_maker: dict[str, int] = {}
        for c in task.cameras:
            k = c.get("manufacturer") or "Unknown"
            by_maker[k] = by_maker.get(k, 0) + 1
        summary = {
            "interfaces_scanned": len(task.interfaces_scanned),
            "networks_scanned": len(task.networks_scanned),
            "addresses_tested": task.tested_ips,
            "cameras_found": len(task.cameras),
            "onvif_count": sum(1 for c in task.cameras if c.get("onvif")),
            "by_manufacturer": by_maker,
            "other_devices_found": len(task.other_devices),
            "errors": task.errors,
            "elapsed_sec": round((task.ended_at or time.time()) - task.started_at, 2),
            "status": task.status,
        }
        await _log(task, "--------------------------------")
        await _log(task, f"Scan {task.status}.")
        await _log(task, f"Cameras: {summary['cameras_found']} · Others: "
                         f"{summary['other_devices_found']} · Errors: "
                         f"{summary['errors']}")
        await _emit(task, "summary", summary)
        await _emit(task, "done", {"status": task.status})


# ═════════════════════════════════════════════════════════════════════════
# API endpoints
# ═════════════════════════════════════════════════════════════════════════
class StartScanInput(BaseModel):
    networks: list[str] = Field(default_factory=list,
                                 description="CIDR à scanner, ex ['192.168.1.0/24']")
    interfaces: list[str] = Field(default_factory=list,
                                   description="Noms des interfaces sélectionnées (info seule)")
    max_hosts_per_network: int = Field(256, ge=1, le=1024)


@discovery_router.post("/start")
async def start_scan(body: StartScanInput,
                     user: dict = Depends(require_role("technician"))):
    """Démarre un scan asynchrone et renvoie un `task_id`."""
    _purge_old_tasks()
    if not body.networks:
        raise HTTPException(400, "Aucun réseau spécifié")
    # Vérifie les CIDR.
    for cidr in body.networks:
        try:
            ipaddress.IPv4Network(cidr, strict=False)
        except ValueError:
            raise HTTPException(400, f"CIDR invalide: {cidr}")

    task_id = uuid.uuid4().hex[:12]
    task = ScanTask(task_id=task_id, user_id=user.get("id") or user.get("email") or "unknown")
    task.interfaces_scanned = list(body.interfaces)
    _TASKS[task_id] = task
    task.bg_task = asyncio.create_task(
        _run_scan(task, body.networks, body.interfaces, body.max_hosts_per_network)
    )
    await log_audit(user, "discovery_scan_start",
                     details=f"task={task_id} nets={body.networks}")
    return {"task_id": task_id, "status": "running"}


@discovery_router.post("/{task_id}/cancel")
async def cancel_scan(task_id: str,
                      user: dict = Depends(require_role("technician"))):
    """Annule proprement un scan en cours."""
    task = _TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "Task inconnu")
    task.cancelled = True
    if task.bg_task and not task.bg_task.done():
        task.bg_task.cancel()
    await log_audit(user, "discovery_scan_cancel", details=f"task={task_id}")
    return {"task_id": task_id, "status": "cancelling"}


@discovery_router.get("/{task_id}/result")
async def get_result(task_id: str,
                     user: dict = Depends(require_role("technician"))):
    """Retourne le résumé final + toutes les caméras trouvées."""
    task = _TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "Task inconnu")
    by_maker: dict[str, int] = {}
    for c in task.cameras:
        k = c.get("manufacturer") or "Unknown"
        by_maker[k] = by_maker.get(k, 0) + 1
    return {
        "task_id": task_id,
        "status": task.status,
        "cameras": task.cameras,
        "other_devices": task.other_devices,
        "interfaces_scanned": task.interfaces_scanned,
        "networks_scanned": task.networks_scanned,
        "addresses_tested": task.tested_ips,
        "total_ips": task.total_ips,
        "cameras_found": len(task.cameras),
        "other_devices_found": len(task.other_devices),
        "onvif_count": sum(1 for c in task.cameras if c.get("onvif")),
        "by_manufacturer": by_maker,
        "errors": task.errors,
        "elapsed_sec": round(
            (task.ended_at or time.time()) - task.started_at, 2
        ),
    }


@discovery_router.get("/{task_id}/stream")
async def stream_scan(task_id: str, request: Request,
                      user: dict = Depends(require_role("technician"))):
    """Flux SSE des événements du scan.

    Le paramètre `token` (JWT) est accepté en query-string via
    `get_current_user` (fallback natif) — nécessaire car les EventSource
    natifs ne permettent pas de headers custom.
    """
    task = _TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "Task inconnu")

    async def event_gen():
        # Rejouer un event 'hello' pour synchroniser le client.
        yield f"event: hello\ndata: {{\"task_id\":\"{task_id}\"}}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(task.queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                # Keep-alive commentaire SSE (ligne débutant par `:`).
                yield ": keep-alive\n\n"
                if task.status != "running" and task.queue.empty():
                    break
                continue
            import json as _json
            yield (f"event: {payload['event']}\n"
                   f"data: {_json.dumps(payload['data'], default=str)}\n\n")
            if payload["event"] == "done":
                break

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache",
                                       "X-Accel-Buffering": "no"})
