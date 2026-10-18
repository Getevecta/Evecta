from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.schemas.domain import DomainCreate, DomainRead, DomainUpdate
from app.dependencies.auth import require_role
from app.services.domain_service import (
    create_domain,
    get_domains,
    get_domain_by_id,
    update_domain,
    delete_domain
)

router = APIRouter(prefix="/domains", tags=["Domains"])


@router.post("/", response_model=DomainRead, dependencies=[Depends(require_role("admin"))])
async def create_domain_route(payload: DomainCreate, db: AsyncSession = Depends(get_session)):
    return await create_domain(payload, db)


@router.get("/", response_model=list[DomainRead], dependencies=[Depends(require_role("admin"))])
async def list_domains_route(db: AsyncSession = Depends(get_session)):
    return await get_domains(db)


@router.get("/{domain_id}", response_model=DomainRead, dependencies=[Depends(require_role("admin"))])
async def get_domain_route(domain_id: str, db: AsyncSession = Depends(get_session)):
    domain = await get_domain_by_id(domain_id, db)
    if not domain:
        raise HTTPException(404, "Domain not found")
    return domain


@router.put("/{domain_id}", response_model=DomainRead, dependencies=[Depends(require_role("admin"))])
async def update_domain_route(domain_id: str, payload: DomainUpdate, db: AsyncSession = Depends(get_session)):
    return await update_domain(domain_id, payload, db)


@router.delete("/{domain_id}", dependencies=[Depends(require_role("admin"))])
async def delete_domain_route(domain_id: str, db: AsyncSession = Depends(get_session)):
    await delete_domain(domain_id, db)
    return {"status": "deleted"}
