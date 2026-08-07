"""Route module — TLS / HTTPS settings (v0.7.f).

Nouveau sous-menu du Centre de sécurité : gérer nom de domaine local +
externe, importer un certificat existant, générer un certificat
auto-signé, consulter l'état du certificat actif.

Endpoints (prefix `/api/security/tls`) :
  * `GET  /config`                              — domaines + liste certs
  * `PUT  /domains`                             — met à jour domaines local/externe
  * `GET  /certificates`                        — liste des certs stockés
  * `GET  /certificates/{cid}`                  — détail parsé (CN, SAN, dates, …)
  * `GET  /certificates/{cid}/pem`              — récupère le PEM (cert public)
  * `POST /certificates/upload`                 — importe cert + clé PEM
  * `POST /certificates/self-signed`            — génère un cert auto-signé
  * `PUT  /certificates/{cid}/activate`         — désigne le cert actif
  * `DELETE /certificates/{cid}`                — supprime un cert non-actif

Stockage : collection Mongo `tls_certificates` (petits blobs base64) —
convient pour ≤ 20 certs. La prod peut synchroniser vers `/etc/mgvms/certs/`
via un binding script séparé (hors scope de cette route).

Sécurité : la clé privée est chiffrée AES-GCM avec `JWT_SECRET` (dérivé)
comme clé — jamais stockée en clair. Elle est **déchiffrée à la volée**
uniquement quand on renvoie le PEM à un admin authentifié via `/pem`
(endpoint qui log dans l'audit).
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_permission, log_audit
from database import db

tls_router = APIRouter(prefix="/api/security/tls", tags=["security-tls"])


# ═════════════════════════════════════════════════════════════════════
# Chiffrement de la clé privée avant persistance Mongo
# ═════════════════════════════════════════════════════════════════════
def _aead_key() -> bytes:
    """Dérive une clé AES-GCM 256 bits depuis JWT_SECRET (déjà fort/random)."""
    secret = os.environ.get("JWT_SECRET", "dev-fallback-not-secure")
    return hashlib.sha256(secret.encode()).digest()


def _encrypt_key_pem(pem_bytes: bytes) -> str:
    """Chiffre la clé privée PEM en AES-GCM et renvoie ``base64(nonce||ct)``."""
    nonce = os.urandom(12)
    aead = AESGCM(_aead_key())
    ct = aead.encrypt(nonce, pem_bytes, associated_data=b"mgvms-tls-key")
    return base64.b64encode(nonce + ct).decode()


def _decrypt_key_pem(blob_b64: str) -> bytes:
    raw = base64.b64decode(blob_b64)
    nonce, ct = raw[:12], raw[12:]
    aead = AESGCM(_aead_key())
    return aead.decrypt(nonce, ct, associated_data=b"mgvms-tls-key")


# ═════════════════════════════════════════════════════════════════════
# Parse X.509
# ═════════════════════════════════════════════════════════════════════
def _parse_cert_metadata(pem_cert: bytes) -> dict:
    """Extrait CN, SAN, dates, issuer, empreinte SHA-256 d'un cert PEM."""
    cert = x509.load_pem_x509_certificate(pem_cert)
    try:
        subject_cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    except IndexError:
        subject_cn = ""
    try:
        issuer_cn = cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    except IndexError:
        issuer_cn = ""
    sans: list[str] = []
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        # cryptography >= 43 renvoie directement des str/ipaddress ; < 43 des objets DNSName/IPAddress.value
        raw_dns = ext.value.get_values_for_type(x509.DNSName)
        sans = [n if isinstance(n, str) else getattr(n, "value", str(n)) for n in raw_dns]
        raw_ip = ext.value.get_values_for_type(x509.IPAddress)
        sans += [str(getattr(ip, "value", ip)) for ip in raw_ip]
    except x509.ExtensionNotFound:
        pass
    fingerprint = cert.fingerprint(hashes.SHA256()).hex()
    self_signed = (cert.subject == cert.issuer)
    not_before = cert.not_valid_before_utc.replace(tzinfo=timezone.utc) \
        if hasattr(cert, "not_valid_before_utc") else cert.not_valid_before.replace(tzinfo=timezone.utc)
    not_after = cert.not_valid_after_utc.replace(tzinfo=timezone.utc) \
        if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days_left = (not_after - now).days
    return {
        "common_name": subject_cn,
        "issuer": issuer_cn,
        "sans": sans,
        "not_before": not_before.isoformat(),
        "not_after": not_after.isoformat(),
        "days_left": days_left,
        "self_signed": self_signed,
        "fingerprint_sha256": fingerprint,
        "expired": now > not_after,
        "not_yet_valid": now < not_before,
    }


