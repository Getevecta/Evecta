from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.models.company import Company
from app.schemas.company import CompanyCreate, CompanyUpdate


# GET COMPANY BY USER ID
async def get_company_by_user_id(db: AsyncSession, user_id: str):
    try:
        result = await db.execute(
            select(Company).where(Company.user_id == user_id)
        )
        return result.scalar_one_or_none()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred. Please try again."
        )


# GET COMPANY BY ID (ensure owner)
async def get_company_by_id(db: AsyncSession, company_id: str, user_id: str):
    try:
        result = await db.execute(
            select(Company).where(
                Company.id == company_id,
                Company.user_id == user_id
            )
        )
        company = result.scalar_one_or_none()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred. Please try again."
        )

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found."
        )

    return company


# CREATE COMPANY (final submit)
async def create_company(db: AsyncSession, payload: CompanyCreate, user_id: str):

    # Prevent duplicate company
    try:
        existing = await get_company_by_user_id(db, user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Failed to save company details. Please try again."
        )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company profile already exists for this user."
        )

    try:
        company = Company(
            user_id=user_id,
            **payload.model_dump(exclude_unset=True)
        )

        db.add(company)
        await db.commit()
        await db.refresh(company)
        return company

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save company details. Please try again."
        )


# UPDATE COMPANY (profile or scraper)
async def update_company(db: AsyncSession, company_id: str, user_id: str, payload: CompanyUpdate):

    try:
        company = await get_company_by_id(db, company_id, user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Failed to save company details. Please try again."
        )

    update_data = payload.model_dump(exclude_unset=True)

    try:
        for key, value in update_data.items():
            setattr(company, key, value)

        await db.commit()
        await db.refresh(company)
        return company

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save company details. Please try again."
        )
