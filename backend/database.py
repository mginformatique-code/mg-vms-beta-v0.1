import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import OperationFailure

log = logging.getLogger("mg-vms.database")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]


async def _safe_index(collection, keys, **opts):
    """Crée un index idempotent et tolère les conflits d'options (TTL différents,
    index déjà existant avec un autre nom). N'échoue jamais le bootstrap : logge.
    """
    try:
        await collection.create_index(keys, **opts)
    except OperationFailure as e:
        # 85=IndexOptionsConflict, 86=IndexKeySpecsConflict
        code = getattr(e, "code", None)
        if code in (85, 86):
            log.info("index %s.%s skipped (conflict, existing keeps precedence): %s",
                     collection.name, keys, str(e)[:120])
        else:
            log.warning("index %s.%s failed (code=%s): %s",
                        collection.name, keys, code, str(e)[:120])
    except Exception as e:  # pragma: no cover
        log.warning("index %s.%s failed: %s", collection.name, keys, str(e)[:120])


async def create_indexes():
    """v0.8-rc3 · Bootstrap MongoDB indexes complet.

    Applique automatiquement les recommandations issues de `stress/mongo_audit.py`
    (missing_index + missing_ttl) pour toutes les collections critiques.
    Toutes les opérations sont idempotentes et tolérantes aux conflits d'options
    (via `_safe_index`) — un TTL existant est préservé, un index déjà créé skippé.
    """
    # ── Auth / users / sessions ──
    await _safe_index(db.users, "email", unique=True)
    await _safe_index(db.sessions, "user_id")
    await _safe_index(db.sessions, "created_at")
    await _safe_index(db.login_attempts, "identifier", unique=True)
    await _safe_index(db.password_reset_tokens, "token", unique=True)

    # ── Caméras ──
    await _safe_index(db.cameras, "id")
    await _safe_index(db.cameras, "site_id")
    await _safe_index(db.cameras, "status")

    # ── Événements IA (recherche par temps/caméra/type) ──
    await _safe_index(db.events, "timestamp")
    await _safe_index(db.events, "camera_id")
    await _safe_index(db.events, "type")
    await _safe_index(db.events, "kind")
    await _safe_index(db.events, [("camera_id", 1), ("timestamp", -1)])

    # ── Plaques ANPR ──
    await _safe_index(db.plates, "plate")
    await _safe_index(db.plates, "timestamp")
    await _safe_index(db.plates, "camera_id")
    await _safe_index(db.plates, "track_id", sparse=True)
    await _safe_index(db.plates, [("plate", 1), ("timestamp", -1)])

    # ── Enregistrements ──
    await _safe_index(db.recordings, "camera_id")
    await _safe_index(db.recordings, "start")
    await _safe_index(db.recordings, "start_ts")
    await _safe_index(db.recordings, "end_ts")
    await _safe_index(db.recordings, [("camera_id", 1), ("start_ts", -1)])

    # ── Équipements ──
    await _safe_index(db.equipment, "site_id")
    await _safe_index(db.equipment, "parent_id")

    # ── Audit logs ──
    await _safe_index(db.audit_logs, "timestamp")
    await _safe_index(db.audit_logs, "actor")

    # ── Journal lifecycle streams ──
    await _safe_index(db.stream_lifecycle_journal, [("camera_id", 1), ("ts", -1)])
    await _safe_index(db.stream_lifecycle_journal, "ts")

    # ── TLS certificats (v0.7.f) ──
    await _safe_index(db.tls_certificates, "id")
    await _safe_index(db.tls_certificates, "active")

    # ── Alertes ──
    await _safe_index(db.alerts, "timestamp")
    await _safe_index(db.alerts, "camera_id")

    # Traçabilité moteurs (P8+, demande CEO Feb 2026) — backfill léger pour que le
    # frontend puisse afficher "reconnu par fast-alpr" sur toutes les plaques.
    await db.plates.update_many({"engine": {"$exists": False}},
                                 {"$set": {"engine": "fast-alpr"}})
