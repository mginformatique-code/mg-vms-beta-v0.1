"""v3.27 · Suggestions de fusion d'identités CONFIRMÉES, assistées par Qwen.

Demande explicite, suite au bouton "Tout sélectionner" (fusion 100%
manuelle, jamais automatique — voir vehicles.py::merge_identities) de la
fenêtre "Fusion & identités véhicule (IA)" : "peut-on l'automatiser de
manière intelligente ? avec une lecture IA ?"

Même architecture que vehicle_dedup.py (candidats par distance d'édition,
Qwen juge au cas par cas, jamais de fusion automatique sans validation —
sauf auto-approbation optionnelle, désactivée par défaut, réglage
indépendant), mais au niveau IDENTITÉ déjà confirmée plutôt que plaque
brute : compare les plaques d'une identité contre celles d'une autre
identité déjà existante (315 identités mesurées en prod → ~49k paires,
comparaison de chaînes courtes, negligeable en coût CPU ; seul le nombre
d'appels Qwen est budgétisé par run).

Une fusion acceptée réutilise TEL QUEL `vehicles.py::merge_identities`
(même garde-fou de taille `_MAX_PLAUSIBLE_FAMILY_SIZE`, même logique de
survivant) plutôt que de dupliquer cette logique.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_permission, require_role, log_audit
from database import db

logger = logging.getLogger("routes.identity_merge_ai")

identity_merge_ai_router = APIRouter(prefix="/api/vehicles/identities/merge-ai", tags=["identity-merge-ai"])

_MAX_DISTANCE = 3
_MAX_CANDIDATES_PER_RUN = 40
_MAX_PAIRS_PER_IDENTITY_PER_RUN = 3
_BATCH_INTERVAL_HOURS = 24
# Même garde-fou que vehicles.py::_MAX_PLAUSIBLE_FAMILY_SIZE — inutile de
# générer un candidat qu'un accept rejetterait de toute façon.
_MAX_PLAUSIBLE_FAMILY_SIZE = 8
_AUTO_APPROVE_POLL_S = 60
_AUTO_APPROVE_ACTOR = "Auto-approbation fusion identités (IA)"


def _levenshtein(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > _MAX_DISTANCE:
        return 99
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (ca != cb))
            prev = cur
    return dp[-1]


def _iso_to_ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _min_plate_distance(plates_a: list[str], plates_b: list[str]) -> int:
    best = 99
    for p1 in plates_a:
        for p2 in plates_b:
            if abs(len(p1) - len(p2)) > _MAX_DISTANCE:
                continue
            d = _levenshtein(p1, p2)
            if d < best:
                best = d
    return best


async def _identity_sample_thumb(plates: list[str]) -> str | None:
    """id d'une lecture récente avec photo, pour permettre au frontend un
    comparatif visuel (même principe que vehicle_dedup.py::_plate_stats —
    demande explicite après un premier cas réel où deux plaques proches
    textuellement s'avéraient être deux véhicules visiblement différents,
    invisible sur le seul texte/attributs)."""
    if not plates:
        return None
    doc = await db.plates.find(
        {"plate": {"$in": plates}, "vehicle_crop": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "timestamp": 1},
    ).sort("timestamp", -1).limit(1).to_list(1)
    return doc[0]["id"] if doc else None


async def _already_suggested_pairs() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    async for s in db.identity_merge_suggestions.find({}, {"_id": 0, "identity_a_id": 1, "identity_b_id": 1}):
        pairs.add(tuple(sorted((s["identity_a_id"], s["identity_b_id"]))))
    return pairs


async def _find_candidates(limit: int = _MAX_CANDIDATES_PER_RUN) -> list[tuple[dict, dict, int]]:
    """Paires (identité_a, identité_b, distance min. entre leurs plaques),
    triées par distance croissante puis diversifiées pour qu'une identité
    très fragmentée en variantes ne monopolise pas tout le budget du run
    (même logique que vehicle_dedup.py::_find_candidates)."""
    identities = await db.vehicle_identities.find(
        {}, {"_id": 0, "id": 1, "name": 1, "plates": 1, "vehicle_make": 1, "vehicle_color": 1},
    ).to_list(5000)
    seen_pairs = await _already_suggested_pairs()

    candidates: list[tuple[dict, dict, int]] = []
    for i, a in enumerate(identities):
        for b in identities[i + 1:]:
            key = tuple(sorted((a["id"], b["id"])))
            if key in seen_pairs:
                continue
            if len(set(a.get("plates") or []) | set(b.get("plates") or [])) > _MAX_PLAUSIBLE_FAMILY_SIZE:
                continue
            dist = _min_plate_distance(a.get("plates") or [], b.get("plates") or [])
            if dist <= _MAX_DISTANCE:
                candidates.append((a, b, dist))
    candidates.sort(key=lambda c: c[2])

    per_identity: dict[str, int] = {}
    out: list[tuple[dict, dict, int]] = []
    for c in candidates:
        a, b, _dist = c
        if (per_identity.get(a["id"], 0) >= _MAX_PAIRS_PER_IDENTITY_PER_RUN
                or per_identity.get(b["id"], 0) >= _MAX_PAIRS_PER_IDENTITY_PER_RUN):
            continue
        out.append(c)
        per_identity[a["id"]] = per_identity.get(a["id"], 0) + 1
        per_identity[b["id"]] = per_identity.get(b["id"], 0) + 1
        if len(out) >= limit:
            break
    return out


async def _ask_qwen_same_identity(a: dict, b: dict, min_distance: int) -> dict:
    from routes.llm_settings import get_active_llm_config
    cfg = await get_active_llm_config()
    if not cfg:
        raise HTTPException(status_code=503, detail={"code": "IDENTITY_MERGE_AI_LLM_NOT_CONFIGURED",
                                                        "message": "LLM non configuré (Administration → LLM)."})
    import httpx
    schema = {
        "type": "object",
        "properties": {
            "same_vehicle": {"type": "string", "enum": ["oui", "non"]},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["same_vehicle", "confidence", "reason"],
    }
    system = (
        "Tu compares deux identités véhicule déjà créées dans un système de vidéosurveillance ANPR. "
        "Réponds UNIQUEMENT avec un objet JSON valide respectant EXACTEMENT ce schéma : "
        '{"same_vehicle": "oui"|"non", "confidence": nombre entre 0 et 1, "reason": texte court}. '
        "Aucun texte hors JSON."
    )
    prompt = (
        f"Identité A \"{a['name']}\" — plaques : {', '.join(a.get('plates') or [])}, "
        f"marque={a.get('vehicle_make') or 'inconnue'}, couleur={a.get('vehicle_color') or 'inconnue'}.\n"
        f"Identité B \"{b['name']}\" — plaques : {', '.join(b.get('plates') or [])}, "
        f"marque={b.get('vehicle_make') or 'inconnue'}, couleur={b.get('vehicle_color') or 'inconnue'}.\n"
        f"Distance d'édition minimale entre une plaque de A et une plaque de B : {min_distance} "
        "(confusions OCR courantes : 0/O, 1/I, 5/S, 8/B, 2/Z). Ces deux identités représentent-elles "
        "probablement le MÊME véhicule (plaques mal lues différemment à chaque fusion précédente) ? "
        "Une marque ou une couleur incohérente entre A et B est un signal FORT que ce sont deux "
        "véhicules distincts, pas le même mal lu deux fois."
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
    from llm_call_log import log_llm_call
    _t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
    except Exception as e:
        await log_llm_call(source="identity_merge_ai", url=url, model=payload.get("model"), request_payload=payload,
                            status_code=getattr(getattr(e, "response", None), "status_code", None),
                            error=f"{type(e).__name__}: {e}", latency_ms=int((time.monotonic() - _t0) * 1000))
        raise
    await log_llm_call(source="identity_merge_ai", url=url, model=payload.get("model"), request_payload=payload,
                        status_code=resp.status_code, response_body=body,
                        latency_ms=int((time.monotonic() - _t0) * 1000))
    raw = (body["choices"][0]["message"]["content"] or "").strip()
    if "<think>" in raw:
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    parsed = json.loads(raw)
    return {
        "same_vehicle": parsed.get("same_vehicle") == "oui",
        "confidence": parsed.get("confidence"),
        "reason": parsed.get("reason", ""),
    }


async def _run_identity_merge_batch(limit: int = _MAX_CANDIDATES_PER_RUN) -> int:
    candidates = await _find_candidates(limit)
    created = 0
    for a, b, dist in candidates:
        try:
            verdict = await _ask_qwen_same_identity(a, b, dist)
        except Exception:
            logger.exception("identity_merge_ai: échec comparaison %s / %s", a["id"], b["id"])
            continue
        # v3.27.1 · Comparatif photo — demande explicite après un cas réel où
        # deux plaques proches textuellement (confusion OCR plausible)
        # correspondaient à deux véhicules visiblement DIFFÉRENTS sur les
        # crops réels. Uniquement pour les suggestions retenues (jamais
        # gaspillé sur celles que Qwen vient de rejeter).
        sample_a = sample_b = None
        if verdict.get("same_vehicle"):
            sample_a = await _identity_sample_thumb(a.get("plates") or [])
            sample_b = await _identity_sample_thumb(b.get("plates") or [])
        doc = {
            "id": str(uuid.uuid4()),
            "identity_a_id": a["id"], "identity_a_name": a["name"], "identity_a_plates": a.get("plates") or [],
            "identity_a_sample_plate_id": sample_a,
            "identity_b_id": b["id"], "identity_b_name": b["name"], "identity_b_plates": b.get("plates") or [],
            "identity_b_sample_plate_id": sample_b,
            "min_distance": dist,
            "same_vehicle": bool(verdict.get("same_vehicle")),
            "confidence": verdict.get("confidence"),
            "reason": verdict.get("reason", ""),
            # Même convention que vehicle_dedup.py : toute paire comparée est
            # enregistrée (jamais redemandée le lendemain), seules celles
            # jugées "même véhicule" passent en "pending" (visibles en revue).
            "status": "pending" if verdict.get("same_vehicle") else "auto_rejected",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.identity_merge_suggestions.insert_one(doc)
        if doc["status"] == "pending":
            created += 1
    return created


async def identity_merge_ai_batch_loop() -> None:
    from routes.llm_settings import is_feature_enabled
    await asyncio.sleep(180)
    while True:
        if await is_feature_enabled("identity_merge_ai_enabled"):
            try:
                n = await _run_identity_merge_batch()
                if n:
                    logger.info("identity_merge_ai: %s suggestion(s) générée(s)", n)
            except Exception:
                logger.exception("identity_merge_ai: erreur boucle identity_merge_ai_batch_loop")
        await asyncio.sleep(_BATCH_INTERVAL_HOURS * 3600)


@identity_merge_ai_router.post("/run")
async def run_now(user: dict = Depends(require_role("admin"))):
    from routes.llm_settings import is_feature_enabled
    if not await is_feature_enabled("identity_merge_ai_enabled"):
        raise HTTPException(status_code=400, detail={
            "code": "IDENTITY_MERGE_AI_DISABLED",
            "message": "Fusion identités IA désactivée — Administration → LLM (MG-IA).",
        })

    async def _run_bg():
        try:
            n = await _run_identity_merge_batch()
            logger.info("identity_merge_ai: recherche manuelle terminée, %s suggestion(s)", n)
        except Exception:
            logger.exception("identity_merge_ai: erreur pendant la recherche manuelle")
    asyncio.create_task(_run_bg())
    await log_audit(user, "identity_merge_ai_run_started", "lancée en arrière-plan")
    return {"started": True}


@identity_merge_ai_router.get("/suggestions")
async def list_suggestions(status: str = "pending", user: dict = Depends(require_permission("read_plates"))):
    q = {} if status == "all" else {"status": status}
    docs = await db.identity_merge_suggestions.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"count": len(docs), "items": docs}


class MergeAiDecision(BaseModel):
    name: str = ""


async def _accept_suggestion_doc(sugg: dict, name: str, user: dict | None) -> dict:
    """Réutilise TEL QUEL vehicles.py::merge_identities (même garde-fou de
    taille, même logique de survivant) — jamais de logique de fusion
    dupliquée. `user=None` pour l'auto-approbation (log_audit tolère déjà
    None, voir auth.py::log_audit)."""
    from routes.vehicles import merge_identities, IdentityMergeBody
    body = IdentityMergeBody(identity_ids=[sugg["identity_a_id"], sugg["identity_b_id"]], name=name)
    merged = await merge_identities(body, user=user)
    now = datetime.now(timezone.utc).isoformat()
    await db.identity_merge_suggestions.update_one(
        {"id": sugg["id"]},
        {"$set": {"status": "accepted",
                   "reviewed_by": (user or {}).get("email", _AUTO_APPROVE_ACTOR), "reviewed_at": now}},
    )
    return merged


@identity_merge_ai_router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion(suggestion_id: str, body: MergeAiDecision = MergeAiDecision(),
                             user: dict = Depends(require_permission("read_plates"))):
    sugg = await db.identity_merge_suggestions.find_one({"id": suggestion_id}, {"_id": 0})
    if not sugg:
        raise HTTPException(404, "Suggestion introuvable")
    merged = await _accept_suggestion_doc(sugg, body.name, user)
    await log_audit(user, "identity_merge_ai_accepted", f"{sugg['identity_a_id']} + {sugg['identity_b_id']}")
    return merged


@identity_merge_ai_router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(suggestion_id: str, user: dict = Depends(require_permission("read_plates"))):
    now = datetime.now(timezone.utc).isoformat()
    res = await db.identity_merge_suggestions.update_one(
        {"id": suggestion_id},
        {"$set": {"status": "rejected", "reviewed_by": user.get("email"), "reviewed_at": now}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Suggestion introuvable")
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════
# Auto-approbation périodique optionnelle — même principe que
# vehicle_dedup.py::dedup_auto_approve_loop, réglage totalement
# indépendant (désactivé par défaut) : la génération de suggestions
# (ci-dessus) n'implique jamais de fusion automatique par elle-même.
# ═══════════════════════════════════════════════════════════════════
async def _run_auto_approve() -> int:
    pending = await db.identity_merge_suggestions.find({"status": "pending"}, {"_id": 0}).to_list(1000)
    n = 0
    for sugg in pending:
        try:
            await _accept_suggestion_doc(sugg, "", None)
            n += 1
        except Exception:
            logger.exception("identity_merge_ai: auto-approve — échec sur suggestion %s", sugg.get("id"))
    return n


async def _maybe_auto_approve() -> None:
    from routes.llm_settings import is_feature_enabled, get_identity_merge_ai_auto_approve_settings
    if not await is_feature_enabled("identity_merge_ai_enabled"):
        return
    cfg = await get_identity_merge_ai_auto_approve_settings()
    if not cfg["enabled"]:
        return
    state = (await db.settings.find_one({"key": "identity_merge_ai_auto_approve_state"}, {"_id": 0}) or {}).get("value") or {}
    last_run = _iso_to_ts(state.get("last_run_at"))
    if last_run is not None and (datetime.now(timezone.utc).timestamp() - last_run) < cfg["interval_min"] * 60:
        return
    n = await _run_auto_approve()
    await db.settings.update_one(
        {"key": "identity_merge_ai_auto_approve_state"},
        {"$set": {"key": "identity_merge_ai_auto_approve_state",
                   "value": {"last_run_at": datetime.now(timezone.utc).isoformat(), "approved_count": n}}},
        upsert=True,
    )
    if n:
        logger.info("identity_merge_ai: auto-approve — %d fusion(s) approuvée(s) automatiquement", n)


async def identity_merge_ai_auto_approve_loop() -> None:
    await asyncio.sleep(90)
    while True:
        try:
            await _maybe_auto_approve()
        except Exception:
            logger.exception("identity_merge_ai: erreur boucle identity_merge_ai_auto_approve_loop")
        await asyncio.sleep(_AUTO_APPROVE_POLL_S)


@identity_merge_ai_router.get("/auto-approve/status")
async def auto_approve_status(user: dict = Depends(require_permission("read_plates"))):
    from routes.llm_settings import get_identity_merge_ai_auto_approve_settings
    cfg = await get_identity_merge_ai_auto_approve_settings()
    state = (await db.settings.find_one({"key": "identity_merge_ai_auto_approve_state"}, {"_id": 0}) or {}).get("value") or {}
    last_run = state.get("last_run_at")
    next_run = None
    if cfg["enabled"] and last_run:
        ts = _iso_to_ts(last_run)
        if ts is not None:
            next_run = datetime.fromtimestamp(ts + cfg["interval_min"] * 60, tz=timezone.utc).isoformat()
    pending_count = await db.identity_merge_suggestions.count_documents({"status": "pending"})
    return {
        "enabled": cfg["enabled"],
        "interval_min": cfg["interval_min"],
        "last_run_at": last_run,
        "last_approved_count": state.get("approved_count"),
        "next_run_at": next_run,
        "pending_count": pending_count,
    }
