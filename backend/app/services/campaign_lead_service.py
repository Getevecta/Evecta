from sqlalchemy import select, delete, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from fastapi import HTTPException
from datetime import datetime, timezone
from uuid import UUID
from typing import List

from app.core.pagination import normalize_pagination
from app.models.campaign import Campaign
from app.models.campaign_lead import CampaignLead
from app.models.lead import Lead
from app.models.email_activity import EmailActivity, EmailStatus
from app.models.email_job import EmailJob, EmailJobStatus
from app.services.campaign_guard import ensure_campaign_editable
from app.services.personalization_service import (
    lead_data_from_sources,
    resolve_personalization,
    snapshot_context_fields,
)

# ---------------------------------------------------------
# Step 2: Checkbox Sync Logic
# ---------------------------------------------------------
async def sync_campaign_leads(
    campaign_id: UUID,
    user_id: UUID,
    lead_ids: List[UUID],
    db: AsyncSession,
):
    """
    Synchronize a campaign’s leads with the latest checkbox selection.
    Adds new leads and removes unchecked automatically.
    """
    try:
        #  Verify campaign ownership
        campaign = await db.scalar(
            select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user_id)
        )
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found or unauthorized.")


        ensure_campaign_editable(campaign, action="modify_leads")

        # Get currently linked leads
        existing_result = await db.scalars(
            select(CampaignLead.lead_id).where(CampaignLead.campaign_id == campaign_id)
        )
        existing_ids = set(existing_result.all())

        new_ids = set(lead_ids)
        to_add = new_ids - existing_ids
        to_remove = existing_ids - new_ids

        # Validate ownership of leads being added
        if to_add:
            valid_result = await db.scalars(
                select(Lead.id).where(Lead.user_id == user_id, Lead.id.in_(to_add))
            )
            valid_ids = set(valid_result.all())
            invalid = to_add - valid_ids
            if invalid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Some leads are invalid or not owned by user: {list(invalid)}",
                )
            to_add = valid_ids

        # Remove unchecked leads
        if to_remove:
            await db.execute(
                delete(CampaignLead).where(
                    CampaignLead.campaign_id == campaign_id,
                    CampaignLead.lead_id.in_(to_remove),
                )
            )

        # Add newly selected leads with snapshot data
        if to_add:
            # Fetch lead details to store snapshot
            leads_to_add = await db.scalars(
                select(Lead).where(Lead.id.in_(to_add))
            )
            leads_dict = {lead.id: lead for lead in leads_to_add.all()}
            
            db.add_all(
                [
                    CampaignLead(
                        campaign_id=campaign_id,
                        lead_id=lid,
                        created_at=datetime.now(timezone.utc),
                        # Store snapshot of lead data
                        business_name=leads_dict[lid].business_name,
                        email=leads_dict[lid].email,
                        industry=leads_dict[lid].industry,
                        address=leads_dict[lid].address,
                        contact_number=leads_dict[lid].contact_number,
                        website=leads_dict[lid].website,
                        lead_score=leads_dict[lid].lead_score,
                        **snapshot_context_fields(leads_dict[lid]),
                    )
                    for lid in to_add
                ]
            )

        # Refresh context snapshot for leads that remain selected (enrichment may have finished since last sync)
        to_refresh = new_ids & existing_ids
        if to_refresh:
            existing_rows = await db.scalars(
                select(CampaignLead).where(
                    CampaignLead.campaign_id == campaign_id,
                    CampaignLead.lead_id.in_(to_refresh),
                )
            )
            refresh_leads = await db.scalars(
                select(Lead).where(Lead.id.in_(to_refresh), Lead.user_id == user_id)
            )
            refresh_dict = {lead.id: lead for lead in refresh_leads.all()}
            for cl in existing_rows.all():
                lead = refresh_dict.get(cl.lead_id)
                if not lead:
                    continue
                ctx = snapshot_context_fields(lead)
                cl.services = ctx["services"]
                cl.website_summary = ctx["website_summary"]
                cl.business_description = ctx["business_description"]

        await db.commit()
        return {
            "message": f"{len(to_add)} added, {len(to_remove)} removed.",
            "added": list(to_add),
            "removed": list(to_remove),
        }

    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")
    

