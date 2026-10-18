from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from datetime import date
from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services.campaign_insight_service import get_campaign_insight

router = APIRouter(prefix="/campaigns", tags=["Campaign Insights"])

@router.get("/{campaign_id}/insight", status_code=status.HTTP_200_OK)
async def campaign_insight(
    campaign_id: UUID,
    range: int = Query(7, enum=[7, 30, 90]),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return await get_campaign_insight(
        campaign_id=str(campaign_id),
        user_id=user.id,
        db=db,
        range_days=range,
        start_date=start_date,
        end_date=end_date,
    )
