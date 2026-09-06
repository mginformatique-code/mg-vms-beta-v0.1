"""v3.27 · Menu « Logs LLM » (remplace « Log ANPR », qui n'affichait qu'un
tableau statique sans aucun lien avec l'IA — demande explicite). Expose en
lecture le journal détaillé alimenté par `llm_call_log.log_llm_call()`,
appelé par chaque plugin IA (couleur, marque, anomalies, dédoublonnage,
réglage ANPR, recherche IA) : un doc par appel réseau vers Qwen, succès ou
échec, avec latence et corps tronqué — pensé pour le debug.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from auth import require_role
from database import db

llm_logs_router = APIRouter(prefix="/api/llm-logs", tags=["llm-logs"])


def _serialize(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    ts = doc.get("ts")
    if hasattr(ts, "isoformat"):
        doc["ts"] = ts.isoformat()
    return doc


@llm_logs_router.get("")
async def list_llm_logs(
    limit: int = Query(100, ge=1, le=500),
    source: str | None = None,
    status: str | None = Query(None, description="ok | error"),
    user: dict = Depends(require_role("admin")),
):
    query: dict = {}
    if source:
        query["source"] = source
    if status == "ok":
        query["ok"] = True
    elif status == "error":
        query["ok"] = False
    cursor = db.llm_call_logs.find(query).sort("ts", -1).limit(limit)
    items = [_serialize(d) async for d in cursor]
    return {"items": items}


@llm_logs_router.get("/sources")
async def list_llm_log_sources(user: dict = Depends(require_role("admin"))):
    sources = await db.llm_call_logs.distinct("source")
    return {"sources": sorted(sources)}
