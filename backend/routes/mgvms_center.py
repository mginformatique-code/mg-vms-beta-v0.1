"""Connexion MG-VMS <-> MG-VMS Center (v3.49).

MG-VMS Center est un service SÉPARÉ, hébergé par MG Informatique, qui
centralise l'état de tous les déploiements clients (version, caméras,
santé). Ce module gère UNIQUEMENT le côté MG-VMS de la relation :

  1. Assistant de connexion (admin MG Informatique authentifié par
     mot de passe + MFA — voir docstring de `connect_login` ci-dessous
     pour la raison de cette restriction) : sélection/création du
     tenant+site, création du déploiement côté central, récupération de
     la clé API.
  2. Rapport périodique (voir `mgvms_center_report_loop` dans server.py) :
     pousse version/caméras/santé vers le central, encaisse en retour un
     éventuel `update_available`.

Design "jamais de régression de connectivité" : toute erreur réseau vers
MG-VMS Center est absorbée localement (log + `connected` reste tel quel
en base) — un MG-VMS Center injoignable ne doit JAMAIS impacter le
fonctionnement normal de ce déploiement.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_role
from crypto_utils import decrypt_secret, encrypt_secret
from database import db

logger = logging.getLogger("mgvms_center")

mgvms_center_router = APIRouter(prefix="/api/mgvms-center", tags=["mgvms-center"])

REQUEST_TIMEOUT_S = 10.0


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
    site_id: Optional[str] = None
    new_site_name: Optional[str] = None
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
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
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
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            resp = await client.post(f"{_base_url(data.url)}/api/v1/auth/mfa-verify",
                                      json={"mfa_token": data.mfa_token, "code": data.code})
    except httpx.RequestError as e:
        raise HTTPException(502, f"MG-VMS Center injoignable : {type(e).__name__}")
    if resp.status_code != 200:
        raise HTTPException(401, "Code MFA invalide")
    payload = resp.json()
    token = payload["access_token"]
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
        headers = {"Authorization": f"Bearer {token}"}
        tenants = (await client.get(f"{_base_url(data.url)}/api/v1/tenants", headers=headers)).json()
        sites = (await client.get(f"{_base_url(data.url)}/api/v1/sites", headers=headers)).json()
    return {"pairing_token": token, "tenants": tenants, "sites": sites}


@mgvms_center_router.post("/connect/finish")
async def connect_finish(data: ConnectFinishInput, user: dict = Depends(require_role("admin"))):
    headers = {"Authorization": f"Bearer {data.pairing_token}"}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            tenant_id = data.tenant_id
            if not tenant_id:
                if not data.new_tenant_name:
                    raise HTTPException(400, "Nom du tenant requis")
                r = await client.post(f"{_base_url(data.url)}/api/v1/tenants",
                                       json={"name": data.new_tenant_name}, headers=headers)
                r.raise_for_status()
                tenant_id = r.json()["id"]

            site_id = data.site_id
            if not site_id:
                if not data.new_site_name:
                    raise HTTPException(400, "Nom du site requis")
                r = await client.post(f"{_base_url(data.url)}/api/v1/sites",
                                       json={"tenant_id": tenant_id, "name": data.new_site_name},
                                       headers=headers)
                r.raise_for_status()
                site_id = r.json()["id"]

            r = await client.post(f"{_base_url(data.url)}/api/v1/deployments",
                                   json={"site_id": site_id, "label": data.label}, headers=headers)
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


# ── Rapport périodique (voir server.py::on_startup) ──────────────────
REPORT_INTERVAL_S = 30 * 60
_process_started_at = time.monotonic()


async def mgvms_center_report_loop() -> None:
    """Boucle de fond — no-op tant qu'aucune connexion n'est configurée
    (voir l'assistant ci-dessus). Toute erreur reste locale : un MG-VMS
    Center injoignable ne doit jamais affecter ce déploiement."""
    import asyncio
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

    camera_count = await db.cameras.count_documents({})
    site_count_local = await db.sites.count_documents({})
    payload = {
        "version": _current_version(),
        "git_commit": os.environ.get("GIT_COMMIT"),
        "camera_count": camera_count,
        "site_count_local": site_count_local,
        "uptime_seconds": time.monotonic() - _process_started_at,
        "health_summary": {"status": "ok"},
    }
    api_key = decrypt_secret(s["api_key_encrypted"])
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
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
            }},
        )
    except Exception as e:
        logger.warning("mgvms_center: échec du rapport (%s) — nouvelle tentative dans %ds",
                        type(e).__name__, REPORT_INTERVAL_S)
        await db.settings.update_one(
            {"key": "mgvms_center"},
            {"$set": {"last_report_at": time.time(), "last_report_ok": False}},
        )
