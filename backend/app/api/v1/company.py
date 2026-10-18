from fastapi import APIRouter, Depends, HTTPException, Request, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services.company_scraper_worker import process_company_website_async
from app.schemas.company import (
    CompanyCreate,
    CompanyUpdate,
    CompanyResponse,
)

from app.core.limiter import limiter
from app.services.company_service import (
    create_company,
    update_company,
    get_company_by_user_id,
    get_company_by_id,
)

router = APIRouter(prefix="/company", tags=["Company"])


@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour")
async def create_new_company(
    request: Request,
    payload: CompanyCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Final submit of 3-step wizard onboarding.
    Creates a new Company profile for the current user.
    """
    company = await create_company(db, payload, user.id)
    
    if company.company_website:
        background_tasks.add_task(
            process_company_website_async,
            company.id,
            company.company_website
        )
    return CompanyResponse.model_validate(company)


@router.get("/me", response_model=CompanyResponse)
async def get_my_company(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Fetch the company profile for the logged-in user.
    Used for onboarding check and profile settings prefill.
    """
    company = await get_company_by_user_id(db, user.id)

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile does not exist for this user.",
        )

    return CompanyResponse.model_validate(company)


@router.put("/{company_id}", response_model=CompanyResponse)
async def update_existing_company(
    company_id: UUID,
    payload: CompanyUpdate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Update the company profile fields.
    Can be triggered by profile settings or background scraper.
    """
    company = await update_company(db, str(company_id), user.id, payload)
        
    return CompanyResponse.model_validate(company)
