"""MG-VMS — Initialisation RÉELLE : comptes + purge des anciennes données factices.

Plus aucune donnée simulée : les caméras, équipements, plaques, événements et
enregistrements proviennent exclusivement du réel (flux RTSP, ping ICMP, IA YOLO,
LAPI fast-alpr, enregistreur FFmpeg).
"""
import os
import uuid
from datetime import datetime, timezone

from database import db
from auth import hash_password

PURGE_FLAG = "purged_fake_data_v1"


async def seed():
    now = datetime.now(timezone.utc).isoformat()

    # ---- Comptes ----
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "id": str(uuid.uuid4()), "email": admin_email, "password_hash": hash_password(admin_password),
            "name": "Administrateur", "role": "admin", "twofa_enabled": False, "twofa_secret": None,
            "active": True, "site_ids": [], "created_at": now,
        })
    else:
        from auth import verify_password
        if not verify_password(admin_password, existing["password_hash"]):
            await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_password)}})

    demo_users = [
        ("tech@mg-vms.com", "Tech@2026", "Thomas Technicien", "technician"),
        ("client@mg-vms.com", "Client@2026", "Claire Cliente", "client"),
        ("viewer@mg-vms.com", "Viewer@2026", "Victor Lecteur", "readonly"),
    ]
    for email, pwd, name, role in demo_users:
        if not await db.users.find_one({"email": email}):
            await db.users.insert_one({
                "id": str(uuid.uuid4()), "email": email, "password_hash": hash_password(pwd),
                "name": name, "role": role, "twofa_enabled": False, "twofa_secret": None,
                "active": True, "site_ids": [], "created_at": now,
            })

    # ---- Purge unique des données factices (migration vers le tout-réel) ----
    if not await db.meta.find_one({"id": PURGE_FLAG}):
        await db.cameras.delete_many({})
        await db.equipment.delete_many({})
        await db.plates.delete_many({})
        await db.events.delete_many({})
        await db.alerts.delete_many({})
        await db.recordings.delete_many({})
        await db.exports.delete_many({})
        await db.watchlist.delete_many({})
        await db.sites.delete_many({})
        await db.users.update_many({}, {"$set": {"site_ids": []}})
        await db.meta.insert_one({"id": PURGE_FLAG, "at": now})

    # ---- Site par défaut ----
    if await db.sites.count_documents({}) == 0:
        await db.sites.insert_one({
            "id": str(uuid.uuid4()), "name": "Site principal", "type": "Site",
            "address": "", "lat": 46.2276, "lng": 2.2137,
            "camera_count": 0, "created_at": now,
        })
