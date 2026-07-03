"""MG-VMS — Service de notifications multi-canal.

Consomme la file Redis `mgvms:notifications` et relaie vers :
Email (SMTP), Discord (webhook), Telegram (bot), Webhook générique.
Expose /health pour Docker.
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from email.message import EmailMessage

import aiosmtplib
import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("notification")

REDIS_URL = os.environ["REDIS_URL"]
QUEUE = "mgvms:notifications"

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "mg-vms@localhost")


async def send_email(to: str, subject: str, body: str) -> None:
    if not SMTP_HOST:
        logger.warning("SMTP non configuré — email ignoré (%s)", subject)
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = SMTP_FROM, to, subject
    msg.set_content(body)
    await aiosmtplib.send(msg, hostname=SMTP_HOST, port=SMTP_PORT,
                          username=SMTP_USER or None, password=SMTP_PASSWORD or None,
                          start_tls=SMTP_PORT == 587)


async def send_discord(webhook_url: str, title: str, message: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(webhook_url, json={"embeds": [{"title": title, "description": message, "color": 15158332}]})


async def send_telegram(bot_token: str, chat_id: str, title: str, message: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
                          json={"chat_id": chat_id, "text": f"*{title}*\n{message}", "parse_mode": "Markdown"})


async def send_webhook(url: str, payload: dict) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json=payload)


async def dispatch(payload: dict) -> None:
    kind = payload.get("type")
    title = payload.get("title", "MG-VMS")
    message = payload.get("message", "")

    if kind == "password_reset":
        await send_email(payload["email"], "MG-VMS — Réinitialisation du mot de passe",
                         f"Jeton de réinitialisation : {payload['token']}\nValide 1 heure.")
        return

    cfg = payload.get("channel_config", {})
    channel_type = payload.get("channel_type", "")
    try:
        if channel_type == "email":
            await send_email(cfg.get("to", ""), title, message)
        elif channel_type == "discord":
            await send_discord(cfg.get("webhook_url", ""), title, message)
        elif channel_type == "telegram":
            await send_telegram(cfg.get("bot_token", ""), cfg.get("chat_id", ""), title, message)
        elif channel_type == "webhook":
            await send_webhook(cfg.get("url", ""), payload)
        else:
            logger.warning("Type de canal inconnu : %s", channel_type)
    except Exception:
        logger.exception("Échec d'envoi (%s)", channel_type)


async def consume_queue() -> None:
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    logger.info("Consommateur démarré sur la file %s", QUEUE)
    while True:
        try:
            item = await r.blpop(QUEUE, timeout=5)
            if item:
                await dispatch(json.loads(item[1]))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erreur de consommation — reprise dans 3s")
            await asyncio.sleep(3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(consume_queue())
    yield
    task.cancel()


app = FastAPI(title="MG-VMS Notification Service", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"service": "notification", "status": "ok"}
