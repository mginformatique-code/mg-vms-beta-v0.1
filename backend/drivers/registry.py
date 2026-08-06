"""Registre des drivers caméra.

Chaque driver concret s'enregistre au chargement du module via
``register_driver("vendor", DriverClass)``. Le service utilise
``resolve_driver(vendor, host, user, pass)`` pour obtenir une instance
prête à ``connect()``.
"""
from __future__ import annotations

from typing import Optional

from .camera_driver import CameraDriver

_DRIVERS: dict[str, type[CameraDriver]] = {}


def register_driver(vendor: str, driver_cls: type[CameraDriver]) -> None:
    """Enregistre un driver (idempotent — un vendor = un driver)."""
    _DRIVERS[vendor.lower()] = driver_cls


def get_driver(vendor: str) -> Optional[type[CameraDriver]]:
    """Retourne la classe driver pour un vendor, ou None si absent.

    Fallback silencieux vers 'onvif' si le vendor exact n'est pas connu — c'est
    la garantie que MG-VMS fonctionne sur n'importe quelle caméra ONVIF-compatible.
    """
    v = (vendor or "").lower()
    return _DRIVERS.get(v) or _DRIVERS.get("onvif")


def resolve_driver(vendor: str, host: str, username: str, password: str,
                   port: Optional[int] = None) -> CameraDriver:
    """Instancie un driver pour une caméra donnée."""
    cls = get_driver(vendor)
    if cls is None:
        # Aucun driver ONVIF chargé — extrêmement improbable, mais on
        # renvoie une erreur claire plutôt qu'un TypeError.
        from .exceptions import CameraDriverError
        raise CameraDriverError(
            f"Aucun driver disponible pour le vendor '{vendor}' et pas de fallback ONVIF",
            code="no_driver_available",
        )
    return cls(host=host, username=username, password=password, port=port)


def list_supported_vendors() -> list[str]:
    return sorted(_DRIVERS.keys())
