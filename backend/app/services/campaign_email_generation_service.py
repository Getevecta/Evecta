from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import ObjectDeletedError, StaleDataError

from app.core.email_tones import default_tone_for_plan, is_tone_unlocked_for_plan
from app.core.pagination import normalize_pagination
from app.core.personalization import normalize_tone
from app.email_engine.repetition import is_too_similar, most_similar
from app.models.campaign import Campaign, DraftType
from app.models.campaign_lead import CampaignLead
from app.models.campaign_lead_email import (
    CampaignLeadEmail,
    ComplianceStatus,
    GenerationStatus,
    ReviewStatus,
)
from app.models.lead import Lead
from app.models.overture_place import OverturePlace
from app.models.user import User
from app.services.campaign_draft_service import strip_p_tags_from_content
from app.services.campaign_guard import (
    get_editable_campaign_or_404,
    get_owned_campaign_or_404,
    is_campaign_editable,
)
from app.services.campaign_status_counts import (
    count_campaign_leads,
    fetch_generation_status_summary,
    generation_status_summary_from_counts,
)
from app.services.compliance_gate import (
    apply_compliance_rewrite_if_ready,
    evaluate_email_compliance,
    strip_html_for_check,
)
from app.services.personalization_service import lead_data_from_sources, resolve_personalization
from app.services.writing_spec_service import (
    build_writing_spec_from_campaign_lead,
    writing_spec_summary,
)
from app.utils.email_personalization import replace_placeholders
from app.utils.ai_email_generator import generate_per_lead_email

logger = logging.getLogger(__name__)

# Legacy: first N leads used to generate inline on POST /generate. That path
# routinely exceeded reverse-proxy timeouts (504 → "Request timed out") while
# leaving the UI at 0/N Queued. Generation is fully backgrounded now.
INSTANT_LEAD_COUNT = 0
MAX_COMPLIANCE_ATTEMPTS = 5
REPETITION_THRESHOLD = 0.6
# Repetition guard compares against at most this many other emails (the LLM
# prompt only ever shows the last 3) — keeps large campaigns from loading and
# scanning every body on every attempt.
PRIOR_BODIES_MAX = 25
# GENERATING rows older than this are treated as abandoned (worker crash /
# StaleDataError) so resume can re-queue them.
STALE_GENERATING_SECONDS = 180
GENERATION_CHUNK_SIZE = 25
GENERATION_CHUNK_CONCURRENCY = 3
# Cap how many stalled campaigns one beat tick will try to resume.
STALLED_RESUME_BATCH_LIMIT = 20

# In-process fallback when Celery workers are not running (common in local dev).
_campaign_email_generation_tasks: dict[str, asyncio.Task[None]] = {}
_campaign_email_celery_task_ids: dict[str, list[str]] = {}
_campaign_email_generation_cancelled: set[str] = set()
_campaign_email_last_dispatch: dict[str, float] = {}
_DISPATCH_COOLDOWN_SECONDS = 30

GENERATION_CANCELLED_ERROR = "generation_cancelled_by_user"
INSUFFICIENT_CREDITS_ERROR = "insufficient_email_gen_credits"

# §5.8 timing gate: before generating a lead's email, wait for that business's
# enrichment (context scrape) to finish so the email isn't generic. Bounded by a
# shared per-generation budget — one slow/unscrapeable site can never hang the run.
ENRICHMENT_WAIT_MAX_SECONDS = 180  # total wait budget across the whole generation
ENRICHMENT_POLL_SECONDS = 5


async def _await_business_enriched(
    overture_id: str | None,
    deadline_monotonic: float,
    session_factory: Callable[..., Any],
) -> None:
    """Block until this business's master enrichment is terminal, or the budget runs out.

    Uses a short-lived session per poll so the generation session is not held
    during asyncio.sleep (the API pool is only 5+10 connections).

    Terminal = 'done' or 'failed'. Leads with no overture_id (Google/manual) or no
    master row don't wait. On timeout we proceed anyway (graceful degrade — the email
    generates with whatever context exists; enrichment finishes independently). Once
    the master is 'done', the promoted Lead already carries the scraped context (the
    enrichment job syncs it), so generation picks it up via lead_data_from_sources —
    which is why no separate context-overlay is needed here.
    """
    if not overture_id:
        return

    while True:
        async with session_factory() as poll_db:
            row = (
                await poll_db.execute(
                    select(OverturePlace.enrichment_status).where(
                        OverturePlace.overture_id == overture_id
                    )
                )
            ).first()
        if row is None:
            return  # no master row for this id → nothing to wait for
        status = row[0]
        if status in ("done", "failed"):
            return  # terminal — enrichment finished (or gave up)
        # NULL / 'pending' / 'processing' → still enriching; wait within budget.
        if time.monotonic() >= deadline_monotonic:
            logger.info(
                "[GEN][enrich-gate] budget exhausted; generating with available "
                "context (overture_id=%s, status=%s)", overture_id, status
            )
            return
        await asyncio.sleep(ENRICHMENT_POLL_SECONDS)


def _is_generation_cancelled(campaign_id: str) -> bool:
    return str(campaign_id) in _campaign_email_generation_cancelled


def _clear_generation_cancelled(campaign_id: str) -> None:
    _campaign_email_generation_cancelled.discard(str(campaign_id))


def _mark_generation_cancelled(campaign_id: str) -> None:
    _campaign_email_generation_cancelled.add(str(campaign_id))


def _revoke_celery_generation_task(campaign_id: str) -> None:
    task_ids = _campaign_email_celery_task_ids.pop(str(campaign_id), None) or []
    if not task_ids:
        return
    try:
        from app.core.celery_app import celery_app

        for task_id in task_ids:
            celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        logger.info(
            "Revoked %s Celery campaign email generation task(s) campaign=%s",
            len(task_ids),
            campaign_id,
        )
    except Exception as exc:
        logger.warning(
            "Failed to revoke Celery task for campaign=%s: %s",
            campaign_id,
            exc,
        )


def _in_process_generation_running(campaign_id: str) -> bool:
    task = _campaign_email_generation_tasks.get(str(campaign_id))
    return task is not None and not task.done()


def _stop_background_workers(campaign_id: str) -> None:
    """Stop in-process/Celery workers without marking rows cancelled."""
    _revoke_celery_generation_task(campaign_id)
    task = _campaign_email_generation_tasks.get(str(campaign_id))
    if task and not task.done():
        task.cancel()


async def _has_fresh_generating_rows(db: AsyncSession, campaign_id: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_GENERATING_SECONDS)
    row_id = await db.scalar(
        select(CampaignLeadEmail.id).where(
            CampaignLeadEmail.campaign_id == campaign_id,
            CampaignLeadEmail.generation_status == GenerationStatus.GENERATING,
            CampaignLeadEmail.updated_at >= cutoff,
        ).limit(1)
    )
    return row_id is not None


async def _generation_already_running(db: AsyncSession, campaign_id: str) -> bool:
    if _in_process_generation_running(campaign_id):
        return True
    return await _has_fresh_generating_rows(db, campaign_id)


