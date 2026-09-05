"""v3.45 · Correction couleur véhicule via modèle vision (qwen2.5vl).

Cadrage — le classifieur CV existant (pipeline_v2/frame_context.py::
dominant_color_fr, HSV + seuils fixes, déjà patché 2 fois : v3.1.2 masque
teinte, v3.20 seuil saturation 45→65) montre encore un biais mesuré :
6146 lectures "Bleu" contre 41 "Blanc" sur 22417 (statistiquement
impossible pour une flotte réelle — blanc/gris/noir dominent toujours).
Vérifié sur un cas réel (plaque E58703) : véhicule visuellement GRIS,
classé "Bleu" par le CV, classé "Gris" (confiance 0.95) par qwen2.5vl:7b
sur le MÊME crop stocké.

Décision explicite (04/09) après vérification qu'aucun modèle texte du
serveur ia.mginformatique.com ne peut voir une image : déploiement d'un
modèle vision dédié (qwen2.5vl:7b, ~6 Go, testé fonctionnel en conditions
réelles avant tout code ci-dessous).

Design — PAS de chemin temps réel : `dominant_color_fr` reste le SEUL
calcul de couleur dans le chemin chaud (camera_worker.py, zéro latence
ajoutée, zéro dépendance à un service GPU partagé distant pour CHAQUE
détection — voir la leçon opérationnelle déjà tirée pour Smart Search :
un appel LLM lent a déjà gelé tout le backend MG-VMS faute de timeout).
Ce module tourne en tâche PÉRIODIQUE (même pattern que vehicle_dedup.py/
anpr_tuning.py/vehicle_anomaly_ai.py) et RE-VÉRIFIE les lectures récentes
déjà en base via le modèle vision.

Nuit / IR (préoccupation explicite de l'utilisateur, à prévoir dans le
code) : réutilise `dominant_color_fr` LUI-MÊME comme détecteur IR — si son
verdict est None (image monochrome, R≈G≈B), aucune information de teinte
n'existe dans le crop et la vision ne peut structurellement pas deviner
mieux qu'une hallucination ; on laisse "Inconnue" tel quel, aucun appel
vision gaspillé. La "phase d'apprentissage" demandée se traduit ici par
une correction PROGRESSIVE des ~22k lectures déjà en base (vision comme
oracle plus fiable que les seuils fixes), pas un modèle entraîné from
scratch — plus rapide à livrer, cohérence avec le choix déjà acté pour
les anomalies (règles/CV + IA qui juge, pas de ML from scratch).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from auth import require_permission, require_role, log_audit
from database import db

logger = logging.getLogger("routes.vehicle_color_ai")

vehicle_color_ai_router = APIRouter(prefix="/api/vehicles/color-ai", tags=["vehicle-color-ai"])

_LOOKBACK_DAYS = 30
_BATCH_SIZE = 200
_BATCH_INTERVAL_HOURS = 6
_VALID_COLORS = {"Blanc", "Noir", "Gris", "Bleu", "Rouge", "Vert", "Jaune", "Orange", "Violet", "Rose"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _decode_crop_bgr(data_uri: str):
    """data:image/jpeg;base64,... -> tableau BGR (cv2), None si invalide."""
    import cv2
    import numpy as np
    try:
        b64 = data_uri.split(",", 1)[1] if "," in data_uri else data_uri
        raw = base64.b64decode(b64)
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


async def _ask_qwen_vision_color(vehicle_crop_data_uri: str) -> dict:
    from routes.llm_settings import get_vision_llm_config
    cfg = await get_vision_llm_config()
    if not cfg:
        raise HTTPException(status_code=503, detail={"code": "COLOR_AI_LLM_NOT_CONFIGURED",
                                                        "message": "Modèle vision non configuré (Administration → LLM)."})
    import httpx
    system = (
        "Tu es un analyste ANPR. Réponds UNIQUEMENT avec un objet JSON valide "
        'respectant EXACTEMENT ce schéma : {"couleur": '
        '"Blanc"|"Noir"|"Gris"|"Bleu"|"Rouge"|"Vert"|"Jaune"|"Orange"|"Violet"|"Rose", '
        '"confiance": nombre entre 0 et 1}. Base ton jugement sur la couleur RÉELLE de '
        "la carrosserie peinte, pas sur les reflets, l'éclairage ambiant ou les vitres. "
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
                {"type": "text", "text": "Quelle est la couleur de la carrosserie de ce véhicule ?"},
                {"type": "image_url", "image_url": {"url": vehicle_crop_data_uri}},
            ]},
        ],
        "stream": False,
    }
    # v3.45 · Endpoint OpenAI-compatible (/v1/chat/completions), pas
    # /api/chat/completions (natif Open WebUI) — c'est le format qui
    # accepte content=[...] avec image_url, vérifié en conditions réelles
    # avant tout code (voir docstring module).
    url = f"{cfg['base_url']}/v1/chat/completions"
    async with httpx.AsyncClient(timeout=40.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()
    raw = (body["choices"][0]["message"]["content"] or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    parsed = json.loads(raw)
    couleur = parsed.get("couleur")
    if couleur not in _VALID_COLORS:
        couleur = None
    return {"couleur": couleur, "confiance": float(parsed.get("confiance") or 0)}


async def _run_color_ai_batch() -> dict:
    from pipeline_v2.frame_context import dominant_color_fr
    since = _iso(datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS))
    docs = await db.plates.find(
        {"timestamp": {"$gte": since}, "vehicle_crop": {"$exists": True, "$ne": None},
         "vehicle_color_ai_checked_at": {"$exists": False}},
        {"_id": 0, "id": 1, "vehicle_crop": 1, "vehicle_color": 1},
    ).limit(_BATCH_SIZE).to_list(_BATCH_SIZE)

    checked = corrected = skipped_ir = errors = 0
    for doc in docs:
        now_iso = _iso(datetime.now(timezone.utc))
        crop_bgr = _decode_crop_bgr(doc["vehicle_crop"])
        if crop_bgr is None:
            continue
        # Réutilise le détecteur IR déjà en place — si le CV lui-même ne
        # trouve aucune teinte fiable (image monochrome), la vision ne peut
        # structurellement pas faire mieux : on ne gaspille pas un appel
        # GPU partagé pour une hallucination probable.
        if dominant_color_fr(crop_bgr) is None:
            await db.plates.update_one({"id": doc["id"]}, {"$set": {"vehicle_color_ai_checked_at": now_iso}})
            skipped_ir += 1
            continue
        try:
            verdict = await _ask_qwen_vision_color(doc["vehicle_crop"])
        except Exception:
            logger.exception("color_ai: échec vérification %s", doc["id"])
            errors += 1
            continue
        checked += 1
        update = {"vehicle_color_ai_checked_at": now_iso, "vehicle_color_ai_confidence": verdict["confiance"]}
        if verdict["couleur"] and verdict["couleur"] != doc.get("vehicle_color"):
            update["vehicle_color"] = verdict["couleur"]
            update["vehicle_color_source"] = "vision_ai"
            corrected += 1
        await db.plates.update_one({"id": doc["id"]}, {"$set": update})
    return {"checked": checked, "corrected": corrected, "skipped_ir": skipped_ir, "errors": errors}


async def color_ai_batch_loop() -> None:
    """Même garde-fou anti-jamais-exécuté que les autres tâches périodiques
    (dedup_batch_loop/anpr_tuning_loop/anomaly_ai_batch_loop) : court délai
    initial, puis 1re passe réelle, ensuite l'intervalle normal."""
    from routes.llm_settings import is_feature_enabled
    await asyncio.sleep(240)
    while True:
        if await is_feature_enabled("color_ai_enabled"):
            try:
                counts = await _run_color_ai_batch()
                if counts["checked"] or counts["skipped_ir"]:
                    logger.info("color_ai: run terminé — %s", counts)
            except Exception:
                logger.exception("color_ai: erreur boucle color_ai_batch_loop")
        await asyncio.sleep(_BATCH_INTERVAL_HOURS * 3600)


