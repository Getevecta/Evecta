"""Step 6 — unified campaign launch readiness (generation + review + sending setup)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.email_sending_mode import EmailSendingMode
from app.models.campaign import Campaign
from app.models.campaign_lead import CampaignLead
from app.models.lead import Lead
from app.models.mailbox import Mailbox, MailboxType
from app.models.overture_place import OverturePlace
from app.services.campaign_guard import get_owned_campaign_or_404, is_campaign_editable
from app.services.campaign_sender_email import resolve_campaign_sender_email
from app.services.campaign_status_counts import (
    fetch_lead_email_status_groups,
    fold_generation_counts,
    generation_status_summary_from_counts,
    review_summary_from_groups,
)
from app.services.campaign_send_status_service import get_campaign_send_status
from app.utils.campaign_placeholders import check_unmodified_placeholders


def _check_item(key: str, label: str, passed: bool, message: str) -> dict[str, Any]:
    return {"key": key, "label": label, "passed": passed, "message": message}


async def _count_active_mailboxes(
    db: AsyncSession,
    *,
    user_id: str | None,
    mailbox_type: MailboxType,
    require_domain: bool = False,
) -> int:
    query = select(func.count(Mailbox.id)).where(
        Mailbox.mailbox_type == mailbox_type,
        Mailbox.is_active.is_(True),
    )
    if require_domain:
        query = query.where(Mailbox.domain_id.isnot(None))
    if mailbox_type == MailboxType.USER:
        query = query.where(Mailbox.user_id == user_id)
    return int(await db.scalar(query) or 0)


async def _count_leads_still_enriching(db: AsyncSession, campaign_id: str) -> int:
    """Campaign leads whose master business is not done enriching yet (§5.8).

    Soft signal only — leads with no overture_id (Google/manual) are never counted.
    'still enriching' = master status NULL/pending/processing (not done/failed).
    """
    return int(
        await db.scalar(
            select(func.count())
            .select_from(CampaignLead)
            .join(Lead, Lead.id == CampaignLead.lead_id)
            .join(OverturePlace, OverturePlace.overture_id == Lead.overture_id)
            .where(
                CampaignLead.campaign_id == campaign_id,
                (OverturePlace.enrichment_status.is_(None))
                | (OverturePlace.enrichment_status.in_(["pending", "processing"])),
            )
        )
        or 0
    )


async def reconcile_campaign_sending_mode(
    campaign: Campaign,
    user_id: str,
    db: AsyncSession,
) -> None:
    """
    If campaign is set to SYSTEM but no usable system mailbox exists, fall back to USER
    when the user has a connected account (common in local/dev).
    """
    if campaign.email_sending_mode != EmailSendingMode.SYSTEM:
        return
    system_count = await _count_active_mailboxes(
        db, user_id=user_id, mailbox_type=MailboxType.SYSTEM
    )
    if system_count > 0:
        return
    user_count = await _count_active_mailboxes(db, user_id=user_id, mailbox_type=MailboxType.USER)
    if user_count > 0:
        campaign.email_sending_mode = EmailSendingMode.USER
        campaign.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(campaign)


async def get_campaign_launch_readiness(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or str(campaign.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail="Campaign not found or unauthorized.")

    await reconcile_campaign_sending_mode(campaign, user_id, db)

    checks: list[dict[str, Any]] = []
    blockers: list[str] = []

    if not is_campaign_editable(campaign):
        checks.append(
            _check_item(
                "campaign_draft",
                "Campaign is editable",
                False,
                f"Campaign is already {campaign.status.value}.",
            )
        )
        blockers.append("Campaign has already been launched.")
        return _build_response(campaign, checks, blockers, approved_to_send=0, skipped_rejected=0)

    draft_ready = bool(campaign.email_subject and campaign.email_content)
    checks.append(
        _check_item(
            "email_draft",
            "Email draft saved",
            draft_ready,
            "Subject and body are required." if not draft_ready else "Draft is ready.",
        )
    )
    if not draft_ready:
        blockers.append("Draft not ready for launch.")

    placeholder_hits: list[str] = []
    if campaign.email_content:
        placeholder_hits = check_unmodified_placeholders(campaign.email_content)
    checks.append(
        _check_item(
            "placeholders",
            "Square-bracket placeholders filled",
            len(placeholder_hits) == 0,
            "Unresolved [placeholders] in email content."
            if placeholder_hits
            else "No unresolved placeholders.",
        )
    )
    if placeholder_hits:
        blockers.append("Your email content contains unresolved [placeholders].")

    lead_count = (
        await db.scalar(
            select(func.count())
            .select_from(CampaignLead)
            .where(CampaignLead.campaign_id == campaign_id)
        )
        or 0
    )
    checks.append(
        _check_item(
            "leads",
            "Leads attached",
            lead_count > 0,
            f"{lead_count} lead(s) selected." if lead_count else "Add at least one lead.",
        )
    )
    if lead_count == 0:
        blockers.append("No leads attached to the campaign.")

    if campaign.email_sending_mode is None:
        checks.append(
            _check_item(
                "sending_mode",
                "Email sending method",
                False,
                "Choose System Email or Existing Email Account.",
            )
        )
        blockers.append("Email sending method not selected.")
    elif campaign.email_sending_mode == EmailSendingMode.SYSTEM:
        system_count = await _count_active_mailboxes(
            db,
            user_id=user_id,
            mailbox_type=MailboxType.SYSTEM,
        )
        user_count = await _count_active_mailboxes(
            db, user_id=user_id, mailbox_type=MailboxType.USER
        )
        ok = system_count > 0 or user_count > 0
        checks.append(
            _check_item(
                "mailbox",
                "System mailbox available",
                ok,
                "System email is available." if system_count > 0 else (
                    "Connected email account will be used."
                    if user_count > 0
                    else "System email is currently unavailable."
                ),
            )
        )
        if not ok:
            blockers.append(
                "No sending account is available. Go back to Step 4 and connect "
                "Gmail or IMAP, or configure a system mailbox with a domain."
            )
    else:
        user_count = await _count_active_mailboxes(
            db, user_id=user_id, mailbox_type=MailboxType.USER
        )
        ok = user_count > 0
        checks.append(
            _check_item(
                "mailbox",
                "Connected email account",
                ok,
                "Email account connected." if ok else "No active email account found.",
            )
        )
        if not ok:
            blockers.append(
                "No email account connected. Go back to Step 4 and connect "
                "an Existing Email Account (Gmail or IMAP)."
            )

    email_groups = await fetch_lead_email_status_groups(db, campaign_id)
    gen_summary = None
    review_summary = None

    approved_to_send = lead_count
    skipped_rejected = 0

    if email_groups:
        by_gen, by_comp, row_count = fold_generation_counts(email_groups)
        gen_summary = generation_status_summary_from_counts(
            by_gen, by_comp, row_count=row_count, expected_total=lead_count
        )
        review_summary = review_summary_from_groups(email_groups)

        generating = gen_summary.get("generating", 0)
        gen_ok = gen_summary["is_complete"] or (
            review_summary["approved"] > 0 and generating == 0
        )
        checks.append(
            _check_item(
                "generation",
                "Per-lead emails generated",
                gen_ok,
                f"{gen_summary['ready']}/{gen_summary['total']} ready."
                if not gen_ok
                else "All per-lead emails generated.",
            )
        )
        if not gen_ok:
            blockers.append("Per-lead email generation is still in progress.")

        review_ok = review_summary["can_launch"]
        checks.append(
            _check_item(
                "review",
                "User review complete",
                review_ok,
                f"{review_summary['approved']} approved, {review_summary['pending_review']} pending."
                if not review_ok
                else f"{review_summary['approved']} email(s) approved.",
            )
        )
        blockers.extend(review_summary["launch_blockers"])

        approved_to_send = review_summary["approved"]
        skipped_rejected = review_summary["rejected"]

    # Soft, non-blocking signal: how many leads are still being enriched. Shown to
    # the user so a rushed launch is an informed choice; never a launch blocker
    # (the generation gate handles quality — §5.8).
    enriching_count = await _count_leads_still_enriching(db, campaign_id)

    return _build_response(
        campaign,
        checks,
        blockers,
        approved_to_send=approved_to_send,
        skipped_rejected=skipped_rejected,
        generation_summary=gen_summary,
        review_summary=review_summary,
        enriching={"count": enriching_count, "total": lead_count},
    )


def _build_response(
    campaign: Campaign,
    checks: list[dict[str, Any]],
    blockers: list[str],
    *,
    approved_to_send: int,
    skipped_rejected: int,
    generation_summary: dict | None = None,
    review_summary: dict | None = None,
    enriching: dict | None = None,
) -> dict[str, Any]:
    unique_blockers = list(dict.fromkeys(blockers))
    can_launch = len(unique_blockers) == 0 and all(c["passed"] for c in checks)
    return {
        "campaign_id": str(campaign.id),
        "campaign_status": campaign.status.value,
        "can_launch": can_launch,
        "launch_blockers": unique_blockers,
        "checks": checks,
        "approved_to_send": approved_to_send,
        "skipped_rejected": skipped_rejected,
        "email_sending_mode": (
            campaign.email_sending_mode.value if campaign.email_sending_mode else None
        ),
        "generation": generation_summary,
        "review": review_summary,
        # Soft signal for the launch UI ({"count", "total"}); None when N/A.
        "enriching": enriching,
    }


async def _campaign_lead_stats(db: AsyncSession, campaign_id) -> tuple[int, float]:
    lead_count = int(
        await db.scalar(
            select(func.count(CampaignLead.id)).where(CampaignLead.campaign_id == campaign_id)
        )
        or 0
    )
    if lead_count == 0:
        return 0, 0.0
    avg = await db.scalar(
        select(
            func.coalesce(
                func.avg(func.coalesce(Lead.lead_score, CampaignLead.lead_score)),
                0,
            )
        )
        .select_from(CampaignLead)
        .outerjoin(Lead, CampaignLead.lead_id == Lead.id)
        .where(CampaignLead.campaign_id == campaign_id)
    )
    return lead_count, round(float(avg or 0), 2)


async def build_campaign_launch_summary(
    campaign: Campaign,
    user_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    lead_count, avg_score = await _campaign_lead_stats(db, campaign.id)
    email_sending_mode_value = None
    if campaign.email_sending_mode is not None:
        email_sending_mode_value = (
            campaign.email_sending_mode.value
            if hasattr(campaign.email_sending_mode, "value")
            else str(campaign.email_sending_mode)
        )
    sender_email = await resolve_campaign_sender_email(
        db,
        campaign_id=campaign.id,
        user_id=user_id,
        email_sending_mode=campaign.email_sending_mode,
    )
    return {
        "id": campaign.id,
        "name": campaign.name,
        "description": campaign.description,
        "goal_id": campaign.goal_id,
        "category_id": campaign.category_id,
        "tags": campaign.tags.split(",") if campaign.tags else [],
        "status": campaign.status.value,
        "lead_count": lead_count,
        "avg_lead_score": avg_score,
        "email_sending_mode": email_sending_mode_value,
        "sender_email": sender_email,
        "email_subject": campaign.email_subject,
        "email_content": campaign.email_content,
        "created_at": campaign.created_at,
        "updated_at": campaign.updated_at,
        "launched_at": getattr(campaign, "launched_at", None),
    }


async def get_campaign_launch_view(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """One-shot read model for launch/review screens: campaign + readiness or send status."""
    campaign = await get_owned_campaign_or_404(campaign_id, user_id, db)
    summary = await build_campaign_launch_summary(campaign, user_id, db)
    if is_campaign_editable(campaign):
        readiness = await get_campaign_launch_readiness(campaign_id, user_id, db)
        return {"campaign": summary, "readiness": readiness, "status": None}
    send_status = await get_campaign_send_status(campaign_id, user_id, db)
    return {"campaign": summary, "readiness": None, "status": send_status}
