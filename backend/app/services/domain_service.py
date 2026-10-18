import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException

from app.models.domain import Domain
from app.schemas.domain import DomainCreate, DomainUpdate

logger = logging.getLogger(__name__)


async def create_domain(payload: DomainCreate, db: AsyncSession):
    try:
        domain = Domain(**payload.dict())
        db.add(domain)
        await db.commit()
        await db.refresh(domain)
        return domain

    except SQLAlchemyError:
        await db.rollback()
        logger.exception("DB error creating domain")
        raise HTTPException(status_code=500, detail="Failed to create domain. Please try again.")

    except Exception:
        await db.rollback()
        logger.exception("Unexpected error creating domain")
        raise HTTPException(status_code=500, detail="An unexpected error occurred. Please try again.")


async def get_domains(db: AsyncSession):
    try:
        stmt = select(Domain).order_by(Domain.domain_name)
        return (await db.scalars(stmt)).all()

    except SQLAlchemyError:
        logger.exception("DB error fetching domains")
        raise HTTPException(status_code=500, detail="Failed to fetch domains. Please try again.")

    except Exception:
        logger.exception("Unexpected error fetching domains")
        raise HTTPException(status_code=500, detail="An unexpected error occurred. Please try again.")


async def get_domain_by_id(domain_id: str, db: AsyncSession):
    try:
        domain = await db.get(Domain, domain_id)
        return domain

    except SQLAlchemyError:
        logger.exception("DB error fetching domain %s", domain_id)
        raise HTTPException(status_code=500, detail="Failed to fetch domain. Please try again.")

    except Exception:
        logger.exception("Unexpected error fetching domain %s", domain_id)
        raise HTTPException(status_code=500, detail="An unexpected error occurred. Please try again.")


async def update_domain(domain_id: str, payload: DomainUpdate, db: AsyncSession):
    try:
        domain = await db.get(Domain, domain_id)
        if not domain:
            raise HTTPException(404, "Domain not found")

        for key, value in payload.dict(exclude_none=True).items():
            setattr(domain, key, value)

        db.add(domain)
        await db.commit()
        await db.refresh(domain)
        return domain

    except HTTPException:
        raise

    except SQLAlchemyError:
        await db.rollback()
        logger.exception("DB error updating domain %s", domain_id)
        raise HTTPException(status_code=500, detail="Failed to update domain. Please try again.")

    except Exception:
        await db.rollback()
        logger.exception("Unexpected error updating domain %s", domain_id)
        raise HTTPException(status_code=500, detail="An unexpected error occurred. Please try again.")


async def delete_domain(domain_id: str, db: AsyncSession):
    try:
        domain = await db.get(Domain, domain_id)
        if not domain:
            raise HTTPException(404, "Domain not found")

        await db.delete(domain)
        await db.commit()
        return True

    except HTTPException:
        raise

    except SQLAlchemyError:
        await db.rollback()
        logger.exception("DB error deleting domain %s", domain_id)
        raise HTTPException(status_code=500, detail="Failed to delete domain. Please try again.")

    except Exception:
        await db.rollback()
        logger.exception("Unexpected error deleting domain %s", domain_id)
        raise HTTPException(status_code=500, detail="An unexpected error occurred. Please try again.")
