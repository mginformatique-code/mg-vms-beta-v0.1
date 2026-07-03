"""Plans de sites (cartes/floor plans) et positionnement des caméras."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_tech
from app.db.session import get_db
from app.models import FloorPlan, User
from app.schemas import FloorPlanIn, FloorPlanOut

router = APIRouter(prefix="/maps", tags=["maps"])


@router.get("", response_model=list[FloorPlanOut])
async def list_plans(site_id: UUID | None = None, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    query = select(FloorPlan)
    if site_id:
        query = query.where(FloorPlan.site_id == site_id)
    return (await db.scalars(query)).all()


@router.post("", response_model=FloorPlanOut, status_code=201)
async def create_plan(body: FloorPlanIn, user: User = Depends(require_tech), db: AsyncSession = Depends(get_db)):
    plan = FloorPlan(**body.model_dump())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.patch("/{plan_id}", response_model=FloorPlanOut)
async def update_plan(plan_id: UUID, body: FloorPlanIn, user: User = Depends(require_tech),
                      db: AsyncSession = Depends(get_db)):
    plan = await db.get(FloorPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan introuvable")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(plan, key, value)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.delete("/{plan_id}", status_code=204)
async def delete_plan(plan_id: UUID, user: User = Depends(require_tech), db: AsyncSession = Depends(get_db)):
    plan = await db.get(FloorPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan introuvable")
    await db.delete(plan)
    await db.commit()
