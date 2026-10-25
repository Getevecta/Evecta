from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, delete, case
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from uuid import UUID
from typing import List, Optional
from app.models.lead import Lead
from app.models.lead_log import LeadLog
from app.models.lead_log_lead import LeadLogLead
from app.models.email_activity import EmailActivity
from app.models.campaign_lead import CampaignLead
from app.models.campaign import Campaign, CampaignStatus
from app.schemas.lead import LeadCreate, LeadUpdate, lead_to_response
from app.schemas.response import BaseResponse
from app.utils.lead_dedup import (
    normalize_business_name,
    normalize_email,
)


class _PromoteResolveIndex:
    """In-memory lookup built from one candidate Lead query (avoids per-row resolves)."""

    __slots__ = (
        "by_overture_log",
        "by_overture",
        "by_email_log",
        "by_email",
        "by_name_log",
    )

    def __init__(self) -> None:
        self.by_overture_log: dict[str, Lead] = {}
        self.by_overture: dict[str, Lead] = {}
        self.by_email_log: dict[str, Lead] = {}
        self.by_email: dict[str, Lead] = {}
        self.by_name_log: dict[str, Lead] = {}


def _resolve_from_index(
    index: _PromoteResolveIndex,
    log_lead: LeadLogLead,
) -> Optional[Lead]:
    """Same priority as the old per-row DB resolver, using preloaded maps."""
    overture_id = str(log_lead.overture_id).strip() if log_lead.overture_id else None
    if overture_id:
        found = index.by_overture_log.get(overture_id) or index.by_overture.get(overture_id)
        if found:
            return found

    norm_email = normalize_email(log_lead.email)
    if norm_email:
        found = index.by_email_log.get(norm_email) or index.by_email.get(norm_email)
        if found:
            return found

    if log_lead.business_name:
        found = index.by_name_log.get(log_lead.business_name)
        if found:
            return found
    return None


async def _build_promote_resolve_index(
    db: AsyncSession,
    user_id: UUID,
    log_id: UUID,
    leads_in_log: list[LeadLogLead],
) -> tuple[_PromoteResolveIndex, set[str], set[tuple[str, str]], set[str]]:
    """
    One candidate query for this promote batch.
    Returns resolve index + dedup key sets for save-all mode.
    """
    index = _PromoteResolveIndex()
    existing_overture_ids: set[str] = set()
    existing_email_name_pairs: set[tuple[str, str]] = set()
    existing_names_no_email: set[str] = set()

    candidate_overture_ids: set[str] = set()
    candidate_emails: set[str] = set()
    candidate_names: set[str] = set()
    candidate_raw_names: set[str] = set()

    for l in leads_in_log:
        oid = str(l.overture_id).strip() if l.overture_id else None
        if oid:
            candidate_overture_ids.add(oid)
        email = normalize_email(l.email)
        name = normalize_business_name(l.business_name)
        if email:
            candidate_emails.add(email)
        if name:
            candidate_names.add(name)
        if l.business_name:
            candidate_raw_names.add(l.business_name)

    dedup_filters = []
    if candidate_overture_ids:
        dedup_filters.append(Lead.overture_id.in_(candidate_overture_ids))
    if candidate_emails:
        dedup_filters.append(func.lower(Lead.email).in_(candidate_emails))
    if candidate_names:
        dedup_filters.append(func.lower(Lead.business_name).in_(candidate_names))
    if candidate_raw_names:
        dedup_filters.append(Lead.business_name.in_(candidate_raw_names))

    if not dedup_filters:
        return index, existing_overture_ids, existing_email_name_pairs, existing_names_no_email

    # Newest first so first-write into maps matches previous order_by(created_at.desc())
    existing_leads = (
        await db.scalars(
            select(Lead)
            .where(Lead.user_id == user_id, or_(*dedup_filters))
            .order_by(Lead.created_at.desc())
        )
    ).all()

    for lead in existing_leads:
        norm_email = normalize_email(lead.email)
        norm_name = normalize_business_name(lead.business_name)
        norm_overture_id = str(lead.overture_id).strip() if lead.overture_id else None

        if norm_overture_id:
            existing_overture_ids.add(norm_overture_id)
            if norm_overture_id not in index.by_overture:
                index.by_overture[norm_overture_id] = lead
            if lead.lead_log_id == log_id and norm_overture_id not in index.by_overture_log:
                index.by_overture_log[norm_overture_id] = lead

        if norm_email:
            if norm_email not in index.by_email:
                index.by_email[norm_email] = lead
            if lead.lead_log_id == log_id and norm_email not in index.by_email_log:
                index.by_email_log[norm_email] = lead

        if lead.lead_log_id == log_id and lead.business_name and lead.business_name not in index.by_name_log:
            index.by_name_log[lead.business_name] = lead

        if norm_email and norm_name:
            existing_email_name_pairs.add((norm_email, norm_name))
        elif norm_name:
            existing_names_no_email.add(norm_name)

    return index, existing_overture_ids, existing_email_name_pairs, existing_names_no_email


