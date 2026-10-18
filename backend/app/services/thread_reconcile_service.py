"""
Backfill EmailThread + outbound EmailMessage rows from existing EmailActivity.

Some deployments (or older workers) recorded SENT activities without creating
thread rows, so campaign insights / legacy inbox show sends while the thread
inbox stays empty. Reconciliation repairs that gap idempotently.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.campaign import Campaign
from app.models.email_activity import EmailActivity, EmailStatus
from app.models.email_message import EmailMessage, MessageDirection
from app.models.email_thread import EmailThread
from app.models.lead import Lead
from app.models.mailbox import Mailbox
from app.models.user import User
from app.utils.sender_name_extractor import get_display_sender_from_content
from app.utils.unsubscribe_url import build_unsubscribe_urls

logger = logging.getLogger(__name__)


async def reconcile_email_threads_for_user(db: AsyncSession, user_id: UUID) -> int:
    """
    For each campaign where the user has SENT EmailActivity rows but no EmailThread,
    create the thread and outbound EmailMessage rows (best-effort body reconstruction).

    Returns the number of EmailThread rows created (0 if nothing to do).
    """
    # Campaigns with at least one non-FAILED activity (matches campaign insights / sent counts)
    sent_campaigns = (
        await db.execute(
            select(EmailActivity.campaign_id)
            .where(
                EmailActivity.user_id == user_id,
                EmailActivity.status != EmailStatus.FAILED,
            )
            .distinct()
        )
    ).scalars().all()

    if not sent_campaigns:
        return 0

    have_thread = (
        await db.execute(
            select(EmailThread.campaign_id).where(EmailThread.user_id == user_id)
        )
    ).scalars().all()
    have_set = set(have_thread)

    missing = [cid for cid in sent_campaigns if cid not in have_set]
    if not missing:
        return 0

    # Lazy import: mail_job pulls celery; keep startup graphs small
    from app.utils.email_personalization import replace_placeholders, format_plain_text_as_html, build_footer

    settings = get_settings()
    created_threads = 0

    for campaign_id in missing:
        campaign = await db.get(Campaign, campaign_id)
        if not campaign or campaign.user_id != user_id:
            continue

        activities = (
            await db.execute(
                select(EmailActivity)
                .where(
                    EmailActivity.campaign_id == campaign_id,
                    EmailActivity.user_id == user_id,
                    EmailActivity.status != EmailStatus.FAILED,
                )
                .order_by(EmailActivity.sent_at.asc())
            )
        ).scalars().all()

        if not activities:
            continue

        # Skip if another request inserted the thread (race)
        existing = await db.scalar(
            select(EmailThread).where(EmailThread.campaign_id == campaign_id)
        )
        if existing:
            continue

        now = datetime.now(timezone.utc)
        first = activities[0]
        last_at = max(a.sent_at for a in activities if a.sent_at) if activities else now

        lead0 = await db.get(Lead, first.lead_id)
        subject_seed = campaign.email_subject or ""
        if lead0:
            subject_seed = replace_placeholders(subject_seed, lead0)
        subject_seed = (subject_seed or "")[:255]

        thread = EmailThread(
            id=uuid.uuid4(),
            campaign_id=campaign_id,
            user_id=user_id,
            subject=subject_seed or None,
            total_recipients=len(activities),
            unread_reply_count=0,
            is_starred=False,
            last_message_at=last_at,
            created_at=first.sent_at or now,
        )
        db.add(thread)
        await db.flush()

        owner = await db.get(User, user_id)
        fallback_sender = (
            str(owner.full_name).strip()
            if owner and getattr(owner, "full_name", None) and str(owner.full_name).strip()
            else "Evecta Outreach"
        )

        for activity in activities:
            already = await db.scalar(
                select(EmailMessage.id).where(
                    EmailMessage.email_activity_id == activity.id
                )
            )
            if already:
                continue

            lead = await db.get(Lead, activity.lead_id)
            if not lead or not lead.email:
                continue

            personalized_subject = replace_placeholders(campaign.email_subject or "", lead)
            personalized_content = replace_placeholders(campaign.email_content or "", lead)
            personalized_content_html = format_plain_text_as_html(personalized_content)

            unsub_urls = build_unsubscribe_urls(str(lead.id), lead.email)
            confirm_unsubscribe_url = unsub_urls["confirm_url"]

            display_sender = get_display_sender_from_content(personalized_content)
            if display_sender == "Evecta Outreach":
                display_sender = fallback_sender

            body_html = personalized_content_html + build_footer(
                confirm_unsubscribe_url, sender_name=display_sender
            )

            mailbox_id = None
            if activity.sent_from:
                mb = await db.scalar(
                    select(Mailbox.id).where(
                        and_(
                            Mailbox.user_id == user_id,
                            func.lower(Mailbox.email) == activity.sent_from.strip().lower(),
                        )
                    )
                )
                mailbox_id = mb

            db.add(
                EmailMessage(
                    id=uuid.uuid4(),
                    thread_id=thread.id,
                    lead_id=activity.lead_id,
                    campaign_id=campaign_id,
                    direction=MessageDirection.OUTBOUND,
                    sender_email=activity.sent_from,
                    recipient_email=activity.email,
                    body=body_html,
                    message_id=activity.message_id,
                    sent_at=activity.sent_at or now,
                    is_read=True,
                    mailbox_id=mailbox_id,
                    email_activity_id=activity.id,
                )
            )

        await db.flush()
        created_threads += 1
        logger.info(
            "Reconciled EmailThread for campaign %s user %s (%s outbound messages)",
            campaign_id,
            user_id,
            len(activities),
        )

    if created_threads:
        await db.commit()

    return created_threads
