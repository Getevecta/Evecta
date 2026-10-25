from app.core.celery_app import celery_app
import asyncio
import logging
from sqlalchemy import update, select, func
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.core.celery_helper import get_celery_session_factory, cleanup_event_loop 
from app.models.email_activity import EmailActivity, EmailStatus
from app.models.email_job import EmailJob, EmailJobStatus
from app.enums.email_sending_mode import EmailSendingMode
from app.models.lead import Lead
from app.models.mailbox import Mailbox, MailboxType, MailboxProvider
from app.models.domain import Domain
from app.models.campaign import Campaign, CampaignStatus
from app.models.campaign_lead_email import CampaignLeadEmail, ComplianceStatus, GenerationStatus, ReviewStatus
from app.models.user import User
from app.core.config import get_settings
from app.core.email_limits import DAILY_EMAIL_LIMIT
from app.utils.email_sender import send_campaign_email
from app.utils.unsubscribe_url import build_unsubscribe_urls
from app.utils.email_unsubscribe_html import build_top_unsubscribe_html
from app.utils.email_personalization import (
    build_footer,
    format_plain_text_as_html,
    replace_placeholders,
)
from app.services.email_send_idempotency import duplicate_send_skip_reason
from app.services.google_gmail_token_service import refresh_google_token
from app.services.mailbox_selector_service import (
    classify_mailbox_unavailability,
    get_next_available_mailbox,
)
from app.utils.sender_name_extractor import get_display_sender_from_content
import uuid
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.email_thread import EmailThread
from app.models.email_message import EmailMessage, MessageDirection

logger = logging.getLogger(__name__)
settings = get_settings()


async def _has_successful_send_activity(db: AsyncSession, campaign_id, lead_id) -> bool:
    existing = await db.scalar(
        select(EmailActivity.id).where(
            EmailActivity.campaign_id == campaign_id,
            EmailActivity.lead_id == lead_id,
            EmailActivity.status != EmailStatus.FAILED,
        ).limit(1)
    )
    return existing is not None


async def _mark_failed(db: AsyncSession, job_id: str, error: str) -> dict:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(EmailJob)
        .where(EmailJob.id == job_id)
        .values(status=EmailJobStatus.FAILED, last_error=error, updated_at=now)
    )
    await db.commit()
    return {"job_id": job_id, "status": "failed", "error": error}

async def _mark_sent(db: AsyncSession, job_id: str) -> dict:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(EmailJob)
        .where(EmailJob.id == job_id)
        .values(status=EmailJobStatus.SENT, last_error=None, updated_at=now)
    )
    await db.commit()
    return {"job_id": job_id, "status": "sent"}


async def _mark_job_failed_if_sending(
    session_factory,
    job_id: str,
    error: str,
) -> None:
    async with session_factory() as db:
        job = await db.get(EmailJob, job_id)
        if job and job.status == EmailJobStatus.SENDING:
            await _mark_failed(db, job_id, error)


async def _resolve_mailbox_and_domain(
    db: AsyncSession,
    *,
    user_id: str,
    sending_mode: EmailSendingMode,
) -> tuple[Mailbox | None, Domain | None, EmailSendingMode]:
    """Pick a mailbox strictly in the campaign's sending mode. A SYSTEM campaign
    must never send through the user's own mailboxes — a system mailbox without a
    domain sends via its own verified SES/SMTP identity, and when no system slot
    is free the job waits (rescheduled by the caller) instead of switching modes."""
    mailbox = await get_next_available_mailbox(
        db=db,
        user_id=user_id,
        sending_mode=sending_mode,
    )
    if mailbox is None:
        return None, None, sending_mode

    if mailbox.mailbox_type == MailboxType.USER:
        return mailbox, None, EmailSendingMode.USER

    domain = None
    if mailbox.mailbox_type != MailboxType.USER and mailbox.domain_id:
        domain = await db.get(Domain, mailbox.domain_id)
    return mailbox, domain, sending_mode