# --- Promote leads from log to main database ---
async def promote_lead_log_to_database(
    log_id: UUID,
    db: AsyncSession,
    user_id: UUID,
    selected_lead_ids: Optional[List[UUID]] = None,
) -> BaseResponse:
    """
    Promote selected or all leads from LeadLogLead → Lead.

    Rules:
    - If selected_lead_ids is provided → promote only those.
    - If not provided or empty → promote all unpromoted leads in that log.
    - Skips duplicates (same email, or same company when no real email).
    - Mark promoted=True in LeadLogLead for moved leads (when not explicitly selected).
    - Mark LeadLog.promoted=True if all leads in that log are now promoted.
    - Returns ``lead_ids`` (Lead Database UUIDs) so Create Campaign can load them
      without fragile email/name matching (critical while enrichment is still running).
    """

    try:
        # --- Step 1: Validate log ownership ---
        log = await db.scalar(select(LeadLog).where(LeadLog.id == log_id, LeadLog.user_id == user_id))
        if not log:
            raise HTTPException(status_code=404, detail="Lead log not found or unauthorized access.")

        # --- Step 2: Fetch leads to promote ---
        # If specific lead IDs are provided, fetch those (regardless of promoted status)
        # Otherwise, fetch only unpromoted leads
        if selected_lead_ids:
            query = select(LeadLogLead).where(
                LeadLogLead.lead_log_id == log_id,
                LeadLogLead.id.in_(selected_lead_ids)
            )
        else:
            query = select(LeadLogLead).where(
                LeadLogLead.lead_log_id == log_id,
                LeadLogLead.promoted.is_(False)
            )

        leads_in_log = (await db.scalars(query)).all()
        if not leads_in_log:
            if selected_lead_ids:
                raise HTTPException(status_code=404, detail="No leads found with the selected IDs.")
            else:
                raise HTTPException(status_code=404, detail="No unpromoted leads found in this log.")

        # --- Step 3: Create new lead records ---
        # When explicit lead ids are provided (Save Selected), preserve the exact
        # selected count 1:1 from Lead Log -> Lead Database, even if two rows share
        # the same email. Dedup against existing DB is only applied for implicit
        # bulk mode (save all unpromoted).
        now = datetime.now(timezone.utc)
        new_records: list[Lead] = []
        resolved_lead_ids: list[str] = []
        promoted_count = 0
        skipped_count = 0
        reused_count = 0

        (
            resolve_index,
            existing_overture_ids,
            existing_email_name_pairs,
            existing_names_no_email,
        ) = await _build_promote_resolve_index(db, user_id, log_id, list(leads_in_log))

        for index, l in enumerate(leads_in_log):
            # When not explicitly selected (bulk save), only save unpromoted leads
            if not selected_lead_ids and l.promoted:
                continue

            # Already promoted → reuse existing Lead Database row (no duplicates)
            if l.promoted:
                existing = _resolve_from_index(resolve_index, l)
                if existing:
                    resolved_lead_ids.append(str(existing.id))
                    reused_count += 1
                    continue

            norm_email = normalize_email(l.email)
            norm_name = normalize_business_name(l.business_name)
            norm_overture_id = (str(l.overture_id).strip() if l.overture_id else None)
            duplicate = False
            if not selected_lead_ids:
                # Save-all mode: keep dedupe to avoid re-inserting known leads.
                # Save-selected mode intentionally skips this so repeated emails
                # are preserved as separate leads when the user explicitly chose them.
                if norm_overture_id and norm_overture_id in existing_overture_ids:
                    duplicate = True
                elif norm_email and norm_name and (norm_email, norm_name) in existing_email_name_pairs:
                    duplicate = True
                elif not norm_email and norm_name and norm_name in existing_names_no_email:
                    duplicate = True

            if duplicate:
                skipped_count += 1
                if not l.promoted:
                    l.promoted = True
                existing = _resolve_from_index(resolve_index, l)
                if existing:
                    resolved_lead_ids.append(str(existing.id))
                continue

            stored_email = norm_email
            # Unique timestamps keep offset pagination stable for large promote batches
            row_time = now - timedelta(microseconds=index)
            new_records.append(
                Lead(
                    business_name=l.business_name,
                    industry=l.industry,
                    email=stored_email,
                    contact_number=l.contact_number,
                    address=l.address,
                    website=l.website,
                    lead_score=l.lead_score,
                    # Carry scraped context so leads promoted after enrichment keep it.
                    services=l.services,
                    website_summary=l.website_summary,
                    business_description=l.business_description,
                    # Master-catalog link → lets the campaign enrichment gate read
                    # live enrichment status (NULL for Google/manual leads).
                    overture_id=l.overture_id,
                    starred=False,  # New leads start unstarred
                    user_id=user_id,
                    lead_log_id=log_id,
                    created_at=row_time,
                    updated_at=row_time,
                )
            )
            if norm_overture_id:
                existing_overture_ids.add(norm_overture_id)
            if norm_email and norm_name:
                existing_email_name_pairs.add((norm_email, norm_name))
            elif norm_name:
                existing_names_no_email.add(norm_name)
            # Mark as promoted to prevent duplicate saves
            if not l.promoted:
                l.promoted = True
            promoted_count += 1

        if not new_records and not resolved_lead_ids and skipped_count == 0:
            if selected_lead_ids:
                raise HTTPException(status_code=400, detail="No leads to promote from the selected IDs.")
            else:
                raise HTTPException(status_code=400, detail="No new leads to promote (all already promoted).")

        # If all leads were skipped (duplicates) and we could not resolve any DB ids
        if not new_records and not resolved_lead_ids and skipped_count > 0:
            if selected_lead_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"All selected leads already exist in your Lead Database. {skipped_count} lead(s) skipped.",
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"All leads already exist in your Lead Database. {skipped_count} lead(s) skipped.",
                )

        if new_records:
            db.add_all(new_records)
            await db.flush()
            resolved_lead_ids.extend(str(record.id) for record in new_records)

        # --- Step 4: If all leads in log are promoted, mark log.promoted=True ---
        total_leads = await db.scalar(
            select(func.count()).select_from(LeadLogLead).where(LeadLogLead.lead_log_id == log_id)
        )
        promoted_leads = await db.scalar(
            select(func.count()).select_from(LeadLogLead).where(
                LeadLogLead.lead_log_id == log_id, LeadLogLead.promoted.is_(True)
            )
        )

        if promoted_leads == total_leads:
            log.promoted = True

        log.updated_at = now
        await db.commit()

        # Build success message
        if skipped_count > 0:
            message = f"{promoted_count} lead(s) saved successfully. {skipped_count} duplicate(s) skipped."
        elif reused_count and not promoted_count:
            message = f"{reused_count} lead(s) already in Lead Database."
        else:
            message = f"{promoted_count} lead(s) saved successfully."

        # Preserve order, drop accidental duplicates
        unique_lead_ids = list(dict.fromkeys(resolved_lead_ids))

        return BaseResponse(
            status="success",
            message=message,
            data={
                "count": promoted_count,
                "skipped": skipped_count,
                "reused": reused_count,
                "total_leads": total_leads,
                "promoted_leads": promoted_leads,
                "all_promoted": log.promoted,
                "lead_ids": unique_lead_ids,
            },
        )

    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to promote leads. Please try again.")

    except HTTPException:
        raise

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to promote leads. Please try again.")

