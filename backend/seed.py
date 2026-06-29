import os
import uuid
import random
from datetime import datetime, timezone, timedelta

from database import db
from auth import hash_password

SITES = [
    {"name": "Mairie Centrale", "type": "Mairie", "address": "Place de la République, Lyon", "lat": 45.7640, "lng": 4.8357},
    {"name": "Parking Bellecour", "type": "Parking", "address": "Place Bellecour, Lyon", "lat": 45.7578, "lng": 4.8320},
    {"name": "École Jean Moulin", "type": "École", "address": "Rue de la Paix, Lyon", "lat": 45.7700, "lng": 4.8500},
    {"name": "Stade Municipal", "type": "Stade", "address": "Avenue du Sport, Lyon", "lat": 45.7450, "lng": 4.8200},
    {"name": "Zone Industrielle Nord", "type": "Zone industrielle", "address": "ZI Nord, Vénissieux", "lat": 45.7000, "lng": 4.8800},
]

CAMERA_MODELS = ["Hikvision DS-2CD2", "Dahua IPC-HFW", "Axis P3245", "Hanwha XNV-6", "Bosch FLEXIDOME"]
CODECS = ["H264", "H265", "MJPEG"]
PROTOCOLS = ["RTSP", "ONVIF", "HTTP"]

PLATE_PREFIXES = ["AB", "CD", "EF", "GH", "AA", "BC", "DE", "FG"]
COLORS = ["Blanc", "Noir", "Gris", "Bleu", "Rouge", "Vert", "Argent"]
MAKES = ["Renault", "Peugeot", "Citroën", "Volkswagen", "BMW", "Mercedes", "Toyota", "Audi"]
MODELS = {"Renault": ["Clio", "Megane", "Captur"], "Peugeot": ["208", "308", "3008"], "Citroën": ["C3", "C4", "Berlingo"],
          "Volkswagen": ["Golf", "Polo", "Tiguan"], "BMW": ["Série 3", "X5", "Série 1"], "Mercedes": ["Classe A", "Classe C", "GLC"],
          "Toyota": ["Yaris", "Corolla", "RAV4"], "Audi": ["A3", "A4", "Q5"]}
VTYPES = ["Voiture", "Camion", "Moto", "Bus", "Utilitaire"]
EVENT_TYPES = ["Personne", "Voiture", "Camion", "Moto", "Vélo", "Animal", "Incendie", "Fumée", "Intrusion"]
DIRECTIONS = ["Nord", "Sud", "Est", "Ouest", "Entrée", "Sortie"]


def fr_plate():
    return f"{random.choice(PLATE_PREFIXES)}-{random.randint(100,999)}-{random.choice(PLATE_PREFIXES)}"