async def get_leads_for_campaign(
    campaign_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 50,
):
    """Return a page of leads linked to a campaign, with email status attached."""
    page, per_page, offset = normalize_pagination(page, per_page)

    owned = await db.scalar(
        select(Campaign.id).where(Campaign.id == campaign_id, Campaign.user_id == user_id)
    )
    if not owned:
        return [], 0, page, per_page

    total_items = int(
        await db.scalar(
            select(func.count())
            .select_from(CampaignLead)
            .where(CampaignLead.campaign_id == campaign_id)
        )
        or 0
    )

    user_added_order = case(
        (and_(Lead.id.is_not(None), Lead.lead_log_id.is_(None)), 0),
        else_=1,
    )
    result = await db.scalars(
        select(CampaignLead)
        .outerjoin(Lead, CampaignLead.lead_id == Lead.id)
        .options(selectinload(CampaignLead.lead))
        .where(CampaignLead.campaign_id == campaign_id)
        .order_by(user_added_order.asc(), CampaignLead.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    campaign_leads = list(result.all())

    lead_ids = [cl.lead_id for cl in campaign_leads if cl.lead_id]
    activity_map: dict = {}
    job_map: dict = {}
    if lead_ids:
        activities = (await db.scalars(
            select(EmailActivity)
            .where(
                EmailActivity.campaign_id == campaign_id,
                EmailActivity.lead_id.in_(lead_ids),
            )
            .order_by(EmailActivity.updated_at.desc())
        )).all()
        for ea in activities:
            existing = activity_map.get(ea.lead_id)
            if existing is None:
                activity_map[ea.lead_id] = ea
                continue
            if (
                existing.status == EmailStatus.FAILED
                and not existing.bounced
                and ea.status != EmailStatus.FAILED
            ):
                activity_map[ea.lead_id] = ea

        jobs = (await db.scalars(
            select(EmailJob)
            .where(
                EmailJob.campaign_id == campaign_id,
                EmailJob.user_id == user_id,
                EmailJob.lead_id.in_(lead_ids),
            )
            .order_by(EmailJob.updated_at.desc())
        )).all()
        for ej in jobs:
            existing = job_map.get(ej.lead_id)
            if existing is None:
                job_map[ej.lead_id] = ej
                continue
            if (
                existing.status == EmailJobStatus.FAILED
                and ej.status == EmailJobStatus.SENT
            ):
                job_map[ej.lead_id] = ej

    for cl in campaign_leads:
        email_activity = activity_map.get(cl.lead_id)
        if email_activity:
            if email_activity.bounced:
                cl.email_status = "bounced"
            elif email_activity.clicked:
                cl.email_status = "clicked"
            elif email_activity.opened:
                cl.email_status = "opened"
            else:
                cl.email_status = email_activity.status.value
            cl.email_sent_at = email_activity.sent_at
        else:
            email_job = job_map.get(cl.lead_id)
            if email_job:
                if (
                    email_job.status.value == "failed"
                    and email_job.last_error == "Lead has unsubscribed"
                ):
                    cl.email_status = "unsubscribed"
                else:
                    cl.email_status = email_job.status.value
            else:
                cl.email_status = None
            cl.email_sent_at = email_job.updated_at if email_job else None

    return campaign_leads, total_items, page, per_page


def enrich_campaign_leads_personalization(
    campaign_leads: list,
    plan: str | None,
    tone: str | None = None,
) -> None:
    """Attach context_score and effective_depth to each CampaignLead in-place."""
    for cl in campaign_leads:
        lead_data = lead_data_from_sources(campaign_lead=cl, lead=cl.lead)
        profile = resolve_personalization(plan=plan, tone=tone, lead_data=lead_data)
        cl.context_score = profile["context_score"]
        cl.effective_depth = profile["effective_depth"]
