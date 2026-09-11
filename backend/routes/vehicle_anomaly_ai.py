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
from pydantic import BaseModel

from auth import require_permission, require_role, log_audit, allowed_sites
from database import db
from realtime import broadcast_alert

logger = logging.getLogger("routes.vehicle_anomaly_ai")

vehicle_anomaly_ai_router = APIRouter(prefix="/api/vehicles/anomaly-ai", tags=["vehicle-anomaly-ai"])

_LOOKBACK_DAYS = 30
_BATCH_INTERVAL_HOURS = 6

# Convoi : deux plaques vues à quelques minutes d'écart sur la même caméra,
# de façon répétée — un seul croisement est une coïncidence, pas un motif.
# v3.44.1 · Vérifié sur données réelles : la 1ère version (fenêtre 180s,
# 3 occurrences) rapportait 4482 "convois" — quasi tous des paires de
# plaques textuellement PRESQUE IDENTIQUES (ex. "CG633SE"/"CG6335E",
# "F43384"/"F45334") : le même véhicule mal lu deux fois par l'ANPR à
# quelques secondes d'écart, pas deux véhicules distincts. Fenêtre
# resserrée à 30s (déplacement physique conjoint, pas une simple
# corrélation d'horaires de trajet) + seuil relevé à 5 occurrences +
# exclusion des paires à distance d'édition faible (même filtre que
# vehicle_dedup.py, la variante OCR d'UN véhicule n'est jamais un convoi).
_CONVOY_WINDOW_SEC = 30
_CONVOY_MIN_OCCURRENCES = 5
_CONVOY_OCR_EXCLUDE_DISTANCE = 3
_CONVOY_MAX_PLATE_FREQUENCY = 100

# Vague : nombre de véhicules distincts sur une caméra dans une fenêtre de
# 15 min, comparé à la médiane historique de CETTE caméra sur des fenêtres
# comparables (pas un seuil unique pour toutes les caméras — un rond-point
# et une impasse n'ont pas le même trafic normal).
_WAVE_SLOT_MIN = 15
_WAVE_MULTIPLIER = 3.0
_WAVE_MIN_COUNT = 3

# Trajet inter-site minimum plausible — signal PUREMENT logique (aucune
# vision requise, coût nul), voir _detect_cross_site_impossible. Pas de
# coordonnées GPS configurées à ce jour (vérifié : lat/lng NULL sur toutes
# les caméras) — une distance haversine précise nécessiterait de saisir
# les coordonnées de chaque site, non fait aujourd'hui. 20 min reste une
# valeur plancher très conservatrice : même deux sites voisins dans la
# même ville prennent plus longtemps porte à porte.
_CROSS_SITE_MIN_MINUTES = 20


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
        {"_id": 0, "plate": 1, "camera_id": 1, "camera_name": 1, "timestamp": 1, "site_id": 1},
    ).sort([("camera_id", 1), ("timestamp", 1)]).to_list(50000)


async def _camera_site_map() -> dict[str, Optional[str]]:
    cams = await db.cameras.find({}, {"_id": 0, "id": 1, "site_id": 1}).to_list(2000)
    return {c["id"]: c.get("site_id") for c in cams}


