"""Exceptions du device layer.

Toutes les erreurs des drivers doivent hériter de ``CameraDriverError`` pour
être traitées uniformément par le service et retournées comme
``{"success": false, "error": "<code>", "message": "<...>"}`` — jamais un 500.
"""
from __future__ import annotations


class CameraDriverError(Exception):
    """Base pour toutes les erreurs des drivers caméra."""
    code: str = "driver_error"

    def __init__(self, message: str = "", *, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code

    def to_dict(self) -> dict:
        return {"success": False, "error": self.code, "message": self.message}


class UnsupportedCapabilityError(CameraDriverError):
    """La commande demandée n'est pas supportée par la caméra."""
    code = "unsupported_capability"


class DeviceConnectionError(CameraDriverError):
    """La caméra ne répond pas (timeout, connect refused, DNS…)."""
    code = "device_unreachable"


class AuthenticationError(CameraDriverError):
    """Identifiants invalides / rejetés par la caméra."""
    code = "authentication_failed"


class CommandTimeoutError(CameraDriverError):
    """La commande a été acceptée mais n'a pas répondu dans les délais."""
    code = "command_timeout"


class DeviceLockedError(CameraDriverError):
    """La caméra est temporairement verrouillée après plusieurs tentatives
    d'authentification (protection anti-brute-force côté caméra)."""
    code = "device_locked"
