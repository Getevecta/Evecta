import logging
from fastapi import APIRouter, Depends, HTTPException, status

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.campaign import CampaignCreate, CampaignUpdate, CampaignResponse, PaginatedCampaignResponse, CampaignCreateResponse
from app.services.campaign_service import (
    create_campaign,
    get_all_campaigns,
    get_campaign_by_id,
    update_campaign,
    delete_campaign,
    auto_set_email_sending_mode_for_draft_campaigns,
)
from app.core.pagination import DEFAULT_PER_PAGE, PageQuery, PerPageQuery
from app.schemas.mailbox import EmailSendingModeUpdate

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])

@router.post("", response_model=CampaignCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_new_campaign(
    payload: CampaignCreate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Step 1 - Create a draft campaign."""
    try:
        campaign = await create_campaign(user.id, payload, db)
        return CampaignCreateResponse.model_validate(campaign)
    except HTTPException as e:
        # Re-raise HTTPExceptions with their original status and detail
        raise e
    except Exception as e:
        logger.exception("Unexpected error creating campaign: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again."
        )


@router.get("", response_model=PaginatedCampaignResponse)
async def list_campaigns(
    search: str | None = None,
    min_avg_score: float | None = None,
    max_avg_score: float | None = None,
    page: PageQuery = 1,
    per_page: PerPageQuery = DEFAULT_PER_PAGE,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Fetch all user campaigns with filters and pagination metadata."""
    try:
        result = await get_all_campaigns(user.id, db, search, min_avg_score, max_avg_score, page, per_page)
        # Explicitly validate the response before returning
        try:
            validated_response = PaginatedCampaignResponse.model_validate(result)
            return validated_response
        except Exception as validation_error:
            logger.exception("Validation error in list_campaigns: %s", validation_error)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred. Please try again."
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in list_campaigns endpoint: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again."
        )


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Fetch a specific campaign."""
    campaign = await get_campaign_by_id(str(campaign_id), user.id, db)
    return CampaignResponse.model_validate(campaign)


@router.put("/email-sending-mode", status_code=status.HTTP_200_OK)
async def set_campaign_email_sending_mode(
    payload: EmailSendingModeUpdate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Set email_sending_mode for all draft campaigns. Used when user connects email accounts."""
    updated_count = await auto_set_email_sending_mode_for_draft_campaigns(
        user_id=str(user.id),
        email_sending_mode=payload.email_sending_mode,
        db=db
    )
    return {
        "message": f"Email sending mode set to {payload.email_sending_mode.value} for {updated_count} draft campaign(s)",
        "updated_count": updated_count,
        "email_sending_mode": payload.email_sending_mode.value
    }


@router.put("/{campaign_id}", response_model=CampaignResponse)
async def update_existing_campaign(
    campaign_id: UUID,
    payload: CampaignUpdate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Edit Step 1 campaign info."""
    campaign = await update_campaign(str(campaign_id), user.id, payload, db)
    return CampaignResponse.model_validate(campaign)


@router.delete("/{campaign_id}", status_code=status.HTTP_200_OK)
async def delete_existing_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Delete a draft campaign. Only draft campaigns can be deleted."""
    result = await delete_campaign(str(campaign_id), user.id, db)
    return result

