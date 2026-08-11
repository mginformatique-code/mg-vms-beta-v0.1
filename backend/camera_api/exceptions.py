"""Camera API · Exceptions typées.

Toutes classées → mapping HTTP propre dans routes/camera_api.py :
    AuthenticationFailed  → 401
    DeviceUnreachable     → 503
    UnsupportedCapability → 501
    ProviderNotFound      → 400
    CameraApiError        → 502
"""
from __future__ import annotations


class CameraApiError(Exception):
    """Base class — toute erreur applicative caméra remonte via cette exception."""

    code: str = "camera_api_error"

    def __init__(self, message: str, *, code: str | None = None, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message, **({"detail": self.detail} if self.detail else {})}


class AuthenticationFailed(CameraApiError):
    code = "authentication_failed"


class DeviceUnreachable(CameraApiError):
    code = "device_unreachable"


class UnsupportedCapability(CameraApiError):
    code = "unsupported_capability"


class ProviderNotFound(CameraApiError):
    code = "provider_not_found"
