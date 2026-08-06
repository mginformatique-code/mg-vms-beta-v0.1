"""Tests — Assistant de découverte réseau avancée (v0.5.5).

Vérifie :
  - `GET /api/discovery/interfaces` renvoie les interfaces IPv4.
  - `POST /api/discovery/start` accepte des CIDR et démarre un task.
  - `GET /api/discovery/{task_id}/result` renvoie un résumé cohérent
    une fois le scan terminé.
  - `POST /api/discovery/{task_id}/cancel` annule proprement.
  - CIDR invalide → HTTP 400.
  - Non authentifié → HTTP 401.

On scanne uniquement `127.0.0.1/30` (2 IPs) pour rester rapide et sans
effets de bord réseau.
"""
import time
from pathlib import Path

import pytest
import requests


_env = Path("/app/frontend/.env").read_text()
BASE_URL = None
for line in _env.splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL manquant"

ADMIN_EMAIL = "admin@mg-vms.com"
ADMIN_PASSWORD = "Admin@2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                       timeout=8)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("access_token") or j.get("token")


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_discovery_requires_auth():
    r = requests.get(f"{BASE_URL}/api/discovery/interfaces", timeout=5)
    assert r.status_code == 401


def test_list_interfaces(token):
    r = requests.get(f"{BASE_URL}/api/discovery/interfaces",
                       headers=_auth(token), timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "interfaces" in body and isinstance(body["interfaces"], list)
    assert body["count"] == len(body["interfaces"])
    assert body["count"] >= 1
    for it in body["interfaces"]:
        for key in ("name", "ip", "netmask", "cidr", "virtual", "state"):
            assert key in it, f"Missing key {key} in iface {it}"
    # Il doit toujours y avoir au moins l'interface loopback.
    names = {i["name"] for i in body["interfaces"]}
    assert "lo" in names


def test_start_invalid_cidr_rejected(token):
    r = requests.post(f"{BASE_URL}/api/discovery/start",
                       headers=_auth(token),
                       json={"networks": ["not-a-cidr"],
                             "interfaces": [], "max_hosts_per_network": 4},
                       timeout=6)
    assert r.status_code == 400


def test_start_empty_networks_rejected(token):
    r = requests.post(f"{BASE_URL}/api/discovery/start",
                       headers=_auth(token),
                       json={"networks": [], "interfaces": [],
                             "max_hosts_per_network": 4},
                       timeout=6)
    assert r.status_code == 400


def test_start_and_get_result(token):
    """Lance un scan trivial (127.0.0.1/30) puis récupère le résumé."""
    r = requests.post(f"{BASE_URL}/api/discovery/start",
                       headers=_auth(token),
                       json={"networks": ["127.0.0.1/30"],
                             "interfaces": ["lo"],
                             "max_hosts_per_network": 8},
                       timeout=6)
    assert r.status_code == 200, r.text
    task_id = r.json()["task_id"]

    # Poll jusqu'à statut terminal (max 20s).
    status = None
    for _ in range(20):
        time.sleep(1)
        rr = requests.get(f"{BASE_URL}/api/discovery/{task_id}/result",
                          headers=_auth(token), timeout=6)
        assert rr.status_code == 200
        body = rr.json()
        status = body["status"]
        if status in ("completed", "cancelled", "error"):
            break
    assert status in ("completed", "cancelled"), f"unexpected status {status}"
    for key in ("cameras", "other_devices", "cameras_found",
                 "addresses_tested", "onvif_count", "elapsed_sec"):
        assert key in body


def test_cancel_scan(token):
    r = requests.post(f"{BASE_URL}/api/discovery/start",
                       headers=_auth(token),
                       json={"networks": ["10.99.99.0/24"],
                             "interfaces": [],
                             "max_hosts_per_network": 256},
                       timeout=6)
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    # Annulation immédiate.
    time.sleep(0.3)
    rc = requests.post(f"{BASE_URL}/api/discovery/{task_id}/cancel",
                        headers=_auth(token), timeout=6)
    assert rc.status_code == 200
    assert rc.json()["status"] == "cancelling"

    # Le statut doit basculer en 'cancelled' rapidement.
    final = None
    for _ in range(15):
        time.sleep(1)
        rr = requests.get(f"{BASE_URL}/api/discovery/{task_id}/result",
                          headers=_auth(token), timeout=6)
        assert rr.status_code == 200
        final = rr.json()["status"]
        if final in ("cancelled", "completed", "error"):
            break
    assert final == "cancelled", f"expected cancelled, got {final}"


def test_result_unknown_task_404(token):
    r = requests.get(f"{BASE_URL}/api/discovery/deadbeefdead/result",
                       headers=_auth(token), timeout=5)
    assert r.status_code == 404