# --- Fetch all user leads ---
async def get_all_leads(
    user_id: UUID,
    db: AsyncSession,
    search: str | None = None,
    min_score: int | None = None,
    max_score: int | None = None,
    page: int = 1,
    limit: int = 50,
) -> BaseResponse:
    """Return paginated leads for a user, with optional filtering."""
    try:
        query = (
            select(Lead)
            .where(Lead.user_id == user_id)
            .order_by(
                case((Lead.lead_log_id.is_(None), 0), else_=1),
                Lead.created_at.desc(),
                # Unique tiebreaker: promote/import batches can share (or nearly share)
                # created_at, so without a stable secondary key the ordering of tied
                # rows is arbitrary and DIFFERS between page requests. That makes
                # offset/limit pagination drop and repeat rows — the client dedups the
                # repeats and the dropped ones never arrive (490 rows rendered as 356).
                Lead.id.desc(),
            )
        )

        # search filters
        if search:
            like_pattern = f"%{search.lower()}%"
            query = query.where(
                or_(
                    Lead.business_name.ilike(like_pattern),
                    Lead.industry.ilike(like_pattern),
                    Lead.email.ilike(like_pattern),
                    Lead.address.ilike(like_pattern),
                )
            )

        # score range
        if min_score is not None and max_score is not None:
            query = query.where(and_(Lead.lead_score >= min_score, Lead.lead_score <= max_score))
        elif min_score is not None:
            query = query.where(Lead.lead_score >= min_score)
        elif max_score is not None:
            query = query.where(Lead.lead_score <= max_score)

        leads = (await db.scalars(query.offset((page - 1) * limit).limit(limit))).all()
        lead_ids = [lead.id for lead in leads]
        
        # Get last contacted date and outreach status for each lead
        last_contacted_map = {}
        outreach_status_map = {}
        if lead_ids:
            # Get latest email activity for each lead
            last_activity_query = (
                select(
                    EmailActivity.lead_id,
                    func.max(EmailActivity.sent_at).label("last_sent_at")
                )
                .where(EmailActivity.lead_id.in_(lead_ids))
                .group_by(EmailActivity.lead_id)
            )
            last_activities = await db.execute(last_activity_query)
            activity_lead_ids = set()
            for row in last_activities.all():
                lead_id = row.lead_id
                activity_lead_ids.add(lead_id)
                last_contacted_map[lead_id] = row.last_sent_at
            
            # Check for replies separately
            replied_query = (
                select(EmailActivity.lead_id)
                .where(
                    EmailActivity.lead_id.in_(lead_ids),
                    EmailActivity.replied == True
                )
                .distinct()
            )
            replied_results = await db.execute(replied_query)
            replied_lead_ids = {row.lead_id for row in replied_results.all()}
            
            # Determine outreach status for each lead
            for lead_id in activity_lead_ids:
                if lead_id in replied_lead_ids:
                    outreach_status_map[lead_id] = "replied"
                else:
                    # Check if the last sent email was recent (within last 7 days)
                    last_sent = last_contacted_map.get(lead_id)
                    if last_sent:
                        days_since_sent = (datetime.now(timezone.utc) - last_sent).days
                        if days_since_sent <= 7:
                            outreach_status_map[lead_id] = "no_response"
                        else:
                            outreach_status_map[lead_id] = "contacted"
                    else:
                        outreach_status_map[lead_id] = "not_started"
        
        # Get campaign status for each lead
        campaign_status_map = {}
        if lead_ids:
            # Get ongoing campaigns for each lead
            campaign_query = (
                select(
                    CampaignLead.lead_id,
                    Campaign.status
                )
                .join(Campaign, CampaignLead.campaign_id == Campaign.id)
                .where(
                    CampaignLead.lead_id.in_(lead_ids),
                    Campaign.status == CampaignStatus.ONGOING
                )
            )
            campaign_results = await db.execute(campaign_query)
            for row in campaign_results.all():
                campaign_status_map[row.lead_id] = "ongoing"
        
        data = []
        for lead in leads:
            lead_data = {
                "id": lead.id,
                "business_name": lead.business_name,
                "industry": lead.industry,
                "email": lead.email,
                "contact_number": lead.contact_number,
                "address": lead.address,
                "website": lead.website,
                "lead_score": lead.lead_score,
                "starred": getattr(lead, 'starred', False),
                "created_at": lead.created_at,
                "updated_at": lead.updated_at,
                "last_contacted": last_contacted_map.get(lead.id),
                "campaign_status": campaign_status_map.get(lead.id),
                "outreach_status": outreach_status_map.get(lead.id, "not_started"),
                "is_user_added": lead.lead_log_id is None,
            }
            data.append(lead_data)

        return BaseResponse(
            status="success",
            message=f"Found {len(data)} lead(s).",
            data=data,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to load leads. Please try again.")

async def create_lead_service(
    db: AsyncSession,
    lead_data: LeadCreate,
    user_id: UUID,
) -> Lead:
    try:
        now = datetime.now(timezone.utc)

        new_lead = Lead(
            **lead_data.model_dump(),
            user_id=user_id,

            # ✅ REQUIRED non-null fields
            starred=False,
            email_subscribed=True,

            created_at=now,
            updated_at=now,
        )

        db.add(new_lead)
        await db.commit()
        await db.refresh(new_lead)

        return new_lead

    except SQLAlchemyError as e:
        await db.rollback()
        # Log the real error
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again.",
        )

