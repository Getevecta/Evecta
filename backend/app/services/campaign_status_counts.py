"""Grouped status counts for campaign progress polling.

Status endpoints only need tallies (queued / generating / sent / failed). Fetching
full ``CampaignLeadEmail`` or ``EmailJob`` rows — including email bodies — just to
count them is wasted work that grows with campaign size and poll frequency.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign_lead import CampaignLead
from app.models.campaign_lead_email import (
    CampaignLeadEmail,
    ComplianceStatus,
    GenerationStatus,
    ReviewStatus,
)
from app.models.email_job import EmailJob, EmailJobStatus


def enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


async def count_campaign_leads(db: AsyncSession, campaign_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(CampaignLead)
            .where(CampaignLead.campaign_id == campaign_id)
        )
        or 0
    )


async def fetch_lead_email_status_groups(
    db: AsyncSession,
    campaign_id: str,
) -> list[tuple[Any, Any, Any, int]]:
    """Return (generation_status, compliance_status, review_status, count) rows."""
    result = await db.execute(
        select(
            CampaignLeadEmail.generation_status,
            CampaignLeadEmail.compliance_status,
            CampaignLeadEmail.review_status,
            func.count(),
        )
        .where(CampaignLeadEmail.campaign_id == campaign_id)
        .group_by(
            CampaignLeadEmail.generation_status,
            CampaignLeadEmail.compliance_status,
            CampaignLeadEmail.review_status,
        )
    )
    return [(gs, cs, rs, int(n)) for gs, cs, rs, n in result.all()]


async def count_email_jobs_by_status(
    db: AsyncSession,
    campaign_id: str,
) -> dict[str, int]:
    result = await db.execute(
        select(EmailJob.status, func.count())
        .where(EmailJob.campaign_id == campaign_id)
        .group_by(EmailJob.status)
    )
    counts = {s.value: 0 for s in EmailJobStatus}
    for status, n in result.all():
        counts[enum_value(status)] = int(n)
    return counts


def fold_generation_counts(
    groups: list[tuple[Any, Any, Any, int]],
) -> tuple[dict[str, int], dict[str, int], int]:
    by_gen = {s.value: 0 for s in GenerationStatus}
    by_comp = {s.value: 0 for s in ComplianceStatus}
    row_count = 0
    for gs, cs, _rs, n in groups:
        row_count += n
        gs_key = enum_value(gs)
        cs_key = enum_value(cs)
        by_gen[gs_key] = by_gen.get(gs_key, 0) + n
        by_comp[cs_key] = by_comp.get(cs_key, 0) + n
    return by_gen, by_comp, row_count


def generation_status_summary_from_counts(
    by_gen: dict[str, int],
    by_comp: dict[str, int],
    *,
    row_count: int,
    expected_total: int | None = None,
) -> dict[str, Any]:
    total = max(expected_total if expected_total is not None else row_count, row_count)
    missing_rows = max(0, total - row_count)
    complete = by_gen.get(GenerationStatus.READY.value, 0) + by_gen.get(
        GenerationStatus.FAILED.value, 0
    )
    queued = by_gen.get(GenerationStatus.PENDING.value, 0) + missing_rows
    generating = by_gen.get(GenerationStatus.GENERATING.value, 0)
    in_flight = queued + generating
    return {
        "total": total,
        "complete": complete,
        "queued": queued,
        "generating": generating,
        "pending": in_flight,
        "ready": by_gen.get(GenerationStatus.READY.value, 0),
        "failed": by_gen.get(GenerationStatus.FAILED.value, 0),
        "compliance_passed": by_comp.get(ComplianceStatus.PASSED.value, 0),
        "compliance_failed": by_comp.get(ComplianceStatus.FAILED.value, 0),
        "is_complete": total > 0 and complete >= total and in_flight == 0,
    }


def review_summary_from_groups(
    groups: list[tuple[Any, Any, Any, int]],
) -> dict[str, Any]:
    if not groups:
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
    total = 0

    for gs, cs, rs, n in groups:
        gs_key = enum_value(gs)
        cs_key = enum_value(cs)
        rs_key = enum_value(rs)
        total += n
        if gs_key == GenerationStatus.GENERATING.value:
            gen_in_progress += n
        elif gs_key == GenerationStatus.FAILED.value:
            gen_failed += n
        elif gs_key == GenerationStatus.READY.value and cs_key == ComplianceStatus.PASSED.value:
            ready_for_review += n
            if rs_key == ReviewStatus.REJECTED.value:
                rejected += n
            else:
                approved += n
        elif gs_key == GenerationStatus.READY.value and rs_key == ReviewStatus.PENDING.value:
            pending_review += n

    blockers: list[str] = []
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

    return {
        "has_per_lead_emails": True,
        "total": total,
        "pending_review": pending_review,
        "approved": approved,
        "rejected": rejected,
        "generation_in_progress": gen_in_progress,
        "generation_failed": gen_failed,
        "ready_for_review": ready_for_review,
        "can_launch": len(blockers) == 0 and approved > 0,
        "launch_blockers": blockers,
    }


def send_status_from_counts(
    by_status: dict[str, int],
    *,
    campaign_id: str,
    campaign_status: str,
) -> dict[str, Any]:
    total = sum(by_status.values())
    queued = by_status.get(EmailJobStatus.QUEUED.value, 0)
    sending = by_status.get(EmailJobStatus.SENDING.value, 0)
    sent = by_status.get(EmailJobStatus.SENT.value, 0)
    failed = by_status.get(EmailJobStatus.FAILED.value, 0)
    terminal = sent + failed
    in_flight = queued + sending
    return {
        "campaign_id": str(campaign_id),
        "campaign_status": campaign_status,
        "total_jobs": total,
        "queued": queued,
        "sending": sending,
        "sent": sent,
        "failed": failed,
        "in_progress": in_flight,
        "is_complete": total > 0 and terminal >= total,
        "progress_percent": round((terminal / total) * 100) if total else 0,
    }


async def fetch_generation_status_summary(
    db: AsyncSession,
    campaign_id: str,
    *,
    expected_total: int | None = None,
) -> dict[str, Any]:
    groups = await fetch_lead_email_status_groups(db, campaign_id)
    by_gen, by_comp, row_count = fold_generation_counts(groups)
    if expected_total is None:
        expected_total = await count_campaign_leads(db, campaign_id)
    return generation_status_summary_from_counts(
        by_gen,
        by_comp,
        row_count=row_count,
        expected_total=expected_total,
    )
