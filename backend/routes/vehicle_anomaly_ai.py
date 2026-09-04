"""v3.44 · IA anomalies véhicule — cadrage explicite du 04/09 avec l'utilisateur.

Décisions actées avant tout code (voir échange) :
1) "Vrai apprentissage" = le moteur de règles existant (habitudes RÉELLES
   calculées par véhicule depuis l'historique, pas des seuils figés en dur)
   reste le signal ; Qwen (déjà intégré, même pattern que
   routes/vehicle_dedup.py::_ask_qwen_same_vehicle) transforme chaque
   anomalie brute en explication concrète et contextualisée, plutôt qu'un
   simple tag ("off_hours"). Pas un modèle ML entraîné — décision explicite,
   plus rapide à livrer, réutilise l'infra existante.
2) Périmètre v1 inclut les CORRÉLATIONS multi-véhicules/caméras (pas
   seulement par véhicule) — décision explicite de l'utilisateur, qui a
   choisi cette option plus large plutôt que la recommandation initiale
   (par véhicule seul).

Trois familles de signaux, toutes calculées depuis les vraies données
(`db.plates`), jamais de seuil arbitraire :
  - per_vehicle : réutilise _compute_anomaly (routes/vehicles.py) tel quel —
    habitudes RÉELLES de CE véhicule (arrivée/départ typiques, jours
    prédominants, historique nocturne).
  - convoy      : paires de plaques vues ensemble, même caméra, à quelques
    minutes d'écart, de façon RÉPÉTÉE (pas une coïncidence isolée).
  - wave        : nombre de véhicules DISTINCTS sur une caméra dans une
    fenêtre courte, largement au-dessus de ce que CETTE caméra voit
    d'habitude à ce moment (médiane historique, pas un chiffre en dur).

Tâche périodique (comme dedup_batch_loop/anpr_tuning_loop) + bouton manuel
+ interrupteur dédié (Administration → LLM, anomaly_ai_enabled).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from auth import require_permission, require_role, log_audit, allowed_sites
from database import db

logger = logging.getLogger("routes.vehicle_anomaly_ai")

vehicle_anomaly_ai_router = APIRouter(prefix="/api/vehicles/anomaly-ai", tags=["vehicle-anomaly-ai"])

_LOOKBACK_DAYS = 30
_BATCH_INTERVAL_HOURS = 6

# Convoi : deux plaques vues à quelques minutes d'écart sur la même caméra,
# de façon répétée — un seul croisement est une coïncidence, pas un motif.
_CONVOY_WINDOW_SEC = 180
_CONVOY_MIN_OCCURRENCES = 3

# Vague : nombre de véhicules distincts sur une caméra dans une fenêtre de
# 15 min, comparé à la médiane historique de CETTE caméra sur des fenêtres
# comparables (pas un seuil unique pour toutes les caméras — un rond-point
# et une impasse n'ont pas le même trafic normal).
_WAVE_SLOT_MIN = 15
_WAVE_MULTIPLIER = 3.0
_WAVE_MIN_COUNT = 3


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _iso_to_dt(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _load_recent_plates() -> list[dict]:
    """Fenêtre bornée (_LOOKBACK_DAYS) — mêmes champs minimaux que
    _find_variants (vehicle_dedup.py) pour rester léger sur une collection
    en croissance continue."""
    since = _iso(datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS))
    return await db.plates.find(
        {"timestamp": {"$gte": since}},
        {"_id": 0, "plate": 1, "camera_id": 1, "camera_name": 1, "timestamp": 1},
    ).sort([("camera_id", 1), ("timestamp", 1)]).to_list(50000)


async def _camera_site_map() -> dict[str, Optional[str]]:
    cams = await db.cameras.find({}, {"_id": 0, "id": 1, "site_id": 1}).to_list(2000)
    return {c["id"]: c.get("site_id") for c in cams}


# ═══════════════════════════════════════════════════════════════════
# Détection — convoi (paires répétées)
# ═══════════════════════════════════════════════════════════════════
def _detect_convoys(rows: list[dict]) -> list[dict]:
    """Même technique de scan que
    vehicle_dedup.py::_find_time_proximity_candidates (trié par caméra puis
    temps, fenêtre glissante, O(n) par caméra) — mais compte les
    OCCURRENCES DISTINCTES d'une paire (pas juste sa présence), et
    déduplique les lectures multiples d'un même croisement (plusieurs
    passages ANPR à quelques secondes d'écart pour le même événement réel)
    en un seul "occurrence" par tranche de _CONVOY_WINDOW_SEC."""
    pair_events: dict[tuple, list[float]] = defaultdict(list)
    for i, r1 in enumerate(rows):
        t1 = _iso_to_dt(r1.get("timestamp"))
        if t1 is None:
            continue
        for r2 in rows[i + 1:]:
            if r2["camera_id"] != r1["camera_id"]:
                break
            t2 = _iso_to_dt(r2.get("timestamp"))
            if t2 is None or (t2 - t1).total_seconds() > _CONVOY_WINDOW_SEC:
                break
            if r1["plate"] == r2["plate"]:
                continue
            key = (r1["camera_id"], tuple(sorted((r1["plate"], r2["plate"]))))
            pair_events[key].append(t1.timestamp())

    convoys = []
    for (cam_id, plates), timestamps in pair_events.items():
        timestamps.sort()
        occurrences = 1
        last = timestamps[0]
        for ts in timestamps[1:]:
            if ts - last > _CONVOY_WINDOW_SEC:
                occurrences += 1
                last = ts
        if occurrences >= _CONVOY_MIN_OCCURRENCES:
            convoys.append({
                "camera_id": cam_id,
                "plates": list(plates),
                "occurrences": occurrences,
                "first_seen": _iso(datetime.fromtimestamp(timestamps[0], tz=timezone.utc)),
                "last_seen": _iso(datetime.fromtimestamp(timestamps[-1], tz=timezone.utc)),
            })
    return convoys


# ═══════════════════════════════════════════════════════════════════
# Détection — vague (véhicules distincts inhabituels sur une fenêtre)
# ═══════════════════════════════════════════════════════════════════
def _detect_waves(rows: list[dict]) -> list[dict]:
    by_camera: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_camera[r["camera_id"]].append(r)

    waves = []
    for cam_id, cam_rows in by_camera.items():
        slots: dict[datetime, set] = defaultdict(set)
        for r in cam_rows:
            dt = _iso_to_dt(r.get("timestamp"))
            if dt is None:
                continue
            minute_bucket = (dt.minute // _WAVE_SLOT_MIN) * _WAVE_SLOT_MIN
            slot_start = dt.replace(minute=minute_bucket, second=0, microsecond=0)
            slots[slot_start].add(r["plate"])

        if len(slots) < 4:
            continue  # historique trop court pour une médiane fiable sur cette caméra
        counts = sorted(len(v) for v in slots.values())
        median = counts[len(counts) // 2]

        # N'évalue que le DERNIER créneau complet (le plus récent de la
        # fenêtre de lookback) — les créneaux plus anciens ont déjà été vus
        # lors d'un run précédent, la dédup à l'écriture (upsert par clé
        # caméra+créneau) évite de toute façon les doublons si on les
        # réévaluait.
        latest_slot = max(slots.keys())
        latest_count = len(slots[latest_slot])
        threshold = max(_WAVE_MIN_COUNT, median * _WAVE_MULTIPLIER)
        if latest_count >= threshold and latest_count > median:
            waves.append({
                "camera_id": cam_id,
                "camera_name": cam_rows[0].get("camera_name"),
                "plates": sorted(slots[latest_slot]),
                "slot_start": _iso(latest_slot),
                "slot_minutes": _WAVE_SLOT_MIN,
                "distinct_count": latest_count,
                "median_baseline": median,
            })
    return waves


# ═══════════════════════════════════════════════════════════════════
# Narration Qwen — même pattern que vehicle_dedup.py::_ask_qwen_same_vehicle
# ═══════════════════════════════════════════════════════════════════
async def _ask_qwen_narrate(kind: str, facts: dict) -> dict:
    from routes.llm_settings import get_active_llm_config
    cfg = await get_active_llm_config()
    if not cfg:
        raise HTTPException(status_code=503, detail={"code": "ANOMALY_AI_LLM_NOT_CONFIGURED",
                                                        "message": "LLM non configuré (Administration → LLM)."})
    import httpx
    schema = {
        "type": "object",
        "properties": {
            "severity": {"type": "string", "enum": ["info", "warning", "high"]},
            "message": {"type": "string"},
        },
        "required": ["severity", "message"],
    }
    system = (
        "Tu es un analyste vidéosurveillance. Réponds UNIQUEMENT avec un objet "
        "JSON valide respectant EXACTEMENT ce schéma : "
        '{"severity": "info"|"warning"|"high", "message": texte court en français}. '
        "Le message doit être CONCRET et FACTUEL (citer les chiffres/heures/plaques "
        "fournis), jamais une reformulation générique du type \"comportement inhabituel "
        "détecté\". Aucun texte hors JSON."
    )
    prompts = {
        "per_vehicle": (
            f"Véhicule {facts['plate']} — habitudes observées sur son historique réel : "
            f"arrivée typique {facts.get('typical_arrival') or 'inconnue'}, départ typique "
            f"{facts.get('typical_departure') or 'inconnu'}, jours habituels "
            f"{', '.join(facts.get('typical_days') or []) or 'aucun motif clair'}. "
            f"Dernier passage : {facts['last_seen']} sur la caméra {facts.get('camera_name') or facts.get('camera_id')}. "
            f"Anomalies détectées par les règles : {', '.join(facts['anomalies'])}. "
            "Explique en une phrase concrète pourquoi ce passage sort de l'ordinaire pour "
            "CE véhicule précis, en citant les horaires/jours réels."
        ),
        "convoy": (
            f"Les plaques {facts['plates'][0]} et {facts['plates'][1]} ont été vues ensemble "
            f"(à moins de {_CONVOY_WINDOW_SEC}s d'écart) sur la caméra "
            f"{facts.get('camera_name') or facts.get('camera_id')} à {facts['occurrences']} reprises "
            f"distinctes entre le {facts['first_seen']} et le {facts['last_seen']}. "
            "Explique en une phrase concrète ce motif de déplacement répété conjoint, "
            "en citant le nombre de fois et la caméra."
        ),
        "wave": (
            f"La caméra {facts.get('camera_name') or facts.get('camera_id')} a vu "
            f"{facts['distinct_count']} véhicules DIFFÉRENTS en {facts['slot_minutes']} minutes "
            f"à partir de {facts['slot_start']}, alors que cette même caméra n'en voit "
            f"habituellement que {facts['median_baseline']} sur une fenêtre comparable "
            f"(médiane calculée sur son propre historique). Plaques concernées : "
            f"{', '.join(facts['plates'])}. Explique en une phrase concrète pourquoi ce "
            "pic de trafic sort de l'ordinaire pour CETTE caméra précise, en citant les chiffres."
        ),
    }
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompts[kind]},
        ],
        "think": False,
        "format": schema,
        "stream": False,
    }
    url = f"{cfg['base_url']}/api/chat/completions"
    async with httpx.AsyncClient(timeout=25.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()
    raw = (body["choices"][0]["message"]["content"] or "").strip()
    if "<think>" in raw:
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    parsed = json.loads(raw)
    return {"severity": parsed.get("severity", "info"), "message": parsed.get("message", "")}


# ═══════════════════════════════════════════════════════════════════
# Orchestration — un run complet, persistance dédupliquée par clé stable
# ═══════════════════════════════════════════════════════════════════
async def _run_per_vehicle(site_map: dict) -> int:
    """Réutilise _compute_anomaly (routes/vehicles.py) — même moteur que le
    bouton manuel existant sur la fiche véhicule, appliqué ici en masse
    sur les plaques ayant assez d'historique. Ne narre QUE les anomalies
    non déjà narrées pour ce last_seen précis (clé stable plate+last_seen)."""
    from routes.vehicles import _compute_anomaly
    counts = {}
    async for row in db.plates.aggregate([
        {"$match": {"timestamp": {"$gte": _iso(datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS))}}},
        {"$group": {"_id": "$plate", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": 5}}},
    ]):
        counts[row["_id"]] = row["n"]

    created = 0
    for plate in counts:
        try:
            report = await _compute_anomaly(plate, user={"role": "admin"}, exact=True)
        except Exception:
            continue
        if not report.get("anomalies") or report["severity"] == "info":
            continue
        key = f"per_vehicle:{plate}:{report.get('last_seen')}"
        existing = await db.vehicle_anomaly_reports.find_one({"dedup_key": key}, {"_id": 0, "id": 1})
        if existing:
            continue
        cam_doc = await db.plates.find_one({"plate": plate}, {"_id": 0, "camera_id": 1, "camera_name": 1},
                                            sort=[("timestamp", -1)])
        facts = {**report, "camera_id": (cam_doc or {}).get("camera_id"),
                 "camera_name": (cam_doc or {}).get("camera_name")}
        try:
            verdict = await _ask_qwen_narrate("per_vehicle", facts)
        except Exception:
            logger.exception("anomaly_ai: échec narration per_vehicle %s", plate)
            continue
        await db.vehicle_anomaly_reports.insert_one({
            "id": str(uuid.uuid4()), "kind": "per_vehicle", "dedup_key": key,
            "plates": [plate], "camera_ids": [facts["camera_id"]] if facts["camera_id"] else [],
            "site_id": site_map.get(facts["camera_id"]),
            "facts": {k: v for k, v in facts.items() if k != "habits"},
            "severity": verdict["severity"], "message": verdict["message"],
            "created_at": _iso(datetime.now(timezone.utc)),
            "acknowledged": False,
        })
        created += 1
    return created


async def _run_convoys(rows: list[dict], site_map: dict) -> int:
    created = 0
    for c in _detect_convoys(rows):
        key = f"convoy:{c['camera_id']}:{c['plates'][0]}:{c['plates'][1]}"
        existing = await db.vehicle_anomaly_reports.find_one({"dedup_key": key}, {"_id": 0, "facts.occurrences": 1})
        if existing and (existing.get("facts") or {}).get("occurrences", 0) >= c["occurrences"]:
            continue  # déjà signalé avec un compte égal ou supérieur
        cam = await db.cameras.find_one({"id": c["camera_id"]}, {"_id": 0, "name": 1})
        facts = {**c, "camera_name": (cam or {}).get("name")}
        try:
            verdict = await _ask_qwen_narrate("convoy", facts)
        except Exception:
            logger.exception("anomaly_ai: échec narration convoy %s", c["plates"])
            continue
        await db.vehicle_anomaly_reports.update_one(
            {"dedup_key": key},
            {"$set": {
                "id": (existing or {}).get("id") or str(uuid.uuid4()), "kind": "convoy", "dedup_key": key,
                "plates": c["plates"], "camera_ids": [c["camera_id"]],
                "site_id": site_map.get(c["camera_id"]),
                "facts": facts, "severity": verdict["severity"], "message": verdict["message"],
                "created_at": _iso(datetime.now(timezone.utc)), "acknowledged": False,
            }},
            upsert=True,
        )
        created += 1
    return created


async def _run_waves(rows: list[dict], site_map: dict) -> int:
    created = 0
    for w in _detect_waves(rows):
        key = f"wave:{w['camera_id']}:{w['slot_start']}"
        existing = await db.vehicle_anomaly_reports.find_one({"dedup_key": key}, {"_id": 0, "id": 1})
        if existing:
            continue
        try:
            verdict = await _ask_qwen_narrate("wave", w)
        except Exception:
            logger.exception("anomaly_ai: échec narration wave %s", w["camera_id"])
            continue
        await db.vehicle_anomaly_reports.insert_one({
            "id": str(uuid.uuid4()), "kind": "wave", "dedup_key": key,
            "plates": w["plates"], "camera_ids": [w["camera_id"]],
            "site_id": site_map.get(w["camera_id"]),
            "facts": w, "severity": verdict["severity"], "message": verdict["message"],
            "created_at": _iso(datetime.now(timezone.utc)),
            "acknowledged": False,
        })
        created += 1
    return created


async def _run_anomaly_ai_batch() -> dict:
    site_map = await _camera_site_map()
    rows = await _load_recent_plates()
    n_conv = await _run_convoys(rows, site_map)
    n_wave = await _run_waves(rows, site_map)
    n_veh = await _run_per_vehicle(site_map)
    return {"convoys": n_conv, "waves": n_wave, "per_vehicle": n_veh}


async def anomaly_ai_batch_loop() -> None:
    """Même garde-fou anti-jamais-exécuté que dedup_batch_loop/anpr_tuning_loop
    (v3.28) : court délai initial, puis 1re passe réelle, ensuite l'intervalle
    normal — un conteneur qui redémarre plus souvent que _BATCH_INTERVAL_HOURS
    ne doit jamais rester bloqué à "jamais exécuté"."""
    from routes.llm_settings import is_feature_enabled
    await asyncio.sleep(180)
    while True:
        if await is_feature_enabled("anomaly_ai_enabled"):
            try:
                counts = await _run_anomaly_ai_batch()
                total = sum(counts.values())
                if total:
                    logger.info("anomaly_ai: %s rapport(s) généré(s) (%s)", total, counts)
            except Exception:
                logger.exception("anomaly_ai: erreur boucle anomaly_ai_batch_loop")
        await asyncio.sleep(_BATCH_INTERVAL_HOURS * 3600)


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════
@vehicle_anomaly_ai_router.post("/run")
async def run_now(user: dict = Depends(require_role("admin"))):
    from routes.llm_settings import is_feature_enabled
    if not await is_feature_enabled("anomaly_ai_enabled"):
        raise HTTPException(status_code=400, detail={
            "code": "ANOMALY_AI_DISABLED",
            "message": "IA anomalies désactivée — Administration → LLM (MG-IA).",
        })

    async def _run_bg():
        try:
            counts = await _run_anomaly_ai_batch()
            logger.info("anomaly_ai: recherche manuelle terminée, %s", counts)
        except Exception:
            logger.exception("anomaly_ai: erreur pendant la recherche manuelle")
    asyncio.create_task(_run_bg())
    await log_audit(user, "anomaly_ai_run_started", "lancée en arrière-plan")
    return {"started": True}


@vehicle_anomaly_ai_router.get("")
async def list_reports(
    status: str = "pending",
    kind: Optional[str] = None,
    limit: int = 100,
    user: dict = Depends(require_permission("read_plates")),
):
    q: dict = {} if status == "all" else {"acknowledged": status == "acknowledged"}
    if kind:
        q["kind"] = kind
    sites = allowed_sites(user)
    if sites is not None:
        q["site_id"] = {"$in": sites}
    docs = await db.vehicle_anomaly_reports.find(q, {"_id": 0}) \
        .sort("created_at", -1).to_list(limit)
    return {"count": len(docs), "items": docs}


@vehicle_anomaly_ai_router.post("/{report_id}/acknowledge")
async def acknowledge_report(report_id: str, user: dict = Depends(require_permission("read_plates"))):
    now = _iso(datetime.now(timezone.utc))
    res = await db.vehicle_anomaly_reports.update_one(
        {"id": report_id},
        {"$set": {"acknowledged": True, "acknowledged_by": user.get("email"), "acknowledged_at": now}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Rapport introuvable")
    return {"ok": True}
