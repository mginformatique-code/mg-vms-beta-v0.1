"""MG-VMS — Journal de cycle de vie des streams caméra (in-memory, circulaire).

Trace précisément TOUTES les transitions d'un flux caméra pour diagnostiquer
les cycles de déconnexion/reconnexion :

  [Camera 3] stream_lifecycle: created reason="POST /api/cameras" caller="admin"
  [Camera 3] stream_lifecycle: consumer_attached reason="live.mjpeg?hd=1" caller="tech"
  [Camera 3] stream_lifecycle: consumer_detached reason="client disconnect" caller="tech"
  [Camera 3] stream_lifecycle: status_probe_ok reason="/api/streams contains name"
  [Camera 3] stream_lifecycle: status_offline_confirmed reason="3 consecutive probe failures"

L'idée : rien ne DOIT jamais réenregistrer un stream automatiquement. Si un cycle
de reconnexion apparaît, ce journal permet de trouver le composant fautif.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("lifecycle")

# Journal par camera_id : max 100 entrées récentes par caméra (deque circulaire).
_JOURNAL_MAX_PER_CAMERA = 100
_journal: dict[str, deque] = defaultdict(lambda: deque(maxlen=_JOURNAL_MAX_PER_CAMERA))
_journal_lock = asyncio.Lock()


def record(camera_id: str, action: str, reason: str = "",
           caller: str = "", extra: Optional[dict] = None) -> None:
    """Enregistre une transition dans le journal + log ligne unique format standard.

    Actions typiques :
      - created                 : register_camera_stream a créé/PUT le stream go2rtc
      - registered_idempotent   : register_camera_stream a été appelé mais rien changé
      - destroyed               : unregister_camera_stream a fait DELETE
      - consumer_attached       : un client HTTP s'est connecté au proxy live.mjpeg
      - consumer_detached       : le client HTTP est parti (normal ou upstream mort)
      - status_probe_ok         : probe périodique = online
      - status_probe_fail       : probe périodique = échec (transitoire, pas encore confirmé)
      - status_offline_confirmed: N échecs consécutifs → status flip online→offline
      - status_online_restored  : probe OK après série d'échecs → status flip offline→online
      - webrtc_negotiation      : SDP offer/answer proxy
      - variants_ensured        : _ensure_variants a créé HD/SD dans go2rtc
      - variants_cache_hit      : _ensure_variants_cached a court-circuité (TTL)
      - stream_absent_from_go2rtc: probe /api/streams ne trouve pas le stream (situation anormale, NON auto-réparée)

    Certaines actions "notables" sont AUSSI persistées en base MongoDB pour survivre
    au redémarrage du backend (voir `_NOTABLE_ACTIONS`).
    """
    ts = datetime.now(timezone.utc).isoformat()
    entry = {
        "ts": ts,
        "action": action,
        "reason": reason,
        "caller": caller,
    }
    if extra:
        entry["extra"] = extra
    _journal[camera_id].append(entry)
    # Log ligne unique format standard (parseable via grep) :
    logger.info(
        "[Camera %s] stream_lifecycle: %s reason=%r caller=%r",
        camera_id, action, reason, caller,
    )
    # Persistance en MongoDB pour les actions notables (asynchrone, non bloquant)
    if action in _NOTABLE_ACTIONS:
        try:
            asyncio.get_event_loop().create_task(_persist(camera_id, entry))
        except RuntimeError:
            # pas d'event loop actif (import time, tests) — skip persistance
            pass


# Actions considérées "notables" et donc persistées en base pour l'historique
_NOTABLE_ACTIONS = {
    "created", "destroyed", "register_failed",
    "stream_absent_from_go2rtc",
    "status_offline_confirmed", "status_online_restored",
    "webrtc_failed",
}


async def _persist(camera_id: str, entry: dict) -> None:
    """Persiste UNE entrée notable en collection `stream_lifecycle_journal`.
    Collection cappée à 20 000 documents (auto-rotation FIFO) via un TTL manuel.
    Non bloquant : les erreurs sont silencieusement ignorées."""
    try:
        from database import db
        await db.stream_lifecycle_journal.insert_one({**entry, "camera_id": camera_id})
        # Rotation légère : purge les vieilles entrées si la collection dépasse 20k docs
        # (opération peu coûteuse car les indexes ts sont maintenus)
        count = await db.stream_lifecycle_journal.estimated_document_count()
        if count > 20000:
            # Supprime les 1000 plus vieilles pour rester sous le seuil
            old = await db.stream_lifecycle_journal.find({}, {"_id": 1}).sort("ts", 1).limit(1000).to_list(1000)
            if old:
                await db.stream_lifecycle_journal.delete_many({"_id": {"$in": [d["_id"] for d in old]}})
    except Exception:
        pass


async def hydrate_journal_from_db() -> None:
    """Au démarrage du backend, recharge les 100 dernières entrées notables de chaque
    caméra depuis MongoDB dans la deque mémoire. Permet à la page Diagnostics de
    montrer les incidents PRÉ-redémarrage plutôt qu'une page vide."""
    try:
        from database import db
        # Les 2000 entrées les plus récentes toutes caméras confondues, triées par ts asc
        docs = await db.stream_lifecycle_journal.find({}, {"_id": 0}).sort("ts", -1).limit(2000).to_list(2000)
        docs.reverse()   # chronologique asc pour préserver l'ordre dans deque
        for d in docs:
            cam_id = d.pop("camera_id", None)
            if cam_id:
                _journal[cam_id].append(d)
        logger.info("lifecycle: %d entrées notables re-hydratées depuis MongoDB", len(docs))
    except Exception as e:
        logger.warning("lifecycle: échec re-hydratation MongoDB (%s) — journal démarré vide", e)


