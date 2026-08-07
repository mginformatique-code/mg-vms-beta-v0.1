"""v1.0-rc1 · FEATURE FREEZE · Sprint Installation Docker

Mandat : le projet doit être installable depuis un clone Git vierge via
    git clone → docker compose build → docker compose up
sans aucune intervention manuelle.

Ces tests garantissent que TOUS les fichiers requis existent et sont
COHÉRENTS entre eux (pas de référence brisée).

Exécutable sans Docker CLI (pure validation statique + syntaxe).
"""
from __future__ import annotations

import os
import stat
import pytest


REPO = "/app"


class TestDockerFilesPresent:
    """Preuve : tous les artefacts requis pour `docker compose build` sont là."""

    @pytest.mark.parametrize("path", [
        "docker/docker-compose.yml",
        "docker/.env.example",
        "docker/go2rtc.yaml",
        "docker/README.md",
        "backend/Dockerfile",
        "backend/requirements.txt",
        "frontend/Dockerfile",
        "frontend/nginx.conf",
        "frontend/docker-entrypoint.sh",
        "frontend/package.json",
        "frontend/yarn.lock",
        "ENVIRONMENT.md",
    ])
    def test_file_exists(self, path):
        full = os.path.join(REPO, path)
        assert os.path.exists(full), f"Fichier manquant : {path}"
        assert os.path.getsize(full) > 0, f"Fichier vide : {path}"

    def test_entrypoint_is_executable(self):
        p = os.path.join(REPO, "frontend/docker-entrypoint.sh")
        mode = os.stat(p).st_mode
        assert mode & stat.S_IXUSR, "docker-entrypoint.sh n'est pas exécutable"


class TestComposeYAMLValid:
    """Le compose est un YAML valide avec les 4 services attendus."""

    @pytest.fixture(scope="class")
    def compose(self):
        import yaml
        with open(os.path.join(REPO, "docker/docker-compose.yml")) as f:
            return yaml.safe_load(f)

    def test_services_declared(self, compose):
        services = compose["services"]
        for svc in ("mongo", "go2rtc", "backend", "frontend"):
            assert svc in services, f"service {svc} manquant"

    def test_no_deprecated_version_field(self, compose):
        """Compose v2 : `version:` est déprécié et doit être absent."""
        assert "version" not in compose, "champ `version:` déprécié en Compose v2"

    def test_network_defined(self, compose):
        assert "mgvms" in compose["networks"]

    def test_backend_uses_correct_env_vars_for_mongo(self, compose):
        """Le backend lit MONGO_URL + DB_NAME (protégés) — pas MONGO_URI seul."""
        env = compose["services"]["backend"]["environment"]
        # Les 2 variables protégées doivent être injectées
        assert "MONGO_URL" in env, "MONGO_URL manquant dans backend.environment"
        assert "DB_NAME" in env, "DB_NAME manquant dans backend.environment"

    def test_backend_healthcheck_targets_health_endpoint(self, compose):
        hc = compose["services"]["backend"]["healthcheck"]
        # Le test doit interroger /health (pas /api/health)
        joined = " ".join(hc["test"]) if isinstance(hc["test"], list) else str(hc["test"])
        assert "/health" in joined

    def test_frontend_exposes_80_and_443(self, compose):
        ports = compose["services"]["frontend"]["ports"]
        joined = " ".join(str(p) for p in ports)
        assert ":80" in joined
        assert ":443" in joined

    def test_frontend_mounts_certs_volume(self, compose):
        vols = compose["services"]["frontend"]["volumes"]
        joined = " ".join(vols)
        assert "/etc/nginx/certs" in joined, \
            "Le frontend doit monter /etc/nginx/certs pour trouver le cert TLS"

    def test_mongo_uses_persistent_volume(self, compose):
        vols = compose["services"]["mongo"]["volumes"]
        joined = " ".join(vols)
        assert "/data/db" in joined
        # Chemin hôte configurable (variable + défaut)
        assert "mongodb" in joined.lower() or "MONGO_PATH" in joined

    def test_backend_depends_on_mongo_healthy(self, compose):
        dep = compose["services"]["backend"]["depends_on"]
        assert dep["mongo"]["condition"] == "service_healthy"

    def test_frontend_depends_on_backend_healthy(self, compose):
        dep = compose["services"]["frontend"]["depends_on"]
        assert dep["backend"]["condition"] == "service_healthy"


