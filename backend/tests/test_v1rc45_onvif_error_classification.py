"""Tests v1.0-rc4.5 · Classification granulaire des erreurs ONVIF.

Vérifie que ``_classify_onvif_exception`` produit le bon type d'erreur
typé pour chaque cas connu — plus jamais de "Unknown error" côté frontend.
"""
from drivers.exceptions import (
    AuthenticationError, DeviceConnectionError, DeviceLockedError,
    CommandTimeoutError, CameraDriverError,
)
from drivers.onvif_driver import _classify_onvif_exception


def _mk(cls_name, msg="", status=None):
    """Fabrique une exception brute avec attributs status_code éventuels."""
    exc = type(cls_name, (Exception,), {})(msg)
    if status is not None:
        exc.status_code = status
    return exc


def test_classify_401_unauthorized_string():
    exc = Exception("HTTP 401 Unauthorized: bad user name or password")
    r = _classify_onvif_exception(exc, "192.168.1.72", 80)
    assert isinstance(r, AuthenticationError), f"attendu Auth, got {type(r)}"
    assert r.code == "authentication_failed"
    assert "vérifiez" in r.message.lower() or "verifiez" in r.message.lower()


def test_classify_401_status_attribute():
    exc = _mk("SoapFault", "Sender not authorized", status=401)
    r = _classify_onvif_exception(exc, "10.0.0.1", 8899)
    assert isinstance(r, AuthenticationError)


def test_classify_403_forbidden():
    exc = Exception("HTTP 403 Forbidden")
    r = _classify_onvif_exception(exc, "cam", 80)
    assert isinstance(r, AuthenticationError)


def test_classify_device_locked_priority_over_401():
    """`locked` DOIT être détecté AVANT auth car les messages caméra
    contiennent souvent les deux mots (401 + locked)."""
    exc = Exception("HTTP 401: Account locked out. Too many failed attempts.")
    r = _classify_onvif_exception(exc, "cam", 80)
    assert isinstance(r, DeviceLockedError), f"attendu Locked, got {type(r)}"
    assert r.code == "device_locked"


def test_classify_timeout():
    exc = Exception("The read operation timed out")
    r = _classify_onvif_exception(exc, "cam", 80)
    assert isinstance(r, CommandTimeoutError)
    assert r.code == "command_timeout"
    assert "délai" in r.message.lower() or "delai" in r.message.lower()


def test_classify_connection_refused():
    exc = Exception("[Errno 111] Connection refused")
    r = _classify_onvif_exception(exc, "cam", 80)
    assert isinstance(r, DeviceConnectionError)
    assert r.code == "device_unreachable"
    assert "injoignable" in r.message.lower()


def test_classify_dns_failure():
    exc = Exception("getaddrinfo failed: Name or service not known")
    r = _classify_onvif_exception(exc, "camnotfound", 80)
    assert isinstance(r, DeviceConnectionError)


def test_classify_unknown_falls_back_to_connection_error_not_generic():
    """Un cas inconnu doit produire un CameraDriverError typé — jamais un
    driver_error générique 'Unknown error'."""
    exc = Exception("Some random exotic SOAP fault message")
    r = _classify_onvif_exception(exc, "cam", 80)
    assert isinstance(r, CameraDriverError)
    assert r.code != "driver_error", "fallback doit être typé (device_unreachable)"
    assert r.code == "device_unreachable"


def test_device_locked_mapped_to_423_in_routes():
    """L'endpoint /devices/{id}/capabilities doit mapper device_locked → 423."""
    with open("/app/backend/routes/devices.py") as f:
        src = f.read()
    assert '"device_locked": 423' in src, (
        "Le mapping HTTP dans _driver_error_response doit inclure "
        "device_locked → 423 (Locked)"
    )


def test_frontend_hook_has_error_labels_for_all_codes():
    """Chaque code d'erreur backend doit avoir un label français côté hook."""
    with open("/app/frontend/src/hooks/useDeviceCapabilities.js") as f:
        src = f.read()
    for code in ["authentication_failed", "device_locked", "device_unreachable",
                 "command_timeout", "camera_missing_ip", "camera_not_found",
                 "unsupported_capability", "no_driver_available"]:
        assert f"{code}:" in src or f'"{code}"' in src, (
            f"Code d'erreur '{code}' non mappé dans ERROR_LABELS "
            f"(useDeviceCapabilities.js)"
        )
