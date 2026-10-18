from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.core.pagination import DEFAULT_PER_PAGE, PageQuery, PerPageQuery
from app.schemas.campaign_category import (
    CampaignCategoryCreate,
    CampaignCategoryUpdate,
    CampaignCategoryResponse,
)
from app.schemas.pagination import PaginatedResponse
from app.services.campaign_category_service import (
    create_campaign_category,
    get_categories,
    update_campaign_category,
    delete_campaign_category,
)

router = APIRouter(prefix="/campaign-categories", tags=["Campaign Categories"])


@router.post("", response_model=CampaignCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(payload: CampaignCategoryCreate, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    return await create_campaign_category(user.id, payload, db)


@router.get("", response_model=PaginatedResponse[CampaignCategoryResponse])
async def list_categories(
    page: PageQuery = 1,
    per_page: PerPageQuery = DEFAULT_PER_PAGE,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return await get_categories(user.id, db, page=page, per_page=per_page)


@router.put("/{category_id}", response_model=CampaignCategoryResponse)
async def update_category(category_id: UUID, payload: CampaignCategoryUpdate, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    return await update_campaign_category(str(category_id), user.id, payload, db)


@router.delete("/{category_id}", status_code=status.HTTP_200_OK)
async def delete_category(category_id: UUID, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    return await delete_campaign_category(str(category_id), user.id, db)
