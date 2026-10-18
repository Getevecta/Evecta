from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.core.pagination import DEFAULT_PER_PAGE, PageQuery, PerPageQuery
from app.schemas.campaign_goal import (
    CampaignGoalCreate,
    CampaignGoalUpdate,
    CampaignGoalResponse,
)
from app.schemas.pagination import PaginatedResponse
from app.services.campaign_goal_service import (
    create_campaign_goal,
    get_goals,
    update_campaign_goal,
    delete_campaign_goal,
)

router = APIRouter(prefix="/campaign-goals", tags=["Campaign Goals"])


@router.post("", response_model=CampaignGoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(payload: CampaignGoalCreate, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    return await create_campaign_goal(user.id, payload, db)


@router.get("", response_model=PaginatedResponse[CampaignGoalResponse])
async def list_goals(
    page: PageQuery = 1,
    per_page: PerPageQuery = DEFAULT_PER_PAGE,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return await get_goals(user.id, db, page=page, per_page=per_page)


@router.put("/{goal_id}", response_model=CampaignGoalResponse)
async def update_goal(goal_id: UUID, payload: CampaignGoalUpdate, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    return await update_campaign_goal(str(goal_id), user.id, payload, db)


@router.delete("/{goal_id}", status_code=status.HTTP_200_OK)
async def delete_goal(goal_id: UUID, db: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    return await delete_campaign_goal(str(goal_id), user.id, db)
