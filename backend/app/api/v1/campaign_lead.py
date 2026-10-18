from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.response import BaseResponse
from app.core.limiter import limiter
from app.core.pagination import DEFAULT_PER_PAGE, PageQuery, PerPageQuery, paginated_payload
from app.schemas.campaign_lead import CampaignLeadCreate, CampaignLeadResponse
from app.schemas.pagination import PaginatedResponse
from app.services.campaign_lead_service import (
    sync_campaign_leads,
    get_leads_for_campaign,
    enrich_campaign_leads_personalization,
)

router = APIRouter(prefix="/campaigns/{campaign_id}/leads", tags=["Campaign Leads"])


# ---------------------------------------------------------
# Step 2: Sync leads (checkbox logic — add/remove together)
# ---------------------------------------------------------
@router.post("", response_model=BaseResponse, status_code=status.HTTP_200_OK)
@limiter.limit("60/hour")
async def sync_leads_with_campaign(
    request: Request,
    campaign_id: UUID,
    payload: CampaignLeadCreate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Step 2 — Lead Selection (Sync checkbox state)
    - Frontend sends ALL selected leads (checked boxes)
    - Backend adds new ones, removes unchecked
    - Automatically keeps everything in sync
    """
    if not isinstance(payload.lead_ids, list):
        raise HTTPException(status_code=400, detail="lead_ids must be a list")

    result = await sync_campaign_leads(campaign_id, user.id, payload.lead_ids, db)
    return BaseResponse(
        status="success",
        message=result["message"],
        data={"added": result["added"], "removed": result["removed"]},
    )


# ---------------------------------------------------------
# Get all leads for campaign
# ---------------------------------------------------------
@router.get("", response_model=PaginatedResponse[CampaignLeadResponse], status_code=status.HTTP_200_OK)
async def get_campaign_leads(
    campaign_id: UUID,
    page: PageQuery = 1,
    per_page: PerPageQuery = DEFAULT_PER_PAGE,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return leads currently linked to this campaign (paginated)."""
    campaign_leads, total_items, page, per_page = await get_leads_for_campaign(
        campaign_id, user.id, db, page=page, per_page=per_page
    )
    enrich_campaign_leads_personalization(campaign_leads, user.plan)
    return paginated_payload(
        [CampaignLeadResponse.from_orm_with_snapshot(cl) for cl in campaign_leads],
        total_items=total_items,
        page=page,
        per_page=per_page,
    )
