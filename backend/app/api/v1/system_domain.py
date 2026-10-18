from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone
from sqlalchemy.exc import SQLAlchemyError
from uuid import UUID

from app.database.session import get_session
from app.models.domain import Domain
from app.models.mailbox import Mailbox, MailboxType
from app.schemas.system_domain import SystemDomainCreate, SystemDomainUpdate
from app.dependencies.auth import require_role

router = APIRouter(
    prefix="/system/domains",
    tags=["System · Domains"],
)


async def _get_domain(db: AsyncSession, domain_id: str) -> Domain:
    try:
        did = UUID(str(domain_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid domain id") from exc

    domain = await db.get(Domain, did)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    return domain


@router.post("/", dependencies=[Depends(require_role("admin"))])
async def create_system_domain(
    payload: SystemDomainCreate,
    db: AsyncSession = Depends(get_session),
):
    try:
        existing = await db.scalar(
            select(Domain).where(Domain.domain_name == payload.name)
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Domain already exists"
            )

        domain = Domain(
            domain_name=payload.name,
            daily_limit=payload.daily_limit,
            sent_today=0,
            is_active=True,
            last_used=datetime.now(timezone.utc),
        )

        db.add(domain)
        await db.commit()
        await db.refresh(domain)

        return domain

    except HTTPException:
        raise

    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Database error while creating domain",
        )


@router.get("/", dependencies=[Depends(require_role("admin"))])
async def list_system_domains(
    db: AsyncSession = Depends(get_session),
):
    try:
        result = await db.execute(
            select(Domain).order_by(Domain.last_used.desc())
        )
        return result.scalars().all()

    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=500,
            detail="Database error while fetching domains",
        ) from e

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Unexpected error occurred",
        ) from e


@router.put("/{domain_id}", dependencies=[Depends(require_role("admin"))])
async def update_system_domain(
    domain_id: str,
    payload: SystemDomainUpdate,
    db: AsyncSession = Depends(get_session),
):
    try:
        domain = await _get_domain(db, domain_id)
        data = payload.model_dump(exclude_unset=True)

        if "name" in data and data["name"]:
            clash = await db.scalar(
                select(Domain.id).where(
                    Domain.domain_name == data["name"],
                    Domain.id != domain.id,
                )
            )
            if clash:
                raise HTTPException(status_code=400, detail="Domain already exists")
            domain.domain_name = data["name"]

        if "daily_limit" in data and data["daily_limit"] is not None:
            used_limit = await db.scalar(
                select(func.coalesce(func.sum(Mailbox.daily_limit), 0)).where(
                    Mailbox.domain_id == domain.id,
                    Mailbox.mailbox_type == MailboxType.SYSTEM,
                )
            ) or 0
            if used_limit > data["daily_limit"]:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Domain daily limit ({data['daily_limit']}) is below "
                        f"mailbox limits already allocated ({used_limit})"
                    ),
                )
            domain.daily_limit = data["daily_limit"]

        if "is_active" in data and data["is_active"] is not None:
            domain.is_active = data["is_active"]

        domain.last_used = datetime.now(timezone.utc)
        db.add(domain)
        await db.commit()
        await db.refresh(domain)
        return domain

    except HTTPException:
        raise
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Database error while updating domain",
        )


@router.delete("/{domain_id}", dependencies=[Depends(require_role("admin"))])
async def delete_system_domain(
    domain_id: str,
    db: AsyncSession = Depends(get_session),
):
    try:
        domain = await _get_domain(db, domain_id)
        await db.delete(domain)
        await db.commit()
        return {"status": "deleted"}

    except HTTPException:
        raise
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Database error while deleting domain",
        )
