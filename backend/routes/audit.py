"""Route module — Audit log.
Extrait de `routers.py` (P1 modularisation, Feb 2026).
"""
from fastapi import APIRouter, Depends, Response

from auth import require_role
from database import db

audit_router = APIRouter(prefix="/api", tags=["audit"])


@audit_router.get("/audit")
async def list_audit(response: Response, limit: int = 100, offset: int = 0,
                     user: dict = Depends(require_role("technician"))):
    total = await db.audit_logs.count_documents({})
    response.headers["X-Total-Count"] = str(total)
    return await db.audit_logs.find({}, {"_id": 0}).sort("timestamp", -1).skip(offset).limit(limit).to_list(limit)