async def _site_name_map() -> dict[str, str]:
    sites = await db.sites.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)
    return {s["id"]: s.get("name") or s["id"] for s in sites}


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
    en un seul "occurrence" par tranche de _CONVOY_WINDOW_SEC.

    v3.44.1 · 2e correctif vérifié sur données réelles : une plaque à très
    forte fréquence de lecture (ex. AA2307JA, 667 lectures sur la fenêtre —
    plaque de test/démo utilisée pendant les vérifications de cette même
    session) co-occurrait "par hasard" avec des dizaines de plaques
    différentes en 30s, juste par densité de trafic sur sa caméra — pas un
    vrai déplacement conjoint. Exclut les plaques dont le total de lectures
    dépasse _CONVOY_MAX_PLATE_FREQUENCY : au-delà, la co-occurrence n'est
    plus un signal fiable de "voyagent ensemble" avec une simple compte
    d'occurrences (nécessiterait de normaliser par le taux de base, hors
    scope de ce 1er passage)."""
    from routes.vehicles import _levenshtein
    plate_freq: dict[str, int] = defaultdict(int)
    for r in rows:
        plate_freq[r["plate"]] += 1
    pair_events: dict[tuple, list[float]] = defaultdict(list)
    for i, r1 in enumerate(rows):
        if plate_freq[r1["plate"]] > _CONVOY_MAX_PLATE_FREQUENCY:
            continue
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
            if plate_freq[r2["plate"]] > _CONVOY_MAX_PLATE_FREQUENCY:
                continue
            # v3.44.1 · Exclut les paires textuellement quasi identiques —
            # presque toujours LE MÊME véhicule mal lu deux fois par
            # l'ANPR à quelques secondes d'écart, pas deux véhicules
            # distincts voyageant ensemble (voir commentaire des constantes).
            if abs(len(r1["plate"]) - len(r2["plate"])) <= _CONVOY_OCR_EXCLUDE_DISTANCE and \
                    _levenshtein(r1["plate"], r2["plate"]) <= _CONVOY_OCR_EXCLUDE_DISTANCE:
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
    # v3.44.1 · Un dict littéral {"kind": f"...{facts[...]}"} évalue TOUS les
    # f-strings immédiatement, y compris ceux des `kind` non sélectionnés —
    # crash garanti sur une clé absente d'un autre kind (ex. `facts['plate']`
    # du prompt per_vehicle évalué même en appelant avec kind="convoy").
    # if/elif : un seul prompt construit, celui réellement demandé.
    if kind == "per_vehicle":
        prompt = (
            f"Véhicule {facts['plate']} — habitudes observées sur son historique réel : "
            f"arrivée typique {facts.get('typical_arrival') or 'inconnue'}, départ typique "
            f"{facts.get('typical_departure') or 'inconnu'}, jours habituels "
            f"{', '.join(facts.get('typical_days') or []) or 'aucun motif clair'}. "
            f"Dernier passage : {facts['last_seen']} sur la caméra {facts.get('camera_name') or facts.get('camera_id')}. "
            f"Anomalies détectées par les règles : {', '.join(facts['anomalies'])}. "
            "Explique en une phrase concrète pourquoi ce passage sort de l'ordinaire pour "
            "CE véhicule précis, en citant les horaires/jours réels."
        )
    elif kind == "convoy":
        prompt = (
            f"Les plaques {facts['plates'][0]} et {facts['plates'][1]} ont été vues ensemble "
            f"(à moins de {_CONVOY_WINDOW_SEC}s d'écart) sur la caméra "
            f"{facts.get('camera_name') or facts.get('camera_id')} à {facts['occurrences']} reprises "
            f"distinctes entre le {facts['first_seen']} et le {facts['last_seen']}. "
            "Explique en une phrase concrète ce motif de déplacement répété conjoint, "
            "en citant le nombre de fois et la caméra."
        )
    elif kind == "wave":
        prompt = (
            f"La caméra {facts.get('camera_name') or facts.get('camera_id')} a vu "
            f"{facts['distinct_count']} véhicules DIFFÉRENTS en {facts['slot_minutes']} minutes "
            f"à partir de {facts['slot_start']}, alors que cette même caméra n'en voit "
            f"habituellement que {facts['median_baseline']} sur une fenêtre comparable "
            f"(médiane calculée sur son propre historique). Plaques concernées : "
            f"{', '.join(facts['plates'])}. Explique en une phrase concrète pourquoi ce "
            "pic de trafic sort de l'ordinaire pour CETTE caméra précise, en citant les chiffres."
        )
    elif kind == "plate_confusion":
        prompt = (
            f"La plaque {facts['plate']} est associée à {facts['sample_count']} lectures "
            f"vérifiées par un modèle de vision (pas le simple OCR), mais ces lectures montrent "
            f"{len(facts['makes'])} marques de véhicule RÉELLEMENT différentes : "
            f"{', '.join(facts['makes'])}. Une même immatriculation ne peut pas porter plusieurs "
            "marques réelles — c'est le signe d'une confusion de lecture ANPR entre plusieurs "
            "véhicules distincts, probablement lue depuis des plaques dégradées/ambiguës qui "
            "convergent vers ce même texte. Explique ce constat en une phrase concrète, en "
            "citant les marques trouvées."
        )
    elif kind == "cross_site_impossible":
        prompt = (
            f"La plaque {facts['plate']} a été lue sur le site \"{facts['site_a_name']}\" "
            f"à {facts['time_a']}, puis sur le site \"{facts['site_b_name']}\" à "
            f"{facts['time_b']} — seulement {facts['gap_minutes']} minutes plus tard. "
            "Ce sont deux sites clients géographiquement distincts (adresses différentes) : "
            "un trajet aussi court entre les deux est physiquement implausible. Explique ce "
            "constat en une phrase concrète, en citant les 2 sites et l'écart de temps réel."
        )
    elif kind == "long_parking":
        vehicle_desc = " ".join(v for v in [facts.get("vehicle_make"), facts.get("vehicle_color")] if v)
        prompt = (
            f"Le véhicule {facts['plate']}"
            + (f" ({vehicle_desc})" if vehicle_desc else "")
            + f" est stationné sur la caméra {facts.get('camera_name') or '?'}"
            + (f" ({facts['site_name']})" if facts.get("site_name") else "")
            + f" depuis {facts['arrived_at']}, soit {int(facts['duration_seconds'] // 60)} minutes sans "
            "interruption détectée. Explique ce constat en une phrase concrète, en citant la durée réelle "
            "et le lieu — reste factuel, ne suppose jamais une infraction ou une intention sans preuve."
        )
    else:
        raise ValueError(f"kind inconnu: {kind}")
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "think": False,
        "format": schema,
        "stream": False,
    }
    url = f"{cfg['base_url']}/api/chat/completions"
    from llm_call_log import log_llm_call
    import time
    _t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
    except Exception as e:
        await log_llm_call(source=f"anomaly_ai:{kind}", url=url, model=payload.get("model"), request_payload=payload,
                            status_code=getattr(getattr(e, "response", None), "status_code", None),
                            error=f"{type(e).__name__}: {e}", latency_ms=int((time.monotonic() - _t0) * 1000))
        raise
    await log_llm_call(source=f"anomaly_ai:{kind}", url=url, model=payload.get("model"), request_payload=payload,
                        status_code=resp.status_code, response_body=body,
                        latency_ms=int((time.monotonic() - _t0) * 1000))
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
# v3.71 · Jonction Alertes <-> Anomalies IA — jusqu'ici deux systemes
# totalement etanches (menu unifie en 2 onglets seulement, voir
# AiAlertsCenter.jsx, mais db.alerts et db.vehicle_anomaly_reports ne se
# parlaient jamais) : une anomalie vehicule detectee ici n'apparaissait
# JAMAIS dans le fil d'Alertes principal (pas de badge, pas de push
# temps reel, pas de notification) - il fallait penser a aller consulter
# l'onglet Anomalies manuellement. Chaque nouveau rapport publie
# desormais AUSSI une entree db.alerts (meme mecanisme que les autres
# sources d'alertes : ANPR blacklist, reseau, scenarios IA), avec un
# type dedie "ai_anomaly" et une reference vers le rapport d'origine
# pour naviguer vers le detail complet.
_ANOMALY_SEVERITY_TO_ALERT = {"info": "info", "warning": "warning", "high": "critical"}


async def _publish_anomaly_alert(report: dict) -> None:
    cam_id = (report.get("camera_ids") or [None])[0]
    cam_name = "—"
    if cam_id:
        cam = await db.cameras.find_one({"id": cam_id}, {"_id": 0, "name": 1})
        cam_name = (cam or {}).get("name") or "—"
    site_name = "—"
    if report.get("site_id"):
        site = await db.sites.find_one({"id": report["site_id"]}, {"_id": 0, "name": 1})
        site_name = (site or {}).get("name") or "—"
    alert = {
        "id": str(uuid.uuid4()), "type": "ai_anomaly",
        "anomaly_kind": report["kind"], "anomaly_report_id": report["id"],
        "severity": _ANOMALY_SEVERITY_TO_ALERT.get(report["severity"], "info"),
        "message": report["message"],
        "camera_id": cam_id or "", "camera_name": cam_name,
        "site_id": report.get("site_id") or "", "site_name": site_name,
        "acknowledged": False, "timestamp": report["created_at"],
    }
    await db.alerts.insert_one(dict(alert))
    alert.pop("_id", None)
    await broadcast_alert(alert)
    if alert["severity"] == "critical":
        try:
            from notifications import send_notification
            await send_notification(
                "ANOMALIE IA VÉHICULE",
                f"{alert['message']}\nCaméra : {cam_name} · Site : {site_name}",
            )
        except Exception:
            logger.exception("anomaly_ai: échec send_notification")


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
        doc = {
            "id": str(uuid.uuid4()), "kind": "per_vehicle", "dedup_key": key,
            "plates": [plate], "camera_ids": [facts["camera_id"]] if facts["camera_id"] else [],
            "site_id": site_map.get(facts["camera_id"]),
            "facts": {k: v for k, v in facts.items() if k != "habits"},
            "severity": verdict["severity"], "message": verdict["message"],
            "created_at": _iso(datetime.now(timezone.utc)),
            "acknowledged": False,
        }
        await db.vehicle_anomaly_reports.insert_one(doc)
        await _publish_anomaly_alert(doc)
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
        doc = {
            "id": (existing or {}).get("id") or str(uuid.uuid4()), "kind": "convoy", "dedup_key": key,
            "plates": c["plates"], "camera_ids": [c["camera_id"]],
            "site_id": site_map.get(c["camera_id"]),
            "facts": facts, "severity": verdict["severity"], "message": verdict["message"],
            "created_at": _iso(datetime.now(timezone.utc)), "acknowledged": False,
        }
        await db.vehicle_anomaly_reports.update_one({"dedup_key": key}, {"$set": doc}, upsert=True)
        # v3.71 · Un convoi deja signale est mis a jour (compteur d'occurrences
        # croissant) sans redeclencher une alerte a chaque passage — seule la
        # toute premiere detection publie dans le fil d'Alertes.
        if not existing:
            await _publish_anomaly_alert(doc)
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
        doc = {
            "id": str(uuid.uuid4()), "kind": "wave", "dedup_key": key,
            "plates": w["plates"], "camera_ids": [w["camera_id"]],
            "site_id": site_map.get(w["camera_id"]),
            "facts": w, "severity": verdict["severity"], "message": verdict["message"],
            "created_at": _iso(datetime.now(timezone.utc)),
            "acknowledged": False,
        }
        await db.vehicle_anomaly_reports.insert_one(doc)
        await _publish_anomaly_alert(doc)
        created += 1
    return created


# ═══════════════════════════════════════════════════════════════════
# Détection — confusion de plaque (plusieurs marques réelles sous 1 texte)
# ═══════════════════════════════════════════════════════════════════
# v3.47 · Découvert le 05/09 en creusant un signalement utilisateur (plaque
# "AA2307JA" vue à Rieux ET Villeparisis, géographiquement incompatible) :
# 1004 lectures fast-alpr sous ce texte, confiance 0.55-0.85 (PAS basse —
# un seuil de confiance ne filtrerait rien) sur 4 caméras/2 sites. Vérifié
# directement via le modèle vision (vehicle_make_ai) sur 6 échantillons
# espacés dans le temps : 3 marques RÉELLEMENT différentes trouvées
# (Renault, Peugeot, Mercedes-Benz, confiance 0.95 chacune) — preuve
# directe qu'il s'agit de plusieurs véhicules réels convergeant vers le
# même texte OCR ("attracteur"), pas un seul véhicule mal classé. Ce
# détecteur croise les marques déjà vision-vérifiées (vehicle_make_ai,
# livré le 05/09) par plaque : une plaque associée à 2+ marques
# RÉELLEMENT différentes (jamais "Inconnue", qui n'est pas un désaccord)
# est un signal fiable de confusion ANPR — pas un ML entraîné, une
# simple cohérence logique sur des données déjà vérifiées par la vision.
_PLATE_CONFUSION_MIN_SAMPLES = 3
_PLATE_CONFUSION_MIN_DISTINCT_MAKES = 2


async def _detect_plate_confusions() -> list[dict]:
    pipeline = [
        {"$match": {"vehicle_make_source": "vision_ai", "vehicle_make": {"$ne": None}}},
        {"$group": {
            "_id": "$plate",
            "makes": {"$addToSet": "$vehicle_make"},
            "count": {"$sum": 1},
            "camera_ids": {"$addToSet": "$camera_id"},
            "last_seen": {"$max": "$timestamp"},
        }},
        {"$match": {"count": {"$gte": _PLATE_CONFUSION_MIN_SAMPLES}}},
    ]
    out = []
    async for row in db.plates.aggregate(pipeline):
        if len(row["makes"]) >= _PLATE_CONFUSION_MIN_DISTINCT_MAKES:
            out.append({
                "plate": row["_id"], "makes": sorted(row["makes"]),
                "sample_count": row["count"], "camera_ids": row["camera_ids"],
                "last_seen": row["last_seen"],
            })
    return out


async def _run_plate_confusions(site_map: dict) -> int:
    created = 0
    for pc in await _detect_plate_confusions():
        key = f"plate_confusion:{pc['plate']}"
        existing = await db.vehicle_anomaly_reports.find_one({"dedup_key": key}, {"_id": 0, "facts.makes": 1})
        # Ne re-narre que si la liste de marques a grandi depuis le dernier
        # passage (nouvelle preuve) — évite de re-générer le même rapport à
        # chaque run tant que rien de nouveau n'a été vérifié.
        if existing and sorted((existing.get("facts") or {}).get("makes") or []) == pc["makes"]:
            continue
        try:
            verdict = await _ask_qwen_narrate("plate_confusion", pc)
        except Exception:
            logger.exception("anomaly_ai: échec narration plate_confusion %s", pc["plate"])
            continue
        site_id = next((site_map.get(c) for c in pc["camera_ids"] if site_map.get(c)), None)
        await db.vehicle_anomaly_reports.update_one(
            {"dedup_key": key},
            {"$set": {
                "id": (existing or {}).get("id") or str(uuid.uuid4()), "kind": "plate_confusion", "dedup_key": key,
                "plates": [pc["plate"]], "camera_ids": pc["camera_ids"], "site_id": site_id,
                "facts": pc, "severity": verdict["severity"], "message": verdict["message"],
                "created_at": _iso(datetime.now(timezone.utc)), "acknowledged": False,
            }},
            upsert=True,
        )
        created += 1
    return created


# ═══════════════════════════════════════════════════════════════════
# Détection — trajet inter-site implausible (purement logique, coût nul)
# ═══════════════════════════════════════════════════════════════════
# v3.47 · Complément à plate_confusion, découvert sur le même cas réel
# (plaque AA2307JA vue à Rieux ET Villeparisis). plate_confusion a besoin
# du modèle vision (marques différentes) ; ce signal-ci ne coûte RIEN — il
# ne fait que comparer site_id + timestamp, déjà stockés sur chaque
# lecture. Se déclenche même AVANT que vehicle_make_ai ait eu le temps de
# vérifier quoi que ce soit sur cette plaque.
def _detect_cross_site_impossible(rows: list[dict]) -> list[dict]:
    by_plate: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("site_id"):
            by_plate[r["plate"]].append(r)

    out = []
    for plate, reads in by_plate.items():
        reads.sort(key=lambda r: r["timestamp"])
        for i in range(len(reads) - 1):
            a, b = reads[i], reads[i + 1]
            if a["site_id"] == b["site_id"]:
                continue
            ta, tb = _iso_to_dt(a["timestamp"]), _iso_to_dt(b["timestamp"])
            if ta is None or tb is None:
                continue
            gap_min = (tb - ta).total_seconds() / 60.0
            if gap_min < _CROSS_SITE_MIN_MINUTES:
                out.append({
                    "plate": plate,
                    "site_id_a": a["site_id"], "site_id_b": b["site_id"],
                    "time_a": a["timestamp"], "time_b": b["timestamp"],
                    "gap_minutes": round(gap_min, 1),
                    "camera_ids": [a["camera_id"], b["camera_id"]],
                })
                break  # une preuve suffit par plaque pour ce run — évite le bruit de paires multiples
    return out


async def _run_cross_site_impossible(rows: list[dict]) -> int:
    site_names = await _site_name_map()
    created = 0
    for cs in _detect_cross_site_impossible(rows):
        key = f"cross_site:{cs['plate']}:{cs['site_id_a']}:{cs['site_id_b']}"
        existing = await db.vehicle_anomaly_reports.find_one({"dedup_key": key}, {"_id": 0, "id": 1})
        if existing:
            continue
        facts = {
            **cs,
            "site_a_name": site_names.get(cs["site_id_a"], cs["site_id_a"]),
            "site_b_name": site_names.get(cs["site_id_b"], cs["site_id_b"]),
        }
        try:
            verdict = await _ask_qwen_narrate("cross_site_impossible", facts)
        except Exception:
            logger.exception("anomaly_ai: échec narration cross_site_impossible %s", cs["plate"])
            continue
        doc = {
            "id": str(uuid.uuid4()), "kind": "cross_site_impossible", "dedup_key": key,
            "plates": [cs["plate"]], "camera_ids": cs["camera_ids"], "site_id": cs["site_id_a"],
            "facts": facts, "severity": verdict["severity"], "message": verdict["message"],
            "created_at": _iso(datetime.now(timezone.utc)), "acknowledged": False,
        }
        await db.vehicle_anomaly_reports.insert_one(doc)
        await _publish_anomaly_alert(doc)
        created += 1
    return created


# ═══════════════════════════════════════════════════════════════════
# Détection — stationnement prolongé (demande explicite : "faire
# fonctionner tout ça avec Qwen" au sujet de parking_sessions.py). Réutilise
# le journal déjà persisté (aucun calcul d'immobilité dupliqué) — se
# déclenche sur les sessions encore EN COURS dépassant le seuil, une seule
# narration par session (dedup_key sur l'id de session, pas sur la plaque —
# une même plaque peut légitimement dépasser le seuil plusieurs fois dans
# le temps, sur des sessions différentes).
# ═══════════════════════════════════════════════════════════════════
_LONG_PARKING_THRESHOLD_S = 3600  # 1h — ajustable si trop/pas assez sensible en usage réel


async def _run_long_parking() -> int:
    created = 0
    async for sess in db.parking_sessions.find(
            {"status": "ongoing", "duration_seconds": {"$gte": _LONG_PARKING_THRESHOLD_S}}, {"_id": 0}):
        key = f"long_parking:{sess['id']}"
        existing = await db.vehicle_anomaly_reports.find_one({"dedup_key": key}, {"_id": 0, "id": 1})
        if existing:
            continue
        facts = {
            "plate": sess["plate"], "camera_name": sess.get("camera_name"), "site_name": sess.get("site_name"),
            "arrived_at": sess["arrived_at"], "duration_seconds": sess["duration_seconds"],
            "vehicle_make": sess.get("vehicle_make"), "vehicle_color": sess.get("vehicle_color"),
        }
        try:
            verdict = await _ask_qwen_narrate("long_parking", facts)
        except Exception:
            logger.exception("anomaly_ai: échec narration long_parking %s", sess["plate"])
            continue
        doc = {
            "id": str(uuid.uuid4()), "kind": "long_parking", "dedup_key": key,
            "plates": [sess["plate"]], "camera_ids": [sess["camera_id"]], "site_id": sess.get("site_id"),
            "facts": facts, "severity": verdict["severity"], "message": verdict["message"],
            "created_at": _iso(datetime.now(timezone.utc)), "acknowledged": False,
        }
        await db.vehicle_anomaly_reports.insert_one(doc)
        await _publish_anomaly_alert(doc)
        created += 1
    return created


async def _run_anomaly_ai_batch() -> dict:
    site_map = await _camera_site_map()
    rows = await _load_recent_plates()
    n_conv = await _run_convoys(rows, site_map)
    n_wave = await _run_waves(rows, site_map)
    n_veh = await _run_per_vehicle(site_map)
    n_confusion = await _run_plate_confusions(site_map)
    n_cross_site = await _run_cross_site_impossible(rows)
    n_long_parking = await _run_long_parking()
    return {"convoys": n_conv, "waves": n_wave, "per_vehicle": n_veh,
            "plate_confusions": n_confusion, "cross_site": n_cross_site, "long_parking": n_long_parking}


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


class BulkAcknowledgeBody(BaseModel):
    ids: list[str]


@vehicle_anomaly_ai_router.post("/bulk-acknowledge")
async def bulk_acknowledge_reports(body: BulkAcknowledgeBody, user: dict = Depends(require_permission("read_plates"))):
    """v3.27 · Bouton « Tout sélectionner » (fenêtre Anomalies IA) — traite
    en un seul appel réseau plutôt qu'une requête par carte cochée."""
    if not body.ids:
        return {"acknowledged": 0}
    now = _iso(datetime.now(timezone.utc))
    res = await db.vehicle_anomaly_reports.update_many(
        {"id": {"$in": body.ids}},
        {"$set": {"acknowledged": True, "acknowledged_by": user.get("email"), "acknowledged_at": now}},
    )
    return {"acknowledged": res.modified_count}