def _chunk_ranges_for_pending(pending_indices: list[int], chunk_size: int) -> list[tuple[int, int]]:
    """Disjoint (start_index, count) windows over the campaign lead list."""
    if not pending_indices or chunk_size <= 0:
        return []
    pending = sorted(set(pending_indices))
    ranges: list[tuple[int, int]] = []
    i = 0
    while i < len(pending):
        start = pending[i]
        end = start + chunk_size
        ranges.append((start, chunk_size))
        while i < len(pending) and pending[i] < end:
            i += 1
    return ranges


def _indices_needing_generation(
    campaign_leads: list[CampaignLead],
    rows_by_lead_id: dict[str, CampaignLeadEmail],
    *,
    regenerate_all: bool,
) -> list[int]:
    indices: list[int] = []
    for idx, cl in enumerate(campaign_leads):
        if not cl.lead_id:
            continue
        if _lead_needs_generation(rows_by_lead_id.get(str(cl.lead_id)), regenerate_all=regenerate_all):
            indices.append(idx)
    return indices


async def _row_was_cancelled(row: CampaignLeadEmail) -> bool:
    return row.last_error == GENERATION_CANCELLED_ERROR


async def _fetch_email_row_for_lead(
    db: AsyncSession,
    campaign_id,
    lead_id,
) -> CampaignLeadEmail | None:
    """Current email row for a campaign lead (None if discarded / never created)."""
    if not lead_id:
        return None
    return await db.scalar(
        select(CampaignLeadEmail).where(
            CampaignLeadEmail.campaign_id == campaign_id,
            CampaignLeadEmail.lead_id == lead_id,
        )
    )


async def _safe_commit_email_row(
    db: AsyncSession,
    row: CampaignLeadEmail,
) -> CampaignLeadEmail | None:
    """Flush+commit row updates. Returns None if the row was deleted concurrently."""
    try:
        await db.flush()
        await db.commit()
        return row
    except StaleDataError:
        logger.warning(
            "StaleDataError updating campaign_lead_emails id=%s — row gone (discard/regen race)",
            getattr(row, "id", None),
        )
        await db.rollback()
        return None
    except ObjectDeletedError:
        logger.warning(
            "ObjectDeletedError on campaign_lead_emails id=%s",
            getattr(row, "id", None),
        )
        await db.rollback()
        return None


async def _safe_reload_email_row(
    db: AsyncSession,
    row: CampaignLeadEmail,
) -> CampaignLeadEmail | None:
    """
    Re-load a row after long LLM work. Prefer the same PK; if it was discarded and
    a replacement row exists for the same lead, return that instead.
    """
    row_id = row.id
    campaign_id = row.campaign_id
    lead_id = row.lead_id
    try:
        await db.refresh(row)
        return row
    except ObjectDeletedError:
        await db.rollback()
    except Exception:
        # Session may be dirty after concurrent deletes — recover via get().
        try:
            await db.rollback()
        except Exception:
            pass

    fresh = await db.get(CampaignLeadEmail, row_id)
    if fresh is not None:
        return fresh
    if campaign_id and lead_id:
        replacement = await _fetch_email_row_for_lead(db, campaign_id, lead_id)
        if replacement is not None:
            logger.info(
                "Email row id=%s was replaced by id=%s for campaign=%s lead=%s",
                row_id,
                replacement.id,
                campaign_id,
                lead_id,
            )
            return replacement
    logger.warning(
        "Email row id=%s no longer exists for campaign=%s lead=%s",
        row_id,
        campaign_id,
        lead_id,
    )
    return None


async def _requeue_stale_generating_rows(
    db: AsyncSession,
    campaign_id: str,
    *,
    force_all: bool = False,
) -> int:
    """Reset abandoned GENERATING rows so resume / polling can continue."""
    cutoff = datetime.now(timezone.utc).timestamp() - STALE_GENERATING_SECONDS
    rows = list(
        await db.scalars(
            select(CampaignLeadEmail).where(
                CampaignLeadEmail.campaign_id == campaign_id,
                CampaignLeadEmail.generation_status == GenerationStatus.GENERATING,
            )
        )
    )
    reset = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        if not force_all:
            updated = row.updated_at
            if updated is None:
                continue
            ts = (
                updated.timestamp()
                if updated.tzinfo
                else updated.replace(tzinfo=timezone.utc).timestamp()
            )
            if ts > cutoff:
                continue
        row.generation_status = GenerationStatus.PENDING
        row.last_error = None
        row.updated_at = now
        reset += 1
    if reset:
        await db.commit()
        logger.info(
            "Re-queued %s stale GENERATING email row(s) for campaign=%s (force_all=%s)",
            reset,
            campaign_id,
            force_all,
        )
    return reset


async def _should_stop_generation(campaign_id: str, db: AsyncSession) -> bool:
    """True when user cancelled and no lead is still marked in-flight in the DB."""
    if _is_generation_cancelled(campaign_id):
        return True
    cancelled_count = await db.scalar(
        select(func.count())
        .select_from(CampaignLeadEmail)
        .where(
            CampaignLeadEmail.campaign_id == campaign_id,
            CampaignLeadEmail.last_error == GENERATION_CANCELLED_ERROR,
        )
    )
    if not cancelled_count:
        return False
    in_flight = await db.scalar(
        select(func.count())
        .select_from(CampaignLeadEmail)
        .where(
            CampaignLeadEmail.campaign_id == campaign_id,
            CampaignLeadEmail.generation_status.in_(
                [GenerationStatus.PENDING, GenerationStatus.GENERATING]
            ),
        )
    )
    return (in_flight or 0) == 0


def _celery_workers_available() -> bool:
    """True when at least one Celery worker responds to ping."""
    try:
        from app.core.celery_app import celery_app

        inspect = celery_app.control.inspect(timeout=1.0)
        ping = inspect.ping()
        return bool(ping)
    except Exception as exc:
        logger.debug("Celery worker check failed: %s", exc)
        return False


def _schedule_in_process_campaign_email_generation(
    campaign_id: str,
    user_id: str,
    *,
    regenerate_all: bool,
    chunk_ranges: list[tuple[int, int]],
    replace: bool = False,
) -> None:
    """Continue per-lead generation in the API process (no Celery worker required)."""
    existing = _campaign_email_generation_tasks.get(campaign_id)
    if existing and not existing.done():
        if not replace:
            return
        existing.cancel()

    async def _run() -> None:
        from app.database.session import async_session_factory

        try:
            for start_index, count in chunk_ranges:
                if _is_generation_cancelled(campaign_id):
                    break
                await generate_pending_campaign_emails(
                    campaign_id,
                    user_id,
                    async_session_factory,
                    regenerate_all=regenerate_all,
                    start_index=start_index,
                    count=count,
                )
        except asyncio.CancelledError:
            logger.info(
                "In-process campaign email generation cancelled for campaign=%s",
                campaign_id,
            )
            raise
        except Exception:
            logger.exception(
                "In-process campaign email generation failed for campaign=%s",
                campaign_id,
            )
            try:
                async with async_session_factory() as db:
                    await _requeue_stale_generating_rows(db, campaign_id, force_all=True)
            except Exception:
                logger.exception(
                    "Failed to re-queue stale GENERATING rows after crash campaign=%s",
                    campaign_id,
                )
        finally:
            _campaign_email_generation_tasks.pop(campaign_id, None)

    loop = asyncio.get_running_loop()
    task = loop.create_task(_run())
    _campaign_email_generation_tasks[campaign_id] = task
    logger.info(
        "Scheduled in-process campaign email generation campaign=%s chunks=%s",
        campaign_id,
        chunk_ranges,
    )