async def update_lead_service(
    db: AsyncSession,
    lead_id: UUID,
    user_id: UUID,
    lead_data: LeadUpdate,
) -> Lead:
    """
    Update an existing lead (partial update).
    """
    try:
        stmt = select(Lead).where(
            Lead.id == lead_id,
            Lead.user_id == user_id,
        )
        lead = await db.scalar(stmt)

        if not lead:
            raise ValueError("Lead not found")

        update_data = lead_data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(lead, field, value)

        lead.updated_at = datetime.now(timezone.utc)

        db.add(lead)
        await db.commit()
        await db.refresh(lead)

        return lead

    except SQLAlchemyError:
        await db.rollback()
        raise

# --- Delete a single lead ---
async def delete_lead(lead_id: UUID, user_id: UUID, db: AsyncSession) -> BaseResponse:
    """Delete a lead owned by the user."""
    try:
        # First fetch the lead to get its name for the response message
        query = select(Lead).where(Lead.id == lead_id, Lead.user_id == user_id)
        lead = await db.scalar(query)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found or unauthorized access.")

        business_name = lead.business_name

        # Use explicit delete statement for reliable async deletion
        delete_stmt = delete(Lead).where(Lead.id == lead_id, Lead.user_id == user_id)
        result = await db.execute(delete_stmt)
        await db.commit()

        # Check if deletion was successful
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Lead not found or already deleted.")

        return BaseResponse(
            status="success",
            message=f"Lead '{business_name}' deleted successfully.",
            data={"id": str(lead_id)},
        )

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete lead(s). Please try again.")


