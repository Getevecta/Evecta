"""Step 6 — post-launch email job send progress."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign, CampaignStatus
from app.models.email_job import EmailJob, EmailJobStatus
from app.services.campaign_guard import get_owned_campaign_or_404
from app.services.campaign_status_counts import (
    count_email_jobs_by_status,
    send_status_from_counts,
)


async def get_campaign_send_status(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    campaign = await get_owned_campaign_or_404(campaign_id, user_id, db)
    by_status = await count_email_jobs_by_status(db, campaign_id)
    return send_status_from_counts(
        by_status,
        campaign_id=campaign_id,
        campaign_status=campaign.status.value,
    )


async def maybe_complete_campaign(db: AsyncSession, campaign_id) -> bool:
    """Mark campaign COMPLETED when all email jobs are terminal."""
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.status != CampaignStatus.ONGOING:
        return False

    total = (
        await db.scalar(
            select(func.count()).select_from(EmailJob).where(EmailJob.campaign_id == campaign_id)
        )
        or 0
    )
    if total == 0:
        return False

    pending = (
        await db.scalar(
            select(func.count())
            .select_from(EmailJob)
            .where(
                EmailJob.campaign_id == campaign_id,
                EmailJob.status.in_([EmailJobStatus.QUEUED, EmailJobStatus.SENDING]),
            )
        )
        or 0
    )
    if pending > 0:
        return False

    campaign.status = CampaignStatus.COMPLETED
    await db.flush()
    return True
