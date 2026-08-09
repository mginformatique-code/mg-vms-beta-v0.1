#!/usr/bin/env python3
"""MG-VMS · CLI administrative · v1.0-rc4.6

Commandes serveur qui contournent l'UI HTTP — utilisées pour les opérations
critiques nécessitant un accès physique au serveur (déverrouillage compte
admin principal, seed, etc.).

Usage :
    python3 -m scripts.mgvms_admin unlock-user <email>
    python3 -m scripts.mgvms_admin list-locked

Ou via le wrapper `mgvms-admin` copié dans /usr/local/bin (voir Dockerfile).

Codes retour : 0 = succès, 1 = erreur (utilisateur introuvable, arg invalide,
Mongo indisponible, etc.). Adapté à une utilisation dans des scripts shell.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Le script tourne DEPUIS /app/backend (WORKDIR de l'image) — ajoute le dossier
# au sys.path pour permettre `import database` sans installer le package.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_BACKEND_DIR / ".env")

from database import db  # noqa: E402


async def cmd_unlock_user(email: str) -> int:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        print(f"[ERREUR] Email invalide : {email!r}", file=sys.stderr)
        return 1
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        print(f"[ERREUR] Utilisateur introuvable : {email}", file=sys.stderr)
        return 1
    was_locked = bool(user.get("locked"))
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {"locked": False, "failed_login_count": 0},
            "$unset": {"locked_at": ""},
        },
    )
    # Audit (best-effort — la collection peut ne pas exister sur un fresh install)
    try:
        await db.audit_logs.insert_one({
            "action": "account_unlocked",
            "target": email,
            "details": "CLI mgvms-admin",
            "ip": "cli",
            "actor": "cli/root",
            "timestamp": now_iso,
        })
    except Exception:
        pass
    status = "verrouillé → déverrouillé" if was_locked else "déjà déverrouillé (compteur remis à 0)"
    print(f"[OK] Compte {email} : {status}")
    return 0


async def cmd_list_locked() -> int:
    cursor = db.users.find(
        {"locked": True},
        {"_id": 0, "email": 1, "name": 1, "role": 1, "locked_at": 1,
         "failed_login_count": 1, "last_failed_login_ip": 1},
    )
    rows = await cursor.to_list(500)
    if not rows:
        print("Aucun compte verrouillé.")
        return 0
    print(f"{len(rows)} compte(s) verrouillé(s) :\n")
    for r in rows:
        print(f"  • {r['email']:40s} · role={r.get('role','?'):10s} · "
              f"locked_at={r.get('locked_at','?')} · "
              f"failed={r.get('failed_login_count','?')} · "
              f"last_ip={r.get('last_failed_login_ip','?')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="mgvms-admin", description="MG-VMS admin CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_unlock = sub.add_parser("unlock-user", help="Déverrouille un compte (y compris admin principal)")
    p_unlock.add_argument("email", help="Email du compte à déverrouiller")

    sub.add_parser("list-locked", help="Liste tous les comptes actuellement verrouillés")

    args = parser.parse_args()

    if args.cmd == "unlock-user":
        return asyncio.run(cmd_unlock_user(args.email))
    if args.cmd == "list-locked":
        return asyncio.run(cmd_list_locked())
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