# --- Bulk delete leads ---
async def delete_leads_bulk(lead_ids: List[UUID], user_id: UUID, db: AsyncSession) -> BaseResponse:
    """Delete many of the user's leads in a single transaction.

    Scoped to user_id, so ids that don't belong to the caller are silently
    skipped (never an error). Returns how many were actually deleted vs.
    requested — some requested ids may already be gone or not owned. The caller
    (route/schema) enforces the 1000-id cap.
    """
    try:
        unique_ids = list(dict.fromkeys(lead_ids))  # dedupe, preserve order
        if not unique_ids:
            return BaseResponse(
                status="success",
                message="No leads to delete.",
                data={"requested": 0, "deleted": 0},
            )

        delete_stmt = delete(Lead).where(
            Lead.id.in_(unique_ids), Lead.user_id == user_id
        )
        result = await db.execute(delete_stmt)
        await db.commit()

        deleted = result.rowcount or 0
        return BaseResponse(
            status="success",
            message=f"Deleted {deleted} lead(s).",
            data={"requested": len(unique_ids), "deleted": deleted},
        )

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete lead(s). Please try again.")


async def get_leads_by_ids(lead_ids: List[UUID], user_id: UUID, db: AsyncSession) -> BaseResponse:
    """Fetch many leads owned by the user in one query."""
    try:
        unique_ids = list(dict.fromkeys(lead_ids))
        if not unique_ids:
            return BaseResponse(status="success", message="No leads requested.", data=[])

        rows = (await db.scalars(
            select(Lead).where(Lead.user_id == user_id, Lead.id.in_(unique_ids))
        )).all()
        row_map = {str(row.id): row for row in rows}
        ordered = [row_map[str(i)] for i in unique_ids if str(i) in row_map]

        return BaseResponse(
            status="success",
            message=f"Found {len(ordered)} lead(s).",
            data=[lead_to_response(lead) for lead in ordered],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to load leads. Please try again.")


# --- Toggle star status for a lead ---
async def toggle_lead_star(lead_id: UUID, user_id: UUID, db: AsyncSession) -> BaseResponse:
    """Toggle the starred status of a lead."""
    try:
        query = select(Lead).where(Lead.id == lead_id, Lead.user_id == user_id)
        lead = await db.scalar(query)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found or unauthorized access.")

        # Toggle starred status
        lead.starred = not lead.starred
        lead.updated_at = datetime.now(timezone.utc)
        
        await db.commit()
        
        return BaseResponse(
            status="success",
            message=f"Lead {'starred' if lead.starred else 'unstarred'} successfully.",
            data={
                "id": str(lead_id),
                "starred": lead.starred,
            },
        )

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update lead. Please try again.")