async def seed():
    # ---- Users ----
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    now = datetime.now(timezone.utc).isoformat()
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

    # Assigner les sites de démo (cloisonnement) — idempotent, basé sur les sites existants
    async def assign_demo_sites():
        existing = await db.sites.find({}, {"_id": 0, "id": 1}).sort("created_at", 1).to_list(20)
        if not existing:
            return
        ids = [s["id"] for s in existing]
        await db.users.update_one({"email": "client@mg-vms.com"}, {"$set": {"site_ids": ids[:1]}})
        await db.users.update_one({"email": "viewer@mg-vms.com"}, {"$set": {"site_ids": ids[1:2] or ids[:1]}})

    await assign_demo_sites()

    # If cameras already seeded, skip heavy seeding
    if await db.cameras.count_documents({}) > 0:
        return

    # ---- Sites ----
    site_docs = []
    for s in SITES:
        doc = {"id": str(uuid.uuid4()), "created_at": now, "camera_count": 0, **s}
        site_docs.append(doc)
    await db.sites.insert_many([dict(d) for d in site_docs])
    await assign_demo_sites()

    # ---- Cameras ----
    cam_docs = []
    for si, site in enumerate(site_docs):
        n = random.randint(4, 8)
        for c in range(n):
            online = random.random() > 0.18
            cam_docs.append({
                "id": str(uuid.uuid4()),
                "name": f"{site['type'][:3].upper()}-CAM-{c+1:02d}",
                "site_id": site["id"],
                "site_name": site["name"],
                "ip": f"192.168.{si+10}.{c+20}",
                "port": 554,
                "protocol": random.choice(PROTOCOLS),
                "codec": random.choice(CODECS),
                "model": random.choice(CAMERA_MODELS),
                "rtsp_url": f"rtsp://192.168.{si+10}.{c+20}:554/stream1",
                "username": "admin",
                "status": "online" if online else "offline",
                "ptz_enabled": random.random() > 0.5,
                "lat": site["lat"] + random.uniform(-0.002, 0.002),
                "lng": site["lng"] + random.uniform(-0.002, 0.002),
                "last_seen": now,
                "created_at": now,
            })
        await db.sites.update_one({"id": site["id"]}, {"$set": {"camera_count": n}})
    await db.cameras.insert_many([dict(d) for d in cam_docs])

    # ---- Events ----
    events = []
    for _ in range(120):
        cam = random.choice(cam_docs)
        ts = datetime.now(timezone.utc) - timedelta(minutes=random.randint(0, 4320))
        events.append({
            "id": str(uuid.uuid4()),
            "type": random.choice(EVENT_TYPES),
            "camera_id": cam["id"], "camera_name": cam["name"],
            "site_id": cam["site_id"], "site_name": cam["site_name"],
            "confidence": round(random.uniform(0.72, 0.99), 2),
            "timestamp": ts.isoformat(),
            "thumbnail": "https://images.unsplash.com/photo-1707829248830-578d2b0cbe65?w=400&q=80",
        })
    await db.events.insert_many(events)

    # ---- Plates (ANPR) ----
    plates = []
    for _ in range(80):
        cam = random.choice(cam_docs)
        make = random.choice(MAKES)
        ts = datetime.now(timezone.utc) - timedelta(minutes=random.randint(0, 4320))
        plates.append({
            "id": str(uuid.uuid4()),
            "plate": fr_plate(),
            "camera_id": cam["id"], "camera_name": cam["name"],
            "site_id": cam["site_id"], "site_name": cam["site_name"],
            "confidence": round(random.uniform(0.80, 0.99), 2),
            "vehicle_color": random.choice(COLORS),
            "vehicle_make": make,
            "vehicle_model": random.choice(MODELS[make]),
            "vehicle_type": random.choice(VTYPES),
            "country": "France",
            "direction": random.choice(DIRECTIONS),
            "lat": cam["lat"], "lng": cam["lng"],
            "list_status": "none",
            "vehicle_crop": "https://images.unsplash.com/photo-1489169413288-513451305ec1?w=400&q=80",
            "plate_crop": "https://images.unsplash.com/photo-1689702301603-08bd1b92d985?w=400&q=80",
            "timestamp": ts.isoformat(),
        })
    await db.plates.insert_many(plates)

    # ---- Watchlist ----
    wl = [
        {"id": str(uuid.uuid4()), "plate": plates[0]["plate"], "list_type": "black", "reason": "Véhicule volé signalé", "created_at": now},
        {"id": str(uuid.uuid4()), "plate": plates[1]["plate"], "list_type": "white", "reason": "Personnel autorisé", "created_at": now},
        {"id": str(uuid.uuid4()), "plate": "ZZ-999-ZZ", "list_type": "black", "reason": "Liste de surveillance préfecture", "created_at": now},
    ]
    await db.watchlist.insert_many(wl)
    await db.plates.update_one({"id": plates[0]["id"]}, {"$set": {"list_status": "black"}})
    await db.plates.update_one({"id": plates[1]["id"]}, {"$set": {"list_status": "white"}})

    # ---- Alerts ----
    alerts = []
    severities = ["critical", "warning", "info"]
    alert_msgs = [
        ("Intrusion détectée", "critical"), ("Plaque en liste noire détectée", "critical"),
        ("Caméra hors ligne", "warning"), ("Détection de fumée", "critical"),
        ("Mouvement après horaires", "warning"), ("Stockage à 85%", "warning"),
        ("Nouvelle détection véhicule", "info"),
    ]
    for _ in range(15):
        cam = random.choice(cam_docs)
        msg, sev = random.choice(alert_msgs)
        ts = datetime.now(timezone.utc) - timedelta(minutes=random.randint(0, 1440))
        alerts.append({
            "id": str(uuid.uuid4()), "type": "detection", "severity": sev, "message": msg,
            "camera_id": cam["id"], "camera_name": cam["name"], "site_id": cam["site_id"], "site_name": cam["site_name"],
            "acknowledged": random.random() > 0.6, "timestamp": ts.isoformat(),
        })
    await db.alerts.insert_many(alerts)