# ═════════════════════════════════════════════════════════════════════
# Domaines local + externe (stockés dans settings)
# ═════════════════════════════════════════════════════════════════════
DEFAULT_DOMAINS = {
    "internal": "mgvms.local",
    "external": "",   # à renseigner (ex : vms.example.com)
    "force_https": False,
    "hsts_enabled": False,
    "hsts_max_age_seconds": 15552000,   # 180 jours
}


class DomainsPayload(BaseModel):
    internal: str = Field("", max_length=253)
    external: str = Field("", max_length=253)
    force_https: bool = False
    hsts_enabled: bool = False
    hsts_max_age_seconds: int = Field(15552000, ge=0, le=63072000)   # ≤ 2 ans

    @staticmethod
    def _validate_hostname(name: str) -> str:
        name = (name or "").strip().lower()
        if not name:
            return name
        # RFC 1123 hostname (labels ≤ 63, chars alphanum + tiret, points)
        if not re.fullmatch(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$", name):
            raise HTTPException(400, {"error": "invalid_hostname", "value": name})
        return name


async def _read_domains() -> dict:
    doc = await db.settings.find_one({"key": "tls_domains"}, {"_id": 0, "value": 1})
    return {**DEFAULT_DOMAINS, **(doc.get("value") if doc else {})}


# ═════════════════════════════════════════════════════════════════════
# Endpoints
# ═════════════════════════════════════════════════════════════════════
@tls_router.get("/config")
async def get_tls_config(user: dict = Depends(require_permission("admin"))):
    """État global : domaines + liste des certs + certificat actif."""
    domains = await _read_domains()
    certs_cursor = db.tls_certificates.find({}, {"_id": 0, "key_pem_enc": 0})
    certs = []
    async for c in certs_cursor:
        c.pop("cert_pem", None)  # ne pas renvoyer le blob PEM ici (utiliser /pem)
        certs.append(c)
    active_id = next((c["id"] for c in certs if c.get("active")), None)
    return {
        "domains": domains,
        "certificates": certs,
        "active_certificate_id": active_id,
        "letsencrypt_enabled": bool(os.environ.get("MGVMS_LETSENCRYPT", "").lower()
                                     in ("1", "true", "yes")),
    }


@tls_router.put("/domains")
async def put_domains(data: DomainsPayload,
                       user: dict = Depends(require_permission("admin"))):
    payload = {
        "internal": DomainsPayload._validate_hostname(data.internal),
        "external": DomainsPayload._validate_hostname(data.external),
        "force_https": data.force_https,
        "hsts_enabled": data.hsts_enabled,
        "hsts_max_age_seconds": data.hsts_max_age_seconds,
    }
    await db.settings.update_one(
        {"key": "tls_domains"},
        {"$set": {"key": "tls_domains", "value": payload}},
        upsert=True,
    )
    await log_audit(user, "tls_domains_updated", "tls",
                     details=f"internal={payload['internal']} · external={payload['external']} · force_https={payload['force_https']}")
    return {"ok": True, **payload}


@tls_router.get("/certificates")
async def list_certificates(user: dict = Depends(require_permission("admin"))):
    return await get_tls_config(user)


@tls_router.get("/certificates/{cid}")
async def get_certificate_details(cid: str,
                                    user: dict = Depends(require_permission("admin"))):
    doc = await db.tls_certificates.find_one({"id": cid}, {"_id": 0, "key_pem_enc": 0})
    if not doc:
        raise HTTPException(404, {"error": "not_found"})
    return doc


class UploadCertPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    cert_pem: str = Field(..., min_length=50)
    key_pem: str = Field(..., min_length=50)
    activate: bool = False


@tls_router.post("/certificates/upload")
async def upload_certificate(data: UploadCertPayload,
                              user: dict = Depends(require_permission("admin"))):
    """Importe un certificat PEM + clé privée PEM existants (ex : Let's Encrypt manuel)."""
    cert_pem = data.cert_pem.strip().encode()
    key_pem = data.key_pem.strip().encode()
    try:
        meta = _parse_cert_metadata(cert_pem)
        # Valide que la clé se charge et matche
        priv = serialization.load_pem_private_key(key_pem, password=None)
        pub_cert = x509.load_pem_x509_certificate(cert_pem).public_key()
        if priv.public_key().public_numbers() != pub_cert.public_numbers():
            raise HTTPException(400, {"error": "key_does_not_match_cert"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, {"error": "invalid_pem", "message": str(e)[:120]})
    cid = str(uuid.uuid4())
    doc = {
        "id": cid,
        "name": data.name,
        "source": "uploaded",
        "cert_pem": cert_pem.decode(),
        "key_pem_enc": _encrypt_key_pem(key_pem),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "active": False,
        **meta,
    }
    await db.tls_certificates.insert_one(doc)
    if data.activate:
        await _activate(cid)
    await log_audit(user, "tls_certificate_uploaded", data.name,
                     details=f"CN={meta['common_name']} · self_signed={meta['self_signed']}")
    doc.pop("_id", None)
    doc.pop("cert_pem", None)
    doc.pop("key_pem_enc", None)
    return doc


class SelfSignedPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    common_name: str = Field(..., min_length=1, max_length=253)
    sans: list[str] = Field(default_factory=list, max_length=32)
    organization: str = Field("MG-VMS", max_length=64)
    country: str = Field("FR", min_length=2, max_length=2)
    validity_days: int = Field(365, ge=1, le=3650)
    key_bits: int = Field(2048, ge=2048, le=4096)
    activate: bool = False


@tls_router.post("/certificates/self-signed")
async def generate_self_signed(data: SelfSignedPayload,
                                 user: dict = Depends(require_permission("admin"))):
    """Génère une paire clé/cert auto-signée. À réserver aux déploiements
    LAN / intranet — les navigateurs afficheront un avertissement en clair
    tant que le cert n'est pas ajouté aux trust stores clients."""
    if data.key_bits not in (2048, 3072, 4096):
        raise HTTPException(400, {"error": "key_bits_invalid"})
    # 1. Clé RSA
    priv = rsa.generate_private_key(public_exponent=65537, key_size=data.key_bits)
    key_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    # 2. Sujet / SAN
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, data.country.upper()),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, data.organization),
        x509.NameAttribute(NameOID.COMMON_NAME, data.common_name),
    ])
    san_names: list = [x509.DNSName(data.common_name)]
    for s in data.sans:
        s = s.strip()
        if not s:
            continue
        try:
            # IP ?
            import ipaddress
            san_names.append(x509.IPAddress(ipaddress.ip_address(s)))
        except ValueError:
            san_names.append(x509.DNSName(s))
    # 3. Certificat
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(priv.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))   # marge horloge
        .not_valid_after(now + timedelta(days=data.validity_days))
        .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True, key_agreement=False,
                content_commitment=False, data_encipherment=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(priv, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    meta = _parse_cert_metadata(cert_pem)
    cid = str(uuid.uuid4())
    doc = {
        "id": cid,
        "name": data.name,
        "source": "self-signed",
        "cert_pem": cert_pem.decode(),
        "key_pem_enc": _encrypt_key_pem(key_pem),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "active": False,
        **meta,
    }
    await db.tls_certificates.insert_one(doc)
    if data.activate:
        await _activate(cid)
    await log_audit(user, "tls_certificate_self_signed", data.name,
                     details=f"CN={data.common_name} · SAN={len(san_names)} · {data.validity_days}j")
    doc.pop("_id", None)
    doc.pop("cert_pem", None)
    doc.pop("key_pem_enc", None)
    return doc


@tls_router.put("/certificates/{cid}/activate")
async def activate_certificate(cid: str,
                                 user: dict = Depends(require_permission("admin"))):
    ok = await _activate(cid)
    if not ok:
        raise HTTPException(404, {"error": "not_found"})
    await log_audit(user, "tls_certificate_activated", cid)
    return {"ok": True, "active_certificate_id": cid}


async def _activate(cid: str) -> bool:
    doc = await db.tls_certificates.find_one({"id": cid}, {"_id": 0, "id": 1})
    if not doc:
        return False
    await db.tls_certificates.update_many({}, {"$set": {"active": False}})
    await db.tls_certificates.update_one({"id": cid}, {"$set": {"active": True}})
    return True


@tls_router.delete("/certificates/{cid}")
async def delete_certificate(cid: str,
                              user: dict = Depends(require_permission("admin"))):
    doc = await db.tls_certificates.find_one({"id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, {"error": "not_found"})
    if doc.get("active"):
        raise HTTPException(409, {"error": "cannot_delete_active",
                                    "message": "Active un autre certificat avant de supprimer celui-ci."})
    await db.tls_certificates.delete_one({"id": cid})
    await log_audit(user, "tls_certificate_deleted", doc.get("name") or cid)
    return {"ok": True}


@tls_router.get("/certificates/{cid}/pem")
async def get_cert_pem(cid: str, include_key: bool = False,
                        user: dict = Depends(require_permission("admin"))):
    """Renvoie le PEM du certificat (et optionnellement de la clé) — audité."""
    doc = await db.tls_certificates.find_one({"id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, {"error": "not_found"})
    out = {"cert_pem": doc.get("cert_pem", "")}
    if include_key:
        try:
            out["key_pem"] = _decrypt_key_pem(doc["key_pem_enc"]).decode()
        except Exception:
            raise HTTPException(500, {"error": "decrypt_failed"})
        await log_audit(user, "tls_private_key_exported", doc.get("name") or cid)
    return out
