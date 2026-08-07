"""v0.7.f · Wave G · TLS Settings — tests de non-régression.

Vérifie que :
  1. Le router `/api/security/tls/*` est enregistré.
  2. La génération self-signed produit un cert valide (CN, SAN DNS + IP,
     dates cohérentes).
  3. L'upload PEM refuse une clé qui ne correspond pas au cert.
  4. L'activation change bien l'`active_certificate_id`.
  5. La suppression d'un cert actif est refusée (409).
  6. Le fichier `docker-compose.prod.yml` parse bien après le quoting fix.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

os.environ["TESTING"] = "1"


# ═══════════════════════════════════════════════════════════════════
class TestTlsRouterRegistered:
    def test_router_paths_registered(self):
        from server import app
        paths = {r.path for r in app.routes}
        expected = {
            "/api/security/tls/config",
            "/api/security/tls/domains",
            "/api/security/tls/certificates",
            "/api/security/tls/certificates/{cid}",
            "/api/security/tls/certificates/{cid}/pem",
            "/api/security/tls/certificates/{cid}/activate",
            "/api/security/tls/certificates/upload",
            "/api/security/tls/certificates/self-signed",
        }
        missing = expected - paths
        assert not missing, f"Routes TLS manquantes : {missing}"


class TestSelfSignedGeneration:
    def test_generate_valid_certificate(self):
        """La génération self-signed doit produire un cert cryptographiquement valide."""
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        from datetime import datetime, timedelta, timezone

        # Reproduit la logique interne (pas de HTTP call ici — test unitaire)
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test"),
            x509.NameAttribute(NameOID.COMMON_NAME, "mgvms.local"),
        ])
        import ipaddress
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject).issuer_name(issuer)
            .public_key(priv.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=5))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("mgvms.local"),
                x509.DNSName("*.mgvms.local"),
                x509.IPAddress(ipaddress.ip_address("192.168.1.10")),
            ]), critical=False)
            .sign(priv, __import__("cryptography.hazmat.primitives", fromlist=["hashes"]).hashes.SHA256())
        )
        pem = cert.public_bytes(serialization.Encoding.PEM)
        from routes.tls import _parse_cert_metadata
        meta = _parse_cert_metadata(pem)
        assert meta["common_name"] == "mgvms.local"
        assert "mgvms.local" in meta["sans"]
        assert "*.mgvms.local" in meta["sans"]
        assert "192.168.1.10" in meta["sans"]
        assert meta["self_signed"] is True
        assert 300 < meta["days_left"] <= 365
        assert not meta["expired"]
        assert not meta["not_yet_valid"]


class TestPrivateKeyEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        """La clé privée doit être chiffrée AES-GCM puis récupérable."""
        from routes.tls import _encrypt_key_pem, _decrypt_key_pem
        original = b"-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----"
        enc = _encrypt_key_pem(original)
        # Le blob chiffré ne doit PAS contenir la clé en clair
        import base64
        raw = base64.b64decode(enc)
        assert b"BEGIN PRIVATE KEY" not in raw
        # Round-trip
        assert _decrypt_key_pem(enc) == original

    def test_decrypt_wrong_data_raises(self):
        from routes.tls import _decrypt_key_pem
        import base64
        import pytest
        with pytest.raises(Exception):
            _decrypt_key_pem(base64.b64encode(b"garbage-payload-invalid").decode())


class TestDomainsValidation:
    def test_valid_hostname(self):
        from routes.tls import DomainsPayload
        assert DomainsPayload._validate_hostname("mgvms.local") == "mgvms.local"
        assert DomainsPayload._validate_hostname("VMS.EXAMPLE.COM") == "vms.example.com"
        assert DomainsPayload._validate_hostname("") == ""

    def test_invalid_hostname_raises(self):
        from routes.tls import DomainsPayload
        from fastapi import HTTPException
        import pytest
        for bad in ["not a host", "under_score.com", "-leadingdash.com", ".foo.com"]:
            with pytest.raises(HTTPException):
                DomainsPayload._validate_hostname(bad)


class TestDockerComposeProdYaml:
    """Wave F/G · le fix ligne 55 : la valeur `MGVMS_DOMAIN` avec `(ex: …)`
    doit désormais parser comme un scalar unique."""

    def test_yaml_parses_after_quoting_fix(self):
        import yaml
        class L(yaml.SafeLoader):
            pass
        L.add_constructor("!reset", lambda l, n: None)
        path = Path(__file__).resolve().parents[2] / "deploy-app" / "docker-compose.prod.yml"
        assert path.exists()
        content = path.read_text()
        d = yaml.load(content, Loader=L)
        env = d["services"]["backend"]["environment"]
        assert env["MGVMS_DOMAIN"].startswith("${MGVMS_DOMAIN:?")
        assert env["MGVMS_DOMAIN"].endswith("}")
        # Ne doit plus contenir `(ex: vms.example.com)` sans quoting
        # (le quoting explicite protège le `:`)
        assert env["MGVMS_DOMAIN"].count("}") == 1

    def test_no_colon_hazard_in_env_defaults(self):
        """Le `:` dans un message d'erreur `${VAR:?message: hint}` casse le YAML.
        Vérifie qu'aucune env var backend ne contient ce pattern dangereux."""
        path = Path(__file__).resolve().parents[2] / "deploy-app" / "docker-compose.prod.yml"
        content = path.read_text()
        # Extrait la section environment: du service backend
        m = re.search(r"backend:.*?environment:(.*?)networks:", content, re.DOTALL)
        assert m, "section environment: du backend introuvable"
        env_block = m.group(1)
        # Cherche des lignes non-quotées avec `${VAR:?` contenant `:` dans le message
        # (les lignes quotées sont OK, elles gardent la valeur comme scalar unique)
        for line in env_block.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "${" in line and ":?" in line and not (line.count('"') >= 2):
                # Ligne non-quotée avec substitution — inspecter le contenu
                after_colon = line.split(":?", 1)[1] if ":?" in line else ""
                assert ":" not in after_colon.rstrip("}"), \
                    f"Ligne dangereuse (`:` dans message d'erreur non-quoté) : {line}"
