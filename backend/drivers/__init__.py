"""MG-VMS · Camera Device Layer (v0.4.6).

Abstraction constructeur unifiée. Le code métier (workflows, UI, API) ne doit
JAMAIS appeler directement une API constructeur. Il traverse toujours :

    CameraDeviceService
            │
            ▼
    CameraDriver (contrat abstrait)
            │
            ├── ONVIFDriver         · base universelle (découverte, PTZ, snapshots)
            ├── ReolinkDriver       · spotlight, sirène, PIR, audio, batterie
            ├── DahuaDriver         · CGI (préparé, minimal)
            └── HikvisionDriver     · ISAPI (préparé, minimal)

Une caméra n'expose que ce que ``get_capabilities()`` déclare. Une commande
non supportée lève ``UnsupportedCapabilityError`` — jamais 500.
"""
from .exceptions import (
    CameraDriverError,
    DeviceConnectionError,
    UnsupportedCapabilityError,
    AuthenticationError,
    CommandTimeoutError,
)
from .camera_models import (
    CameraCapabilities,
    DeviceInfo,
    StreamInfo,
    DeviceStatus,
    LightMode,
    IRMode,
)
from .camera_driver import CameraDriver
from .registry import register_driver, get_driver, list_supported_vendors, resolve_driver

__all__ = [
    "CameraDriver",
    "CameraCapabilities",
    "DeviceInfo",
    "StreamInfo",
    "DeviceStatus",
    "LightMode",
    "IRMode",
    "CameraDriverError",
    "DeviceConnectionError",
    "UnsupportedCapabilityError",
    "AuthenticationError",
    "CommandTimeoutError",
    "register_driver",
    "get_driver",
    "list_supported_vendors",
    "resolve_driver",
]

# Enregistrement des drivers concrets (side-effect import)
from . import onvif_driver as _onvif_driver  # noqa: F401,E402
from . import reolink_driver as _reolink_driver  # noqa: F401,E402
from . import dahua_driver as _dahua_driver  # noqa: F401,E402
from . import hikvision_driver as _hikvision_driver  # noqa: F401,E402