def _schedule_remaining_campaign_email_generation(
    campaign_id: str,
    user_id: str,
    *,
    regenerate_all: bool,
    chunk_ranges: list[tuple[int, int]],
    replace: bool = False,
    allow_in_process: bool = True,
) -> str:
    """Queue remaining leads via Celery chunks when enabled; otherwise run in-process."""
    from app.core.config import get_settings

    settings = get_settings()
    use_celery = settings.CAMPAIGN_EMAIL_GENERATION_USE_CELERY

    if use_celery and _celery_workers_available():
        try:
            from app.tasks.generate_campaign_emails import generate_campaign_emails_task

            if replace:
                _revoke_celery_generation_task(campaign_id)

            task_ids: list[str] = []
            for start_index, count in chunk_ranges:
                result = generate_campaign_emails_task.apply_async(
                    kwargs={
                        "campaign_id": campaign_id,
                        "user_id": user_id,
                        "regenerate_all": regenerate_all,
                        "start_index": start_index,
                        "count": count,
                    },
                )
                task_ids.append(result.id)
            _campaign_email_celery_task_ids[str(campaign_id)] = task_ids
            logger.info(
                "Queued %s Celery campaign email generation chunk(s) campaign=%s",
                len(task_ids),
                campaign_id,
            )
            _campaign_email_last_dispatch[str(campaign_id)] = time.monotonic()
            return "celery"
        except Exception as exc:
            logger.warning(
                "Celery enqueue failed for campaign=%s, using in-process fallback: %s",
                campaign_id,
                exc,
            )

    if not allow_in_process:
        logger.warning(
            "Skipping in-process fallback for campaign=%s (Celery unavailable)",
            campaign_id,
        )
        return "celery_unavailable"

    _schedule_in_process_campaign_email_generation(
        campaign_id,
        user_id,
        regenerate_all=regenerate_all,
        chunk_ranges=chunk_ranges,
        replace=replace,
    )
    _campaign_email_last_dispatch[str(campaign_id)] = time.monotonic()
    return "in_process"


def _campaign_uses_ai_per_lead_generation(campaign: Campaign) -> bool:
    """True when Step 4 should call the LLM per lead (not template placeholder merge)."""
    dt = campaign.draft_type
    if dt is None:
        return False
    if dt == DraftType.AI:
        return True
    raw = dt.value if hasattr(dt, "value") else str(dt)
    return str(raw).lower() in {"ai", "drafttype.ai"}


async def _load_profiles(db: AsyncSession, user_id: str) -> tuple[dict | None, dict | None, User | None]:
    user = await db.get(User, user_id)
    user_profile = None
    if user:
        user_profile = {
            "full_name": user.full_name,
            "username": user.username,
            "email": user.email,
            "bio": user.bio,
            "department": user.department,
            "location": user.location,
            "website": user.website,
        }

    company_profile = None
    try:
        from app.services.company_service import get_company_by_user_id

        company = await get_company_by_user_id(db, user_id)
        if company:
            company_profile = {
                "company_name": company.company_name,
                "company_description": company.company_description,
                "products_and_services": company.products_and_services,
            }
    except Exception:
        pass

    return user_profile, company_profile, user


def _campaign_description(campaign: Campaign) -> str:
    """User's Step 3 AI prompt + optional draft reference for per-lead generation."""
    if campaign.ai_email_prompt and campaign.ai_email_prompt.strip():
        return campaign.ai_email_prompt.strip()
    if campaign.description and campaign.description.strip():
        return campaign.description.strip()
    parts: list[str] = []
    if campaign.email_subject and campaign.email_content:
        parts.append(
            "Match the intent of this campaign draft.\n"
            f"Subject: {campaign.email_subject}\n"
            f"{campaign.email_content[:800]}"
        )
    return "\n\n".join(parts) if parts else "Professional B2B outreach email."


def _plain_body_from_campaign_content(content: str) -> str:
    """Normalize stored campaign body to plain text for merge/send."""
    if not content:
        return ""
    if "<p" in content.lower() or "<br" in content.lower():
        return strip_p_tags_from_content(content)
    return content.strip()


async def _get_campaign_or_404(campaign_id: str, user_id: str, db: AsyncSession) -> Campaign:
    campaign = await get_editable_campaign_or_404(
        campaign_id, user_id, db, action="generate"
    )
    if not campaign.email_subject or not campaign.email_content:
        raise HTTPException(status_code=400, detail="Campaign email draft is not ready.")
    return campaign


async def _fetch_campaign_leads(campaign_id: str, db: AsyncSession) -> list[CampaignLead]:
    result = await db.scalars(
        select(CampaignLead)
        .where(CampaignLead.campaign_id == campaign_id)
        .options(selectinload(CampaignLead.lead))
        .order_by(CampaignLead.created_at.asc())
    )
    return list(result.all())


def _generation_status_summary(
    rows: list[CampaignLeadEmail],
    *,
    expected_total: int | None = None,
) -> dict[str, Any]:
    by_gen = {s.value: 0 for s in GenerationStatus}
    by_comp = {s.value: 0 for s in ComplianceStatus}
    for row in rows:
        gs = row.generation_status.value if hasattr(row.generation_status, "value") else str(row.generation_status)
        cs = row.compliance_status.value if hasattr(row.compliance_status, "value") else str(row.compliance_status)
        by_gen[gs] = by_gen.get(gs, 0) + 1
        by_comp[cs] = by_comp.get(cs, 0) + 1
    return generation_status_summary_from_counts(
        by_gen,
        by_comp,
        row_count=len(rows),
        expected_total=expected_total,
    )


def _lead_needs_generation(
    row: CampaignLeadEmail | None,
    *,
    regenerate_all: bool,
) -> bool:
    if row is None:
        return True
    if regenerate_all:
        return True
    if row.generation_status == GenerationStatus.READY:
        return False
    if row.generation_status == GenerationStatus.FAILED:
        return False
    return True


def _first_lead_index_needing_generation(
    campaign_leads: list[CampaignLead],
    rows_by_lead_id: dict[str, CampaignLeadEmail],
    *,
    regenerate_all: bool,
) -> int | None:
    for idx, cl in enumerate(campaign_leads):
        if not cl.lead_id:
            continue
        lead_id = str(cl.lead_id)
        if _lead_needs_generation(rows_by_lead_id.get(lead_id), regenerate_all=regenerate_all):
            return idx
    return None


def _count_leads_needing_generation_from_index(
    campaign_leads: list[CampaignLead],
    rows_by_lead_id: dict[str, CampaignLeadEmail],
    *,
    regenerate_all: bool,
    from_index: int,
) -> int:
    count = 0
    for idx, cl in enumerate(campaign_leads):
        if idx < from_index or not cl.lead_id:
            continue
        lead_id = str(cl.lead_id)
        if _lead_needs_generation(rows_by_lead_id.get(lead_id), regenerate_all=regenerate_all):
            count += 1
    return count


