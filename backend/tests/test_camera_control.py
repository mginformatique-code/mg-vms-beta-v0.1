"""Tests P9 & P10 · Contrôle caméra avancé + Audio TTS."""
import httpx


BASE = "http://localhost:8001"
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


def _token():
    r = httpx.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=10)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d.get("token")


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


def test_device_info_requires_onvif_mode():
    """Une caméra en mode RTSP doit être rejetée."""
    r = httpx.get(f"{BASE}/api/cameras/demo-cam-001/device-info",
                  headers=_auth(), timeout=15)
    # RTSP mode → 400 ; caméra introuvable → 404
    assert r.status_code in (400, 404, 502)


def test_ir_invalid_state_rejected():
    r = httpx.post(f"{BASE}/api/cameras/demo-cam-001/ir/blabla",
                   headers=_auth(), timeout=10)
    assert r.status_code == 400


def test_reboot_requires_confirm():
    r = httpx.post(f"{BASE}/api/cameras/demo-cam-001/reboot",
                    headers=_auth(), timeout=10)
    assert r.status_code == 400


def test_tts_requires_text():
    r = httpx.post(f"{BASE}/api/cameras/demo-cam-001/audio/tts",
                    json={}, headers=_auth(), timeout=10)
    assert r.status_code == 400


def test_tts_returns_dispatch_result():
    """Même sans plugin tts-notifier installé, doit retourner un résultat
    (l'action est dispatchée et un plugin manquant retourne ok=false)."""
    r = httpx.post(f"{BASE}/api/cameras/demo-cam-001/audio/tts",
                    json={"text": "Bonjour test"}, headers=_auth(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert "type" in d  # dispatch_action retourne toujours au moins {"type", "ok"}


def test_relay_invalid_state():
    r = httpx.post(f"{BASE}/api/cameras/demo-cam-001/relay/tok1/blabla",
                    headers=_auth(), timeout=10)
    assert r.status_code == 400


def test_capabilities_404_on_unknown():
    r = httpx.get(f"{BASE}/api/cameras/nonexistent/capabilities",
                   headers=_auth(), timeout=10)
    assert r.status_code == 404
