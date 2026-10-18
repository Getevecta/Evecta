import logging
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timezone

from app.models.mailbox import Mailbox, MailboxType
from app.enums.email_sending_mode import EmailSendingMode

logger = logging.getLogger(__name__)


async def classify_mailbox_unavailability(
    db: AsyncSession,
    user_id: str,
) -> tuple[bool, str]:
    """
    Classify why no mailbox could be selected.
    Returns (is_permanent, message). Permanent issues won't resolve by waiting.
    """
    from sqlalchemy import func, select

    user_total = int(
        await db.scalar(
            select(func.count())
            .select_from(Mailbox)
            .where(
                Mailbox.user_id == user_id,
                Mailbox.mailbox_type == MailboxType.USER,
                Mailbox.is_active.is_(True),
            )
        )
        or 0
    )
    user_with_capacity = int(
        await db.scalar(
            select(func.count())
            .select_from(Mailbox)
            .where(
                Mailbox.user_id == user_id,
                Mailbox.mailbox_type == MailboxType.USER,
                Mailbox.is_active.is_(True),
                Mailbox.sent_today < Mailbox.daily_limit,
            )
        )
        or 0
    )
    system_total = int(
        await db.scalar(
            select(func.count())
            .select_from(Mailbox)
            .where(
                Mailbox.mailbox_type == MailboxType.SYSTEM,
                Mailbox.is_active.is_(True),
            )
        )
        or 0
    )
    system_with_capacity = int(
        await db.scalar(
            select(func.count())
            .select_from(Mailbox)
            .where(
                Mailbox.mailbox_type == MailboxType.SYSTEM,
                Mailbox.is_active.is_(True),
                Mailbox.sent_today < Mailbox.daily_limit,
            )
        )
        or 0
    )

    if user_total == 0 and system_total == 0:
        return True, (
            "No sending account configured. Connect Gmail or IMAP in Email Setup "
            "(campaign Step 4), or link a domain to the system mailbox."
        )

    if user_with_capacity == 0 and system_with_capacity == 0:
        return False, "Daily mailbox send limit reached."

    return False, "No mailbox available right now."


async def get_next_available_mailbox(
    db: AsyncSession,
    user_id: str,
    sending_mode: EmailSendingMode,
):
    """
    Returns ONE mailbox eligible to send the next email and atomically
    reserves the slot by incrementing sent_today immediately.

    Uses FOR UPDATE SKIP LOCKED so concurrent workers never pick the
    same mailbox. The sent_today increment is committed before this
    function returns, so the slot is consumed even if the caller hasn't
    sent the email yet — preventing over-selection under concurrency.

    Rotation happens by last_used ASC (least-recently-used first).
    """

    try:
        query = (
            select(Mailbox)
            .where(
                Mailbox.is_active.is_(True),
                Mailbox.sent_today < Mailbox.daily_limit,
            )
        )

        # SYSTEM MODE — platform mailboxes (SES/SMTP); domain_id optional
        if sending_mode == EmailSendingMode.SYSTEM:
            query = query.where(Mailbox.mailbox_type == MailboxType.SYSTEM)

        # USER MODE
        elif sending_mode == EmailSendingMode.USER:
            query = query.where(
                Mailbox.mailbox_type == MailboxType.USER,
                Mailbox.user_id == user_id,
            )

        query = (
            query
            .order_by(Mailbox.last_used.asc())
            .limit(1)
            .with_for_update(skip_locked=True, of=Mailbox)  # lock only mailboxes table, not joined tables
        )

        result = await db.execute(query)
        mailbox = result.scalar_one_or_none()

        if mailbox is None:
            return None

        # Atomically reserve the slot — increment sent_today NOW so any
        # other concurrent worker immediately sees this mailbox as fuller.
        now = datetime.now(timezone.utc)
        await db.execute(
            update(Mailbox)
            .where(Mailbox.id == mailbox.id)
            .values(sent_today=Mailbox.sent_today + 1, last_used=now)
        )
        await db.commit()
        await db.refresh(mailbox)

        return mailbox

    except SQLAlchemyError:
        await db.rollback()
        logger.exception("DB error fetching next available mailbox | user=%s | mode=%s", user_id, sending_mode)
        return None

    except Exception:
        await db.rollback()
        logger.exception("Unexpected error fetching next available mailbox | user=%s | mode=%s", user_id, sending_mode)
        return None