# CHANGED: Now accepts session_factory parameter
async def _process_email(job_id: str, session_factory) -> dict:
    now = datetime.now(timezone.utc)

    # CHANGED: Use passed session_factory instead of global celery_session_factory
    async with session_factory() as db:
        job = await db.get(EmailJob, job_id)
        if not job:
            return {"job_id": job_id, "status": "skipped", "reason": "job_not_found"}
        
        # If job is already in a terminal state, skip it
        if job.status in [EmailJobStatus.SENT, EmailJobStatus.FAILED]:
            return {"job_id": job_id, "status": "skipped", "reason": f"job_already_{job.status.name}"}
        
        # If job is not in SENDING state, something went wrong - mark as failed
        if job.status != EmailJobStatus.SENDING:
            return await _mark_failed(db, job_id, f"Job in unexpected state: {job.status.name}")

        # At-least-once: SMTP may already have succeeded on a previous delivery
        # that crashed before this row was marked SENT.
        has_activity = await _has_successful_send_activity(db, job.campaign_id, job.lead_id)
        skip_reason = duplicate_send_skip_reason(
            smtp_started_at=job.smtp_started_at,
            has_successful_activity=has_activity,
        )
        if skip_reason:
            logger.warning(
                "Job %s skipped SMTP (%s); completing as sent to avoid a duplicate",
                job_id,
                skip_reason,
            )
            return await _mark_sent(db, job_id)

        # Load campaign + lead
        campaign = await db.get(Campaign, job.campaign_id)
        lead = await db.get(Lead, job.lead_id)

        
        if not campaign or not lead:
            return await _mark_failed(db, job_id, "Campaign or Lead not found")

        # Campaign must be ongoing
        if campaign.status != CampaignStatus.ONGOING:
            return await _mark_failed(db, job_id, "Campaign not ongoing")

        # Draft check — prefer per-lead email when Step 4 generation produced one
        per_lead_count = await db.scalar(
            select(func.count())
            .select_from(CampaignLeadEmail)
            .where(CampaignLeadEmail.campaign_id == campaign.id)
        ) or 0

        lead_email = await db.scalar(
            select(CampaignLeadEmail).where(
                CampaignLeadEmail.campaign_id == campaign.id,
                CampaignLeadEmail.lead_id == lead.id,
                CampaignLeadEmail.generation_status == GenerationStatus.READY,
                CampaignLeadEmail.compliance_status == ComplianceStatus.PASSED,
                CampaignLeadEmail.review_status == ReviewStatus.APPROVED,
            )
        )

        if per_lead_count > 0:
            if not lead_email or not lead_email.subject or not lead_email.body:
                return await _mark_failed(
                    db, job_id, "Per-lead email not approved or not ready for send"
                )
            base_subject = lead_email.subject
            base_content = lead_email.body
        elif lead_email and lead_email.subject and lead_email.body:
            base_subject = lead_email.subject
            base_content = lead_email.body
        elif campaign.email_subject and campaign.email_content:
            base_subject = campaign.email_subject
            base_content = campaign.email_content
        else:
            return await _mark_failed(db, job_id, "Draft not ready")

        if not lead.email:
            return await _mark_failed(db, job_id, "Lead has no email")

        if lead.email_subscribed is False:
            return await _mark_failed(db, job_id, "Lead has unsubscribed")

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=999999)

        # Count all successful sends today. Must NOT filter status == SENT:
        # status moves to OPENED/CLICKED/BOUNCED once the email gets engagement,
        # which would make those emails stop counting toward the daily cap.
        sent_today = await db.scalar(
            select(func.count(EmailActivity.id)).where(
                EmailActivity.user_id == job.user_id,
                EmailActivity.status != EmailStatus.FAILED,
                EmailActivity.sent_at >= today_start,
                EmailActivity.sent_at <= today_end,
            )
        ) or 0

        if sent_today >= DAILY_EMAIL_LIMIT:
            # Put job back to QUEUED for tomorrow
            # Reschedule for tomorrow 00:01 UTC
            tomorrow = today_end.replace(hour=0, minute=1, second=0, microsecond=0) + timedelta(days=1)
            await db.execute(
                update(EmailJob)
                .where(EmailJob.id == job_id)
                .values(status=EmailJobStatus.QUEUED.value, scheduled_for=tomorrow, updated_at=datetime.now(timezone.utc))
            )

            await db.commit()
            return {"job_id": job_id, "status": "rescheduled", "reason": "daily_limit reached"}

        # -------- Personalize --------
        personalized_subject = replace_placeholders(base_subject, lead)
        personalized_content = replace_placeholders(base_content, lead)

        # Convert to HTML with line breaks preserved so the email shows paragraphs as composed
        personalized_content_html = format_plain_text_as_html(personalized_content)

        unsub_urls = build_unsubscribe_urls(str(lead.id), lead.email)
        one_click_unsubscribe_url = unsub_urls["one_click_url"]
        confirm_unsubscribe_url = unsub_urls["confirm_url"]
        subscribe_url = unsub_urls["subscribe_url"]

        # Use sender name/company from end of email (e.g. "Best regards, Eric") in footer and From header
        display_sender = get_display_sender_from_content(personalized_content)
        # Fallback to campaign owner's full name when extraction fails (e.g. server-stored single-line content)
        if display_sender == "Evecta Outreach":
            user = await db.get(User, job.user_id)
            if user and getattr(user, "full_name", None) and str(user.full_name).strip():
                display_sender = str(user.full_name).strip()
        personalized_content_with_footer = (
            build_top_unsubscribe_html(confirm_unsubscribe_url)
            + personalized_content_html
            + build_footer(confirm_unsubscribe_url, subscribe_url, sender_name=display_sender)
        )

        sending_mode = campaign.email_sending_mode
        from app.services.campaign_launch_readiness_service import reconcile_campaign_sending_mode

        await reconcile_campaign_sending_mode(campaign, str(job.user_id), db)
        sending_mode = campaign.email_sending_mode or EmailSendingMode.USER
        mailbox, domain, sending_mode = await _resolve_mailbox_and_domain(
            db,
            user_id=str(job.user_id),
            sending_mode=sending_mode,
        )

        if mailbox is None:
            permanent, reason = await classify_mailbox_unavailability(db, str(job.user_id))
            if permanent:
                return await _mark_failed(db, job_id, reason)
            tomorrow = (today_end + timedelta(seconds=1)).replace(hour=0, minute=1, second=0, microsecond=0)
            await db.execute(
                update(EmailJob)
                .where(EmailJob.id == job_id)
                .values(
                    status=EmailJobStatus.QUEUED.value,
                    scheduled_for=tomorrow,
                    last_error=reason,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            return {"job_id": job_id, "status": "rescheduled", "reason": reason}

        if mailbox.provider == MailboxProvider.GOOGLE:
            if (
                mailbox.google_token_expires_at is None
                or mailbox.google_token_expires_at
                <= datetime.now(timezone.utc) + timedelta(minutes=2)
            ):
                await refresh_google_token(mailbox=mailbox, db=db)

        # Claim this SMTP attempt atomically. A redelivered worker sees
        # smtp_started_at set and skips send (see duplicate_send_skip_reason).
        claim = await db.execute(
            update(EmailJob)
            .where(
                EmailJob.id == job_id,
                EmailJob.status == EmailJobStatus.SENDING,
                EmailJob.smtp_started_at.is_(None),
            )
            .values(
                mailbox_id=mailbox.id,
                domain_id=(domain.id if domain else None),
                smtp_started_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        if claim.rowcount == 0:
            current = await db.get(EmailJob, job_id)
            if current and current.status == EmailJobStatus.SENT:
                return {
                    "job_id": job_id,
                    "status": "skipped",
                    "reason": "job_already_SENT",
                }
            logger.warning(
                "Job %s lost the SMTP claim (already started); skipping duplicate send",
                job_id,
            )
            return await _mark_sent(db, job_id)

        # send email (pass display_sender so From header shows name, e.g. "Sushma <email>")
        result = await send_campaign_email(
            to_email=lead.email,
            subject=personalized_subject,
            html_content=personalized_content_with_footer,
            campaign_id=str(campaign.id),
            lead_id=str(lead.id),
            user_id=str(job.user_id),
            mailbox=mailbox,
            domain=domain,
            unsubscribe_url=one_click_unsubscribe_url,
            db=None,
            display_sender=display_sender,
        )

        # -------- Log activity + rotation update --------
        now = datetime.now(timezone.utc)

        if result.get("status") == EmailStatus.SENT:
            # Create EmailActivity (unchanged — all tracking/analytics still work)
            activity = EmailActivity(
                campaign_id=campaign.id,
                lead_id=lead.id,
                user_id=job.user_id,
                email=lead.email,
                status=EmailStatus.SENT,
                sent_at=result.get("sent_at", now),
                sent_from=result.get("sent_from"),
                message_id=result.get("message_id"),
                ses_message_id=result.get("ses_message_id"),
                tracking_token=result.get("tracking_token"),
            )
            db.add(activity)
            try:
                await db.flush()  # Get activity.id for EmailMessage link
            except IntegrityError:
                await db.rollback()
                logger.warning(
                    "Job %s hit unique send activity for campaign/lead; treating as already sent",
                    job_id,
                )
                return await _mark_sent(db, job_id)

            # Upsert EmailThread — one per campaign
            # On first send: creates the thread
            # On subsequent sends (more leads): increments total_recipients
            thread_upsert = (
                pg_insert(EmailThread)
                .values(
                    id=uuid.uuid4(),
                    campaign_id=campaign.id,
                    user_id=job.user_id,
                    subject=personalized_subject,
                    total_recipients=1,
                    unread_reply_count=0,
                    is_starred=False,
                    last_message_at=now,
                    created_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["campaign_id"],
                    set_={
                        "total_recipients": EmailThread.__table__.c.total_recipients + 1,
                        "last_message_at": now,
                    },
                )
                .returning(EmailThread.id)
            )
            thread_row = await db.execute(thread_upsert)
            thread_id = thread_row.scalar_one()

            # Create OUTBOUND EmailMessage — links the sent email into the thread
            db.add(
                EmailMessage(
                    thread_id=thread_id,
                    lead_id=lead.id,
                    campaign_id=campaign.id,
                    direction=MessageDirection.OUTBOUND,
                    sender_email=result.get("sent_from"),
                    recipient_email=lead.email,
                    body=personalized_content_with_footer,
                    message_id=result.get("message_id"),
                    sent_at=result.get("sent_at", now),
                    is_read=True,
                    mailbox_id=mailbox.id,
                    email_activity_id=activity.id,
                )
            )

        # Update mailbox last_used to actual send time
        # (sent_today was already incremented atomically in get_next_available_mailbox)
            await db.execute(
                update(Mailbox)
                .where(Mailbox.id == mailbox.id)
                .values(last_used=now)
            )

            # Update domain usage if SYSTEM
            if domain:
                await db.execute(
                    update(Domain)
                    .where(Domain.id == domain.id)
                    .values(last_used=now, sent_today=Domain.sent_today + 1)
                )

            await db.commit()
            from app.services.campaign_send_status_service import maybe_complete_campaign

            await maybe_complete_campaign(db, campaign.id)
            await db.commit()
            return await _mark_sent(db, job_id)
        
        else:
            error_msg = result.get("error", "Unknown error")

            db.add(
                EmailActivity(
                    campaign_id=campaign.id,
                    lead_id=lead.id,
                    user_id=job.user_id,
                    email=lead.email,
                    status=EmailStatus.FAILED,
                    sent_at=now,
                )
            )

            await db.commit()
            from app.services.campaign_send_status_service import maybe_complete_campaign

            await maybe_complete_campaign(db, campaign.id)
            await db.commit()
            return await _mark_failed(db, job_id, error_msg)

# proper event loop management
@celery_app.task(name="app.tasks.mail_job.process_email_job")
def process_email_job(job_id: str):
    """
    Process a single email job with proper event loop and engine management.
    
     Creates fresh event loop
     Creates fresh engine (isolated from other tasks)
     Properly disposes engine before closing loop
     Cancels pending tasks before closing loop
    """
    logger.info("=" * 80)
    logger.info(f"🔄 [MAIL_JOB] Starting mail job: {job_id}")
    logger.info("=" * 80)
    
    # STEP 1: Create fresh engine + session factory for THIS task only
    session_factory, task_engine = get_celery_session_factory()
    logger.info("[MAIL_JOB] ✅ Created fresh engine for this task")
    
    # STEP 2: Create fresh event loop for THIS task only
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    logger.info("[MAIL_JOB] ✅ Created fresh event loop for this task")

    try:
        logger.info(f"[MAIL_JOB] 📧 Processing job: {job_id}")
        result = loop.run_until_complete(_process_email(job_id, session_factory))
        logger.info(f"[MAIL_JOB] ✅ Job completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"[MAIL_JOB] ❌ Job failed: {str(e)}", exc_info=True)
        try:
            loop.run_until_complete(
                _mark_job_failed_if_sending(session_factory, job_id, str(e))
            )
        except Exception:
            logger.exception("[MAIL_JOB] Failed to mark job %s as failed after error", job_id)
        raise
        
    finally:
        # STEP 3: Clean up properly (using helper function)
        logger.info("[MAIL_JOB] 🧹 Cleaning up...")
        cleanup_event_loop(loop, task_engine)
        logger.info("=" * 80)
        logger.info("[MAIL_JOB] ✨ Mail job cleanup complete")
        logger.info("=" * 80)