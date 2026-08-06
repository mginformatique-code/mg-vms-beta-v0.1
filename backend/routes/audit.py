"""Route module — Audit log.
Extrait de `routers.py` (P1 modularisation, Feb 2026).
"""
from fastapi import APIRouter, Depends, Response

from auth import require_permission
from database import db

audit_router = APIRouter(prefix="/api", tags=["audit"])


@audit_router.get("/audit")
async def list_audit(response: Response, limit: int = 100, offset: int = 0,
                     action_prefix: str | None = None,
                     user: dict = Depends(require_permission("view_audit_log"))):
    """Liste les entrées d'audit, avec filtre optionnel `action_prefix`
    (ex ?action_prefix=rbac_ pour ne récupérer que les changements RBAC).
    """
    q: dict = {}
    if action_prefix:
        q["action"] = {"$regex": f"^{action_prefix}"}
    total = await db.audit_logs.count_documents(q)
    response.headers["X-Total-Count"] = str(total)
    return await db.audit_logs.find(q, {"_id": 0}).sort("timestamp", -1).skip(offset).limit(limit).to_list(limit)