async def generate_lead_email_row(
    *,
    campaign: Campaign,
    campaign_lead: CampaignLead,
    lead_index: int,
    row: CampaignLeadEmail,
    user: User | None,
    user_profile: dict | None,
    company_profile: dict | None,
    prior_bodies: list[str],
    db: AsyncSession,
    total_leads: int = 0,
) -> CampaignLeadEmail:
    """Generate (or merge) one per-lead email and update `row` in place."""
    campaign_id = str(campaign.id)
    if _is_generation_cancelled(campaign_id):
        return row

    # Always work from the current DB row — discard/regen may have replaced ours.
    current = await _safe_reload_email_row(db, row)
    if current is None:
        return row
    row = current
    baseline_regen = row.regeneration_count or 0

    now = datetime.now(timezone.utc)
    row.generation_status = GenerationStatus.GENERATING
    row.lead_index = lead_index
    row.updated_at = now
    if await _safe_commit_email_row(db, row) is None:
        return row

    lead = campaign_lead.lead
    if not lead and campaign_lead.lead_id:
        lead = await db.get(Lead, campaign_lead.lead_id)

    tone = normalize_tone(campaign.tone)
    plan = user.plan if user else "free"
    if not is_tone_unlocked_for_plan(plan, tone):
        tone = default_tone_for_plan(plan)

    use_ai = _campaign_uses_ai_per_lead_generation(campaign)

    subject: str | None = None
    body: str | None = None
    last_error: str | None = None
    similarity_offender: str | None = None
    spam_score: int | None = None
    risk_level: str | None = None
    compliance = ComplianceStatus.FAILED
    variant_meta: dict | None = None
    regen_count = 0

    description = _campaign_description(campaign)
    # Recipes are deterministic per (campaign_seed, index) and initial generation
    # used index = lead position — so regens/retries must stride by the campaign
    # size to stay out of the recipe space of every other lead's current email.
    variation_stride = max(total_leads, 1)

    for attempt in range(MAX_COMPLIANCE_ATTEMPTS):
        if _is_generation_cancelled(campaign_id):
            row = await _safe_reload_email_row(db, row)
            if row is None:
                return current
            if await _row_was_cancelled(row):
                return row
            row.generation_status = GenerationStatus.FAILED
            row.last_error = GENERATION_CANCELLED_ERROR
            row.updated_at = datetime.now(timezone.utc)
            await _safe_commit_email_row(db, row)
            return row

        variation_index = lead_index + variation_stride * (baseline_regen + attempt)
        regen_count = attempt
        compliance_feedback = None
        similarity_feedback = None
        if attempt > 0 and last_error:
            if last_error == "too_similar_to_prior_email":
                similarity_feedback = similarity_offender or "another lead's email in this campaign"
            else:
                compliance_feedback = last_error
        # Stricter spam analysis on later retries after fast checks fail.
        use_strict_spam = attempt >= 3

        try:
            if use_ai:
                writing_spec = build_writing_spec_from_campaign_lead(
                    campaign_lead,
                    plan=plan,
                    tone=tone,
                    campaign_seed=str(campaign.id),
                    index=variation_index,
                    user_profile=user_profile,
                    company_profile=company_profile,
                )
                variant_meta = writing_spec_summary(writing_spec)
                lead_data = lead_data_from_sources(campaign_lead=campaign_lead, lead=lead)
                profile = resolve_personalization(
                    plan=plan,
                    tone=tone,
                    lead_data=lead_data,
                )
                lead_data_with_context = {**lead_data, "context": profile.get("context") or {}}

                subject, body = await generate_per_lead_email(
                    tone=tone,
                    description=description,
                    lead_data=lead_data_with_context,
                    user_profile=user_profile,
                    company_profile=company_profile,
                    writing_spec=writing_spec,
                    reference_subject=campaign.email_subject,
                    reference_body=campaign.email_content,
                    prior_bodies=prior_bodies,
                    lead_index=variation_index,
                    compliance_feedback=compliance_feedback,
                    similarity_feedback=similarity_feedback,
                    user_id=getattr(campaign, "user_id", None),
                )
            else:
                if not lead:
                    raise ValueError("Lead not found for placeholder merge.")
                subject = replace_placeholders(campaign.email_subject or "", lead)
                body = _plain_body_from_campaign_content(
                    replace_placeholders(campaign.email_content or "", lead)
                )
                variant_meta = {"mode": "template_merge", "index": variation_index}

            plain_subject = strip_html_for_check(subject or "")
            plain_body = strip_html_for_check(body or "")

            # Template/manual flows intentionally keep the same base wording (with merge tags).
            # Similarity guard is only for AI per-lead drafting where we expect varied copy.
            if use_ai and is_too_similar(plain_body, prior_bodies, threshold=REPETITION_THRESHOLD):
                _sim_score, _sim_idx = most_similar(plain_body, prior_bodies)
                similarity_offender = (
                    prior_bodies[_sim_idx][:220] if 0 <= _sim_idx < len(prior_bodies) else None
                )
                last_error = "too_similar_to_prior_email"
                continue

            result = await evaluate_email_compliance(
                subject=plain_subject,
                body=plain_body,
                user_profile=user_profile,
                company_profile=company_profile,
                fast_mode=not use_strict_spam,
            )
            if use_strict_spam and use_ai:
                subject, body, result = apply_compliance_rewrite_if_ready(
                    subject=subject or "",
                    body=body or "",
                    result=result,
                )

            if result["passed"]:
                spam_score = result["spam_score"]
                risk_level = result["risk_level"]
                compliance = ComplianceStatus.PASSED
                break

            last_error = "; ".join(result.get("violations") or ["compliance_failed"])
        except Exception as exc:
            last_error = "generation_failed"
            logger.warning(
                "Lead email generation attempt %s failed for campaign=%s lead=%s: %s",
                attempt + 1,
                campaign.id,
                campaign_lead.lead_id,
                exc,
            )

    row = await _safe_reload_email_row(db, row)
    if row is None:
        return current
    if await _row_was_cancelled(row) or _is_generation_cancelled(campaign_id):
        return row

    generated_ok = compliance == ComplianceStatus.PASSED and bool(subject) and bool(body)
    if generated_ok:
        row.subject = subject[:255]
        row.body = body
        row.generation_status = GenerationStatus.READY
        row.compliance_status = ComplianceStatus.PASSED
        row.spam_score = spam_score
        row.risk_level = risk_level
        row.last_error = None
        row.review_status = ReviewStatus.PENDING
    else:
        row.generation_status = GenerationStatus.FAILED
        row.compliance_status = ComplianceStatus.FAILED
        row.last_error = last_error or "generation_failed"
        row.review_status = ReviewStatus.PENDING

    row.regeneration_count = baseline_regen + regen_count
    row.variant_metadata = json.dumps(variant_meta) if variant_meta else None
    row.updated_at = datetime.now(timezone.utc)

    if generated_ok and use_ai:
        # 1 email_gen credit per successful AI generation (template merges are free).
        # Flush then spend_credits commits — draft content and charge land together.
        from app.services.credit_service import spend_credits

        try:
            await db.flush()
        except StaleDataError:
            logger.warning(
                "StaleDataError flushing READY draft campaign=%s lead=%s",
                campaign_id,
                campaign_lead.lead_id,
            )
            await db.rollback()
            return current

        try:
            await spend_credits(
                db,
                campaign.user_id,
                "ai_draft",
                description=f"AI email for campaign {campaign_id} (lead #{lead_index + 1})",
            )
        except HTTPException as exc:
            if exc.status_code != 402:
                raise
            # Can't pay for it — don't hand the draft out. Reset the row to PENDING
            # so a post-top-up generate/resume picks it up again, then re-raise:
            # the sync path returns the 402 to the client, background wrappers
            # log it and stop, leaving the remaining rows pending.
            row = await _safe_reload_email_row(db, row)
            if row is None:
                raise
            row.subject = None
            row.body = None
            row.generation_status = GenerationStatus.PENDING
            row.compliance_status = ComplianceStatus.PENDING
            row.spam_score = None
            row.risk_level = None
            row.last_error = INSUFFICIENT_CREDITS_ERROR
            row.updated_at = datetime.now(timezone.utc)
            await _safe_commit_email_row(db, row)
            raise
        return row

    if await _safe_commit_email_row(db, row) is None:
        return current
    return row


