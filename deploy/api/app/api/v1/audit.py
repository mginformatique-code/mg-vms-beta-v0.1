"""Journal d'audit (lecture seule, admin)."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import AuditLog
from app.schemas import AuditOut

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[AuditOut])
async def list_audit(
    action: str | None = None,
    user_email: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(200, le=2000),
    db: AsyncSession = Depends(get_db),
):
    query = select(AuditLog).order_by(AuditLog.ts.desc()).limit(limit)
    if action:
        query = query.where(AuditLog.action == action)
    if user_email:
        query = query.where(AuditLog.user_email == user_email)
    if start:
        query = query.where(AuditLog.ts >= start)
    if end:
        query = query.where(AuditLog.ts <= end)
    return (await db.scalars(query)).all()
