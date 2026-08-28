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
    # v3.17 · `id` manquait ici alors que `db.cameras`/`db.tls_certificates`
    # plus bas l'ont bien. Sans conséquence tant que rien ne cherchait un
    # événement par son id — jusqu'à `GET /events/{id}` (visionneuse, image
    # complète à l'ouverture) : chaque appel faisait un scan complet de la
    # collection (42 336 documents, 8,5 s mesurés) faute d'index. Même
    # défaut sur `plates` et `recordings` ci-dessous, pour la même raison
    # (`GET /plates/{id}`, lookup vidéo par id de segment).
    await _safe_index(db.events, "id")
    await _safe_index(db.events, "timestamp")
    await _safe_index(db.events, "camera_id")
    await _safe_index(db.events, "type")
    await _safe_index(db.events, "kind")
    await _safe_index(db.events, [("camera_id", 1), ("timestamp", -1)])
    # v3.19 · Menu Événements par sous-filtre (Personnes/Camions/Bus/...) —
    # l'index simple sur `type` trouve les docs vite (quelques ms), mais le
    # tri par date qui suit ensuite se fait EN MÉMOIRE faute d'index adapté
    # (stage SORT, mesuré 3.8s sur les 4.4s total pour "Bus", pire pour
    # d'autres filtres — 105 910 événements en base). Ce composé sert le
    # filtre ET le tri en un seul passage d'index, sans étape SORT séparée.
    await _safe_index(db.events, [("type", 1), ("timestamp", -1)])

    # ── Plaques ANPR ──
    await _safe_index(db.plates, "id")
    await _safe_index(db.plates, "plate")
    await _safe_index(db.plates, "timestamp")
    await _safe_index(db.plates, "camera_id")
    await _safe_index(db.plates, "track_id", sparse=True)
    await _safe_index(db.plates, [("plate", 1), ("timestamp", -1)])

    # ── Enregistrements ──
    await _safe_index(db.recordings, "id")
    await _safe_index(db.recordings, "file_path")
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
    # v3.19 · Même cause que events (voir plus haut) : /alerts mesuré à
    # 5.6s (tous) / 2.8s (non acquittées) sur 9 377 alertes — filtre
    # `acknowledged` sans index adapté au tri par date qui suit. Ce composé
    # sert le filtre ET le tri (id, timestamp DESC) en un seul index.
    await _safe_index(db.alerts, [("acknowledged", 1), ("timestamp", -1)])
    await _safe_index(db.alerts, [("timestamp", -1)])

    # Traçabilité moteurs (P8+, demande CEO Feb 2026) — backfill léger pour que le
    # frontend puisse afficher "reconnu par fast-alpr" sur toutes les plaques.
    await db.plates.update_many({"engine": {"$exists": False}},
                                 {"$set": {"engine": "fast-alpr"}})