async def _claim_email_row_for_generation(
    db: AsyncSession,
    row_id,
) -> CampaignLeadEmail | None:
    """Atomically take a PENDING row so overlapping chunks cannot generate it twice."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(CampaignLeadEmail)
        .where(
            CampaignLeadEmail.id == row_id,
            CampaignLeadEmail.generation_status == GenerationStatus.PENDING,
        )
        .values(generation_status=GenerationStatus.GENERATING, updated_at=now)
    )
    if result.rowcount == 0:
        await db.commit()
        return None
    await db.commit()
    return await db.get(CampaignLeadEmail, row_id)


async def _process_chunk_leads(
    *,
    campaign_id: str,
    user_id: str,
    start_index: int,
    count: int,
    regenerate_all: bool,
    session_factory: Callable[..., Any],
) -> None:
    """Generate one disjoint slice of leads with bounded concurrency and per-lead sessions."""
    async with session_factory() as db:
        campaign = await db.get(Campaign, campaign_id)
        if not campaign or str(campaign.user_id) != str(user_id):
            return
        campaign_leads = await _fetch_campaign_leads(campaign_id, db)
        slice_leads = campaign_leads[start_index : start_index + count]
        email_rows = {
            str(r.lead_id): r
            for r in (
                await db.scalars(
                    select(CampaignLeadEmail).where(
                        CampaignLeadEmail.campaign_id == campaign.id
                    )
                )
            ).all()
            if r.lead_id
        }
        jobs: list[tuple[int, Any, str | None]] = []
        for offset, cl in enumerate(slice_leads):
            if not cl.lead_id:
                continue
            row = email_rows.get(str(cl.lead_id))
            if not regenerate_all and row is not None and row.generation_status in (
                GenerationStatus.READY,
                GenerationStatus.FAILED,
            ):
                continue
            jobs.append(
                (
                    start_index + offset,
                    cl.id,
                    cl.lead.overture_id if cl.lead else None,
                )
            )
        existing = await db.scalars(
            select(CampaignLeadEmail)
            .where(
                CampaignLeadEmail.campaign_id == campaign.id,
                CampaignLeadEmail.generation_status == GenerationStatus.READY,
            )
            .order_by(CampaignLeadEmail.lead_index.asc())
        )
        prior_bodies = [
            strip_html_for_check(row.body) for row in existing.all() if row.body
        ]
        total_leads = len(campaign_leads)
        await db.commit()

    if not jobs:
        return

    prior_lock = asyncio.Lock()
    stop_chunk = asyncio.Event()
    sem = asyncio.Semaphore(GENERATION_CHUNK_CONCURRENCY)
    enrichment_deadline = time.monotonic() + ENRICHMENT_WAIT_MAX_SECONDS

    async def _one(lead_index: int, campaign_lead_id, overture_id: str | None) -> None:
        if stop_chunk.is_set() or _is_generation_cancelled(campaign_id):
            return
        async with sem:
            if stop_chunk.is_set() or _is_generation_cancelled(campaign_id):
                return
            await _await_business_enriched(
                overture_id, enrichment_deadline, session_factory
            )
            if stop_chunk.is_set() or _is_generation_cancelled(campaign_id):
                return
            async with session_factory() as db:
                if await _should_stop_generation(campaign_id, db):
                    stop_chunk.set()
                    return
                cl = (
                    await db.execute(
                        select(CampaignLead)
                        .where(CampaignLead.id == campaign_lead_id)
                        .options(selectinload(CampaignLead.lead))
                    )
                ).scalar_one_or_none()
                if cl is None or not cl.lead_id:
                    return
                row = await _fetch_email_row_for_lead(db, campaign_id, cl.lead_id)
                if row is None:
                    logger.warning(
                        "[GEN] No campaign_lead_emails row for campaign=%s lead=%s — "
                        "skipped (start generation with POST /generate or /resume)",
                        campaign_id,
                        cl.lead_id,
                    )
                    return
                if await _row_was_cancelled(row):
                    return
                if not regenerate_all:
                    if row.generation_status in (
                        GenerationStatus.READY,
                        GenerationStatus.FAILED,
                    ):
                        return
                claimed = await _claim_email_row_for_generation(db, row.id)
                if claimed is None:
                    return
                try:
                    campaign = await db.get(Campaign, campaign_id)
                    if campaign is None:
                        return
                    user_profile, company_profile, user = await _load_profiles(db, user_id)
                    async with prior_lock:
                        bodies = list(prior_bodies[-PRIOR_BODIES_MAX:])
                    updated = await generate_lead_email_row(
                        campaign=campaign,
                        campaign_lead=cl,
                        lead_index=lead_index,
                        row=claimed,
                        user=user,
                        user_profile=user_profile,
                        company_profile=company_profile,
                        prior_bodies=bodies,
                        db=db,
                        total_leads=total_leads,
                    )
                except HTTPException as exc:
                    if exc.status_code == 402:
                        # Out of credits: generate_lead_email_row already put the row
                        # back to PENDING for a post-top-up resume.
                        stop_chunk.set()
                    else:
                        await _mark_claimed_row_failed(session_factory, claimed.id, exc)
                    raise
                except StaleDataError:
                    logger.warning(
                        "StaleDataError generating email for campaign=%s lead=%s — skipping",
                        campaign_id,
                        cl.lead_id,
                    )
                    await db.rollback()
                    return
                except Exception as exc:
                    await _mark_claimed_row_failed(session_factory, claimed.id, exc)
                    raise
                if updated.body and updated.generation_status == GenerationStatus.READY:
                    async with prior_lock:
                        prior_bodies.append(strip_html_for_check(updated.body))

    results = await asyncio.gather(
        *(_one(lead_index, cl_id, overture_id) for lead_index, cl_id, overture_id in jobs),
        return_exceptions=True,
    )
    # return_exceptions keeps one lead's failure from cancelling the others, but it
    # also discards the error — log every one with its traceback.
    for (lead_index, cl_id, _overture_id), result in zip(jobs, results):
        if isinstance(result, BaseException):
            logger.error(
                "[GEN] Email generation crashed for campaign=%s lead_index=%s campaign_lead=%s: %s",
                campaign_id,
                lead_index,
                cl_id,
                result,
                exc_info=result,
            )


async def _mark_claimed_row_failed(
    session_factory: Callable[..., Any],
    row_id,
    exc: BaseException,
) -> None:
    """Record a crash on a row this worker claimed.

    Without this the row stays GENERATING; after STALE_GENERATING_SECONDS it is
    re-queued and fails the same way again, forever, with no error shown. FAILED
    rows are not auto-resumed, and "Regenerate failed" retries them. Uses a fresh
    session because the generation session may be unusable after the error.
    """
    try:
        async with session_factory() as fresh:
            await fresh.execute(
                update(CampaignLeadEmail)
                .where(
                    CampaignLeadEmail.id == row_id,
                    CampaignLeadEmail.generation_status == GenerationStatus.GENERATING,
                )
                .values(
                    generation_status=GenerationStatus.FAILED,
                    compliance_status=ComplianceStatus.FAILED,
                    last_error=f"generation_error: {type(exc).__name__}",
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await fresh.commit()
    except Exception:
        logger.exception("[GEN] Could not mark crashed email row %s as failed", row_id)


def _reset_email_row_for_generation(
    row: CampaignLeadEmail,
    *,
    bump_regeneration: bool = False,
) -> None:
    """Clear draft fields and mark a row queued for (re)generation."""
    if bump_regeneration:
        row.regeneration_count = (row.regeneration_count or 0) + 1
    row.generation_status = GenerationStatus.PENDING
    row.compliance_status = ComplianceStatus.PENDING
    row.review_status = ReviewStatus.PENDING
    row.subject = None
    row.body = None
    row.spam_score = None
    row.risk_level = None
    row.last_error = None


async def _upsert_campaign_email_rows(
    campaign: Campaign,
    campaign_leads: list[CampaignLead],
    db: AsyncSession,
    *,
    regenerate_all: bool,
    regenerate_failed: bool = False,
) -> dict[str, CampaignLeadEmail]:
    """Ensure one email row per lead; optionally reset rows for (re)generation."""
    existing = list(
        await db.scalars(
            select(CampaignLeadEmail).where(CampaignLeadEmail.campaign_id == campaign.id)
        )
    )
    existing_by_lead = {str(r.lead_id): r for r in existing if r.lead_id}
    current_lead_ids = {str(cl.lead_id) for cl in campaign_leads if cl.lead_id}

    for row in existing:
        if row.lead_id and str(row.lead_id) not in current_lead_ids:
            await db.delete(row)

    rows_by_lead_id: dict[str, CampaignLeadEmail] = {}
    for idx, cl in enumerate(campaign_leads):
        if not cl.lead_id:
            continue
        lead_id = str(cl.lead_id)
        if lead_id in existing_by_lead:
            row = existing_by_lead[lead_id]
            row.lead_index = idx
            if regenerate_all:
                _reset_email_row_for_generation(row, bump_regeneration=True)
            elif regenerate_failed and row.generation_status == GenerationStatus.FAILED:
                _reset_email_row_for_generation(row, bump_regeneration=True)
        else:
            row = CampaignLeadEmail(
                campaign_id=campaign.id,
                campaign_lead_id=cl.id,
                lead_id=cl.lead_id,
                lead_index=idx,
                generation_status=GenerationStatus.PENDING,
                compliance_status=ComplianceStatus.PENDING,
                review_status=ReviewStatus.PENDING,
            )
            db.add(row)
        rows_by_lead_id[lead_id] = row

    await db.flush()
    await db.commit()
    return rows_by_lead_id


async def start_campaign_email_generation(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
    *,
    regenerate_all: bool = False,
    regenerate_failed: bool = False,
) -> dict[str, Any]:
    """Start per-lead generation in background chunks (poll /status)."""
    if regenerate_all and regenerate_failed:
        regenerate_failed = False

    campaign = await _get_campaign_or_404(campaign_id, user_id, db)

    already_running = await _generation_already_running(db, campaign_id)
    if already_running and not regenerate_all and not regenerate_failed:
        summary = await fetch_generation_status_summary(db, campaign_id)
        return {
            "campaign_id": campaign_id,
            "already_running": True,
            "instant_generated": 0,
            "queued_background": True,
            "remaining": summary.get("queued", 0),
            "regenerate_all": regenerate_all,
            "regenerate_failed": regenerate_failed,
            **summary,
        }

    _clear_generation_cancelled(campaign_id)
    if already_running and regenerate_all:
        _stop_background_workers(campaign_id)

    campaign_leads = await _fetch_campaign_leads(campaign_id, db)
    if not campaign_leads:
        raise HTTPException(status_code=400, detail="Campaign has no leads.")

    # Failed-only: reset FAILED → PENDING, then process like a normal pending run
    # so READY rows are left untouched.
    rows_by_lead_id = await _upsert_campaign_email_rows(
        campaign,
        campaign_leads,
        db,
        regenerate_all=regenerate_all,
        regenerate_failed=regenerate_failed and not regenerate_all,
    )

    # After failed rows are reset to PENDING, treat as a normal (non-all) run.
    process_as_all = regenerate_all

    pending_indices = _indices_needing_generation(
        campaign_leads, rows_by_lead_id, regenerate_all=process_as_all
    )
    expected_total = len(campaign_leads)
    chunk_ranges = _chunk_ranges_for_pending(pending_indices, GENERATION_CHUNK_SIZE)

    if not chunk_ranges:
        refreshed = list(
            await db.scalars(
                select(CampaignLeadEmail).where(CampaignLeadEmail.campaign_id == campaign_id)
            )
        )
        summary = _generation_status_summary(refreshed, expected_total=expected_total)
        return {
            "campaign_id": str(campaign.id),
            "instant_generated": 0,
            "queued_background": False,
            "background_mode": None,
            "remaining": 0,
            "regenerate_all": regenerate_all,
            "regenerate_failed": regenerate_failed,
            **summary,
        }

    if _campaign_uses_ai_per_lead_generation(campaign):
        from app.services.credit_service import require_pool_credits

        await require_pool_credits(db, campaign.user_id, "ai_draft", len(pending_indices))

    remaining = len(pending_indices)
    background_mode = _schedule_remaining_campaign_email_generation(
        str(campaign.id),
        str(user_id),
        regenerate_all=process_as_all,
        chunk_ranges=chunk_ranges,
        replace=regenerate_all,
    )

    refreshed = list(
        await db.scalars(
            select(CampaignLeadEmail).where(CampaignLeadEmail.campaign_id == campaign_id)
        )
    )
    summary = _generation_status_summary(refreshed, expected_total=expected_total)
    return {
        "campaign_id": str(campaign.id),
        "instant_generated": 0,
        "queued_background": remaining > 0,
        "background_mode": background_mode,
        "remaining": remaining,
        "regenerate_all": regenerate_all,
        "regenerate_failed": regenerate_failed,
        **summary,
    }


async def generate_pending_campaign_emails(
    campaign_id: str,
    user_id: str,
    session_factory: Callable[..., Any],
    *,
    regenerate_all: bool = False,
    start_index: int = 0,
    count: int = GENERATION_CHUNK_SIZE,
) -> dict[str, Any]:
    """Process one chunk of leads from `start_index` (size `count`)."""
    async with session_factory() as db:
        if await _should_stop_generation(campaign_id, db):
            campaign_leads = await _fetch_campaign_leads(campaign_id, db)
            result = await db.scalars(
                select(CampaignLeadEmail).where(CampaignLeadEmail.campaign_id == campaign_id)
            )
            rows = list(result.all())
            summary = _generation_status_summary(rows, expected_total=len(campaign_leads))
            return {"campaign_id": str(campaign_id), "cancelled": True, **summary}

        campaign = await db.get(Campaign, campaign_id)
        if not campaign or str(campaign.user_id) != str(user_id):
            raise HTTPException(status_code=404, detail="Campaign not found or unauthorized.")

    await _process_chunk_leads(
        campaign_id=campaign_id,
        user_id=user_id,
        start_index=start_index,
        count=count,
        regenerate_all=regenerate_all,
        session_factory=session_factory,
    )

    async with session_factory() as db:
        campaign_leads = await _fetch_campaign_leads(campaign_id, db)
        refreshed = await db.scalars(
            select(CampaignLeadEmail).where(CampaignLeadEmail.campaign_id == campaign_id)
        )
        summary = _generation_status_summary(
            list(refreshed.all()), expected_total=len(campaign_leads)
        )
        return {"campaign_id": str(campaign_id), **summary}


async def get_campaign_email_generation_status(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    campaign = await get_owned_campaign_or_404(campaign_id, user_id, db)
    await _requeue_stale_generating_rows(db, campaign_id)

    expected_total = await count_campaign_leads(db, campaign_id)
    summary = await fetch_generation_status_summary(
        db, campaign_id, expected_total=expected_total
    )
    summary["generation_stalled"] = (
        summary["total"] > 0
        and not summary["is_complete"]
        and summary.get("generating", 0) == 0
        and summary.get("queued", 0) > 0
    )
    last_dispatch = _campaign_email_last_dispatch.get(str(campaign_id), 0.0)
    recently_dispatched = (time.monotonic() - last_dispatch) < _DISPATCH_COOLDOWN_SECONDS
    # Same preconditions as POST /generate: auto-resuming a campaign whose draft is
    # not saved (or that left DRAFT) only queues Celery chunks that find nothing to do.
    draft_ready = (
        bool(campaign.email_subject)
        and bool(campaign.email_content)
        and is_campaign_editable(campaign)
    )
    if (
        summary["generation_stalled"]
        and draft_ready
        and not _in_process_generation_running(campaign_id)
        and not _is_generation_cancelled(campaign_id)
        and not recently_dispatched
    ):
        campaign_leads = list(
            (
                await db.scalars(
                    select(CampaignLead)
                    .where(CampaignLead.campaign_id == campaign_id)
                    .order_by(CampaignLead.created_at.asc())
                )
            ).all()
        )
        status_rows = (
            await db.execute(
                select(CampaignLeadEmail.lead_id, CampaignLeadEmail.generation_status).where(
                    CampaignLeadEmail.campaign_id == campaign_id
                )
            )
        ).all()
        pending_lead_ids = {
            str(lead_id) for lead_id, gs in status_rows
            if lead_id and gs == GenerationStatus.PENDING
        }
        # Only leads that already have a PENDING row: a missing row means generation
        # never started (POST /generate or /resume create rows), and the worker skips
        # leads without one, so dispatching for them loops forever.
        pending_indices = [
            idx for idx, cl in enumerate(campaign_leads)
            if cl.lead_id and str(cl.lead_id) in pending_lead_ids
        ]
        chunk_ranges = _chunk_ranges_for_pending(pending_indices, GENERATION_CHUNK_SIZE)
        if chunk_ranges:
            _schedule_remaining_campaign_email_generation(
                campaign_id,
                user_id,
                regenerate_all=False,
                chunk_ranges=chunk_ranges,
                replace=False,
            )
            logger.info(
                "Auto-resumed stalled campaign email generation campaign=%s chunks=%s",
                campaign_id,
                chunk_ranges,
            )
    return {"campaign_id": str(campaign_id), **summary}


def stalled_generation_campaign_ids(
    rows: list[tuple[str, GenerationStatus, datetime | None]],
    *,
    now: datetime | None = None,
    stale_after: int = STALE_GENERATING_SECONDS,
) -> list[str]:
    """Campaigns with leftover PENDING/GENERATING work and no live GENERATING heartbeat.

    A campaign is skipped while any GENERATING row was updated within ``stale_after``
    seconds so a beat tick cannot pile extra chunks onto a still-running run.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(seconds=stale_after)
    unfinished: set[str] = set()
    live: set[str] = set()
    for campaign_id, status, updated_at in rows:
        if status not in (GenerationStatus.PENDING, GenerationStatus.GENERATING):
            continue
        unfinished.add(campaign_id)
        if status != GenerationStatus.GENERATING or updated_at is None:
            continue
        ts = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            live.add(campaign_id)
    return sorted(unfinished - live)


