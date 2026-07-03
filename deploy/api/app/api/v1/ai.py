"""IA : règles de détection (intrusion, ligne, objets, LAPI) + analytics + recherche intelligente."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_permission, require_tech
from app.db.session import get_db
from app.models import AIRule, Event, Plate, User
from app.schemas import AIRuleIn, AIRuleOut

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/rules", response_model=list[AIRuleOut])
async def list_rules(camera_id: UUID | None = None, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    query = select(AIRule).order_by(AIRule.created_at)
    if camera_id:
        query = query.where(AIRule.camera_id == camera_id)
    return (await db.scalars(query)).all()


@router.post("/rules", response_model=AIRuleOut, status_code=201)
async def create_rule(body: AIRuleIn, user: User = Depends(require_tech), db: AsyncSession = Depends(get_db)):
    rule = AIRule(**body.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/rules/{rule_id}", response_model=AIRuleOut)
async def update_rule(rule_id: UUID, body: dict, user: User = Depends(require_tech),
                      db: AsyncSession = Depends(get_db)):
    rule = await db.get(AIRule, rule_id)
    if not rule:
        raise HTTPException(404, "Règle introuvable")
    for key in ("name", "config", "enabled"):
        if key in body:
            setattr(rule, key, body[key])
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: UUID, user: User = Depends(require_tech), db: AsyncSession = Depends(get_db)):
    rule = await db.get(AIRule, rule_id)
    if not rule:
        raise HTTPException(404, "Règle introuvable")
    await db.delete(rule)
    await db.commit()


@router.get("/plates")
async def search_plates(
    q: str | None = None,
    site_id: UUID | None = None,
    list_status: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(100, le=1000),
    user: User = Depends(require_permission("read_anpr")),
    db: AsyncSession = Depends(get_db),
):
    """Recherche LAPI (plaques) — recherche partielle insensible à la casse."""
    query = select(Plate).order_by(Plate.ts.desc()).limit(limit)
    if q:
        query = query.where(Plate.plate.ilike(f"%{q.upper()}%"))
    if site_id:
        query = query.where(Plate.site_id == site_id)
    if list_status:
        query = query.where(Plate.list_status == list_status)
    if start:
        query = query.where(Plate.ts >= start)
    if end:
        query = query.where(Plate.ts <= end)
    rows = (await db.scalars(query)).all()
    return [{
        "id": str(p.id), "plate": p.plate, "camera_id": str(p.camera_id), "site_id": str(p.site_id),
        "confidence": p.confidence, "country": p.country, "vehicle_make": p.vehicle_make,
        "vehicle_model": p.vehicle_model, "vehicle_color": p.vehicle_color, "vehicle_type": p.vehicle_type,
        "direction": p.direction, "list_status": p.list_status, "image_url": p.image_url,
        "ts": p.ts.isoformat(),
    } for p in rows]


@router.get("/analytics/summary")
async def analytics_summary(days: int = Query(7, le=90), user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    """Agrégats : événements par type et par jour (dashboards)."""
    by_type = (await db.execute(
        select(Event.type, func.count()).group_by(Event.type)
        .where(Event.ts >= func.now() - func.make_interval(0, 0, 0, days))
    )).all()
    by_day = (await db.execute(
        select(func.date_trunc("day", Event.ts).label("day"), func.count())
        .group_by("day").order_by("day")
        .where(Event.ts >= func.now() - func.make_interval(0, 0, 0, days))
    )).all()
    return {
        "by_type": {t: c for t, c in by_type},
        "by_day": [{"day": d.date().isoformat(), "count": c} for d, c in by_day],
    }
