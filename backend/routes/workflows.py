"""Route module — Workflow Engine CRUD + manual run (P4, Feb 2026)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_permission, log_audit
from database import db
from workflow_engine import engine as wf_engine

workflows_router = APIRouter(prefix="/api", tags=["workflows"])


class WorkflowInput(BaseModel):
    name: str
    enabled: bool = True
    triggers: list[dict[str, Any]] = Field(default_factory=list)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    description: str = ""


def _new_doc(inp: WorkflowInput) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": inp.name, "enabled": inp.enabled,
        "description": inp.description,
        "triggers": inp.triggers, "conditions": inp.conditions, "actions": inp.actions,
        "execution_count": 0,
        "last_run_at": None, "last_status": "idle",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@workflows_router.get("/workflows")
async def list_workflows(user: dict = Depends(require_permission("view_live"))):
    docs = await db.workflows.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    # Fusionne stats runtime
    for d in docs:
        d["runtime"] = wf_engine.stats(d["id"])
    return {"workflows": docs, "count": len(docs)}


@workflows_router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, user: dict = Depends(require_permission("view_live"))):
    doc = await db.workflows.find_one({"id": workflow_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Workflow introuvable")
    doc["runtime"] = wf_engine.stats(workflow_id)
    return doc


@workflows_router.post("/workflows")
async def create_workflow(data: WorkflowInput,
                           user: dict = Depends(require_permission("technician"))):
    doc = _new_doc(data)
    await db.workflows.insert_one(dict(doc))
    wf_engine.invalidate_cache()
    await log_audit(user, "workflow_created", data.name)
    return doc


@workflows_router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, data: WorkflowInput,
                           user: dict = Depends(require_permission("technician"))):
    patch = {"name": data.name, "enabled": data.enabled, "description": data.description,
             "triggers": data.triggers, "conditions": data.conditions, "actions": data.actions}
    r = await db.workflows.update_one({"id": workflow_id}, {"$set": patch})
    if r.matched_count == 0:
        raise HTTPException(404, "Workflow introuvable")
    wf_engine.invalidate_cache()
    await log_audit(user, "workflow_updated", data.name)
    return await db.workflows.find_one({"id": workflow_id}, {"_id": 0})


@workflows_router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str,
                           user: dict = Depends(require_permission("technician"))):
    r = await db.workflows.delete_one({"id": workflow_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Workflow introuvable")
    wf_engine.invalidate_cache()
    await log_audit(user, "workflow_deleted", workflow_id)
    return {"ok": True}


@workflows_router.post("/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str, payload: dict | None = None,
                        user: dict = Depends(require_permission("technician"))):
    """Lance manuellement le workflow avec un contexte optionnel."""
    result = await wf_engine.run_manual(workflow_id, payload or {})
    if not result.get("ok", True) and "error" in result:
        raise HTTPException(400, result["error"])
    await log_audit(user, "workflow_manual_run", workflow_id)
    return result