def _stalled_generation_campaigns_stmt(*, cutoff: datetime, limit: int):
    """SQL for campaigns that match ``stalled_generation_campaign_ids``."""
    fresh_ids = (
        select(CampaignLeadEmail.campaign_id)
        .where(
            CampaignLeadEmail.generation_status == GenerationStatus.GENERATING,
            CampaignLeadEmail.updated_at >= cutoff,
        )
        .distinct()
    )
    return (
        select(CampaignLeadEmail.campaign_id, Campaign.user_id)
        .join(Campaign, Campaign.id == CampaignLeadEmail.campaign_id)
        .where(
            CampaignLeadEmail.generation_status.in_(
                [GenerationStatus.PENDING, GenerationStatus.GENERATING]
            ),
            ~CampaignLeadEmail.campaign_id.in_(fresh_ids),
        )
        .distinct()
        .limit(limit)
    )


async def find_stalled_generation_campaigns(
    db: AsyncSession,
    *,
    limit: int = STALLED_RESUME_BATCH_LIMIT,
    now: datetime | None = None,
) -> list[tuple[str, str]]:
    """Return ``(campaign_id, user_id)`` pairs whose generation run looks abandoned."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=STALE_GENERATING_SECONDS)
    rows = (await db.execute(_stalled_generation_campaigns_stmt(cutoff=cutoff, limit=limit))).all()
    return [(str(campaign_id), str(user_id)) for campaign_id, user_id in rows]


async def resume_campaign_email_generation(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
    *,
    allow_in_process: bool = True,
) -> dict[str, Any]:
    """Restart background generation when leads are stuck in queued/pending."""
    if await _should_stop_generation(campaign_id, db):
        campaign_leads = await _fetch_campaign_leads(campaign_id, db)
        result = await db.scalars(
            select(CampaignLeadEmail).where(CampaignLeadEmail.campaign_id == campaign_id)
        )
        rows = list(result.all())
        summary = _generation_status_summary(rows, expected_total=len(campaign_leads))
        return {"campaign_id": campaign_id, "resumed": False, "cancelled": True, **summary}

    campaign = await _get_campaign_or_404(campaign_id, user_id, db)

    await _requeue_stale_generating_rows(db, campaign_id)

    campaign_leads = await _fetch_campaign_leads(campaign_id, db)
    # Create rows for leads that never got one (POST /generate rejected or never
    # reached); the worker skips leads without a row, so without this a resume can
    # never make progress. Existing rows are left as they are.
    rows_by_lead_id = await _upsert_campaign_email_rows(
        campaign, campaign_leads, db, regenerate_all=False
    )
    rows = list(rows_by_lead_id.values())
    summary = _generation_status_summary(rows, expected_total=len(campaign_leads))

    if summary["is_complete"]:
        return {"campaign_id": campaign_id, "resumed": False, **summary}

    if await _generation_already_running(db, campaign_id):
        return {
            "campaign_id": campaign_id,
            "resumed": False,
            "already_running": True,
            **summary,
        }

    pending_indices = _indices_needing_generation(
        campaign_leads, rows_by_lead_id, regenerate_all=False
    )
    chunk_ranges = _chunk_ranges_for_pending(pending_indices, GENERATION_CHUNK_SIZE)
    if not chunk_ranges:
        return {"campaign_id": campaign_id, "resumed": False, **summary}

    if _campaign_uses_ai_per_lead_generation(campaign):
        from app.services.credit_service import require_pool_credits

        await require_pool_credits(db, campaign.user_id, "ai_draft", len(pending_indices))

    background_mode = _schedule_remaining_campaign_email_generation(
        campaign_id,
        user_id,
        regenerate_all=False,
        chunk_ranges=chunk_ranges,
        replace=False,
        allow_in_process=allow_in_process,
    )
    if background_mode == "celery_unavailable":
        logger.warning(
            "Could not resume campaign email generation campaign=%s — Celery unavailable",
            campaign_id,
        )
        return {
            "campaign_id": campaign_id,
            "resumed": False,
            "celery_unavailable": True,
            **summary,
        }
    logger.info(
        "Resumed campaign email generation campaign=%s chunks=%s",
        campaign_id,
        chunk_ranges,
    )
    return {
        "campaign_id": campaign_id,
        "resumed": True,
        "background_mode": background_mode,
        **summary,
    }


async def resume_stalled_campaign_email_generations(
    session_factory: Callable[..., Any],
) -> dict[str, Any]:
    """Scan for abandoned generation runs and re-dispatch remaining chunks.

    Used by Celery beat so a stalled campaign heals without ``POST /emails/resume``
    or frontend polling. Reuses ``resume_campaign_email_generation`` so cancelled
    campaigns, live heartbeats, and completed runs are skipped the same way.
    """
    async with session_factory() as db:
        candidates = await find_stalled_generation_campaigns(db)

    resumed = 0
    skipped = 0
    errors = 0
    for campaign_id, user_id in candidates:
        try:
            async with session_factory() as db:
                result = await resume_campaign_email_generation(
                    campaign_id,
                    user_id,
                    db,
                    allow_in_process=False,
                )
            if result.get("resumed"):
                resumed += 1
                logger.info(
                    "Beat auto-resumed stalled campaign email generation campaign=%s",
                    campaign_id,
                )
            else:
                skipped += 1
        except HTTPException as exc:
            skipped += 1
            logger.warning(
                "Beat skipped stalled campaign email generation campaign=%s status=%s: %s",
                campaign_id,
                exc.status_code,
                exc.detail,
            )
        except Exception:
            errors += 1
            logger.exception(
                "Beat failed to resume stalled campaign email generation campaign=%s",
                campaign_id,
            )
    return {
        "candidates": len(candidates),
        "resumed": resumed,
        "skipped": skipped,
        "errors": errors,
    }


async def cancel_campaign_email_generation(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Stop background generation and keep only emails already generated as outreach-ready."""
    await _get_campaign_or_404(campaign_id, user_id, db)

    _mark_generation_cancelled(campaign_id)
    _revoke_celery_generation_task(campaign_id)

    task = _campaign_email_generation_tasks.get(campaign_id)
    if task and not task.done():
        task.cancel()

    campaign_leads = await _fetch_campaign_leads(campaign_id, db)
    result = await db.scalars(
        select(CampaignLeadEmail).where(CampaignLeadEmail.campaign_id == campaign_id)
    )
    rows = list(result.all())
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.generation_status in (GenerationStatus.GENERATING, GenerationStatus.PENDING):
            row.generation_status = GenerationStatus.FAILED
            row.last_error = GENERATION_CANCELLED_ERROR
            row.updated_at = now

    await db.commit()

    refreshed = await db.scalars(
        select(CampaignLeadEmail).where(CampaignLeadEmail.campaign_id == campaign_id)
    )
    summary = _generation_status_summary(list(refreshed.all()), expected_total=len(campaign_leads))
    ready = summary.get("ready", 0)
    return {
        "campaign_id": campaign_id,
        "cancelled": True,
        "ready_for_outreach": ready,
        "message": (
            f"{ready} email(s) ready for outreach."
            if ready > 0
            else "No emails ready yet — wait for at least one to finish generating."
        ),
        **summary,
    }


