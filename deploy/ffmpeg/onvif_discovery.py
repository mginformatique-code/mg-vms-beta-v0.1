"""MG-VMS — Découverte ONVIF (PRODUCTION). NON exécuté en dev (pas de réseau caméras).

WS-Discovery sur le LAN -> pour chaque équipement ONVIF, récupère le profil média
(URI RTSP, résolution) et les capacités PTZ, puis insère/maj la caméra en base.
"""
from __future__ import annotations
import os
from urllib.parse import urlparse

from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery
from onvif import ONVIFCamera
from sqlalchemy import create_engine, text

DB_URL = os.environ["DATABASE_URL"]
engine = create_engine(DB_URL, pool_pre_ping=True)


def discover(timeout: int = 4) -> list[str]:
    wsd = WSDiscovery()
    wsd.start()
    services = wsd.searchServices(timeout=timeout)
    hosts = []
    for s in services:
        for addr in s.getXAddrs():
            host = urlparse(addr).hostname
            if host:
                hosts.append(host)
    wsd.stop()
    return sorted(set(hosts))


def probe(host: str, user: str, password: str, port: int = 80) -> dict:
    cam = ONVIFCamera(host, port, user, password)
    media = cam.create_media_service()
    profiles = media.GetProfiles()
    token = profiles[0].token
    uri = media.GetStreamUri({
        "StreamSetup": {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}},
        "ProfileToken": token,
    }).Uri
    ptz = False
    try:
        ptz = bool(cam.create_ptz_service().GetConfigurations())
    except Exception:
        ptz = False
    dev = cam.create_devicemgmt_service().GetDeviceInformation()
    return {"ip": host, "rtsp_url": uri, "ptz_enabled": ptz,
            "model": f"{dev.Manufacturer} {dev.Model}", "protocol": "ONVIF"}


def upsert_camera(site_id: str, info: dict):
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO cameras (site_id, name, ip, rtsp_url, model, protocol, ptz_enabled, status)
            VALUES (:site_id, :name, :ip, :rtsp, :model, 'ONVIF', :ptz, 'offline')
            ON CONFLICT DO NOTHING
        """), {"site_id": site_id, "name": info["model"], "ip": info["ip"],
               "rtsp": info["rtsp_url"], "model": info["model"], "ptz": info["ptz_enabled"]})


if __name__ == "__main__":
    user = os.environ.get("ONVIF_USER", "admin")
    pwd = os.environ.get("ONVIF_PASSWORD", "")
    site = os.environ.get("DISCOVERY_SITE_ID", "")
    for host in discover():
        try:
            info = probe(host, user, pwd)
            print("ONVIF:", info)
            if site:
                upsert_camera(site, info)
        except Exception as e:
            print(f"probe {host} failed: {e}")
