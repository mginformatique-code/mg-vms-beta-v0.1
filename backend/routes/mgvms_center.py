"""Connexion MG-VMS <-> MG-VMS Center (v3.49).

MG-VMS Center est un service SÉPARÉ, hébergé par MG Informatique, qui
centralise l'état de tous les déploiements clients (version, caméras,
santé). Ce module gère UNIQUEMENT le côté MG-VMS de la relation :

  1. Assistant de connexion (admin MG Informatique authentifié par
     mot de passe + MFA — voir docstring de `connect_login` ci-dessous
     pour la raison de cette restriction) : sélection/création du
     tenant, création du déploiement côté central, récupération de
     la clé API. Les sites ne se créent jamais depuis cet assistant :
     un déploiement MG-VMS gère déjà ses propres sites en interne
     (`db.sites`), le central se contente de les redécouvrir à chaque
     rapport (voir `_send_report_once` ci-dessous).
  2. Rapport périodique (voir `mgvms_center_report_loop` dans server.py) :
     pousse version/caméras/sites/santé vers le central, encaisse en
     retour un éventuel `update_available`.

Design "jamais de régression de connectivité" : toute erreur réseau vers
MG-VMS Center est absorbée localement (log + `connected` reste tel quel
en base) — un MG-VMS Center injoignable ne doit JAMAIS impacter le
fonctionnement normal de ce déploiement.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from auth import create_access_token, hash_password, log_audit, require_role
from crypto_utils import decrypt_secret, encrypt_secret
from database import db

logger = logging.getLogger("mgvms_center")

mgvms_center_router = APIRouter(prefix="/api/mgvms-center", tags=["mgvms-center"])

REQUEST_TIMEOUT_S = 10.0
# MG-VMS Center est servi en HTTPS avec un certificat auto-signé (pas de
# domaine public dédié) — verify=False assumé ici, cohérent avec le fait
# que le pairing exige déjà une authentification MG Informatique (mdp+MFA).


# ── Modèles ──────────────────────────────────────────────────────────
class ConnectLoginInput(BaseModel):
    url: str
    email: str
    password: str


class ConnectMfaInput(BaseModel):
    url: str
    mfa_token: str
    code: str


class ConnectFinishInput(BaseModel):
    url: str
    pairing_token: str
    tenant_id: Optional[str] = None
    new_tenant_name: Optional[str] = None
    label: str


def _base_url(url: str) -> str:
    return url.rstrip("/")


async def _get_settings() -> dict:
    return await db.settings.find_one({"key": "mgvms_center"}, {"_id": 0}) or {}


# ── Assistant de connexion (Réglages -> MG-VMS Center) ───────────────
# v3.49 · Restriction volontaire (demande explicite) : cet assistant
# exige un login + MFA valide côté MG-VMS Center lui-même, qui n'a de
# comptes que pour le personnel MG Informatique (voir mgvms-center
# project, `db.admins`) — un client final ne PEUT PAS s'auto-connecter,
# il n'a jamais de compte MG-VMS Center. La connexion se fait donc
# toujours avec MG Informatique présent (sur place ou à distance).
@mgvms_center_router.post("/connect/login")
async def connect_login(data: ConnectLoginInput, user: dict = Depends(require_role("admin"))):
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, verify=False) as client:
            resp = await client.post(f"{_base_url(data.url)}/api/v1/auth/login",
                                      json={"email": data.email, "password": data.password})
    except httpx.RequestError as e:
        raise HTTPException(502, f"MG-VMS Center injoignable : {type(e).__name__}")
    if resp.status_code != 200:
        raise HTTPException(401, "Identifiants MG-VMS Center invalides")
    return resp.json()


@mgvms_center_router.post("/connect/mfa-verify")
async def connect_mfa_verify(data: ConnectMfaInput, user: dict = Depends(require_role("admin"))):
    """Renvoie un jeton d'accès MG-VMS Center de courte durée (8h, côté
    central) directement au navigateur — utilisé UNIQUEMENT le temps de
    l'assistant (choix tenant/site + création du déploiement), jamais
    persisté au-delà de cette session de configuration."""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, verify=False) as client:
            resp = await client.post(f"{_base_url(data.url)}/api/v1/auth/mfa-verify",
                                      json={"mfa_token": data.mfa_token, "code": data.code})
    except httpx.RequestError as e:
        raise HTTPException(502, f"MG-VMS Center injoignable : {type(e).__name__}")
    if resp.status_code != 200:
        raise HTTPException(401, "Code MFA invalide")
    payload = resp.json()
    token = payload["access_token"]
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, verify=False) as client:
        headers = {"Authorization": f"Bearer {token}"}
        tenants = (await client.get(f"{_base_url(data.url)}/api/v1/tenants", headers=headers)).json()
    return {"pairing_token": token, "tenants": tenants}


@mgvms_center_router.post("/connect/finish")
async def connect_finish(data: ConnectFinishInput, user: dict = Depends(require_role("admin"))):
    headers = {"Authorization": f"Bearer {data.pairing_token}"}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, verify=False) as client:
            tenant_id = data.tenant_id
            if not tenant_id:
                if not data.new_tenant_name:
                    raise HTTPException(400, "Nom du tenant requis")
                r = await client.post(f"{_base_url(data.url)}/api/v1/tenants",
                                       json={"name": data.new_tenant_name}, headers=headers)
                r.raise_for_status()
                tenant_id = r.json()["id"]

            r = await client.post(f"{_base_url(data.url)}/api/v1/deployments",
                                   json={"tenant_id": tenant_id, "label": data.label}, headers=headers)
            r.raise_for_status()
            deployment = r.json()
    except httpx.RequestError as e:
        raise HTTPException(502, f"MG-VMS Center injoignable : {type(e).__name__}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, "Échec de la création du déploiement côté MG-VMS Center")

    await db.settings.update_one(
        {"key": "mgvms_center"},
        {"$set": {
            "key": "mgvms_center", "url": _base_url(data.url),
            "api_key_encrypted": encrypt_secret(deployment["api_key"]),
            "deployment_id": deployment["id"], "label": data.label,
            "connected_at": time.time(),
        }},
        upsert=True,
    )
    logger.info("mgvms_center: connexion établie (%s)", _base_url(data.url))
    return {"success": True}


@mgvms_center_router.post("/disconnect")
async def disconnect(user: dict = Depends(require_role("admin"))):
    await db.settings.delete_one({"key": "mgvms_center"})
    return {"success": True}


@mgvms_center_router.get("/status")
async def status():
    """Lecture seule, permissions par défaut (view_live suffit) — utilisée
    par le dialogue "À propos" pour tout profil, pas seulement admin."""
    s = await _get_settings()
    if not s:
        return {"connected": False}
    return {
        "connected": True, "url": s.get("url"), "label": s.get("label"),
        "connected_at": s.get("connected_at"),
        "last_report_at": s.get("last_report_at"),
        "last_report_ok": s.get("last_report_ok"),
        "update_available": s.get("update_available", False),
        "latest_version": s.get("latest_version"),
    }


@mgvms_center_router.get("/messages")
async def messages():
    """Messages diffusés par MG-VMS Center, tels que reçus au dernier
    rapport (voir _send_report_once) — lecture seule, tout profil."""
    s = await _get_settings()
    return {"messages": (s or {}).get("messages", [])}


# ── SSO « Ouvrir MG-VMS » (v3.53) ─────────────────────────────────────
# Le Center ne peut pas fabriquer de session MG-VMS (JWT_SECRET propre à
# ce déploiement, jamais connu du Center) — voir POST /sso-token côté
# Center. Ce endpoint échange le code reçu sur la page publique /sso
# contre une vraie session locale, en rappelant NOUS-MÊMES le Center pour
# vérifier le code (jamais l'inverse — même sens que _send_report_once).
class SsoRedeemInput(BaseModel):
    code: str


CENTER_SSO_EMAIL = "center-sso@mginformatique.local"


async def _get_or_create_sso_user() -> dict:
    user = await db.users.find_one({"email": CENTER_SSO_EMAIL}, {"_id": 0})
    if user:
        return user
    doc = {
        "id": str(_uuid.uuid4()),
        "email": CENTER_SSO_EMAIL,
        # Mot de passe aléatoire, jamais communiqué — ce compte ne se
        # connecte jamais par mot de passe, uniquement via ce flux SSO.
        "password_hash": hash_password(secrets.token_urlsafe(32)),
        "name": "MG-VMS Center (SSO)",
        "role": "admin",
        "active": True,
        "sso_managed": True,
        "twofa_enabled": False,
        "site_ids": [],
        "permissions": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)
    doc.pop("_id", None)
    return doc


@mgvms_center_router.post("/sso/redeem")
async def sso_redeem(data: SsoRedeemInput, request: Request, response: Response):
    """Endpoint PUBLIC — aucune session locale n'existe encore à ce stade
    (même précédent que /status et /messages ci-dessus, seuls autres
    endpoints de ce fichier sans Depends(require_role...)). Appelé par la
    page /sso du frontend juste après avoir reçu ?code= de MG-VMS Center."""
    s = await _get_settings()
    if not s or not s.get("api_key_encrypted"):
        raise HTTPException(400, "MG-VMS Center non connecté")
    api_key = decrypt_secret(s["api_key_encrypted"])
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, verify=False) as client:
            resp = await client.post(f"{s['url']}/api/v1/sso/verify", json={"code": data.code},
                                      headers={"X-API-Key": api_key})
    except httpx.RequestError as e:
        raise HTTPException(502, f"MG-VMS Center injoignable : {type(e).__name__}")
    if resp.status_code != 200:
        raise HTTPException(401, "Code SSO invalide, expiré ou déjà utilisé")
    admin_email = resp.json().get("admin_email") or "?"

    user = await _get_or_create_sso_user()
    if not user.get("active", True):
        raise HTTPException(403, "Compte SSO désactivé")

    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
    jti = str(_uuid.uuid4())
    hours = 8
    access = create_access_token(user["id"], user["email"], user["role"], hours=hours, jti=jti)
    now_iso = datetime.now(timezone.utc).isoformat()
    exp_iso = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    await db.sessions.insert_one({
        "jti": jti, "user_id": user["id"], "email": user["email"],
        "created_at": now_iso, "last_seen_at": now_iso, "expires_at": exp_iso,
        "ip": ip, "user_agent": request.headers.get("user-agent", "")[:250],
        "revoked": False,
    })
    response.set_cookie("access_token", access, httponly=True, secure=True, samesite="lax",
                         max_age=hours * 3600, path="/")
    await log_audit(user, "login_sso", user["email"],
                     f"SSO via MG-VMS Center (compte Center : {admin_email})", ip)
    return {"success": True, "access_token": access}


# ── Rapport périodique (voir server.py::on_startup) ──────────────────
REPORT_INTERVAL_S = 30 * 60
_process_started_at = time.monotonic()


async def mgvms_center_report_loop() -> None:
    """Boucle de fond — no-op tant qu'aucune connexion n'est configurée
    (voir l'assistant ci-dessus). Toute erreur reste locale : un MG-VMS
    Center injoignable ne doit jamais affecter ce déploiement."""
    while True:
        try:
            await _send_report_once()
        except Exception:
            logger.exception("mgvms_center_report_loop: erreur inattendue")
        await asyncio.sleep(REPORT_INTERVAL_S)


async def _send_report_once() -> None:
    s = await _get_settings()
    if not s or not s.get("api_key_encrypted"):
        return

    from routes.welcome import _current_version
    from routes.tls import _read_domains
    from routes.system_admin import load_system_identity
    from routes.health_dashboard import _system_metrics, _mongo_health, _ai_gpu_health, _plugins_health, _recorder_health

    camera_count = await db.cameras.count_documents({})
    local_sites = await db.sites.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)
    sites_report = []
    for site in local_sites:
        cam_count = await db.cameras.count_documents({"site_id": site["id"]})
        sites_report.append({"id": site["id"], "name": site["name"], "camera_count": cam_count})
    identity = await load_system_identity()
    domains = await _read_domains()

    # v3.51 · Nom d'hôte RÉEL de la machine/VM (lu depuis /etc/hostname,
    # monté en lecture seule — voir docker-compose.yml) — sert à
    # l'identification du déploiement côté Center ("je me repère mieux
    # dans les sites" — demande explicite). PAS le "domaine local" saisi
    # à la main dans Réseau > Certificat SSL, qui reste un réglage TLS
    # séparé, pas une identité machine.
    try:
        with open("/etc/host_hostname") as f:
            machine_hostname = f.read().strip()
    except Exception:
        machine_hostname = ""

    # v3.51 · Adresse locale réelle de la machine (IP, pas un nom DNS) —
    # demande explicite : sur un lien VPN, un nom comme "mgvms.local" ne
    # se résout généralement pas à travers le tunnel, alors que l'IP reste
    # joignable si le VPN route ce sous-réseau. Lue depuis l'instantané
    # écrit par network-watch.sh (voir routes/system_admin.py) quand ce
    # timer hôte est installé ; sinon absente (jamais de valeur inventée).
    local_ip = ""
    try:
        with open("/logs/network_status.json") as f:
            local_ip = (json.load(f).get("current") or {}).get("ip") or ""
    except Exception:
        pass

    # Domaine DNS externe (Internet public) — pour un accès distant "à
    # l'ancienne" (port-forwarding/reverse proxy déjà en place côté
    # client). Le vrai accès distant sans configuration réseau manuelle
    # (VPN mesh Tailscale/WireGuard) est une pièce séparée, pas encore
    # câblée ici — voir roadmap MG-VMS Center.
    external_hostname = domains.get("external") or ""

    # v3.51 · Le port HTTPS réel (FRONTEND_HTTPS_PORT côté docker-compose,
    # 3443 par défaut — jamais 443) doit accompagner l'adresse : sans lui,
    # "Ouvrir MG-VMS" côté Center pointerait vers le mauvais port.
    try:
        https_port = int(os.environ.get("MGVMS_HTTPS_PORT", "443"))
    except ValueError:
        https_port = 443

    # v3.52 · Télémétrie réelle pour MG-VMS Center — réutilise TEL QUEL les
    # fonctions déjà utilisées par le propre tableau de bord de MG-VMS
    # (topbar CPU/RAM/Stockage/GPU, panneau Diagnostics) plutôt que de
    # recalculer quoi que ce soit ici. Chronométré avec une limite dure :
    # un sous-système lent (constaté une fois avec un compte Mongo non
    # borné sur une grosse collection, corrigé depuis) ne doit jamais faire
    # rater un cycle de rapport entier — mieux vaut un health_summary
    # partiel que pas de rapport du tout.
    async def _safe(name, coro):
        try:
            return await asyncio.wait_for(coro, timeout=8)
        except Exception as e:
            return {"error": f"{type(e).__name__} (timeout ou échec sur {name})"}

    health_summary = {
        "system": await _safe("system", _system_metrics()),
        "mongo": await _safe("mongo", _mongo_health()),
        "ai": await _safe("ai", _ai_gpu_health()),
        "plugins": await _safe("plugins", _plugins_health()),
        "recorder": await _safe("recorder", _recorder_health()),
    }

    # v3.52 · Liste caméras légère pour l'onglet Caméras du Center — même
    # projection que routes/site_manager.py::list_cameras_map (déjà
    # débarrassée des champs sensibles : pas de mot de passe, pas d'URL RTSP).
    cameras_report = await db.cameras.find({}, {
        "_id": 0, "id": 1, "name": 1, "ip": 1, "manufacturer": 1, "model": 1,
        "site_id": 1, "status": 1, "last_seen": 1,
    }).to_list(1000)

    payload = {
        "version": _current_version(),
        "git_commit": os.environ.get("GIT_COMMIT"),
        "camera_count": camera_count,
        "sites": sites_report,
        "cameras": cameras_report,
        "uptime_seconds": time.monotonic() - _process_started_at,
        "health_summary": health_summary,
        "system_name": identity.get("system_name"),
        "machine_hostname": machine_hostname,
        "local_ip": local_ip,
        "external_hostname": external_hostname,
        "port": https_port,
    }
    api_key = decrypt_secret(s["api_key_encrypted"])
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, verify=False) as client:
            resp = await client.post(f"{s['url']}/api/v1/report", json=payload,
                                      headers={"X-API-Key": api_key})
        resp.raise_for_status()
        body = resp.json()
        await db.settings.update_one(
            {"key": "mgvms_center"},
            {"$set": {
                "last_report_at": time.time(), "last_report_ok": True,
                "update_available": body.get("update_available", False),
                "latest_version": body.get("latest_version"),
                "release_notes_url": body.get("release_notes_url"),
                # v3.51 · Reflète TOUJOURS l'état courant côté Center (un
                # message retiré côté central disparaît ici au rapport
                # suivant, sans action côté client) — jamais fusionné.
                "messages": body.get("messages", []),
            }},
        )

        # v3.52 · Canal de commandes — architecture push-only préservée :
        # le Center ne nous appelle jamais, il dépose la commande dans la
        # RÉPONSE à notre propre rapport, consommée une seule fois côté
        # Center (voir receive_report). Une seule commande existe pour
        # l'instant : reboot, qui réutilise TEL QUEL le mécanisme déjà en
        # place localement (routes/system_admin.py::_write_reboot_flag +
        # deploy-app/reboot-watch.sh) — aucun accusé de réception séparé,
        # le Center déduira le succès du prochain rapport (uptime proche
        # de zéro), même logique "best-effort" que les messages diffusés.
        pending_command = body.get("pending_command")
        if pending_command and pending_command.get("type") == "reboot":
            from routes.system_admin import _write_reboot_flag
            _write_reboot_flag("Demandé depuis MG-VMS Center")
            logger.warning("mgvms_center: redémarrage machine demandé depuis le Center — fichier marqueur déposé")
    except Exception as e:
        logger.warning("mgvms_center: échec du rapport (%s) — nouvelle tentative dans %ds",
                        type(e).__name__, REPORT_INTERVAL_S)
        await db.settings.update_one(
            {"key": "mgvms_center"},
            {"$set": {"last_report_at": time.time(), "last_report_ok": False}},
        )