async def discard_campaign_lead_emails(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Discard all per-lead generated emails (e.g. user returns to tone/prompt compose)."""
    await _get_campaign_or_404(campaign_id, user_id, db)

    _mark_generation_cancelled(campaign_id)
    _revoke_celery_generation_task(campaign_id)

    task = _campaign_email_generation_tasks.get(campaign_id)
    if task and not task.done():
        task.cancel()

    result = await db.scalars(
        select(CampaignLeadEmail).where(CampaignLeadEmail.campaign_id == campaign_id)
    )
    rows = list(result.all())
    discarded = len(rows)
    for row in rows:
        await db.delete(row)

    await db.commit()

    campaign_leads = await _fetch_campaign_leads(campaign_id, db)
    summary = _generation_status_summary([], expected_total=len(campaign_leads))
    return {
        "campaign_id": campaign_id,
        "discarded": True,
        "discarded_count": discarded,
        **summary,
    }


async def list_campaign_lead_emails(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[CampaignLeadEmail], int, int, int]:
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or str(campaign.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail="Campaign not found or unauthorized.")

    page, per_page, offset = normalize_pagination(page, per_page)
    total_items = int(
        await db.scalar(
            select(func.count())
            .select_from(CampaignLeadEmail)
            .where(CampaignLeadEmail.campaign_id == campaign_id)
        )
        or 0
    )
    result = await db.scalars(
        select(CampaignLeadEmail)
        .where(CampaignLeadEmail.campaign_id == campaign_id)
        .options(
            selectinload(CampaignLeadEmail.campaign_lead),
            selectinload(CampaignLeadEmail.lead),
        )
        .order_by(CampaignLeadEmail.lead_index.asc())
        .offset(offset)
        .limit(per_page)
    )
    return list(result.all()), total_items, page, per_page
