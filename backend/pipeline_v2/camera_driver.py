"""v0.5.7 · Universal Camera API — Contrat unique (façade).

Ce module **n'implémente rien**. Il expose sous un chemin d'import unique
(`pipeline_v2.camera_driver`) le contrat abstrait des drivers caméra
déjà défini dans ``backend/drivers/`` et ajoute une facette
``Protocol`` structurelle (utile pour du typing moderne).

Objectif :

    Le reste de MG-VMS (pipeline, plugins, workflows, UI, tests)
    n'importe **jamais** un driver constructeur. Il importe uniquement
    le contrat depuis ce module OU depuis ``drivers/``. Les deux
    chemins pointent vers les **mêmes objets** — pas de duplication.

Règles v0.5.7 :

  1. Un seul ``CameraDriver`` (ABC) — celui de ``drivers/camera_driver.py``.
  2. Une seule ``CameraCapabilities`` — celle de ``drivers/camera_models.py``.
  3. Un seul registry — celui de ``drivers/registry.py``.
  4. Aucune logique métier dans ce fichier. Uniquement re-export + Protocol.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

# ── Re-export du contrat officiel ────────────────────────────────
from drivers import (
    CameraDriver,
    CameraCapabilities,
    DeviceInfo,
    StreamInfo,
    DeviceStatus,
    LightMode,
    IRMode,
    CameraDriverError,
    DeviceConnectionError,
    UnsupportedCapabilityError,
    AuthenticationError,
    CommandTimeoutError,
    register_driver,
    get_driver,
    resolve_driver,
    list_supported_vendors,
)


# ═════════════════════════════════════════════════════════════════════════
# Facette Protocol structurelle (typing uniquement, pas d'exécution)
# ═════════════════════════════════════════════════════════════════════════
@runtime_checkable
class CameraDriverProtocol(Protocol):
    """Vue ``Protocol`` du contrat ``CameraDriver``.

    Utilise ce Protocol pour du **duck-typing** ou pour annoter du code
    qui ne veut pas dépendre de l'ABC concrète. ``isinstance(obj, CameraDriverProtocol)``
    fonctionne (runtime_checkable) et retourne True pour toute instance
    conforme à la surface publique de ``CameraDriver``.

    Ce Protocol **ne remplace pas** ``CameraDriver`` — c'est une facette
    complémentaire. Les drivers concrets héritent toujours de
    ``CameraDriver`` (ABC dans ``drivers/``).
    """
    vendor: str

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def get_device_info(self) -> DeviceInfo: ...
    async def get_capabilities(self) -> CameraCapabilities: ...
    async def get_status(self) -> DeviceStatus: ...
    async def get_streams(self) -> list[StreamInfo]: ...


__all__ = [
    # Contrat abstrait
    "CameraDriver",
    "CameraDriverProtocol",
    # Modèles
    "CameraCapabilities",
    "DeviceInfo",
    "StreamInfo",
    "DeviceStatus",
    "LightMode",
    "IRMode",
    # Exceptions
    "CameraDriverError",
    "DeviceConnectionError",
    "UnsupportedCapabilityError",
    "AuthenticationError",
    "CommandTimeoutError",
    # Registry (source unique)
    "register_driver",
    "get_driver",
    "resolve_driver",
    "list_supported_vendors",
]
