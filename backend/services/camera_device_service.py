"""Camera Device Service — orchestrateur unique du device layer.

Le code métier (workflows, plugins, UI, routes API) obtient un
``CameraDriver`` prêt à l'usage via ce service. Le service :

  - Récupère la caméra depuis MongoDB
  - Instancie le driver correspondant à ``camera.vendor`` (fallback ONVIF)
  - Cache l'instance par ``camera_id`` (une session par caméra)
  - Persiste les ``capabilities`` détectées dans ``cameras.capabilities``

Un driver n'est JAMAIS instancié directement ailleurs dans le code.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from drivers import (
    CameraDriver, CameraCapabilities, DeviceInfo, DeviceStatus, StreamInfo,
    CameraDriverError, UnsupportedCapabilityError, resolve_driver,
)

logger = logging.getLogger("services.camera_device")


def _host_from_rtsp(url: str) -> Optional[str]:
    """Extrait l'hôte d'une URL RTSP (utilisé comme fallback d'IP ONVIF)."""
    if not url:
        return None
    m = re.match(r"^rtsps?://(?:[^@/]*@)?([^:/?#]+)", url, re.IGNORECASE)
    return m.group(1) if m else None


class CameraDeviceService:
    """Service singleton — ``camera_device_service`` en fin de module."""

    def __init__(self):
        self._drivers: dict[str, CameraDriver] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, cam_id: str) -> asyncio.Lock:
        lk = self._locks.get(cam_id)
        if lk is None:
            lk = asyncio.Lock()
            self._locks[cam_id] = lk
        return lk

    async def get_driver(self, cam_id: str) -> CameraDriver:
        """Retourne un driver connecté pour cette caméra (instancie + connect si besoin)."""
        d = self._drivers.get(cam_id)
        if d is not None and d._connected:
            return d
        async with self._lock(cam_id):
            d = self._drivers.get(cam_id)
            if d is not None and d._connected:
                return d
            cam = await self._load_camera(cam_id)
            from crypto_utils import decrypt_secret
            drv = resolve_driver(
                # v3.4 · Aucune caméra existante n'a de champ "vendor" explicite
                # (rien ne le renseigne à la création) — ça retombait TOUJOURS sur
                # le driver ONVIF générique, qui ne détecte que les capacités
                # ONVIF standard. Les extras Reolink (spotlight, sirène, SD card,
                # IR) sont propriétaires et invisibles en ONVIF générique. Le
                # fabricant réel EST déjà détecté et stocké (`manufacturer`, via
                # GetDeviceInformation) — on l'utilise en repli avant "onvif".
                vendor=cam.get("vendor") or cam.get("manufacturer") or "onvif",
                host=cam["ip"],
                username=cam.get("username") or "",
                # v3.4 · Bug critique : le mot de passe caméra est chiffré Fernet
                # en base (voir crypto_utils.py) mais était passé TEL QUEL au
                # driver — l'authentification ONVIF échouait donc TOUJOURS avec
                # le ciphertext comme mot de passe, jamais le vrai mot de passe.
                # Confirmé en prod : ce chemin causait des échecs 401 répétés
                # jusqu'au verrouillage anti-bruteforce de la caméra (Reolink
                # RLC-81MA, "device is locked... wrong username/password many
                # times"). decrypt_secret() est rétro-compatible (renvoie la
                # valeur telle quelle si déjà en clair).
                password=decrypt_secret(cam.get("password") or ""),
                port=cam.get("onvif_port") or 80,
            )
            await drv.connect()
            self._drivers[cam_id] = drv
            return drv

    async def release(self, cam_id: str) -> None:
        d = self._drivers.pop(cam_id, None)
        if d is not None:
            try:
                await d.disconnect()
            except Exception:
                pass

    async def discover(self, cam_id: str) -> dict:
        """Workflow complet : connect → probe → persist capabilities.

        Retourne : ``{"info": DeviceInfo, "capabilities": ..., "streams": [...]}``.
        Persiste automatiquement en Mongo : ``cameras[camera_id].driver`` +
        ``cameras[camera_id].capabilities`` + ``cameras[camera_id].device_info``.
        """
        drv = await self.get_driver(cam_id)
        info = await drv.get_device_info()
        caps = await drv.get_capabilities()
        streams = await drv.get_streams()
        result = {
            "info": info.to_dict(),
            "capabilities": caps.to_dict(),
            "streams": [s.to_dict() for s in streams],
            "driver": drv.vendor,
        }
        await self._persist_capabilities(cam_id, drv.vendor, info, caps, streams)
        return result

    async def _persist_capabilities(self, cam_id: str, vendor: str,
                                     info: DeviceInfo, caps: CameraCapabilities,
                                     streams: list[StreamInfo]) -> None:
        try:
            from database import db
            await db.cameras.update_one(
                {"id": cam_id},
                {"$set": {
                    "driver": vendor,
                    "device_info": info.to_dict(),
                    "capabilities": caps.to_dict(),
                    "streams_detected": [s.to_dict() for s in streams],
                }},
            )
        except Exception as e:
            logger.warning("persist capabilities failed for %s: %s", cam_id, e)

    async def _load_camera(self, cam_id: str) -> dict:
        try:
            from database import db
            cam = await db.cameras.find_one({"id": cam_id})
        except Exception as e:
            raise CameraDriverError(f"DB indispo pour caméra {cam_id}: {e}")
        if not cam:
            raise CameraDriverError(f"Caméra {cam_id} introuvable", code="camera_not_found")
        if not cam.get("ip") and not cam.get("host"):
            # Fallback : extraire l'hôte de rtsp_url (utile quand la caméra est
            # uniquement joignable via URL, ex. NAT/domaine). Le driver ONVIF
            # exige un host — on prend celui de l'URL RTSP à défaut.
            ip_from_rtsp = _host_from_rtsp(cam.get("rtsp_url") or "")
            if ip_from_rtsp:
                cam["ip"] = ip_from_rtsp
            else:
                raise CameraDriverError(
                    f"Caméra {cam_id} sans IP configurée",
                    code="camera_missing_ip",
                )
        # Normalisation clés
        cam["ip"] = cam.get("ip") or cam.get("host")
        return cam


camera_device_service = CameraDeviceService()
