from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional

from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.core.personalization import plan_capabilities
from app.schemas.personalization import (
    CampaignPersonalizationResponse,
    PlanCapabilitiesResponse,
)
from app.services.personalization_service import get_campaign_personalization_preview

router = APIRouter(tags=["Personalization"])
campaign_router = APIRouter(prefix="/campaigns/{campaign_id}/personalization", tags=["Personalization"])


@router.get("/personalization/capabilities", response_model=PlanCapabilitiesResponse, status_code=status.HTTP_200_OK)
async def get_personalization_capabilities(
    user: User = Depends(get_current_user),
):
    """Return personalization limits and tone options for the current user's plan."""
    return plan_capabilities(user.plan)


@campaign_router.get("", response_model=CampaignPersonalizationResponse, status_code=status.HTTP_200_OK)
async def get_campaign_personalization(
    campaign_id: UUID,
    tone: Optional[str] = Query(None, description="Override campaign tone for preview"),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Per-lead personalization profiles for a campaign (plan + context + tone)."""
    return await get_campaign_personalization_preview(
        campaign_id, user.id, db, tone=tone
    )
