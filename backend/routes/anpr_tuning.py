"""v3.20 · Réglage automatique du seuil de confiance ANPR par caméra, assisté par Qwen.

Constaté en réel (31/08) : la caméra `ptz_cour_telephoto` génère 73% de
ses lectures sous 0.7 de confiance (contre 45% pour la flotte) — un
véhicule unique a été lu 7 fois différemment en 19 secondes (confiances
0.56-0.72), créant une fiche véhicule séparée à chaque fois. Le seuil
`anpr_config.min_confidence` par caméra existe déjà dans le pipeline
(`camera_worker.py`) mais n'était exposé nulle part — sa valeur par
défaut (0.0) n'écarte rien.

Un seuil FIXE choisi une fois ne conviendrait pas à toutes les caméras
(45% des lectures de la flotte entière sont sous 0.7 — un seuil trop haut
partout couperait des lectures correctes sur les caméras qui fonctionnent
bien). Qwen recommande donc un seuil PROPRE à chaque caméra, à partir de
sa propre distribution de confiance récente — tâche périodique
automatique (le 31/08, demande explicite : "que ça s'adapte
automatiquement"), avec des garde-fous stricts (jamais > 0.85, jamais <
0, chaque changement journalisé et visible) plutôt qu'une validation
manuelle comme pour les doublons véhicule.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from auth import require_role, log_audit
from database import db

logger = logging.getLogger("routes.anpr_tuning")

anpr_tuning_router = APIRouter(prefix="/api/cameras", tags=["anpr-tuning"])

_TUNING_INTERVAL_HOURS = 7 * 24  # hebdomadaire — le comportement d'une caméra ne change pas d'un jour à l'autre
_MIN_SAMPLES = 30  # pas assez de lectures récentes pour juger sereinement
_HARD_MAX_THRESHOLD = 0.85  # garde-fou : ne jamais braquer une caméra au point de ne plus rien capter
_HARD_MIN_THRESHOLD = 0.0


async def _camera_confidence_stats(camera_id: str, days: int = 14) -> dict | None:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    docs = await db.plates.find(
        {"camera_id": camera_id, "timestamp": {"$gte": since}}, {"_id": 0, "confidence": 1}
    ).to_list(5000)
    confs = [d["confidence"] for d in docs if isinstance(d.get("confidence"), (int, float))]
    if len(confs) < _MIN_SAMPLES:
        return None
    buckets = {"<0.5": 0, "0.5-0.6": 0, "0.6-0.7": 0, "0.7-0.8": 0, "0.8-0.9": 0, ">=0.9": 0}
    for c in confs:
        if c < 0.5:
            buckets["<0.5"] += 1
        elif c < 0.6:
            buckets["0.5-0.6"] += 1
        elif c < 0.7:
            buckets["0.6-0.7"] += 1
        elif c < 0.8:
            buckets["0.7-0.8"] += 1
        elif c < 0.9:
            buckets["0.8-0.9"] += 1
        else:
            buckets[">=0.9"] += 1
    return {"n": len(confs), "mean": round(sum(confs) / len(confs), 3), "buckets": buckets}


async def _ask_qwen_recommend_threshold(camera_name: str, stats: dict, current_threshold: float) -> dict:
    from routes.llm_settings import get_active_llm_config
    cfg = await get_active_llm_config()
    if not cfg:
        raise HTTPException(status_code=503, detail={"code": "TUNING_LLM_NOT_CONFIGURED",
                                                        "message": "LLM non configuré (Administration → LLM)."})
    import httpx
    schema = {
        "type": "object",
        "properties": {
            "recommended_min_confidence": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["recommended_min_confidence", "reason"],
    }
    system = (
        "Tu règles le seuil de confiance minimum ANPR d'une caméra de vidéosurveillance. "
        "Réponds UNIQUEMENT avec un objet JSON valide respectant EXACTEMENT ce schéma : "
        '{"recommended_min_confidence": nombre entre 0 et 0.85, "reason": texte court}. '
        "Aucun texte hors JSON."
    )
    prompt = (
        f"Caméra \"{camera_name}\" — {stats['n']} lectures de plaque sur 14 jours, "
        f"confiance moyenne {stats['mean']}. Répartition : "
        + ", ".join(f"{k}: {v}" for k, v in stats["buckets"].items())
        + f". Seuil minimum actuel : {current_threshold}. "
        "Objectif : écarter les lectures peu fiables (souvent du texte halluciné sur un objet "
        "qui n'est pas une vraie plaque, ou une confusion sévère) SANS perdre la majorité des "
        "lectures correctes. Une caméra où la majorité des lectures se concentre sous 0.7 "
        "indique un problème (angle, distance, zoom) plutôt qu'une flotte de vraies plaques "
        "difficiles à lire — dans ce cas un seuil plus strict est justifié. Recommande un seuil."
    )
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
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
    value = float(parsed.get("recommended_min_confidence", current_threshold))
    value = max(_HARD_MIN_THRESHOLD, min(_HARD_MAX_THRESHOLD, value))
    return {"min_confidence": value, "reason": parsed.get("reason", "")}


async def _tune_camera(camera_id: str, actor: str = "system") -> dict | None:
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "name": 1, "anpr_config": 1})
    if not cam:
        return None
    stats = await _camera_confidence_stats(camera_id)
    if not stats:
        return None
    current = float((cam.get("anpr_config") or {}).get("min_confidence") or 0.0)
    verdict = await _ask_qwen_recommend_threshold(cam.get("name", camera_id), stats, current)
    new_value = verdict["min_confidence"]
    if abs(new_value - current) < 0.02:
        return {"camera_id": camera_id, "changed": False, "min_confidence": current}
    await db.cameras.update_one({"id": camera_id}, {"$set": {"anpr_config.min_confidence": new_value}})
    await db.anpr_tuning_history.insert_one({
        "camera_id": camera_id,
        "camera_name": cam.get("name", camera_id),
        "previous": current,
        "new": new_value,
        "reason": verdict["reason"],
        "stats": stats,
        "actor": actor,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        from ai_engine import signal_camera_config_changed
        signal_camera_config_changed(camera_id)
    except Exception:
        logger.exception("anpr_tuning: signal_camera_config_changed a échoué pour %s", camera_id)
    logger.info("anpr_tuning: %s — seuil %.2f -> %.2f (%s)",
                cam.get("name", camera_id), current, new_value, verdict["reason"][:100])
    return {"camera_id": camera_id, "changed": True, "min_confidence": new_value,
            "previous": current, "reason": verdict["reason"]}


async def anpr_tuning_loop() -> None:
    """Tourne une fois par semaine — jamais dans le chemin chaud de l'IA."""
    from routes.llm_settings import is_feature_enabled
    while True:
        await asyncio.sleep(_TUNING_INTERVAL_HOURS * 3600)
        if not await is_feature_enabled("anpr_tuning_enabled"):
            continue
        try:
            cams = await db.cameras.find({"detect_enabled": True}, {"_id": 0, "id": 1}).to_list(500)
            for cam in cams:
                try:
                    await _tune_camera(cam["id"], actor="auto")
                except Exception:
                    logger.exception("anpr_tuning: échec réglage caméra %s", cam["id"])
        except Exception:
            logger.exception("anpr_tuning: erreur boucle anpr_tuning_loop")


