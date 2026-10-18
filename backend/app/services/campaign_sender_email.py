"""Resolve the From address shown for USER-mode campaigns (own Gmail/IMAP)."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Union
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums.email_sending_mode import EmailSendingMode
from app.models.email_activity import EmailActivity
from app.models.mailbox import Mailbox, MailboxType


def _mode_is_user(mode) -> bool:
    if mode is None:
        return False
    if isinstance(mode, EmailSendingMode):
        return mode == EmailSendingMode.USER
    return str(mode).upper() == EmailSendingMode.USER.value


async def _fallback_user_mailbox_email(
    db: AsyncSession,
    user_id: Union[UUID, str],
) -> Optional[str]:
    email = await db.scalar(
        select(Mailbox.email)
        .where(
            Mailbox.user_id == user_id,
            Mailbox.mailbox_type == MailboxType.USER,
            Mailbox.is_active.is_(True),
        )
        .order_by(Mailbox.last_used.desc())
        .limit(1)
    )
    return email or None


async def resolve_campaign_sender_email(
    db: AsyncSession,
    *,
    campaign_id: Union[UUID, str],
    user_id: Union[UUID, str],
    email_sending_mode,
) -> Optional[str]:
    """
    Return the mailbox address used for a USER-mode campaign.
    SYSTEM / unset → None (UI should hide From).
    Prefers actual EmailActivity.sent_from; falls back to the user's latest mailbox.
    """
    if not _mode_is_user(email_sending_mode):
        return None

    rows = (
        await db.execute(
            select(EmailActivity.sent_from)
            .where(
                EmailActivity.campaign_id == campaign_id,
                EmailActivity.sent_from.isnot(None),
                EmailActivity.sent_from != "",
            )
            .distinct()
        )
    ).scalars().all()

    emails = [e.strip() for e in rows if e and str(e).strip()]
    if emails:
        # Stable order for display when multiple user mailboxes were used
        return ", ".join(sorted(set(emails), key=str.lower))

    return await _fallback_user_mailbox_email(db, user_id)


async def resolve_campaign_sender_emails_batch(
    db: AsyncSession,
    *,
    user_id: Union[UUID, str],
    campaigns: Iterable,
) -> Dict[str, Optional[str]]:
    """
    Batch-resolve sender_email for a list of campaign ORM objects / dicts
    that expose `.id` and `.email_sending_mode`.
    """
    campaigns_list = list(campaigns)
    result: Dict[str, Optional[str]] = {
        str(getattr(c, "id")): None for c in campaigns_list
    }

    user_campaign_ids: List[UUID] = []
    for c in campaigns_list:
        if _mode_is_user(getattr(c, "email_sending_mode", None)):
            cid = getattr(c, "id")
            user_campaign_ids.append(cid if isinstance(cid, UUID) else UUID(str(cid)))

    if not user_campaign_ids:
        return result

    rows = (
        await db.execute(
            select(EmailActivity.campaign_id, EmailActivity.sent_from)
            .where(
                EmailActivity.campaign_id.in_(user_campaign_ids),
                EmailActivity.sent_from.isnot(None),
                EmailActivity.sent_from != "",
            )
            .distinct()
        )
    ).all()

    by_campaign: Dict[str, set[str]] = {}
    for campaign_id, sent_from in rows:
        if not sent_from or not str(sent_from).strip():
            continue
        key = str(campaign_id)
        by_campaign.setdefault(key, set()).add(str(sent_from).strip())

    fallback = None
    need_fallback = any(str(cid) not in by_campaign for cid in user_campaign_ids)
    if need_fallback:
        fallback = await _fallback_user_mailbox_email(db, user_id)

    for cid in user_campaign_ids:
        key = str(cid)
        emails = by_campaign.get(key)
        if emails:
            result[key] = ", ".join(sorted(emails, key=str.lower))
        else:
            result[key] = fallback

    return result
