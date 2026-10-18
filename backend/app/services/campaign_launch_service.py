from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload
from fastapi import HTTPException
from datetime import datetime, timezone, timedelta
from app.models.campaign import Campaign, CampaignStatus
from app.models.campaign_lead import CampaignLead
from app.models.campaign_lead_email import CampaignLeadEmail
from app.models.mailbox import Mailbox, MailboxType
from app.models.user import User
from app.models.email_job import EmailJob, EmailJobStatus
from app.core.config import get_settings
from app.enums.email_sending_mode import EmailSendingMode
from app.services.campaign_guard import ensure_campaign_editable
from app.services.campaign_email_review_service import approved_lead_ids, get_launch_review_blocker
from app.services.campaign_launch_readiness_service import (
    get_campaign_launch_readiness,
    reconcile_campaign_sending_mode,
)
from app.core.email_limits import SEND_STAGGER_SECONDS

settings = get_settings()

async def save_campaign_as_draft(
    campaign_id: str,
    user_id: str,
    db: AsyncSession
):
    """Save campaign progress as draft (editable)."""

    # Fetch campaign and verify ownership
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail="Campaign not found or unauthorized."
        )

    ensure_campaign_editable(campaign, action="save")

    # Update timestamp
    campaign.updated_at = datetime.now(timezone.utc)

    # ---- SAFE COMMIT WITH ROLLBACK ----
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to save changes. Please try again."
        )

    await db.refresh(campaign)

    return {
        "campaign_id": str(campaign.id),
        "status": campaign.status.value,
        "message": "Campaign saved as draft. You can continue editing later."
    }

# ALERT FOR UNMODIFIED PLACEHOLDERS — see app.utils.campaign_placeholders

async def launch_campaign_service(
    campaign_id: str,
    user_id: str,
    db: AsyncSession
):
    """Launch campaign: validate readiness, queue approved leads, begin sending."""
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or str(campaign.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail="Campaign not found or unauthorized.")
    ensure_campaign_editable(campaign, action="launch")

    # Auto-set email_sending_mode before readiness (legacy launch path)
    if campaign.email_sending_mode is None:
        user_mailboxes_result = await db.execute(
            select(func.count(Mailbox.id))
            .where(
                Mailbox.user_id == user_id,
                Mailbox.mailbox_type == MailboxType.USER,
                Mailbox.is_active == True,
            )
        )
        user_mailbox_count = user_mailboxes_result.scalar() or 0
        user = await db.get(User, user_id)
        user_preferred_mode = user.email_sending_mode if user else None

        if user_mailbox_count > 0:
            campaign.email_sending_mode = EmailSendingMode.USER
        elif user_preferred_mode == EmailSendingMode.SYSTEM:
            campaign.email_sending_mode = EmailSendingMode.SYSTEM
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Email sending method not selected. "
                    "Please choose Prewarmed Email or Existing Email Account "
                    "before launching this campaign."
                ),
            )
        campaign.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(campaign)

    await reconcile_campaign_sending_mode(campaign, user_id, db)

    readiness = await get_campaign_launch_readiness(campaign_id, user_id, db)
    if not readiness["can_launch"]:
        detail = readiness["launch_blockers"][0] if readiness["launch_blockers"] else "Campaign not ready to launch."
        raise HTTPException(status_code=400, detail=detail)

    skipped_rejected = readiness.get("skipped_rejected", 0)

    # QUEUE ALL LEADS OF THE CAMPAIGN (including deleted leads using snapshot)
    campaign_leads_result = await db.execute(
        select(CampaignLead)
        .where(CampaignLead.campaign_id == campaign.id)
        .options(selectinload(CampaignLead.lead))
    )
    campaign_leads = campaign_leads_result.scalars().all()

    # check if there are leads attached
    if not campaign_leads:
        raise HTTPException(
            status_code=400,
            detail="No leads attached to the campaign."
        )

    # Build leads list from campaign_leads, using snapshot if lead is deleted
    all_leads = []
    for cl in campaign_leads:
        if cl.lead:
            # Lead still exists, use it
            all_leads.append(cl.lead)
        elif cl.email:
            # Lead deleted but we have snapshot with email - create a mock lead object
            # We'll use the snapshot data for email sending
            class SnapshotLead:
                def __init__(self, campaign_lead):
                    self.id = campaign_lead.lead_id or campaign_lead.id
                    self.business_name = campaign_lead.business_name or "Unknown"
                    self.email = campaign_lead.email
                    self.industry = campaign_lead.industry
                    self.address = campaign_lead.address
                    self.contact_number = campaign_lead.contact_number
                    self.website = campaign_lead.website
                    self.lead_score = campaign_lead.lead_score or 0
            all_leads.append(SnapshotLead(cl))

    # check if the leads have email address or not
    leads_without_email = [lead for lead in all_leads if not lead.email]

    total_leads = len(all_leads)
    missing_email_count = len(leads_without_email)

    if missing_email_count > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{missing_email_count} out of {total_leads} selected leads do not have an email address. "
                "Please update/remove those leads and try again."
            ),
        )

    # Step 5 — per-lead review gate (when generation rows exist)
    email_rows_result = await db.execute(
        select(CampaignLeadEmail).where(CampaignLeadEmail.campaign_id == campaign.id)
    )
    email_rows = list(email_rows_result.scalars().all())
    if email_rows:
        review_blocker = get_launch_review_blocker(email_rows)
        if review_blocker:
            raise HTTPException(status_code=400, detail=review_blocker)
        approved_ids = approved_lead_ids(email_rows)
        all_leads = [lead for lead in all_leads if str(lead.id) in approved_ids]
        if not all_leads:
            raise HTTPException(
                status_code=400,
                detail="No approved leads to send. Approve at least one email before launch.",
            )

    
    # Insert first with ON CONFLICT DO NOTHING, then charge exactly what was inserted.
    # This eliminates the race where two concurrent launches both compute the same
    # net_new, charge double, but only one set of rows actually gets inserted.
    now = datetime.now(timezone.utc)
    rows = [
        {
            "campaign_id": campaign.id,
            "lead_id": lead.id,
            "user_id": user_id,
            "email": lead.email,
            "status": EmailJobStatus.QUEUED.value,
            "attempts": 0,
            "scheduled_for": now + timedelta(seconds=idx * SEND_STAGGER_SECONDS),
            "created_at": now,
            "updated_at": now,
        }
        for idx, lead in enumerate(all_leads)
    ]

    stmt = (
        insert(EmailJob)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["campaign_id", "lead_id"])
    )

    result = await db.execute(stmt)
    net_new = result.rowcount  # exact count of rows actually inserted

    if net_new == 0:
        raise HTTPException(status_code=400, detail="All selected leads are already queued for this campaign.")

    # Charge credits only for the rows that were actually inserted
    from app.services.credit_service import spend_credits
    await spend_credits(
        db, user_id, "email_sent",
        quantity=net_new,
        description=f"Launch campaign {campaign_id} to {net_new} leads",
    )

    # Update campaign status to ONGOING
    campaign.status = CampaignStatus.ONGOING
    campaign.launched_at = now
    campaign.updated_at = now

    await db.commit()
    await db.refresh(campaign)

    return {
        "campaign_id": str(campaign.id),
        "status": campaign.status.value,
        "queued": net_new,
        "approved": len(all_leads),
        "skipped_rejected": skipped_rejected,
        "message": (
            f"Campaign launched. {net_new} email(s) queued for sending"
            + (f" ({skipped_rejected} rejected lead(s) skipped)." if skipped_rejected else ".")
        ),
    }