@anpr_tuning_router.post("/{camera_id}/anpr-tuning/run")
async def run_tuning_now(camera_id: str, user: dict = Depends(require_role("admin"))):
    from routes.llm_settings import is_feature_enabled
    if not await is_feature_enabled("anpr_tuning_enabled"):
        raise HTTPException(status_code=400, detail={
            "code": "ANPR_TUNING_DISABLED",
            "message": "Réglage ANPR IA désactivé — Administration → LLM (MG-IA).",
        })
    result = await _tune_camera(camera_id, actor=user.get("email", "admin"))
    if result is None:
        raise HTTPException(400, {"code": "NOT_ENOUGH_DATA",
                                    "message": f"Moins de {_MIN_SAMPLES} lectures récentes — pas assez de données pour juger."})
    await log_audit(user, "anpr_tuning_run", camera_id, json.dumps(result))
    return result


@anpr_tuning_router.get("/{camera_id}/anpr-tuning/history")
async def tuning_history(camera_id: str, user: dict = Depends(require_role("admin"))):
    docs = await db.anpr_tuning_history.find(
        {"camera_id": camera_id}, {"_id": 0}
    ).sort("at", -1).to_list(50)
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0, "anpr_config": 1})
    current = float((cam.get("anpr_config") or {}).get("min_confidence") or 0.0) if cam else 0.0
    return {"current_min_confidence": current, "history": docs}
