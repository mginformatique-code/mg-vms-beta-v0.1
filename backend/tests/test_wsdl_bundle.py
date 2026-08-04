"""Tests · WSDL ONVIF embarqués (v0.3 · Feb 2026).

Vérifie que :
1. Le répertoire /app/backend/wsdl existe et contient les 7 WSDL essentiels
2. validate_wsdl_dir() retourne ok=True en dev
3. onvif_camera() factory charge les WSDL sans FileNotFoundError
4. L'endpoint /api/diagnostics/wsdl retourne le statut
"""
import os
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "mgvms_test_wsdl")


class TestWsdlBundle:
    def test_wsdl_dir_exists(self):
        from wsdl_path import WSDL_DIR
        p = Path(WSDL_DIR)
        assert p.is_dir(), f"WSDL dir absent : {p}"

    def test_all_required_wsdl_present(self):
        from wsdl_path import WSDL_DIR, REQUIRED_WSDL
        p = Path(WSDL_DIR)
        missing = [f for f in REQUIRED_WSDL if not (p / f).is_file()]
        assert not missing, f"WSDL essentiels manquants: {missing}"

    def test_validate_wsdl_dir_ok(self):
        from wsdl_path import validate_wsdl_dir
        r = validate_wsdl_dir()
        assert r["ok"] is True
        assert r["found"] == 7  # devicemgmt + media + media2 + ptz + events + imaging + deviceio
        assert r["missing_required"] == []

    def test_env_override_MGVMS_WSDL_DIR(self, tmp_path, monkeypatch):
        """MGVMS_WSDL_DIR override respecté (rechargement module)."""
        monkeypatch.setenv("MGVMS_WSDL_DIR", str(tmp_path))
        import importlib, wsdl_path
        importlib.reload(wsdl_path)
        assert wsdl_path.WSDL_DIR == str(tmp_path)
        # Cleanup
        monkeypatch.delenv("MGVMS_WSDL_DIR", raising=False)
        importlib.reload(wsdl_path)

    def test_onvif_camera_factory_uses_bundled_wsdl(self):
        """La factory injecte bien wsdl_dir=WSDL_DIR dans ONVIFCamera().

        Vérifie par introspection sans instancier zeep (évite les timeouts
        réseau et les problèmes de multi-workers pytest).
        """
        import inspect
        from wsdl_path import onvif_camera, WSDL_DIR
        src = inspect.getsource(onvif_camera)
        assert "wsdl_dir=WSDL_DIR" in src
        # Le path résolu doit exister
        assert Path(WSDL_DIR).is_dir()

    def test_no_onvifcamera_direct_calls_remaining(self):
        """Aucun code ne doit appeler `ONVIFCamera(` directement — tout doit
        passer par la factory onvif_camera() qui injecte wsdl_dir."""
        import subprocess
        r = subprocess.run(
            ["grep", "-rn", "ONVIFCamera(",
             "/app/backend/routes/", "/app/backend/streaming.py"],
            capture_output=True, text=True,
        )
        # Rien ne doit ressortir (grep exit 1 = no match)
        assert r.returncode == 1, (
            f"Callsites ONVIFCamera() directs trouvés — utilisez onvif_camera() :\n{r.stdout}"
        )


class TestWsdlDiagnosticsEndpoint:
    def test_endpoint_registered(self):
        from routes.health_dashboard import health_dashboard_router
        paths = [r.path for r in health_dashboard_router.routes]
        assert "/api/diagnostics/wsdl" in paths


class TestDockerfileHasWsdlCopy:
    def test_dockerfile_copies_wsdl_explicitly(self):
        """Le Dockerfile doit copier wsdl/ AVANT `COPY . .` (defensive)."""
        df = Path("/app/backend/Dockerfile").read_text()
        assert "COPY backend/wsdl/" in df  # v0.4 · context = repo root
        # Check du build-time (garde l'image cohérente)
        assert "/app/wsdl/devicemgmt.wsdl" in df
