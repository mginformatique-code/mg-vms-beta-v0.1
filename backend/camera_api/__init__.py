"""MG-VMS · Camera API Layer (HTTP/HTTPS).

Couche d'intégration HTTP/HTTPS avec les caméras IP — INDÉPENDANTE du pipeline
vidéo (RTSP/WebRTC/MediaMTX/go2rtc). Cette couche gère UNIQUEMENT :

    - Authentification API caméra (token/session/digest)
    - Récupération d'infos & capacités
    - Contrôles physiques (IR, PTZ, Light, Siren)
    - Métadonnées d'enregistrements SD (jamais le contenu vidéo)

Architecture :

    CameraApiProvider (ABC)                       ← contract commun
    ├── ReolinkProvider                           ← /cgi-bin/api.cgi JSON + token
    ├── HikvisionProvider (stub)                  ← ISAPI
    ├── DahuaProvider (stub)                      ← HTTP CGI
    ├── OnvifGenericProvider (via wsdl_path.py)
    └── ...

Le frontend ne connaît JAMAIS le protocole propriétaire — il parle uniquement
à `/api/camera-devices/*` (routes agnostiques).
"""
from .base import (
    CameraApiProvider,
    DeviceInfo,
    Capabilities,
    NetworkInfo,
    UserInfo,
)
from .exceptions import (
    CameraApiError,
    AuthenticationFailed,
    DeviceUnreachable,
    UnsupportedCapability,
    ProviderNotFound,
)
from .registry import resolve_provider, register_provider, list_providers

__all__ = [
    "CameraApiProvider",
    "DeviceInfo",
    "Capabilities",
    "NetworkInfo",
    "UserInfo",
    "CameraApiError",
    "AuthenticationFailed",
    "DeviceUnreachable",
    "UnsupportedCapability",
    "ProviderNotFound",
    "resolve_provider",
    "register_provider",
    "list_providers",
]
