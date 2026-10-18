import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

logger = logging.getLogger(__name__)

from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.campaign_draft import (
    CampaignDraftBase,
    CampaignDraftResponse,
    AIDraftRequest,
    SpamCheckRequest,
    SpamCheckResponse,
)
from app.core.limiter import limiter
from app.services.campaign_draft_service import (
    get_campaign_draft,
    update_campaign_draft_template,
    update_campaign_draft_manual,
    generate_campaign_draft_ai,
)

router = APIRouter(prefix="/campaigns/{campaign_id}/draft", tags=["Campaign Drafts"])


# --------------------------------------------
#  Get campaign draft
# --------------------------------------------
@router.get("", response_model=CampaignDraftResponse, status_code=status.HTTP_200_OK)
async def get_draft(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Step 3.2 – Get campaign draft data (subject, content, template, etc.)."""
    return await get_campaign_draft(str(campaign_id), user.id, db)


# --------------------------------------------
#  Template-based draft
# --------------------------------------------
@router.put("", response_model=CampaignDraftResponse, status_code=status.HTTP_200_OK)
async def set_campaign_template(
    campaign_id: UUID,
    payload: CampaignDraftBase,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Step 3.2 – Attach selected email template to campaign."""
    return await update_campaign_draft_template(str(campaign_id), user.id, payload, db)


# --------------------------------------------
#  Manual draft
# --------------------------------------------
@router.put("/manual", response_model=CampaignDraftResponse, status_code=status.HTTP_200_OK)
async def set_campaign_manual(
    campaign_id: UUID,
    payload: CampaignDraftBase,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Step 3.2 – Save manual subject and content for campaign."""
    return await update_campaign_draft_manual(str(campaign_id), user.id, payload, db)


# --------------------------------------------
#  AI draft generation
# --------------------------------------------
@router.post("/ai", response_model=CampaignDraftResponse, status_code=status.HTTP_200_OK)
@limiter.limit("20/hour")
async def set_campaign_ai(
    request: Request,
    campaign_id: UUID,
    payload: AIDraftRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Step 3.2 – Generate AI-based email draft."""
    from app.services.credit_service import spend_credits, refund_credits
    # Check and deduct credits BEFORE running the AI — raises 402 immediately if insufficient
    await spend_credits(db, user.id, "ai_draft", description=f"AI draft for campaign {campaign_id}")
    try:
        return await generate_campaign_draft_ai(str(campaign_id), user.id, payload, db)
    except Exception:
        # spend_credits already committed — rollback cannot undo the charge.
        await refund_credits(
            db, user.id, "ai_draft",
            description=f"Refund: AI draft failed for campaign {campaign_id}",
        )
        raise



# --------------------------------------------
#  Spam check
# --------------------------------------------
@router.post("/spam-check", response_model=SpamCheckResponse, status_code=status.HTTP_200_OK)
@limiter.limit("30/hour")
async def check_spam(
    request: Request,
    campaign_id: UUID,
    payload: SpamCheckRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Check if email will go to spam."""
    from app.models.campaign import Campaign
    from fastapi import HTTPException
    
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.user_id != user.id:
        raise HTTPException(status_code=404, detail="Campaign not found or unauthorized.")

    # Fetch user profile data
    user_profile = {
        'full_name': user.full_name,
        'bio': user.bio,
        'department': user.department,
        'location': user.location,
        'website': user.website,
    }
    
    # Fetch company profile data if available
    company_profile = None
    try:
        from app.services.company_service import get_company_by_user_id
        company = await get_company_by_user_id(db, user.id)
        if company:
            company_profile = {
                'company_name': company.company_name,
                'company_description': company.company_description,
                'products_and_services': company.products_and_services,
            }
    except HTTPException:
        pass  # Company not set up yet — spam check works fine without it
    except Exception:
        logger.warning("Failed to fetch company profile for user %s — continuing without it", user.id, exc_info=True)
    
    from app.services.credit_service import spend_credits, refund_credits
    from app.utils.spam_checker import check_email_spam
    # Check and deduct credits BEFORE running the spam check — raises 402 immediately if insufficient
    await spend_credits(db, user.id, "spam_check", description=f"Spam check for campaign {campaign_id}")
    try:
        result = await check_email_spam(
            payload.subject,
            payload.body,
            user_profile=user_profile,
            company_profile=company_profile,
            fast_mode=payload.fast_mode if hasattr(payload, 'fast_mode') else False,
            user_id=user.id,
        )
        return SpamCheckResponse(**result)
    except Exception:
        # spend_credits already committed — rollback cannot undo the charge.
        # Refund explicitly so a failed spam-check LLM call does not keep the credit.
        await refund_credits(
            db, user.id, "spam_check",
            description=f"Refund: spam check failed for campaign {campaign_id}",
        )
        raise