def get_journal(camera_id: str, limit: int = 100) -> list[dict]:
    """Retourne les N dernières transitions pour une caméra (ordre chronologique)."""
    q = _journal.get(camera_id, deque())
    entries = list(q)
    if limit < len(entries):
        entries = entries[-limit:]
    return entries


def get_all_journal_summary() -> dict:
    """Résumé pour la page Diagnostics : nb entrées par caméra + dernière action."""
    out = {}
    for cam_id, q in _journal.items():
        if not q:
            continue
        last = q[-1]
        out[cam_id] = {
            "count": len(q),
            "last_ts": last["ts"],
            "last_action": last["action"],
            "last_reason": last["reason"],
        }
    return out


def clear(camera_id: Optional[str] = None) -> None:
    """Vide le journal (une caméra ou tout)."""
    if camera_id is None:
        _journal.clear()
    else:
        _journal.pop(camera_id, None)


# ═══════════════════════════════════════════════════════════════════════════
# Compteurs d'échecs consécutifs (pour hystérésis online/offline)
# ═══════════════════════════════════════════════════════════════════════════
# Un stream n'est marqué "offline" qu'après N échecs de probe consécutifs
# (évite les faux négatifs sur blip HTTP transitoire du côté go2rtc).
CONSECUTIVE_FAILURES_TO_OFFLINE = 3   # 3 échecs × 30 s tick = 90 s de grâce
_failure_counters: dict[str, int] = defaultdict(int)


def record_probe_result(camera_id: str, ok: bool, reason: str = "") -> tuple[bool, int]:
    """Enregistre un résultat de probe et retourne (should_flip_offline, counter).

    - ok=True  → reset counter, retourne (False, 0)
    - ok=False → incrément counter, retourne (True, N) si N >= seuil, sinon (False, N)

    Le caller décide de flipper le status en base seulement si should_flip_offline=True.
    """
    if ok:
        prev = _failure_counters.pop(camera_id, 0)
        return (False, 0) if prev == 0 else (False, 0)
    _failure_counters[camera_id] += 1
    n = _failure_counters[camera_id]
    return (n >= CONSECUTIVE_FAILURES_TO_OFFLINE, n)


def reset_probe_counter(camera_id: str) -> int:
    """Reset explicite (ex: après une action réparatrice manuelle)."""
    return _failure_counters.pop(camera_id, 0)


def get_probe_counter(camera_id: str) -> int:
    return _failure_counters.get(camera_id, 0)
