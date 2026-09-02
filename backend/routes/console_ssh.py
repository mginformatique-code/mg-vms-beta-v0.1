"""v3.22 · Console shell hôte (Suivi des performances → Debug), style
« cockpit » — accès à un vrai shell sur la machine hôte via SSH, avec les
identifiants Linux réels de l'utilisateur (jamais ceux de MG-VMS).

Choix tranchés le 01/09 :
  - Vrai shell HÔTE (pas seulement le conteneur backend) — le conteneur
    backend n'a lui-même aucun accès privilégié à l'hôte ; il se contente
    d'ouvrir une connexion SSH sortante vers `host.docker.internal`
    (voir extra_hosts dans docker-compose.yml), exactement comme le
    ferait un utilisateur avec `ssh admin@serveur`.
  - Authentification déléguée à sshd : les identifiants saisis dans le
    prompt ne sont JAMAIS stockés ni journalisés — utilisés une seule
    fois pour établir la connexion asyncssh, puis oubliés. C'est sshd
    (PAM) qui décide, pas MG-VMS.
  - Accès réservé admin (JWT applicatif, vérifié AVANT même de demander
    les identifiants Linux) + journal d'audit à l'ouverture/fermeture de
    session — jamais le contenu de la session ni les identifiants.
"""
from __future__ import annotations

import asyncio
import logging

import asyncssh
import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth import JWT_ALGORITHM, get_jwt_secret, log_audit
from database import db

console_router = APIRouter(prefix="/api/system/console", tags=["system-console"])
logger = logging.getLogger("console_ssh")

_SSH_HOST = "host.docker.internal"  # voir docker-compose.yml::backend.extra_hosts


async def _auth_ws_admin(token: str) -> dict | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
        if not user or user.get("role") != "admin":
            return None
        return user
    except Exception:
        return None


async def _pump_ssh_to_ws(process, ws: WebSocket) -> None:
    try:
        while True:
            data = await process.stdout.read(65536)
            if not data:
                break
            await ws.send_json({"type": "data", "data": data})
    except Exception:
        pass


async def _pump_ws_to_ssh(ws: WebSocket, process) -> None:
    while True:
        msg = await ws.receive_json()
        mtype = msg.get("type")
        if mtype == "input":
            process.stdin.write(msg.get("data", ""))
        elif mtype == "resize":
            try:
                process.change_terminal_size(int(msg.get("cols", 80)), int(msg.get("rows", 24)))
            except Exception:
                pass


@console_router.websocket("/ws")
async def console_ws(ws: WebSocket, token: str = ""):
    user = await _auth_ws_admin(token)
    if not user:
        await ws.close(code=1008)
        return
    await ws.accept()

    try:
        creds = await asyncio.wait_for(ws.receive_json(), timeout=60)
    except Exception:
        await ws.close(code=1003)
        return

    username = (creds.get("username") or "").strip()
    password = creds.get("password") or ""
    if not username or not password:
        await ws.send_json({"type": "error", "message": "Identifiant et mot de passe requis"})
        await ws.close()
        return

    cols = int(creds.get("cols") or 80)
    rows = int(creds.get("rows") or 24)

    await log_audit(user, "host_console_opened", f"linux_user={username}")
    logger.info("console_ssh: session ouverte par %s (linux_user=%s)", user.get("email", "?"), username)
    try:
        async with asyncssh.connect(
            _SSH_HOST, username=username, password=password, known_hosts=None,
        ) as conn:
            async with conn.create_process(
                term_type="xterm-256color", term_size=(cols, rows),
            ) as process:
                await ws.send_json({"type": "connected"})
                ssh_to_ws = asyncio.create_task(_pump_ssh_to_ws(process, ws))
                ws_to_ssh = asyncio.create_task(_pump_ws_to_ssh(ws, process))
                done, pending = await asyncio.wait(
                    [ssh_to_ws, ws_to_ssh], return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
    except asyncssh.PermissionDenied:
        await ws.send_json({"type": "error", "message": "Identifiants Linux refusés"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("console_ssh: échec session %s — %s: %s", username, type(e).__name__, e)
        try:
            await ws.send_json({"type": "error", "message": f"Connexion SSH échouée — {type(e).__name__}"})
        except Exception:
            pass
    finally:
        await log_audit(user, "host_console_closed", f"linux_user={username}")
        logger.info("console_ssh: session fermée (linux_user=%s)", username)
        try:
            await ws.close()
        except Exception:
            pass
