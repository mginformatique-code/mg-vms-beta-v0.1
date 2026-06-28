import os
import base64
import hashlib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

import aiosmtplib
import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

from database import db
from auth import get_current_user, require_role, log_audit

notif_router = APIRouter(prefix="/api/notifications", tags=["notifications"])

SECRET_FIELDS = {"smtp": ["password"], "discord": ["webhook_url"], "telegram": ["bot_token"]}


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(os.environ["JWT_SECRET"].encode()).digest())
    return Fernet(key)


def enc(v: str) -> str:
    if not v:
        return ""
    return _fernet().encrypt(v.encode()).decode()


def dec(v: str) -> str:
    if not v:
        return ""
    try:
        return _fernet().decrypt(v.encode()).decode()
    except Exception:
        return ""


# ---------- Schemas ----------
class SMTPConfig(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_email: str = ""
    to_email: str = ""
    tls: bool = True


class DiscordConfig(BaseModel):
    enabled: bool = False
    webhook_url: str = ""


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


class SettingsIn(BaseModel):
    smtp: SMTPConfig
    discord: DiscordConfig
    telegram: TelegramConfig


# ---------- Senders ----------
async def send_smtp(cfg: dict, subject: str, body: str):
    msg = EmailMessage()
    msg["From"] = cfg["from_email"]
    msg["To"] = cfg["to_email"]
    msg["Subject"] = subject
    msg.set_content(body)
    port = int(cfg.get("port", 587))
    tls = cfg.get("tls", True)
    await aiosmtplib.send(
        msg, hostname=cfg["host"], port=port,
        username=cfg["username"], password=cfg["password"],
        use_tls=(tls and port == 465), start_tls=(tls and port != 465),
        timeout=15,
    )


async def send_discord(cfg: dict, content: str):
    async with httpx.AsyncClient(timeout=12) as http:
        r = await http.post(cfg["webhook_url"], json={"content": content[:1900], "allowed_mentions": {"parse": []}})
        r.raise_for_status()


async def send_telegram(cfg: dict, content: str):
    async with httpx.AsyncClient(timeout=12) as http:
        r = await http.post(
            f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
            json={"chat_id": cfg["chat_id"], "text": content, "disable_web_page_preview": True},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(str(data))


async def _load_raw() -> dict:
    doc = await db.notification_settings.find_one({"id": "global"}, {"_id": 0})
    return doc or {}


async def _channel_cfg(doc: dict, channel: str) -> Optional[dict]:
    c = doc.get(channel)
    if not c:
        return None
    c = dict(c)
    for f in SECRET_FIELDS.get(channel, []):
        c[f] = dec(c.get(f, ""))
    return c


async def send_notification(subject: str, body: str) -> dict:
    doc = await _load_raw()
    results = {}
    text = f"[MG-VMS] {subject}\n{body}"
    if doc.get("smtp", {}).get("enabled"):
        cfg = await _channel_cfg(doc, "smtp")
        try:
            await send_smtp(cfg, f"[MG-VMS] {subject}", body); results["smtp"] = "sent"
        except Exception as e:
            results["smtp"] = f"error: {e}"
    if doc.get("discord", {}).get("enabled"):
        cfg = await _channel_cfg(doc, "discord")
        try:
            await send_discord(cfg, f"**{subject}**\n{body}"); results["discord"] = "sent"
        except Exception as e:
            results["discord"] = f"error: {e}"
    if doc.get("telegram", {}).get("enabled"):
        cfg = await _channel_cfg(doc, "telegram")
        try:
            await send_telegram(cfg, text); results["telegram"] = "sent"
        except Exception as e:
            results["telegram"] = f"error: {e}"
    return results


def _mask(doc: dict) -> dict:
    """Return config without secret values; expose has_<secret> booleans."""
    smtp = doc.get("smtp", {}) or {}
    discord = doc.get("discord", {}) or {}
    telegram = doc.get("telegram", {}) or {}
    return {
        "smtp": {"enabled": smtp.get("enabled", False), "host": smtp.get("host", ""), "port": smtp.get("port", 587),
                 "username": smtp.get("username", ""), "from_email": smtp.get("from_email", ""),
                 "to_email": smtp.get("to_email", ""), "tls": smtp.get("tls", True),
                 "password": "", "has_password": bool(smtp.get("password"))},
        "discord": {"enabled": discord.get("enabled", False), "webhook_url": "",
                    "has_webhook_url": bool(discord.get("webhook_url"))},
        "telegram": {"enabled": telegram.get("enabled", False), "bot_token": "",
                     "has_bot_token": bool(telegram.get("bot_token")), "chat_id": telegram.get("chat_id", "")},
    }


# ---------- Endpoints ----------
@notif_router.get("/settings")
async def get_settings(user: dict = Depends(require_role("technician"))):
    doc = await _load_raw()
    return _mask(doc)


@notif_router.put("/settings")
async def put_settings(data: SettingsIn, user: dict = Depends(require_role("admin"))):
    existing = await _load_raw()
    payload = data.model_dump()
    # Encrypt secrets; if a secret comes empty, keep the previously stored value.
    for channel, fields in SECRET_FIELDS.items():
        for f in fields:
            new_val = payload[channel].get(f, "")
            if new_val:
                payload[channel][f] = enc(new_val)
            else:
                payload[channel][f] = (existing.get(channel, {}) or {}).get(f, "")
    payload["id"] = "global"
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.notification_settings.update_one({"id": "global"}, {"$set": payload}, upsert=True)
    await log_audit(user, "notification_settings_updated", "global")
    return _mask(payload)


@notif_router.post("/test")
async def test_send(channel: str, user: dict = Depends(require_role("technician"))):
    doc = await _load_raw()
    if channel not in ("smtp", "discord", "telegram"):
        raise HTTPException(400, "Canal invalide")
    cfg = await _channel_cfg(doc, channel)
    if not cfg:
        raise HTTPException(400, "Canal non configuré")
    subject = "Test de notification"
    body = f"Ceci est un message de test envoyé depuis MG-VMS par {user['email']}."
    try:
        if channel == "smtp":
            await send_smtp(cfg, f"[MG-VMS] {subject}", body)
        elif channel == "discord":
            await send_discord(cfg, f"**{subject}**\n{body}")
        elif channel == "telegram":
            await send_telegram(cfg, f"[MG-VMS] {subject}\n{body}")
    except Exception as e:
        await log_audit(user, "notification_test_failed", channel, str(e))
        raise HTTPException(500, f"Échec de l'envoi: {e}")
    await log_audit(user, "notification_test_sent", channel)
    return {"ok": True, "channel": channel}