@vehicle_color_ai_router.post("/run")
async def run_now(user: dict = Depends(require_role("admin"))):
    from routes.llm_settings import is_feature_enabled
    if not await is_feature_enabled("color_ai_enabled"):
        raise HTTPException(status_code=400, detail={
            "code": "COLOR_AI_DISABLED",
            "message": "Correction couleur IA désactivée — Administration → LLM (MG-IA).",
        })

    async def _run_bg():
        try:
            counts = await _run_color_ai_batch()
            logger.info("color_ai: recherche manuelle terminée, %s", counts)
        except Exception:
            logger.exception("color_ai: erreur pendant la recherche manuelle")
    asyncio.create_task(_run_bg())
    await log_audit(user, "color_ai_run_started", "lancée en arrière-plan")
    return {"started": True}


@vehicle_color_ai_router.get("/status")
async def status(user: dict = Depends(require_permission("read_plates"))):
    """Volume de progression — combien de lectures récentes ont déjà été
    vérifiées/corrigées par la vision, pour donner une idée concrète de
    l'avancement de la "phase d'apprentissage" plutôt qu'une boîte noire."""
    since = _iso(datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS))
    total = await db.plates.count_documents({"timestamp": {"$gte": since}, "vehicle_crop": {"$exists": True, "$ne": None}})
    checked = await db.plates.count_documents({"timestamp": {"$gte": since}, "vehicle_color_ai_checked_at": {"$exists": True}})
    corrected = await db.plates.count_documents({"timestamp": {"$gte": since}, "vehicle_color_source": "vision_ai"})
    return {"total_eligible": total, "checked": checked, "corrected": corrected}
