"""v3.46 · Identification marque véhicule via modèle vision (qwen2.5vl).

Même principe que vehicle_color_ai.py (même modèle vision, même connexion,
même architecture tâche périodique) mais PAS le même comportement IR :
- Couleur : une image monochrome IR ne contient structurellement AUCUNE
  information de teinte — la vision ne peut pas deviner mieux qu'une
  hallucination, on skip (voir dominant_color_fr).
- Marque : le LOGO/la calandre/la silhouette d'un véhicule restent
  identifiables en niveaux de gris — l'information est dans la FORME, pas
  la couleur. Aucune raison de sauter les crops IR ici.

Vocabulaire OUVERT (contrairement à la couleur, enum fermé à 10 valeurs) :
`vehicle_make` n'a pas de liste fixe. Risque de confusion documenté sur ce
type de champ texte libre avec un petit modèle (voir reference mgai) —
mitigé par (1) une liste de marques courantes du marché français fournie
en suggestion dans le prompt système, PAS une contrainte stricte, (2) une
instruction explicite de répondre "Inconnue" si le logo/la calandre n'est
pas clairement identifiable plutôt que de deviner, (3) un seuil de
confiance minimum avant d'écraser la valeur existante.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from auth import require_permission, require_role, log_audit
from database import db

logger = logging.getLogger("routes.vehicle_make_ai")

vehicle_make_ai_router = APIRouter(prefix="/api/vehicles/make-ai", tags=["vehicle-make-ai"])

_LOOKBACK_DAYS = 30
_BATCH_SIZE = 200
_BATCH_INTERVAL_HOURS = 6
# Sous ce seuil de confiance, on garde la valeur existante plutôt que
# d'écraser avec une supposition faible — un champ texte libre a plus de
# marge d'erreur qu'un enum fermé (voir docstring module).
_MIN_CONFIDENCE_TO_APPLY = 0.6

_SUGGESTED_MAKES = (
    "Renault, Peugeot, Citroën, Volkswagen, Toyota, Ford, Dacia, BMW, "
    "Mercedes-Benz, Audi, Fiat, Opel, Nissan, Hyundai, Kia, Škoda, Seat, "
    "Volvo, Mini, Suzuki, Honda, Mazda, Land Rover, Jeep, Tesla, Alfa Romeo, "
    "Mitsubishi, Porsche, Jaguar, DS Automobiles, Alpine, Smart, Cupra, MG, Lexus"
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


async def _ask_qwen_vision_make(vehicle_crop_data_uri: str) -> dict:
    from routes.llm_settings import get_vision_llm_config
    cfg = await get_vision_llm_config()
    if not cfg:
        raise HTTPException(status_code=503, detail={"code": "MAKE_AI_LLM_NOT_CONFIGURED",
                                                        "message": "Modèle vision non configuré (Administration → LLM)."})
    import httpx
    system = (
        "Tu es un analyste ANPR spécialisé en identification de véhicules. "
        'Réponds UNIQUEMENT avec un objet JSON valide respectant EXACTEMENT ce '
        'schéma : {"marque": texte ou null, "modele": texte ou null, "confiance": nombre entre 0 et 1}. '
        f"Marques courantes en France (liste indicative, pas exhaustive) : {_SUGGESTED_MAKES}. "
        "Base ton jugement sur le logo, la calandre, la silhouette générale, les feux — "
        "cette identification reste valable même sur une image en niveaux de "
        "gris (infrarouge nocturne), l'information est dans la FORME pas la "
        "couleur. `modele` : le modèle commercial précis si identifiable avec "
        "certitude (ex. Clio, 308, C3, Golf) — null si seule la marque est sûre, "
        "ne jamais deviner un modèle au hasard à partir de la seule marque. "
        "Si le logo n'est pas clairement visible ou identifiable, "
        'réponds {"marque": null, "modele": null, "confiance": 0} plutôt que de deviner. '
        "Aucun texte hors JSON."
    )
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": "Quelle est la marque de ce véhicule ?"},
                {"type": "image_url", "image_url": {"url": vehicle_crop_data_uri}},
            ]},
        ],
        "stream": False,
    }
    # v3.46 · Même endpoint que vehicle_color_ai.py (/api/chat/completions,
    # pas /v1/chat/completions) — base_url pointe vers Open WebUI (WAN), pas
    # Ollama brut. Voir le correctif déjà vérifié sur le module couleur.
    url = f"{cfg['base_url']}/api/chat/completions"
    from llm_call_log import log_llm_call
    import time
    _t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
    except Exception as e:
        await log_llm_call(source="make_ai", url=url, model=payload.get("model"), request_payload=payload,
                            status_code=getattr(getattr(e, "response", None), "status_code", None),
                            error=f"{type(e).__name__}: {e}", latency_ms=int((time.monotonic() - _t0) * 1000))
        raise
    await log_llm_call(source="make_ai", url=url, model=payload.get("model"), request_payload=payload,
                        status_code=resp.status_code, response_body=body,
                        latency_ms=int((time.monotonic() - _t0) * 1000))
    raw = (body["choices"][0]["message"]["content"] or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    parsed = json.loads(raw)
    marque = (parsed.get("marque") or "").strip() or None
    modele = (parsed.get("modele") or "").strip() or None
    return {"marque": marque, "modele": modele, "confiance": float(parsed.get("confiance") or 0)}


async def _run_make_ai_batch() -> dict:
    since = _iso(datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS))
    docs = await db.plates.find(
        {"timestamp": {"$gte": since}, "vehicle_crop": {"$exists": True, "$ne": None},
         "vehicle_make_ai_checked_at": {"$exists": False}},
        {"_id": 0, "id": 1, "vehicle_crop": 1, "vehicle_make": 1, "vehicle_model": 1},
    ).sort("timestamp", -1).limit(_BATCH_SIZE).to_list(_BATCH_SIZE)  # v3.27 · du plus récent au plus ancien (demande explicite)

    checked = corrected = low_confidence = errors = 0
    for doc in docs:
        now_iso = _iso(datetime.now(timezone.utc))
        try:
            verdict = await _ask_qwen_vision_make(doc["vehicle_crop"])
        except Exception:
            logger.exception("make_ai: échec vérification %s", doc["id"])
            errors += 1
            continue
        checked += 1
        update = {"vehicle_make_ai_checked_at": now_iso, "vehicle_make_ai_confidence": verdict["confiance"]}
        if verdict["marque"] and verdict["confiance"] >= _MIN_CONFIDENCE_TO_APPLY \
                and verdict["marque"] != doc.get("vehicle_make"):
            update["vehicle_make"] = verdict["marque"]
            update["vehicle_make_source"] = "vision_ai"
            corrected += 1
        elif verdict["marque"] and verdict["confiance"] < _MIN_CONFIDENCE_TO_APPLY:
            low_confidence += 1
        # v3.28 · Modèle (Clio/308/C3...) — même appel vision que la marque,
        # aucun coût Qwen supplémentaire. Même seuil de confiance avant
        # d'écraser une valeur déjà connue.
        if verdict.get("modele") and verdict["confiance"] >= _MIN_CONFIDENCE_TO_APPLY \
                and verdict["modele"] != doc.get("vehicle_model"):
            update["vehicle_model"] = verdict["modele"]
            update["vehicle_model_source"] = "vision_ai"
        await db.plates.update_one({"id": doc["id"]}, {"$set": update})
    return {"checked": checked, "corrected": corrected, "low_confidence": low_confidence, "errors": errors}


async def make_ai_batch_loop() -> None:
    """Même garde-fou anti-jamais-exécuté que les autres tâches périodiques.

    v3.27 · Mode « synchro auto » planifiée à heure fixe — voir
    vehicle_color_ai.py::color_ai_batch_loop (même mécanique, réglage
    indépendant `make_ai_auto_sync_*`)."""
    from routes.llm_settings import is_feature_enabled, get_make_ai_auto_sync_settings
    await asyncio.sleep(300)
    last_triggered_date = None
    last_interval_run = 0.0
    while True:
        try:
            if await is_feature_enabled("make_ai_enabled"):
                sync = await get_make_ai_auto_sync_settings()
                if sync["enabled"]:
                    now = datetime.now()
                    today_key = now.strftime("%Y-%m-%d")
                    if now.strftime("%H:%M") == sync["time"] and last_triggered_date != today_key:
                        counts = await _run_make_ai_batch()
                        logger.info("make_ai: run planifié (%s) terminé — %s", sync["time"], counts)
                        last_triggered_date = today_key
                elif time.monotonic() - last_interval_run >= _BATCH_INTERVAL_HOURS * 3600:
                    counts = await _run_make_ai_batch()
                    if counts["checked"]:
                        logger.info("make_ai: run terminé — %s", counts)
                    last_interval_run = time.monotonic()
        except Exception:
            logger.exception("make_ai: erreur boucle make_ai_batch_loop")
        await asyncio.sleep(60)


@vehicle_make_ai_router.post("/run")
async def run_now(user: dict = Depends(require_role("admin"))):
    from routes.llm_settings import is_feature_enabled
    if not await is_feature_enabled("make_ai_enabled"):
        raise HTTPException(status_code=400, detail={
            "code": "MAKE_AI_DISABLED",
            "message": "Identification marque IA désactivée — Administration → LLM (MG-IA).",
        })

    async def _run_bg():
        try:
            counts = await _run_make_ai_batch()
            logger.info("make_ai: recherche manuelle terminée, %s", counts)
        except Exception:
            logger.exception("make_ai: erreur pendant la recherche manuelle")
    asyncio.create_task(_run_bg())
    await log_audit(user, "make_ai_run_started", "lancée en arrière-plan")
    return {"started": True}


# v3.27 · Même correctif que vehicle_color_ai.py::status — `vehicle_crop`
# stocke l'image en base64 (non indexable, dépasse la limite de 1024
# octets/clé de MongoDB), le filtre d'existence mesuré ~7s pour 23919
# documents. Mis en cache 60s (frontend polle toutes les 30s).
_STATUS_CACHE_TTL_S = 60.0
_status_cache: tuple[float, dict] | None = None


@vehicle_make_ai_router.get("/status")
async def status(user: dict = Depends(require_permission("read_plates"))):
    global _status_cache
    now = time.monotonic()
    if _status_cache and now - _status_cache[0] < _STATUS_CACHE_TTL_S:
        return _status_cache[1]
    since = _iso(datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS))
    total = await db.plates.count_documents({"timestamp": {"$gte": since}, "vehicle_crop": {"$exists": True, "$ne": None}})
    checked = await db.plates.count_documents({"timestamp": {"$gte": since}, "vehicle_make_ai_checked_at": {"$exists": True}})
    corrected = await db.plates.count_documents({"timestamp": {"$gte": since}, "vehicle_make_source": "vision_ai"})
    result = {"total_eligible": total, "checked": checked, "corrected": corrected}
    _status_cache = (now, result)
    return result