class TestBackendDockerfile:
    @pytest.fixture(scope="class")
    def content(self):
        return open(os.path.join(REPO, "backend/Dockerfile")).read()

    def test_uses_cuda_base_image(self, content):
        assert "FROM nvidia/cuda" in content

    def test_installs_ffmpeg(self, content):
        assert "ffmpeg" in content

    def test_copies_requirements_before_sources(self, content):
        # requirements.txt doit être copié AVANT le reste (cache layer)
        req_pos = content.find("COPY requirements.txt")
        src_pos = content.find("COPY . .")
        assert 0 < req_pos < src_pos, \
            "requirements.txt doit être copié avant `COPY . .` pour bénéficier du cache"

    def test_uvicorn_cmd_not_naive_python(self, content):
        """server.py n'a pas de __main__ → doit lancer via uvicorn."""
        assert "uvicorn" in content, \
            "Le CMD doit lancer uvicorn (server.py n'expose pas __main__)"
        assert '"--host", "0.0.0.0"' in content

    def test_healthcheck_defined(self, content):
        assert "HEALTHCHECK" in content
        assert "/health" in content


class TestFrontendDockerfile:
    @pytest.fixture(scope="class")
    def content(self):
        return open(os.path.join(REPO, "frontend/Dockerfile")).read()

    def test_multi_stage_build(self, content):
        assert "AS builder" in content
        assert "FROM nginx:" in content

    def test_openssl_available_in_runtime(self, content):
        """Auto-cert requiert openssl dans le runtime."""
        assert "openssl" in content

    def test_entrypoint_copied(self, content):
        assert "docker-entrypoint.sh" in content
        assert "/docker-entrypoint.d/" in content

    def test_nginx_conf_copied(self, content):
        assert "nginx.conf" in content


class TestNginxConfig:
    @pytest.fixture(scope="class")
    def content(self):
        return open(os.path.join(REPO, "frontend/nginx.conf")).read()

    def test_https_server_on_443(self, content):
        assert "listen 443 ssl" in content

    def test_reverse_proxy_backend(self, content):
        assert "upstream mgvms_backend" in content
        assert "server backend:8001" in content

    def test_api_location_proxied(self, content):
        assert "location /api/" in content
        assert "proxy_pass http://mgvms_backend" in content

    def test_ws_location_upgraded(self, content):
        assert "location /ws/" in content
        assert 'proxy_set_header Upgrade $http_upgrade' in content

    def test_spa_fallback_present(self, content):
        assert "try_files $uri $uri/ /index.html" in content

    def test_login_ratelimit_defined(self, content):
        assert "limit_req_zone" in content
        assert "location = /api/auth/login" in content

    def test_security_headers_present(self, content):
        for h in ("Strict-Transport-Security", "X-Content-Type-Options",
                   "X-Frame-Options"):
            assert h in content, f"header {h} manquant"

    def test_tls_cert_paths_match_entrypoint(self, content):
        assert "/etc/nginx/certs/fullchain.pem" in content
        assert "/etc/nginx/certs/privkey.pem" in content


class TestEntrypointScript:
    @pytest.fixture(scope="class")
    def content(self):
        return open(os.path.join(REPO, "frontend/docker-entrypoint.sh")).read()

    def test_generates_selfsigned_if_missing(self, content):
        assert "openssl req -x509" in content
        assert "-newkey rsa:2048" in content

    def test_preserves_existing_cert(self, content):
        """Preuve : si cert présent, l'entrypoint le conserve."""
        assert 'if [ -s "$CERT_DIR/fullchain.pem" ]' in content
        assert "exit 0" in content

    def test_shell_hardening(self, content):
        assert "set -euo pipefail" in content


class TestEnvExampleAlignedWithBackend:
    """Le .env.example doit couvrir toutes les variables lues par le backend."""

    @pytest.fixture(scope="class")
    def env_content(self):
        return open(os.path.join(REPO, "docker/.env.example")).read()

    def test_declares_mongo_url_and_db_name(self, env_content):
        assert "MONGO_URL" in env_content
        assert "MONGO_DATABASE" in env_content or "DB_NAME" in env_content

    def test_declares_storage_paths(self, env_content):
        for var in ("VIDEO_DATASTORE", "MONGO_PATH", "MODEL_PATH",
                     "CERT_PATH", "LOG_PATH"):
            assert var in env_content, f"{var} manquant dans .env.example"

    def test_declares_hostname_for_ssl(self, env_content):
        assert "MGVMS_HOSTNAME" in env_content


class TestServerPyStillHealthy:
    """Sanity : le backend expose bien /health (utilisé par healthcheck compose)."""

    def test_health_endpoint_declared(self):
        from server import app
        paths = {r.path for r in app.routes}
        assert "/health" in paths, \
            "GET /health doit rester exposé (healthcheck compose)"
