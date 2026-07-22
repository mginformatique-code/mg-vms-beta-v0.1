"""Iteration 17 — P1.a EventViewer uniformisation + P1.b zéro sandbox
Tests:
  - /api/recording-context : 401 sans token, 404 si non couvert, structure quand 200
  - /api/events/{id}/recording : fallback events→plates→alerts
  - Absence de champ 'simulated' dans stream/playback/hardware.info
  - /api/plugins : renvoie la liste attendue et access_control statut
"""
import os
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"] if "access_token" in r.json() else r.json().get("token")


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- /api/recording-context ----------
class TestRecordingContext:
    def test_requires_auth(self):
        r = requests.get(f"{BASE}/api/recording-context",
                         params={"camera_id": "demo-cam-001", "at": "2026-01-01T00:00:00+00:00"},
                         timeout=10)
        assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text[:200]}"

    def test_404_when_no_coverage(self, auth):
        # Timestamp très ancien : aucun enregistrement ne couvre
        r = requests.get(f"{BASE}/api/recording-context", headers=auth,
                         params={"camera_id": "demo-cam-001", "at": "1999-01-01T00:00:00+00:00"},
                         timeout=10)
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text[:200]}"

    def test_structure_if_available(self, auth):
        """Si un enregistrement récent existe, l'API doit renvoyer la structure attendue."""
        # Cherche le dernier enregistrement disponible
        r = requests.get(f"{BASE}/api/recordings/timeline", headers=auth,
                         params={"camera_id": "demo-cam-001"}, timeout=10)
        if r.status_code != 200:
            pytest.skip("Timeline indisponible")
        segs = r.json().get("segments", [])
        if not segs:
            pytest.skip("Aucun segment sur demo-cam-001 pour tester le 200")
        seg = segs[0]
        # Prend un timestamp au milieu du segment
        r2 = requests.get(f"{BASE}/api/recording-context", headers=auth,
                          params={"camera_id": "demo-cam-001", "at": seg["start"]},
                          timeout=10)
        assert r2.status_code == 200, r2.text
        data = r2.json()
        assert "recording" in data
        assert "offset_sec" in data
        assert "stream_url" in data
        assert isinstance(data["offset_sec"], int)


# ---------- /api/events/{id}/recording fallback ----------
class TestEventRecordingFallback:
    def test_404_unknown_id(self, auth):
        r = requests.get(f"{BASE}/api/events/does-not-exist/recording",
                         headers=auth, timeout=10)
        assert r.status_code == 404

    def test_alert_id_accepted(self, auth):
        """Cherche une alerte existante et vérifie qu'elle est acceptée (200 ou 404 si pas d'enregistrement, mais PAS 'Événement introuvable')."""
        r = requests.get(f"{BASE}/api/alerts", headers=auth, params={"limit": 5}, timeout=10)
        assert r.status_code == 200
        alerts = r.json()
        if not alerts:
            pytest.skip("Aucune alerte en base")
        aid = alerts[0]["id"]
        r2 = requests.get(f"{BASE}/api/events/{aid}/recording", headers=auth, timeout=10)
        # 200 si couvert, 404 si pas d'enregistrement pour ce timestamp (mais pas "Événement introuvable")
        assert r2.status_code in (200, 404)
        if r2.status_code == 404:
            detail = r2.json().get("detail", "")
            assert "Événement introuvable" not in detail, \
                f"Alert id refusé (fallback cassé) : {detail}"


# ---------- Zéro 'simulated' ----------
class TestZeroSimulated:
    def test_no_simulated_in_stream(self, auth):
        r = requests.get(f"{BASE}/api/cameras/demo-cam-001/stream", headers=auth, timeout=10)
        assert r.status_code == 200
        assert "simulated" not in r.json()

    def test_no_simulated_in_hardware_info(self, auth):
        r = requests.get(f"{BASE}/api/hardware/info", headers=auth, timeout=10)
        assert r.status_code == 200
        body = r.text.lower()
        # Ni le champ simulated ni le mot sandbox
        assert "simulated" not in body
        assert "sandbox" not in body

    def test_no_simulated_in_playback(self, auth):
        r = requests.get(f"{BASE}/api/recordings/timeline", headers=auth,
                         params={"camera_id": "demo-cam-001"}, timeout=10)
        if r.status_code != 200 or not r.json().get("segments"):
            pytest.skip("Aucun segment pour tester playback")
        rid = r.json()["segments"][0]["id"]
        r2 = requests.get(f"{BASE}/api/recordings/{rid}/playback", headers=auth, timeout=10)
        assert r2.status_code == 200
        assert "simulated" not in r2.text.lower()


# ---------- /api/plugins ----------
class TestPluginsInventory:
    def test_plugins_count(self, auth):
        r = requests.get(f"{BASE}/api/plugins", headers=auth, timeout=15)
        assert r.status_code == 200
        plugins = r.json()
        ids = {p["id"] for p in plugins}
        # La consigne dit 8 mais le catalog en déclare 10 (mqtt + access_control inclus).
        # On vérifie au minimum les 8 attendus par la spec P1 + on rapportera si count != 8.
        expected_min = {"anpr", "ai_detection", "tracking", "face_recognition",
                        "parking", "thermal", "radar", "drone"}
        missing = expected_min - ids
        assert not missing, f"Plugins manquants : {missing}"
        # Rapport info (non bloquant)
        print(f"[INFO] Total plugins renvoyés : {len(plugins)} (ids={sorted(ids)})")

    def test_access_control_status(self, auth):
        r = requests.get(f"{BASE}/api/plugins", headers=auth, timeout=15)
        assert r.status_code == 200
        ac = next((p for p in r.json() if p["id"] == "access_control"), None)
        if ac is None:
            pytest.skip("access_control non exposé dans /api/plugins")
        health = ac.get("health", {})
        warning = (health.get("warning") or "").lower()
        # Ne doit plus contenir 'roadmap P2'
        assert "roadmap" not in warning, f"Warning encore lié à roadmap : {warning}"
        # Cohérence configured / warning
        if health.get("configured"):
            assert warning in ("", "none") or health.get("warning") is None
        else:
            assert warning, "Un warning explicite est attendu si non configuré"
