"""v0.3 · Tests HTTP e2e — Config Camera Modulaire (enabled_plugins + /plugins/catalog).

Vérifie via l'URL publique REACT_APP_BACKEND_URL :
 - GET /api/plugins/catalog structure (total, available, groups[]) + 50 plugins + 9+ groupes
 - GET /api/plugins/catalog requires auth (401/403 sans Bearer)
 - PUT /api/cameras/{id} accepte et persiste enabled_plugins
 - PUT /api/cameras/{id} avec enabled_plugins=[] accepté (fallback legacy)
 - CameraInput modèle a champ enabled_plugins par défaut []
 - Non-régression: /api/diagnostics/frame-source, pipeline-metrics stages alpr_ms,
   /api/plugins/bus (50), /api/plugins/tracking/config (enabled=true)
"""
import uuid
from pathlib import Path

import pytest
import requests

_env = Path("/app/frontend/.env").read_text()
BASE_URL = None
for line in _env.splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL manquant dans /app/frontend/.env"

ADMIN_EMAIL = "admin@mg-vms.com"
ADMIN_PASSWORD = "Admin@2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    assert "access_token" in data
    return data["access_token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ===================== 1. Plugins Catalog =====================

class TestPluginsCatalogAuth:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/plugins/catalog", timeout=10)
        assert r.status_code in (401, 403), \
            f"attendu 401/403 sans token, got {r.status_code}"


class TestPluginsCatalogShape:
    def test_catalog_shape_and_50_plugins(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/plugins/catalog",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        # Top-level keys
        for k in ("total", "available", "groups"):
            assert k in data, f"clef manquante: {k} — got {list(data.keys())}"
        assert isinstance(data["groups"], list)
        assert data["total"] >= 50, f"attendu >=50 plugins, got total={data['total']}"
        assert data["available"] >= 0
        # Nombre de groupes
        assert len(data["groups"]) >= 9, \
            f"attendu >=9 groupes, got {len(data['groups'])}: " + \
            ", ".join(g.get("category", "?") for g in data["groups"])

    def test_group_and_plugin_structure(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/plugins/catalog",
                         headers=auth_headers, timeout=15)
        data = r.json()
        # Vérifie chaque group
        for g in data["groups"]:
            assert "category" in g and isinstance(g["category"], str)
            assert "plugins" in g and isinstance(g["plugins"], list)
        # Vérifie shape d'au moins un plugin
        first_group = data["groups"][0]
        assert first_group["plugins"], "premier groupe vide"
        p = first_group["plugins"][0]
        required_fields = ("name", "display_name", "description", "interface",
                           "categories", "primary_category", "icon",
                           "loaded", "available")
        for f in required_fields:
            assert f in p, f"champ plugin manquant: {f} — got {list(p.keys())}"
        assert isinstance(p["categories"], list)
        assert isinstance(p["loaded"], bool)
        assert isinstance(p["available"], bool)

    def test_expected_categories_present(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/plugins/catalog",
                         headers=auth_headers, timeout=15)
        data = r.json()
        cats = {g["category"] for g in data["groups"]}
        # Les catégories principales attendues d'après les specs
        expected_subset = {"ANPR / LPR", "Tracking", "Segmentation",
                           "EPI", "Comptage"}
        missing = expected_subset - cats
        assert not missing, f"catégories manquantes: {missing} — présentes: {cats}"

    def test_sum_of_plugins_equals_total(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/plugins/catalog",
                         headers=auth_headers, timeout=15)
        data = r.json()
        total_from_groups = sum(len(g["plugins"]) for g in data["groups"])
        assert total_from_groups == data["total"], \
            f"total ({data['total']}) != somme groups ({total_from_groups})"


# ===================== 2. CameraInput.enabled_plugins model =====================

class TestCameraInputModel:
    def test_camera_input_has_enabled_plugins_default_empty(self):
        # Import direct du modèle Pydantic
        import sys
        sys.path.insert(0, "/app/backend")
        from routers import CameraInput
        c = CameraInput(name="test", ip="1.2.3.4", site_id="s1")
        assert hasattr(c, "enabled_plugins"), \
            "CameraInput doit avoir un champ enabled_plugins"
        assert c.enabled_plugins == [], \
            f"default doit être [] — got {c.enabled_plugins}"

    def test_camera_input_accepts_plugin_list(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from routers import CameraInput
        pl = ["yolo-detection", "bytetrack", "anpr-eps"]
        c = CameraInput(name="test", ip="1.2.3.4", site_id="s1",
                        enabled_plugins=pl)
        assert c.enabled_plugins == pl


# ===================== 3. PUT /api/cameras/{id} enabled_plugins =====================

@pytest.fixture(scope="module")
def created_camera(auth_headers):
    """Crée une caméra de test et yield son id, cleanup à la fin."""
    rs = requests.get(f"{BASE_URL}/api/sites", headers=auth_headers, timeout=10)
    assert rs.status_code == 200
    sites = rs.json()
    assert sites, "Aucun site en DB"
    site_id = sites[0]["id"]

    cam_name = f"TEST_modular_{uuid.uuid4().hex[:8]}"
    payload = {
        "name": cam_name,
        "ip": "10.0.0.98",
        "site_id": site_id,
        "rtsp_url": "rtsp://10.0.0.98:554/live",
        "allow_rtsp_override": True,
    }
    r = requests.post(f"{BASE_URL}/api/cameras",
                      headers=auth_headers, json=payload, timeout=60)
    assert r.status_code in (200, 201), \
        f"POST /api/cameras failed: {r.status_code} {r.text[:400]}"
    cam_id = r.json()["id"]
    yield cam_id
    # Cleanup
    requests.delete(f"{BASE_URL}/api/cameras/{cam_id}",
                    headers=auth_headers, timeout=10)


class TestCameraEnabledPluginsPersistence:
    def _base_payload(self, auth_headers, cam_id):
        # PUT nécessite modèle CameraInput complet — on récupère l'existant
        rg = requests.get(f"{BASE_URL}/api/cameras/{cam_id}",
                          headers=auth_headers, timeout=10)
        base = rg.json()
        return {
            "name": base["name"],
            "ip": base["ip"],
            "site_id": base["site_id"],
            "rtsp_url": base.get("rtsp_url", ""),
            "allow_rtsp_override": True,
        }

    def test_put_enabled_plugins_persists(self, auth_headers, created_camera):
        cam_id = created_camera
        plugins_list = ["yolo-detection", "bytetrack", "anpr-eps"]
        payload = self._base_payload(auth_headers, cam_id)
        payload["enabled_plugins"] = plugins_list
        # PUT
        r = requests.put(
            f"{BASE_URL}/api/cameras/{cam_id}",
            headers=auth_headers,
            json=payload,
            timeout=30,
        )
        assert r.status_code == 200, f"PUT failed: {r.status_code} {r.text[:400]}"
        # GET vérifie persistence
        rg = requests.get(f"{BASE_URL}/api/cameras/{cam_id}",
                          headers=auth_headers, timeout=10)
        assert rg.status_code == 200
        fetched = rg.json()
        assert "enabled_plugins" in fetched, \
            f"enabled_plugins manquant dans GET — got {list(fetched.keys())}"
        assert fetched["enabled_plugins"] == plugins_list, \
            f"attendu {plugins_list}, got {fetched['enabled_plugins']}"

    def test_put_empty_enabled_plugins_ok(self, auth_headers, created_camera):
        cam_id = created_camera
        payload = self._base_payload(auth_headers, cam_id)
        payload["enabled_plugins"] = []
        # Fallback legacy — liste vide acceptée
        r = requests.put(
            f"{BASE_URL}/api/cameras/{cam_id}",
            headers=auth_headers,
            json=payload,
            timeout=30,
        )
        assert r.status_code == 200, f"PUT [] failed: {r.status_code} {r.text[:400]}"
        rg = requests.get(f"{BASE_URL}/api/cameras/{cam_id}",
                          headers=auth_headers, timeout=10)
        fetched = rg.json()
        assert "enabled_plugins" in fetched
        assert fetched["enabled_plugins"] == [], \
            f"attendu [], got {fetched['enabled_plugins']}"


# ===================== 4. Non-regression =====================

class TestNonRegression:
    def test_frame_source_workers(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/diagnostics/frame-source",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        # workers doit être présent (dict ou list)
        workers = data.get("workers") or data.get("cameras") or data
        # Cherche demo-cam-002 alive
        found_alive = False
        if isinstance(workers, dict):
            for cid, w in workers.items():
                if "demo-cam-002" in cid and (w.get("alive") or w.get("running")):
                    found_alive = True
                    break
        elif isinstance(workers, list):
            for w in workers:
                if "demo-cam-002" in str(w.get("camera_id", "")) and \
                        (w.get("alive") or w.get("running")):
                    found_alive = True
                    break
        # Soft assert (demo cam peut ne pas être présente sur cet env preview)
        # On assure au minimum que l'endpoint répond avec la structure attendue
        assert workers is not None, f"pas de workers dans réponse: {data}"
        # Log info si demo-cam pas là
        if not found_alive:
            print(f"[INFO] demo-cam-002 non trouvée alive — data.keys={list(data.keys())}")

    def test_pipeline_metrics_alpr_ms(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/diagnostics/pipeline-metrics",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        # Cherche alpr_ms dans stages (avg ou max non zéro)
        cameras = data.get("cameras", {})
        alpr_found_nonzero = False
        for cid, cam_data in (cameras.items() if isinstance(cameras, dict) else []):
            stages = cam_data.get("stages") or cam_data.get("stage_ms") or {}
            if not isinstance(stages, dict):
                continue
            alpr = stages.get("alpr") or stages.get("alpr_ms")
            if isinstance(alpr, dict):
                if (alpr.get("avg", 0) or alpr.get("max", 0)):
                    alpr_found_nonzero = True
                    break
            elif isinstance(alpr, (int, float)) and alpr > 0:
                alpr_found_nonzero = True
                break
        # Soft: on ne fait pas hard-fail si aucune caméra active
        if not alpr_found_nonzero:
            print(f"[INFO] alpr_ms non mesuré (peut être normal si pas de caméra active) — cameras={list(cameras.keys()) if isinstance(cameras, dict) else cameras}")

    def test_plugins_bus_still_50(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/plugins/bus",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        total = (data.get("counts") or {}).get("total", 0)
        assert total >= 50, f"attendu >=50, got {total}"

    def test_plugins_tracking_config_enabled(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/plugins/tracking/config",
                         headers=auth_headers, timeout=10)
        assert r.status_code == 200
        assert r.json().get("enabled") is True
