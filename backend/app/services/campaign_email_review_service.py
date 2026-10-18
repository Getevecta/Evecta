"""Step 5 — per-lead email user review (approve / reject / regenerate)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.campaign import Campaign
from app.models.campaign_lead import CampaignLead
from app.models.campaign_lead_email import (
    CampaignLeadEmail,
    ComplianceStatus,
    GenerationStatus,
    ReviewStatus,
)
from app.services.campaign_email_generation_service import (
    PRIOR_BODIES_MAX,
    _campaign_uses_ai_per_lead_generation,
    _clear_generation_cancelled,
    _fetch_campaign_leads,
    _load_profiles,
    generate_lead_email_row,
    strip_html_for_check,
)
from app.services.campaign_guard import get_editable_campaign_or_404
from app.services.campaign_status_counts import (
    fetch_lead_email_status_groups,
    review_summary_from_groups,
)
from app.services.compliance_gate import evaluate_email_compliance


async def _reload_email_row_for_api(
    db: AsyncSession,
    email_id,
) -> CampaignLeadEmail:
    """Reload a row with relations needed for API serialization."""
    row = await db.scalar(
        select(CampaignLeadEmail)
        .where(CampaignLeadEmail.id == email_id)
        .options(
            selectinload(CampaignLeadEmail.campaign_lead),
            selectinload(CampaignLeadEmail.lead),
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Email draft not found.")
    return row


async def _get_campaign_or_404(campaign_id: str, user_id: str, db: AsyncSession) -> Campaign:
    return await get_editable_campaign_or_404(
        campaign_id, user_id, db, action="review"
    )


async def _list_email_rows(campaign_id: str, db: AsyncSession) -> list[CampaignLeadEmail]:
    result = await db.scalars(
        select(CampaignLeadEmail)
        .where(CampaignLeadEmail.campaign_id == campaign_id)
        .order_by(CampaignLeadEmail.lead_index.asc())
    )
    return list(result.all())


def _review_summary(rows: list[CampaignLeadEmail]) -> dict[str, Any]:
    if not rows:
        return {
            "has_per_lead_emails": False,
            "total": 0,
            "pending_review": 0,
            "approved": 0,
            "rejected": 0,
            "generation_in_progress": 0,
            "generation_failed": 0,
            "ready_for_review": 0,
            "can_launch": False,
            "launch_blockers": [],
        }

    pending_review = 0
    approved = 0
    rejected = 0
    gen_in_progress = 0
    gen_failed = 0
    ready_for_review = 0
    blockers: list[str] = []

    for row in rows:
        gs = row.generation_status
        rs = row.review_status
        cs = row.compliance_status

        if gs == GenerationStatus.GENERATING:
            gen_in_progress += 1
        elif gs == GenerationStatus.FAILED:
            gen_failed += 1
        elif gs == GenerationStatus.READY and cs == ComplianceStatus.PASSED:
            ready_for_review += 1
            if rs == ReviewStatus.REJECTED:
                rejected += 1
            elif rs == ReviewStatus.APPROVED:
                approved += 1
            else:
                # Outreach-ready from Step 3 (compliance passed) — launchable
                approved += 1
        elif gs == GenerationStatus.READY and rs == ReviewStatus.PENDING:
            pending_review += 1

    if gen_in_progress:
        blockers.append(
            f"{gen_in_progress} email(s) still generating — wait for completion before launch."
        )
    if pending_review:
        blockers.append(
            f"{pending_review} email(s) awaiting your review — approve or reject before launch."
        )
    if approved == 0:
        blockers.append("At least one email must be approved to launch.")

    can_launch = len(blockers) == 0 and approved > 0

    return {
        "has_per_lead_emails": True,
        "total": len(rows),
        "pending_review": pending_review,
        "approved": approved,
        "rejected": rejected,
        "generation_in_progress": gen_in_progress,
        "generation_failed": gen_failed,
        "ready_for_review": ready_for_review,
        "can_launch": can_launch,
        "launch_blockers": blockers,
    }


async def get_email_review_summary(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    await _get_campaign_or_404(campaign_id, user_id, db)
    groups = await fetch_lead_email_status_groups(db, campaign_id)
    summary = review_summary_from_groups(groups)
    return {"campaign_id": campaign_id, **summary}


def get_launch_review_blocker(rows: list[CampaignLeadEmail]) -> str | None:
    """Return a single blocker message for launch, or None if review gate passes."""
    summary = _review_summary(rows)
    if not summary["has_per_lead_emails"]:
        return None
    if summary["launch_blockers"]:
        return summary["launch_blockers"][0]
    return None


def approved_lead_ids(rows: list[CampaignLeadEmail]) -> set[str]:
    """Lead IDs that will receive email on launch (explicitly approved or outreach-ready)."""
    ids: set[str] = set()
    for r in rows:
        if not r.lead_id:
            continue
        if r.review_status == ReviewStatus.APPROVED:
            ids.add(str(r.lead_id))
            continue
        if (
            r.generation_status == GenerationStatus.READY
            and r.compliance_status == ComplianceStatus.PASSED
            and r.review_status != ReviewStatus.REJECTED
        ):
            ids.add(str(r.lead_id))
    return ids


async def approve_emails(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
    *,
    email_ids: list[str] | None = None,
    approve_all: bool = False,
) -> dict[str, Any]:
    await _get_campaign_or_404(campaign_id, user_id, db)
    rows = await _list_email_rows(campaign_id, db)
    if not rows:
        raise HTTPException(status_code=400, detail="No per-lead emails to review.")

    id_set = {str(eid) for eid in (email_ids or [])}
    now = datetime.now(timezone.utc)
    updated = 0

    for row in rows:
        if not approve_all and str(row.id) not in id_set:
            continue
        if row.generation_status != GenerationStatus.READY:
            continue
        if row.compliance_status != ComplianceStatus.PASSED:
            continue
        if row.review_status == ReviewStatus.APPROVED:
            continue
        row.review_status = ReviewStatus.APPROVED
        row.updated_at = now
        updated += 1

    if updated == 0 and not approve_all and email_ids:
        raise HTTPException(
            status_code=400,
            detail="No eligible emails to approve (must be ready and compliance-passed).",
        )

    await db.commit()
    refreshed = await _list_email_rows(campaign_id, db)
    summary = _review_summary(refreshed)
    return {"campaign_id": campaign_id, "updated": updated, **summary}


async def reject_emails(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
    *,
    email_ids: list[str] | None = None,
    reject_all_pending: bool = False,
) -> dict[str, Any]:
    await _get_campaign_or_404(campaign_id, user_id, db)
    rows = await _list_email_rows(campaign_id, db)
    if not rows:
        raise HTTPException(status_code=400, detail="No per-lead emails to review.")

    id_set = {str(eid) for eid in (email_ids or [])}
    now = datetime.now(timezone.utc)
    updated = 0

    for row in rows:
        if not reject_all_pending and str(row.id) not in id_set:
            continue
        if reject_all_pending and row.review_status != ReviewStatus.PENDING:
            continue
        if row.review_status == ReviewStatus.REJECTED:
            continue
        row.review_status = ReviewStatus.REJECTED
        row.updated_at = now
        updated += 1

    if updated == 0:
        raise HTTPException(status_code=400, detail="No emails matched for rejection.")

    await db.commit()
    refreshed = await _list_email_rows(campaign_id, db)
    summary = _review_summary(refreshed)
    return {"campaign_id": campaign_id, "updated": updated, **summary}


async def update_lead_email(
    campaign_id: str,
    email_id: str,
    user_id: str,
    db: AsyncSession,
    *,
    subject: str,
    body: str,
    mark_spam_passed: bool = False,
) -> CampaignLeadEmail:
    """Update per-lead draft content; optionally re-run compliance after spam test."""
    await _get_campaign_or_404(campaign_id, user_id, db)
    row = await db.get(CampaignLeadEmail, email_id)
    if not row or str(row.campaign_id) != str(campaign_id):
        raise HTTPException(status_code=404, detail="Email draft not found.")
    if row.generation_status != GenerationStatus.READY:
        raise HTTPException(status_code=400, detail="Email is not ready to edit.")

    trimmed_subject = (subject or "").strip()
    trimmed_body = (body or "").strip()
    if not trimmed_subject or not trimmed_body:
        raise HTTPException(status_code=400, detail="Subject and body are required.")

    now = datetime.now(timezone.utc)
    row.subject = trimmed_subject[:255]
    row.body = trimmed_body
    row.updated_at = now

    if mark_spam_passed:
        user_profile, company_profile, _user = await _load_profiles(db, user_id)
        plain_subject = strip_html_for_check(trimmed_subject)
        plain_body = strip_html_for_check(trimmed_body)
        result = await evaluate_email_compliance(
            subject=plain_subject,
            body=plain_body,
            user_profile=user_profile,
            company_profile=company_profile,
            fast_mode=True,
        )
        if not result.get("passed"):
            violations = result.get("violations") or ["compliance_failed"]
            raise HTTPException(
                status_code=400,
                detail=f"Spam check did not pass: {'; '.join(violations)}",
            )
        row.compliance_status = ComplianceStatus.PASSED
        row.spam_score = result.get("spam_score")
        row.risk_level = result.get("risk_level")
        row.last_error = None
    else:
        row.compliance_status = ComplianceStatus.FAILED
        row.spam_score = None
        row.risk_level = None
        row.last_error = "awaiting_spam_retest"
        if row.review_status == ReviewStatus.APPROVED:
            row.review_status = ReviewStatus.PENDING

    await db.commit()
    return await _reload_email_row_for_api(db, row.id)


async def regenerate_email(
    campaign_id: str,
    email_id: str,
    user_id: str,
    db: AsyncSession,
) -> tuple[CampaignLeadEmail, bool]:
    """Regenerate one email. Returns (row, restored) — restored=True means every
    attempt failed and the previous Ready draft was kept instead of marking FAILED."""
    campaign = await _get_campaign_or_404(campaign_id, user_id, db)
    row = await db.get(CampaignLeadEmail, email_id)
    if not row or str(row.campaign_id) != str(campaign_id):
        raise HTTPException(status_code=404, detail="Email draft not found.")

    if row.generation_status == GenerationStatus.GENERATING:
        raise HTTPException(status_code=400, detail="Email is already generating.")

    if _campaign_uses_ai_per_lead_generation(campaign):
        # Affordability gate (402 before any state is touched). The actual charge
        # happens inside generate_lead_email_row only when regeneration succeeds —
        # a failed attempt restores the previous draft and costs nothing.
        from app.services.credit_service import require_pool_credits

        await require_pool_credits(db, campaign.user_id, "ai_draft", 1)

    # A prior /cancel leaves a sticky in-memory flag that would make this
    # regeneration silently no-op — an explicit regenerate overrides it.
    _clear_generation_cancelled(campaign_id)

    campaign_leads = await _fetch_campaign_leads(campaign_id, db)
    campaign_lead = next(
        (cl for cl in campaign_leads if cl.lead_id and str(cl.lead_id) == str(row.lead_id)),
        None,
    )
    if not campaign_lead:
        raise HTTPException(status_code=404, detail="Campaign lead not found.")

    # Request-scoped snapshot of the current draft so a failed regeneration
    # restores it instead of destroying a launchable email.
    was_ready = row.generation_status == GenerationStatus.READY
    prev_subject = row.subject
    prev_body = row.body
    prev_compliance = row.compliance_status
    prev_spam_score = row.spam_score
    prev_risk_level = row.risk_level

    lead_index = row.lead_index
    row.regeneration_count = (row.regeneration_count or 0) + 1
    row.review_status = ReviewStatus.PENDING
    row.generation_status = GenerationStatus.PENDING
    row.compliance_status = ComplianceStatus.PENDING
    row.last_error = None
    await db.flush()

    user_profile, company_profile, user = await _load_profiles(db, user_id)

    prior_bodies: list[str] = []
    others = await _list_email_rows(campaign_id, db)
    for other in others:
        if other.id == row.id:
            continue
        if other.body and other.generation_status == GenerationStatus.READY:
            prior_bodies.append(strip_html_for_check(other.body))

    try:
        updated = await generate_lead_email_row(
            campaign=campaign,
            campaign_lead=campaign_lead,
            lead_index=lead_index,
            row=row,
            user=user,
            user_profile=user_profile,
            company_profile=company_profile,
            prior_bodies=prior_bodies[-PRIOR_BODIES_MAX:],
            db=db,
            total_leads=len(campaign_leads),
        )
    except HTTPException as exc:
        if exc.status_code != 402 or not (was_ready and prev_subject and prev_body):
            raise
        # Credits ran out between the gate and the charge (concurrent spend).
        # The new draft was already discarded uncharged — put the previous
        # launchable draft back before surfacing the 402.
        row.subject = prev_subject
        row.body = prev_body
        row.generation_status = GenerationStatus.READY
        row.compliance_status = prev_compliance
        row.spam_score = prev_spam_score
        row.risk_level = prev_risk_level
        row.review_status = ReviewStatus.PENDING
        row.last_error = None
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        raise

    restored = False
    if (
        updated.generation_status == GenerationStatus.FAILED
        and was_ready
        and prev_subject
        and prev_body
    ):
        updated.subject = prev_subject
        updated.body = prev_body
        updated.generation_status = GenerationStatus.READY
        updated.compliance_status = prev_compliance
        updated.spam_score = prev_spam_score
        updated.risk_level = prev_risk_level
        updated.review_status = ReviewStatus.PENDING
        updated.last_error = None
        updated.updated_at = datetime.now(timezone.utc)
        restored = True

    await db.commit()
    updated = await _reload_email_row_for_api(db, updated.id)
    return updated, restored
