import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
from sqlalchemy import select, update, func, distinct, exists, and_
from sqlalchemy.orm import aliased
from uuid import UUID
from typing import List

from app.database.session import get_session
from app.services.inbox_service import get_user_inbox
from app.services.reply_fetch_service import fetch_replies_for_user_mailboxes
from app.services.thread_reconcile_service import reconcile_email_threads_for_user
from app.services.thread_reply_service import send_thread_reply
from app.dependencies.auth import get_current_user
from app.models.email_activity import EmailActivity, EmailStatus
from app.models.email_thread import EmailThread
from app.models.email_message import EmailMessage, MessageDirection
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.user import User
from app.schemas.thread import (
    ThreadOut,
    ThreadDetailOut,
    LeadConversationOut,
    MessageOut,
    LeadConversationSummary,
    ThreadReplyRequest,
    ThreadReplyOut,
)
from app.services.campaign_sender_email import resolve_campaign_sender_email
from app.core.limiter import limiter

router = APIRouter(prefix="/inbox", tags=["Inbox"])


# ── Legacy endpoints (unchanged) ──────────────────────────────────────────────

@router.get("/")
async def inbox(
    campaign_id: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """
    Unified inbox (legacy flat list):
    - Shows all persisted replies for the logged-in user
    - Optional campaign filter
    - Paginated: page/per_page (max 100 per page)
    """
    items = await get_user_inbox(
        user_id=str(user.id),
        db=db,
        campaign_filter=campaign_id,
        page=page,
        per_page=per_page,
    )
    return {"total": len(items), "page": page, "per_page": per_page, "items": items}


@router.post("/{activity_id}/star")
async def toggle_inbox_star(
    activity_id: str,
    db: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Toggle star status for an inbox email activity."""
    try:
        activity_uuid = UUID(activity_id)

        stmt = select(EmailActivity).where(
            EmailActivity.id == activity_uuid,
            EmailActivity.user_id == user.id,
        )
        result = await db.execute(stmt)
        activity = result.scalar_one_or_none()

        if not activity:
            raise HTTPException(
                status_code=404,
                detail="Email activity not found or unauthorized",
            )

        activity.starred = not activity.starred
        await db.commit()
        await db.refresh(activity)

        return {"id": str(activity.id), "starred": activity.starred}

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid activity ID format")
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update inbox. Please try again.")


@router.post("/fetch-replies")
@limiter.limit("30/hour")
async def manual_fetch_replies(
    request: Request,
    db: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Manually fetch replies for the logged-in user's mailboxes."""
    # Auth comes from get_current_user (HttpOnly cookie, then Bearer header). A
    # separate OAuth2PasswordBearer dependency used to require the header, which
    # cookie-auth browsers never send — every call 401'd and the refresh/redirect
    # handling bounced the Inbox page between /auth and /dashboard.
    try:
        user_id = user.id
        user_id_str = str(user_id)
        logger.info(f"[MANUAL FETCH] User {user_id_str} triggered reply fetch")

        try:
            await reconcile_email_threads_for_user(db, user_id)
        except Exception:
            logger.exception(
                "thread reconcile failed for user %s during manual fetch",
                user_id_str,
            )

        await fetch_replies_for_user_mailboxes(db=db, user_id=user_id_str)

        items = await get_user_inbox(user_id=user_id_str, db=db)

        return {
            "status": "success",
            "replies_found": len(items),
            "items": items,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to fetch replies. Please try again.")


# ── Thread endpoints ───────────────────────────────────────────────────────────

@router.get("/threads", response_model=List[ThreadOut])
async def list_threads(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """
    List all inbox threads — one per campaign, sorted by most recent activity.
    Each thread shows reply counts and unread status.
    """
    offset = (page - 1) * per_page

    # Thread repair runs on POST /inbox/fetch-replies (and can be triggered
    # explicitly). Keep list GETs O(1) query-count without reconcile side effects.

    # Fetch threads + campaign names
    threads_result = await db.execute(
        select(EmailThread, Campaign.name.label("campaign_name"))
        .join(Campaign, Campaign.id == EmailThread.campaign_id)
        .where(EmailThread.user_id == user.id)
        .order_by(EmailThread.last_message_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    rows = threads_result.all()

    if not rows:
        return []

    thread_ids = [row.EmailThread.id for row in rows]
    campaign_ids = [row.EmailThread.campaign_id for row in rows]

    # Count distinct leads who replied per thread (one query for all threads)
    replied_counts_result = await db.execute(
        select(
            EmailMessage.thread_id,
            func.count(distinct(EmailMessage.lead_id)).label("replied_count"),
        )
        .where(
            EmailMessage.thread_id.in_(thread_ids),
            EmailMessage.direction == MessageDirection.INBOUND,
        )
        .group_by(EmailMessage.thread_id)
    )
    replied_map = {
        str(row.thread_id): row.replied_count
        for row in replied_counts_result.all()
    }

    # Recipient opens per campaign — same EmailActivity.opened source as
    # campaign insight / ongoing Open Rate cards.
    opened_counts_result = await db.execute(
        select(
            EmailActivity.campaign_id,
            func.count().label("opened_count"),
        )
        .where(
            EmailActivity.campaign_id.in_(campaign_ids),
            EmailActivity.opened.is_(True),
            EmailActivity.status != EmailStatus.FAILED,
        )
        .group_by(EmailActivity.campaign_id)
    )
    opened_map = {
        str(row.campaign_id): int(row.opened_count or 0)
        for row in opened_counts_result.all()
    }

    # Evecta-user replies: outbound messages that follow an inbound from the same lead
    InboundMsg = aliased(EmailMessage)
    user_replies_result = await db.execute(
        select(
            EmailMessage.thread_id,
            EmailMessage.lead_id,
        )
        .where(
            EmailMessage.thread_id.in_(thread_ids),
            EmailMessage.direction == MessageDirection.OUTBOUND,
            exists(
                select(1).select_from(InboundMsg).where(
                    InboundMsg.thread_id == EmailMessage.thread_id,
                    InboundMsg.lead_id == EmailMessage.lead_id,
                    InboundMsg.direction == MessageDirection.INBOUND,
                    InboundMsg.sent_at < EmailMessage.sent_at,
                )
            ),
        )
        .distinct()
    )
    user_replied_leads_by_thread: dict[str, set[str]] = {}
    for row in user_replies_result.all():
        tid = str(row.thread_id)
        user_replied_leads_by_thread.setdefault(tid, set()).add(str(row.lead_id))

    # Leads with any unread inbound — needed to compute opened-but-unreplied per lead
    unread_leads_result = await db.execute(
        select(
            EmailMessage.thread_id,
            EmailMessage.lead_id,
        )
        .where(
            EmailMessage.thread_id.in_(thread_ids),
            EmailMessage.direction == MessageDirection.INBOUND,
            EmailMessage.is_read.is_(False),
        )
        .distinct()
    )
    unread_leads_by_thread: dict[str, set[str]] = {}
    for row in unread_leads_result.all():
        tid = str(row.thread_id)
        unread_leads_by_thread.setdefault(tid, set()).add(str(row.lead_id))

    # All leads with inbound replies
    inbound_leads_result = await db.execute(
        select(
            EmailMessage.thread_id,
            EmailMessage.lead_id,
        )
        .where(
            EmailMessage.thread_id.in_(thread_ids),
            EmailMessage.direction == MessageDirection.INBOUND,
        )
        .distinct()
    )
    inbound_leads_by_thread: dict[str, set[str]] = {}
    for row in inbound_leads_result.all():
        tid = str(row.thread_id)
        inbound_leads_by_thread.setdefault(tid, set()).add(str(row.lead_id))

    def _opened_unreplied_count(thread_id: str) -> int:
        inbound = inbound_leads_by_thread.get(thread_id, set())
        unread = unread_leads_by_thread.get(thread_id, set())
        replied = user_replied_leads_by_thread.get(thread_id, set())
        # Opened by Evecta user = inbound read (not in unread) and not yet replied
        return len(inbound - unread - replied)

    return [
        ThreadOut(
            id=str(row.EmailThread.id),
            campaign_id=str(row.EmailThread.campaign_id),
            campaign_name=row.campaign_name,
            subject=row.EmailThread.subject,
            last_message_at=row.EmailThread.last_message_at,
            sent_at=row.EmailThread.created_at,
            total_recipients=row.EmailThread.total_recipients,
            replied_count=replied_map.get(str(row.EmailThread.id), 0),
            opened_count=opened_map.get(str(row.EmailThread.campaign_id), 0),
            unread_reply_count=row.EmailThread.unread_reply_count,
            user_reply_count=len(user_replied_leads_by_thread.get(str(row.EmailThread.id), set())),
            opened_unreplied_count=_opened_unreplied_count(str(row.EmailThread.id)),
            is_starred=row.EmailThread.is_starred,
        )
        for row in rows
    ]


@router.get("/threads/{thread_id}", response_model=ThreadDetailOut)
async def get_thread(
    thread_id: UUID,
    db: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """
    Thread detail view — shows all leads who have replied.
    Each lead entry shows their latest reply + read/unread status.
    """
    row = (
        await db.execute(
            select(EmailThread, Campaign)
            .join(Campaign, Campaign.id == EmailThread.campaign_id)
            .where(
                EmailThread.id == thread_id,
                EmailThread.user_id == user.id,
            )
        )
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Thread not found")

    thread, campaign = row

    # All INBOUND messages for this thread, newest first, with lead info
    inbound_result = await db.execute(
        select(EmailMessage, Lead)
        .join(Lead, Lead.id == EmailMessage.lead_id)
        .where(
            EmailMessage.thread_id == thread_id,
            EmailMessage.direction == MessageDirection.INBOUND,
        )
        .order_by(EmailMessage.sent_at.desc())
    )
    inbound_rows = inbound_result.all()

    # Total message count (both directions) per lead
    count_result = await db.execute(
        select(
            EmailMessage.lead_id,
            func.count().label("total"),
        )
        .where(EmailMessage.thread_id == thread_id)
        .group_by(EmailMessage.lead_id)
    )
    count_map = {str(row.lead_id): row.total for row in count_result.all()}

    # Pre-aggregate unread counts per lead in one query — avoids N+1
    unread_result = await db.execute(
        select(
            EmailMessage.lead_id,
            func.count().label("unread_count"),
        )
        .where(
            EmailMessage.thread_id == thread_id,
            EmailMessage.direction == MessageDirection.INBOUND,
            EmailMessage.is_read   == False,
        )
        .group_by(EmailMessage.lead_id)
    )
    unread_map = {str(row.lead_id): row.unread_count for row in unread_result.all()}

    # Leads the Evecta user has replied to (outbound after inbound)
    InboundMsg = aliased(EmailMessage)
    user_replied_result = await db.execute(
        select(distinct(EmailMessage.lead_id))
        .where(
            EmailMessage.thread_id == thread_id,
            EmailMessage.direction == MessageDirection.OUTBOUND,
            exists(
                select(1).select_from(InboundMsg).where(
                    InboundMsg.thread_id == EmailMessage.thread_id,
                    InboundMsg.lead_id == EmailMessage.lead_id,
                    InboundMsg.direction == MessageDirection.INBOUND,
                    InboundMsg.sent_at < EmailMessage.sent_at,
                )
            ),
        )
    )
    user_replied_leads = {str(lid) for lid in user_replied_result.scalars().all()}

    # Deduplicate: one summary per lead (first row = latest INBOUND)
    seen: set = set()
    replies: List[LeadConversationSummary] = []

    for msg, lead in inbound_rows:
        lead_id_str = str(lead.id)
        if lead_id_str in seen:
            continue
        seen.add(lead_id_str)

        has_unread = unread_map.get(lead_id_str, 0) > 0

        replies.append(
            LeadConversationSummary(
                lead_id=lead_id_str,
                lead_email=lead.email,
                lead_name=lead.business_name,
                lead_industry=lead.industry,
                lead_score=lead.lead_score,
                latest_reply=msg.body,
                replied_at=msg.sent_at,
                is_read=not has_unread,
                message_count=count_map.get(lead_id_str, 0),
                has_user_replied=lead_id_str in user_replied_leads,
            )
        )

    return ThreadDetailOut(
        id=str(thread.id),
        campaign_id=str(thread.campaign_id),
        campaign_name=campaign.name if campaign else "",
        subject=thread.subject,
        campaign_description=campaign.description if campaign else None,
        campaign_status=campaign.status.value if campaign else None,
        campaign_created_at=campaign.created_at if campaign else None,
        thread_started_at=thread.created_at,
        total_recipients=thread.total_recipients,
        unread_reply_count=thread.unread_reply_count,
        is_starred=thread.is_starred,
        email_sending_mode=(
            campaign.email_sending_mode.value
            if campaign and campaign.email_sending_mode is not None
            else None
        ),
        sender_email=(
            await resolve_campaign_sender_email(
                db,
                campaign_id=campaign.id,
                user_id=user.id,
                email_sending_mode=campaign.email_sending_mode,
            )
            if campaign
            else None
        ),
        replies=replies,
    )


@router.get("/threads/{thread_id}/leads/{lead_id}", response_model=LeadConversationOut)
async def get_lead_conversation(
    thread_id: UUID,
    lead_id: UUID,
    db: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """
    Full conversation with a specific lead inside a thread.
    Messages are in chronological order (oldest first).
    Opens the conversation: all unread INBOUND messages are marked as read.
    """
    row = (
        await db.execute(
            select(EmailThread, Lead)
            .join(Lead, and_(Lead.id == lead_id, Lead.user_id == user.id))
            .where(
                EmailThread.id == thread_id,
                EmailThread.user_id == user.id,
            )
        )
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Thread not found")

    _thread, lead = row

    # All messages for this lead in this thread, oldest first
    messages_result = await db.execute(
        select(EmailMessage)
        .where(
            EmailMessage.thread_id == thread_id,
            EmailMessage.lead_id   == lead_id,
        )
        .order_by(EmailMessage.sent_at.asc())
    )
    messages = messages_result.scalars().all()

    # Mark all INBOUND messages as read
    await db.execute(
        update(EmailMessage)
        .where(
            EmailMessage.thread_id == thread_id,
            EmailMessage.lead_id   == lead_id,
            EmailMessage.direction == MessageDirection.INBOUND,
            EmailMessage.is_read   == False,
        )
        .values(is_read=True)
    )

    # Recalculate thread's total unread count
    remaining_unread = await db.scalar(
        select(func.count()).where(
            EmailMessage.thread_id == thread_id,
            EmailMessage.direction == MessageDirection.INBOUND,
            EmailMessage.is_read   == False,
        )
    )
    await db.execute(
        update(EmailThread)
        .where(EmailThread.id == thread_id)
        .values(unread_reply_count=remaining_unread or 0)
    )

    await db.commit()

    return LeadConversationOut(
        lead_id=str(lead.id),
        lead_email=lead.email,
        lead_name=lead.business_name,
        messages=[
            MessageOut(
                id=str(m.id),
                direction=m.direction.value,
                sender_email=m.sender_email,
                recipient_email=m.recipient_email,
                body=m.body,
                message_id=m.message_id,
                sent_at=m.sent_at,
                is_read=m.is_read,
            )
            for m in messages
        ],
    )


@router.post("/threads/{thread_id}/leads/{lead_id}/reply", response_model=ThreadReplyOut)
@limiter.limit("30/hour")
async def reply_to_lead(
    request: Request,
    thread_id: UUID,
    lead_id: UUID,
    body: ThreadReplyRequest,
    db: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """
    Send a reply to a specific lead inside a thread.
    Uses the mailbox that originally received the lead's reply.
    Sets proper In-Reply-To + References headers for email client threading.
    """
    out_message = await send_thread_reply(
        thread_id=thread_id,
        lead_id=lead_id,
        user_id=user.id,
        body=body.message,
        db=db,
    )

    return ThreadReplyOut(
        id=str(out_message.id),
        message_id=out_message.message_id,
        sent_at=out_message.sent_at,
        sender_email=out_message.sender_email,
        recipient_email=out_message.recipient_email,
    )


@router.patch("/threads/{thread_id}/read")
async def mark_thread_read(
    thread_id: UUID,
    db: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Mark all replies in a thread as read."""
    thread = await db.scalar(
        select(EmailThread)
        .where(EmailThread.id == thread_id, EmailThread.user_id == user.id)
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    await db.execute(
        update(EmailMessage)
        .where(
            EmailMessage.thread_id == thread_id,
            EmailMessage.direction == MessageDirection.INBOUND,
        )
        .values(is_read=True)
    )
    await db.execute(
        update(EmailThread)
        .where(EmailThread.id == thread_id)
        .values(unread_reply_count=0)
    )
    await db.commit()

    return {"id": str(thread_id), "unread_reply_count": 0}


@router.patch("/threads/{thread_id}/star")
async def toggle_thread_star(
    thread_id: UUID,
    db: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Toggle star on a thread."""
    thread = await db.scalar(
        select(EmailThread)
        .where(EmailThread.id == thread_id, EmailThread.user_id == user.id)
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    thread.is_starred = not thread.is_starred
    await db.commit()

    return {"id": str(thread_id), "is_starred": thread.is_starred}
