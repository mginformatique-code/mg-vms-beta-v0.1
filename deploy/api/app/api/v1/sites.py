"""Organisations (multi-tenant) et sites."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models import Organization, Site, User, UserSite
from app.schemas import OrgIn, OrgOut, SiteIn, SiteOut

router = APIRouter(tags=["organizations", "sites"])


@router.get("/organizations", response_model=list[OrgOut])
async def list_orgs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Organization).order_by(Organization.name))).all()


@router.post("/organizations", response_model=OrgOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_org(body: OrgIn, db: AsyncSession = Depends(get_db)):
    org = Organization(name=body.name)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@router.delete("/organizations/{org_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_org(org_id: UUID, db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organisation introuvable")
    await db.delete(org)
    await db.commit()


@router.get("/sites", response_model=list[SiteOut])
async def list_sites(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = select(Site).order_by(Site.name)
    if user.role.level > 1:  # non-admin : restreint aux sites assignés
        query = query.join(UserSite, UserSite.site_id == Site.id).where(UserSite.user_id == user.id)
    return (await db.scalars(query)).all()


@router.post("/sites", response_model=SiteOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_site(body: SiteIn, db: AsyncSession = Depends(get_db)):
    site = Site(**body.model_dump())
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return site


@router.patch("/sites/{site_id}", response_model=SiteOut, dependencies=[Depends(require_admin)])
async def update_site(site_id: UUID, body: SiteIn, db: AsyncSession = Depends(get_db)):
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Site introuvable")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(site, key, value)
    await db.commit()
    await db.refresh(site)
    return site


@router.delete("/sites/{site_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_site(site_id: UUID, db: AsyncSession = Depends(get_db)):
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Site introuvable")
    await db.delete(site)
    await db.commit()
