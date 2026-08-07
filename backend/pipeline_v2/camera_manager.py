"""v0.5.7 · Universal Camera API — CameraManager (façade légère).

Le ``CameraManager`` est le point d'entrée unifié pour tout le code
qui a besoin d'un driver caméra. Il **délègue** au ``CameraDeviceService``
existant — il n'ajoute pas de logique métier.

Responsabilités (uniquement) :

  1. Résoudre un ``camera_id`` en instance ``CameraDriver`` prête à l'usage.
  2. Fournir le cache d'instances via le service.
  3. Valider (IP, credentials) au niveau applicatif avant d'appeler le driver.
  4. Exposer la liste des vendors supportés (via le registry unique).
  5. Fournir un point d'ancrage stable pour le futur ``Driver Validator``.

Interdictions strictes (règles v0.5.7) :

  - ❌ Pas d'appel HTTP direct à une caméra.
  - ❌ Pas de logique constructeur.
  - ❌ Pas de commande métier (``snapshot``, ``ptz_move``, ``set_light``, …).
    Ces commandes passent par le driver, obtenu via ``get_driver``.

Toute commande physique doit s'écrire :

    drv = await camera_manager.get_driver(camera_id)
    await drv.ptz_move("up")
"""
from __future__ import annotations

import logging
from typing import Optional

from pipeline_v2.camera_driver import (
    CameraDriver,
    CameraDriverError,
    list_supported_vendors,
)
from services.camera_device_service import camera_device_service

logger = logging.getLogger("pipeline_v2.camera_manager")


class CameraManager:
    """Façade unifiée du device layer (v0.5.7).

    Instance singleton exposée en fin de module (``camera_manager``).
    Aucun état propre — délègue au ``CameraDeviceService``.
    """

    # ── Résolution driver ────────────────────────────────────────
    async def get_driver(self, camera_id: str) -> CameraDriver:
        """Retourne un ``CameraDriver`` connecté et prêt à recevoir des commandes.

        Délègue au ``CameraDeviceService`` (cache par ``camera_id``,
        connexion asynchrone protégée par lock).

        Lève ``CameraDriverError`` (code ``camera_not_found`` /
        ``camera_missing_ip`` / ``device_unreachable`` /
        ``authentication_failed``) — jamais 500.
        """
        return await camera_device_service.get_driver(camera_id)

    async def release(self, camera_id: str) -> None:
        """Ferme et libère l'instance du driver associée."""
        await camera_device_service.release(camera_id)

    # ── Discovery ────────────────────────────────────────────────
    async def discover(self, camera_id: str) -> dict:
        """Probe complète (info + capabilities + streams) + persist Mongo.

        Retour : ``{"info": ..., "capabilities": ..., "streams": [...],
        "driver": "reolink"}``.
        """
        return await camera_device_service.discover(camera_id)

    # ── Introspection registry ───────────────────────────────────
    def supported_vendors(self) -> list[str]:
        """Liste des vendors reconnus par le registry unique."""
        return list_supported_vendors()

    # ── Validation légère (sans I/O) ─────────────────────────────
    def validate_camera_doc(self, camera: dict) -> Optional[str]:
        """Valide un document caméra AVANT toute connexion physique.

        Retourne ``None`` si valide, sinon un message d'erreur court.
        Aucune I/O réseau — cette validation reste purement statique.
        """
        if not isinstance(camera, dict):
            return "camera doc must be a dict"
        ip = camera.get("ip") or camera.get("host")
        if not ip:
            return "camera_missing_ip"
        # Vendor optionnel — le registry fait le fallback ONVIF si inconnu.
        return None


# ── Singleton exposé ─────────────────────────────────────────────
camera_manager = CameraManager()

__all__ = ["CameraManager", "camera_manager"]
