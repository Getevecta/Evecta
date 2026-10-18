from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from fastapi import HTTPException
from app.models.campaign import Campaign
from app.models.campaign_lead import CampaignLead
from app.models.campaign_lead_email import CampaignLeadEmail
from app.enums.email_sending_mode import EmailSendingMode
from app.models.mailbox import Mailbox, MailboxType
from app.services.campaign_email_review_service import _review_summary


async def get_campaign_preview(
    campaign_id: str,
    user_id: str,
    db: AsyncSession
):
    """Return a non-editable summary of campaign before launch (only lead count)."""

    # --- Safe fetch campaign ---
    try:
        campaign = await db.scalar(
            select(Campaign)
            .where(Campaign.id == campaign_id)
            .options(
                selectinload(Campaign.goal_ref),
                selectinload(Campaign.category_ref),
            )
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again."
        )

    if not campaign or campaign.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail="Campaign not found or unauthorized."
        )

    # --- Safe lead count query ---
    try:
        count_query = (
            select(func.count())
            .select_from(CampaignLead)
            .where(CampaignLead.campaign_id == campaign_id)
        )
        result = await db.execute(count_query)
        lead_count = result.scalar() or 0
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Failed to load campaign preview."
        )

    # Determine status
    draft_ready = bool(campaign.email_subject and campaign.email_content)
    status = "ready" if draft_ready and lead_count > 0 else "missing_draft"
    # Launch safety checks
    launch_blockers = []

    # 1. Email sending mode selected?
    if campaign.email_sending_mode is None:
        launch_blockers.append(
            "Email sending method not selected. Please choose System Email or Existing Email Account."
        )

    # 2. Validate availability based on CAMPAIGN mode
    elif campaign.email_sending_mode == EmailSendingMode.SYSTEM:
        result = await db.execute(
            select(func.count(Mailbox.id))
            .where(
                Mailbox.mailbox_type == MailboxType.SYSTEM,
                Mailbox.is_active.is_(True),
            )
        )
        if (result.scalar() or 0) == 0:
            launch_blockers.append(
                "System email is currently unavailable."
            )

    elif campaign.email_sending_mode == EmailSendingMode.USER:
        result = await db.execute(
            select(func.count(Mailbox.id))
            .where(
                Mailbox.mailbox_type == MailboxType.USER,
                Mailbox.user_id == user_id,
                Mailbox.is_active.is_(True),
            )
        )
        if (result.scalar() or 0) == 0:
            launch_blockers.append(
                "No active email account found for this campaign."
            )

    # Step 5 — per-lead email review
    email_rows_result = await db.execute(
        select(CampaignLeadEmail).where(CampaignLeadEmail.campaign_id == campaign_id)
    )
    email_rows = list(email_rows_result.scalars().all())
    review_summary = _review_summary(email_rows)
    if review_summary["has_per_lead_emails"]:
        launch_blockers.extend(review_summary["launch_blockers"])

    return {
        "id": campaign.id,
        "name": campaign.name,
        "goal": campaign.goal_ref.name if campaign.goal_ref else None,
        "category": campaign.category_ref.name if campaign.category_ref else None,
        "draft_type": campaign.draft_type.value if campaign.draft_type else None,
        "email_subject": campaign.email_subject,
        "email_content": campaign.email_content,
        "lead_count": lead_count,
        "status": status,

        # NEW FIELDS (STEP 9)
        "email_sending_mode": (
            campaign.email_sending_mode.value
            if campaign.email_sending_mode
            else None
        ),
        "is_launchable": (
            draft_ready
            and lead_count > 0
            and len(launch_blockers) == 0
        ),
        "launch_blockers": launch_blockers,
        "email_review": review_summary if email_rows else None,
    }
