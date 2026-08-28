"""v0.7 · Smart Search cross-domain — véhicules + personnes/événements.

Un unique endpoint langage naturel qui interroge indifféremment :
  - la collection ``plates`` (véhicules ANPR)
  - la collection ``events``  (détections IA : Personne, Vélo, Voiture, …)

Le LLM (Claude Sonnet 5) parse la requête en JSON structuré et détermine
le ``target`` (``vehicles`` / ``persons`` / ``both``). L'endpoint exécute
les deux recherches en parallèle et retourne un résultat unifié.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_permission
from database import db

logger = logging.getLogger("routes.smart_search")

smart_search_router = APIRouter(prefix="/api/smart-search", tags=["smart-search"])


class SmartQuery(BaseModel):
    query: str


# ────────────────────────────────────────────────────────────────
# Prompt système — parseur JSON strict
# ────────────────────────────────────────────────────────────────
def _system_prompt() -> str:
    return (
        "Tu es un parseur qui convertit une requête utilisateur en JSON strict "
        "pour interroger une base de vidéosurveillance ANPR + détections IA. "
        "Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour.\n\n"
        "Schéma :\n"
        "{\n"
        '  "target": "vehicles" | "persons" | "both",   // domaine cible\n'
        '  "plate": string|null,\n'
        '  "colors": [string],                          // couleur véhicule OU vêtement\n'
        '  "makes": [string],                           // marques véhicule\n'
        '  "types": [string],                           // pour véhicule : voiture, camion, moto, vélo, bus, personne\n'
        '  "date_from": "YYYY-MM-DD"|null,\n'
        '  "date_to":   "YYYY-MM-DD"|null,\n'
        '  "time_from": "HH:MM"|null,\n'
        '  "time_to":   "HH:MM"|null,\n'
        '  "camera_hint": string|null,                  // nom/mot-clé caméra\n'
        '  "object_description": string|null            // description textuelle libre pour tri visuel\n'
        "}\n\n"
        f"Date courante : {datetime.now(timezone.utc).date().isoformat()}. "
        "« ce matin » = 06:00-12:00 aujourd'hui. « hier » = date - 1. "
        "« cette semaine » = 7 derniers jours. « ce soir » = 18:00-23:59 aujourd'hui.\n"
        "Si la requête mentionne « personne », « quelqu'un », « individu », un vêtement, "
        "ou une couleur portée, mets ``target: \"persons\"``. Si elle mentionne uniquement "
        "des attributs véhicule (plaque, marque, camion, voiture...), mets ``target: \"vehicles\"``. "
        "Si les deux, mets ``\"both\"``."
    )


def _norm_plate(p: str) -> str:
    return (p or "").upper().replace(" ", "").replace("-", "")


async def _parse_query_llm(query: str) -> dict:
    # v3.19 · Remplace la clé cloud EMERGENT_LLM_KEY par une instance Qwen
    # auto-hébergée, configurée via le menu admin LLM (routes/llm_settings.py)
    # plutôt qu'une variable d'env par site — objectif : déploiement client
    # sans édition manuelle de fichier .env. Format d'appel OpenAI-compatible
    # (chat completions), convention supportée par Ollama/Open WebUI.
    from routes.llm_settings import get_active_llm_config
    cfg = await get_active_llm_config()
    if not cfg:
        # v1.0-rc4 · Code + message explicites pour le frontend (pas de
        # "Une erreur est survenue"). Le fallback UI côté Events.jsx doit
        # afficher ce message sans casser la vue.
        raise HTTPException(status_code=503,
                            detail={"code": "SMART_SEARCH_LLM_NOT_CONFIGURED",
                                    "error": "no_llm_key",
                                    "message": "La recherche IA n'est pas configurée sur ce serveur. "
                                               "Configurez-la dans Administration → LLM (MG-IA)."})
    import httpx
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": query},
        ],
        "stream": False,
    }
    # v3.19 · Open WebUI expose son API native sous /api/chat/completions
    # (vérifié en direct : /v1/chat/completions -> 405, /api/chat/completions
    # -> 401 sans clé, donc bien le bon endpoint) — pas le chemin
    # OpenAI-compat standard /v1/... sur cette instance.
    url = f"{cfg['base_url']}/api/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        raw = body["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("smart-search LLM failed: %s", e)
        raise HTTPException(status_code=502,
                            detail={"code": "SMART_SEARCH_LLM_ERROR",
                                    "error": "llm_error",
                                    "message": f"Le service LLM a échoué : {str(e)[:150]}"})
    txt = (raw or "").strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.startswith("json"): txt = txt[4:].strip()
    try:
        return json.loads(txt)
    except Exception:
        raise HTTPException(status_code=502,
                            detail={"code": "SMART_SEARCH_LLM_PARSE_ERROR",
                                    "error": "llm_parse_error",
                                    "message": "Réponse LLM invalide (JSON attendu).",
                                    "raw": txt[:300]})


# ────────────────────────────────────────────────────────────────
# Traducteurs FR ↔ EN
# ────────────────────────────────────────────────────────────────
COLOR_MAP = {
    "rouge": "red", "noir": "black", "blanc": "white", "bleu": "blue",
    "vert": "green", "jaune": "yellow", "gris": "gray", "argent": "silver",
    "orange": "orange", "marron": "brown", "violet": "purple", "rose": "pink",
}

TYPE_MAP_VEHICLE = {
    "voiture": "car", "camion": "truck", "moto": "motorcycle", "bus": "bus",
    "vélo": "bike", "camionnette": "van",
}

# Événements : normalisation vers les types stockés (FR)
EVENT_TYPE_MAP = {
    "personne": ["Personne", "Person"],
    "person": ["Person", "Personne"],
    "vélo": ["Vélo", "Bike", "Bicycle"],
    "voiture": ["Voiture", "Car"],
    "camion": ["Camion", "Truck"],
    "moto": ["Moto", "Motorcycle"],
    "bus": ["Bus"],
}


def _expand_bilingual(values: list[str], mapping: dict) -> set[str]:
    """Étend une liste (fr/en) via un mapping bidirectionnel."""
    out = set()
    for v in values or []:
        if not v: continue
        lv = v.lower()
        out.add(lv)
        m = mapping.get(lv)
        if m:
            if isinstance(m, list): out.update(m)
            else: out.add(m)
        for fr, en in mapping.items():
            if isinstance(en, list):
                if lv in [x.lower() for x in en]: out.add(fr)
            elif en == lv:
                out.add(fr)
    return out


async def _base_match(user: dict) -> dict:
    q: dict = {}
    try:
        from routers import site_scope
        site_scope(q, user)
    except Exception:
        pass
    return q


def _apply_time_range(match: dict, f: dict) -> None:
    date_from, date_to = f.get("date_from"), f.get("date_to")
    time_from, time_to = f.get("time_from") or "00:00", f.get("time_to") or "23:59"
    # v1.0-rc4 · « personne à 12h » sans date ⇒ on borne sur AUJOURD'HUI.
    if (f.get("time_from") or f.get("time_to")) and not (date_from or date_to):
        today = datetime.now(timezone.utc).date().isoformat()
        date_from = date_to = today
    if date_from or date_to:
        rng = {}
        if date_from:
            rng["$gte"] = f"{date_from}T{time_from}:00"
        if date_to:
            rng["$lte"] = f"{date_to}T{time_to}:59.999Z"
        match["timestamp"] = rng


# ────────────────────────────────────────────────────────────────
# Recherche VÉHICULES (fondée sur la collection plates)
# ────────────────────────────────────────────────────────────────
async def _search_vehicles(f: dict, user: dict) -> list[dict]:
    match = await _base_match(user)
    if f.get("plate"):
        match["plate"] = {"$regex": _norm_plate(f["plate"]), "$options": "i"}
    if f.get("colors"):
        colors = _expand_bilingual(f["colors"], COLOR_MAP)
        regex = "|".join([f"^{c}$" for c in colors])
        if regex: match["vehicle_color"] = {"$regex": regex, "$options": "i"}
    if f.get("makes"):
        regex = "|".join([f"^{m}$" for m in f["makes"] if m])
        if regex: match["vehicle_make"] = {"$regex": regex, "$options": "i"}
    if f.get("types"):
        # Exclure "personne" du filtre véhicules
        types_v = [t for t in (f["types"] or []) if t and t.lower() not in ("personne", "person")]
        if types_v:
            types = _expand_bilingual(types_v, TYPE_MAP_VEHICLE)
            regex = "|".join([f"^{t}$" for t in types])
            if regex: match["vehicle_type"] = {"$regex": regex, "$options": "i"}
    _apply_time_range(match, f)
    if f.get("camera_hint"):
        match["camera_name"] = {"$regex": f["camera_hint"], "$options": "i"}

    pipe = [
        {"$match": match},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id": "$plate",
            "passages_count": {"$sum": 1},
            "last_seen": {"$first": "$timestamp"}, "first_seen": {"$last": "$timestamp"},
            "cameras": {"$addToSet": "$camera_id"},
            "makes": {"$push": "$vehicle_make"}, "models": {"$push": "$vehicle_model"},
            "colors": {"$push": "$vehicle_color"}, "types": {"$push": "$vehicle_type"},
            "best": {"$first": "$id"},
        }},
        {"$sort": {"last_seen": -1}}, {"$limit": 30},
    ]
    docs = await db.plates.aggregate(pipe).to_list(30)

    def majority(values):
        vv = [v for v in values if v]
        if not vv: return None
        from collections import Counter
        return Counter(vv).most_common(1)[0][0]

    return [{
        "plate": d["_id"], "passages_count": d["passages_count"],
        "first_seen": d.get("first_seen"), "last_seen": d.get("last_seen"),
        "cameras_count": len(d.get("cameras") or []),
        "vehicle_make": majority(d.get("makes") or []),
        "vehicle_model": majority(d.get("models") or []),
        "vehicle_color": majority(d.get("colors") or []),
        "vehicle_type": majority(d.get("types") or []),
        "best_thumb_id": d.get("best"),
    } for d in docs]


# ────────────────────────────────────────────────────────────────
# Recherche PERSONNES / événements humains
# ────────────────────────────────────────────────────────────────
async def _search_persons(f: dict, user: dict) -> list[dict]:
    match = await _base_match(user)
    # Toujours filtrer sur "Personne" (ou variantes anglaises)
    types_expanded = _expand_bilingual(["personne"], EVENT_TYPE_MAP)
    # Si le LLM a précisé d'autres types (« vélo » par exemple), on les ajoute.
    if f.get("types"):
        for t in f["types"]:
            types_expanded |= _expand_bilingual([t], EVENT_TYPE_MAP)
    match["type"] = {"$in": list(types_expanded)}
    _apply_time_range(match, f)
    if f.get("camera_hint"):
        match["camera_name"] = {"$regex": f["camera_hint"], "$options": "i"}

    docs = await db.events.find(
        match, {"_id": 0, "thumbnail": 0}   # on renvoie l'ID pour recharger le crop à la demande
    ).sort("timestamp", -1).limit(60).to_list(60)
    # Réponse : on retourne un descriptif léger + on garde crop_thumbnail
    return [{
        "id": e.get("id"),
        "type": e.get("type"),
        "camera_id": e.get("camera_id"),
        "camera_name": e.get("camera_name"),
        "timestamp": e.get("timestamp"),
        "confidence": e.get("confidence"),
        "crop_thumbnail": e.get("crop_thumbnail"),
    } for e in docs]


# ────────────────────────────────────────────────────────────────
# Recherche ÉVÉNEMENTS (v1.0-rc4 · vue Événements fusionnée)
# Retourne des events COMPLETS (thumbnail, crops, plaque, OCR) pour
# alimenter les fiches événement — tous types confondus.
# ────────────────────────────────────────────────────────────────
async def _search_events(f: dict, user: dict, target: str) -> list[dict]:
    match = await _base_match(user)
    match["type"] = {"$nin": ["qos_alert"]}
    types_expanded: set = set()
    if f.get("types"):
        for t in f["types"]:
            types_expanded |= _expand_bilingual([t], EVENT_TYPE_MAP)
    elif target == "persons":
        types_expanded = _expand_bilingual(["personne"], EVENT_TYPE_MAP)
    elif target == "vehicles":
        for t in ("voiture", "camion", "bus", "moto"):
            types_expanded |= _expand_bilingual([t], EVENT_TYPE_MAP)
    if types_expanded:
        match["type"] = {"$in": list(types_expanded)}
    _apply_time_range(match, f)
    if f.get("camera_hint"):
        match["camera_name"] = {"$regex": f["camera_hint"], "$options": "i"}
    if f.get("plate"):
        match["plate"] = {"$regex": _norm_plate(f["plate"]), "$options": "i"}
    if f.get("colors"):
        match["vehicle_color"] = {"$in": list(_expand_bilingual(f["colors"], COLOR_MAP))}
    return await db.events.find(match, {"_id": 0}) \
        .sort("timestamp", -1).limit(60).to_list(60)


# ────────────────────────────────────────────────────────────────
# Endpoint principal
# ────────────────────────────────────────────────────────────────
@smart_search_router.post("")
async def smart_search(body: SmartQuery,
                        user: dict = Depends(require_permission("read_plates"))):
    q_text = (body.query or "").strip()
    if not q_text:
        raise HTTPException(status_code=400,
                            detail={"error": "empty_query", "message": "Requête vide"})

    filters = await _parse_query_llm(q_text)
    target = (filters.get("target") or "vehicles").lower()

    vehicles: list[dict] = []
    persons:  list[dict] = []

    if target in ("vehicles", "both"):
        vehicles = await _search_vehicles(filters, user)
    if target in ("persons", "both"):
        persons = await _search_persons(filters, user)
    # v1.0-rc4 · Fiches événement complètes pour la vue Événements fusionnée
    events = await _search_events(filters, user, target)

    return {
        "query": q_text,
        "target": target,
        "filters": filters,
        "vehicles_count": len(vehicles),
        "persons_count": len(persons),
        "events_count": len(events),
        "vehicles": vehicles,
        "persons": persons,
        "events": events,
    }
