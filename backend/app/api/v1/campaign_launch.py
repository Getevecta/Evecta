from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.campaign_launch import (
    CampaignLaunchReadinessResponse,
    CampaignLaunchResponse,
    CampaignLaunchViewResponse,
    CampaignSendStatusResponse,
)
from app.services.campaign_launch_service import launch_campaign_service, save_campaign_as_draft
from app.services.campaign_launch_readiness_service import (
    get_campaign_launch_readiness,
    get_campaign_launch_view,
)
from app.services.campaign_send_status_service import get_campaign_send_status
from app.services.campaign_test_email_service import send_test_email_service
from app.core.limiter import limiter

router = APIRouter(prefix="/campaigns", tags=["Campaign Launch"])


@router.post("/{campaign_id}/save-draft", status_code=status.HTTP_200_OK)
async def save_campaign_draft(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Allow saving as draft without launching."""
    return await save_campaign_as_draft(str(campaign_id), user.id, db)


@router.post("/{campaign_id}/send-test-email", status_code=status.HTTP_200_OK)
@limiter.limit("10/hour")
async def send_test_email(
    request: Request,
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Send a test email preview to the user's email address.
    This allows testing the campaign email before launching to actual leads.
    """
    user_email = (user.email or "").strip()
    if not user_email:
        raise HTTPException(
            status_code=400,
            detail="User email not found. Please update your profile with an email address."
        )
    # Convert UUID to string to avoid async context issues
    user_id_str = str(user.id)
    return await send_test_email_service(str(campaign_id), user_id_str, user_email, db)


@router.get("/{campaign_id}/launch/readiness", response_model=CampaignLaunchReadinessResponse, status_code=status.HTTP_200_OK)
async def get_launch_readiness(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Step 6 — unified launch readiness checklist."""
    result = await get_campaign_launch_readiness(str(campaign_id), str(user.id), db)
    return CampaignLaunchReadinessResponse(**result)


@router.get("/{campaign_id}/launch/status", response_model=CampaignSendStatusResponse, status_code=status.HTTP_200_OK)
async def get_launch_send_status(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Step 6 — post-launch email job progress."""
    result = await get_campaign_send_status(str(campaign_id), str(user.id), db)
    return CampaignSendStatusResponse(**result)


@router.get("/{campaign_id}/launch", response_model=CampaignLaunchViewResponse, status_code=status.HTTP_200_OK)
async def get_launch_view(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Campaign summary plus readiness (draft) or send status (launched) in one response."""
    result = await get_campaign_launch_view(str(campaign_id), str(user.id), db)
    return CampaignLaunchViewResponse(**result)


@router.post("/{campaign_id}/launch", response_model=CampaignLaunchResponse, status_code=status.HTTP_200_OK)
@limiter.limit("10/hour")
async def launch_campaign(
    request: Request,
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Step 6 — Launch campaign (queue approved leads for sending)."""
    result = await launch_campaign_service(str(campaign_id), user.id, db)
    return CampaignLaunchResponse(
        campaign_id=campaign_id,
        status=result["status"],
        queued=result["queued"],
        approved=result.get("approved", result["queued"]),
        skipped_rejected=result.get("skipped_rejected", 0),
        message=result["message"],
    )
