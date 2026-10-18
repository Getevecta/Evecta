from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.campaign_preview import CampaignPreviewResponse
from app.services.campaign_preview_service import get_campaign_preview
from app.core.limiter import limiter

router = APIRouter(prefix="/campaigns", tags=["Campaign Preview"])

@router.get("/{campaign_id}/preview", response_model=CampaignPreviewResponse)
@limiter.limit("30/minute")
async def preview_campaign(
    request: Request,
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Step 4 – Read-only campaign preview before launch."""
    data = await get_campaign_preview(str(campaign_id), user.id, db)
    return data
