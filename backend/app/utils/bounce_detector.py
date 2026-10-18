"""Detect Delivery Status Notifications (bounce DSNs) for user-connected mailboxes.

SES Bounce webhooks call ``apply_email_event(activity, "bounce")`` with no soft/hard
split — this module mirrors that simplicity for IMAP/Gmail DSN replies.
"""

from __future__ import annotations

import logging
import re
from email.message import Message
from email.utils import parseaddr
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_activity import EmailActivity

logger = logging.getLogger(__name__)

# Same pattern as reply_fetch_service.IN_REPLY_TO_REGEX — imported lazily in
# extract_bounce_ids to avoid circular imports with the reply-fetch modules.

_DAEMON_LOCALPARTS = frozenset(
    {
        "mailer-daemon",
        "mailerdaemon",
        "postmaster",
        "mail-daemon",
        "maildaemon",
    }
)

_FINAL_RECIPIENT_RE = re.compile(
    r"final-recipient:\s*(?:rfc822\s*;\s*)?([^\s;]+)",
    re.IGNORECASE,
)
_ORIGINAL_RECIPIENT_RE = re.compile(
    r"original-recipient:\s*(?:rfc822\s*;\s*)?([^\s;]+)",
    re.IGNORECASE,
)


def is_bounce_headers(from_header: str | None, content_type: str | None) -> bool:
    """Header-only bounce check (useful before fetching Gmail raw MIME)."""
    _, addr = parseaddr(from_header or "")
    local = (addr.split("@", 1)[0] if addr else "").strip().lower()
    if local in _DAEMON_LOCALPARTS:
        return True

    ct = (content_type or "").lower().replace(" ", "")
    if "multipart/report" in ct and "report-type=delivery-status" in ct:
        return True
    # Some parsers put report-type only as a structured param
    if "multipart/report" in ct and "delivery-status" in ct:
        return True
    return False


def is_bounce_message(msg: Message) -> bool:
    """
    True when this message is a bounce / DSN.

    Matches mailer-daemon@ / postmaster@ senders, or
    Content-Type: multipart/report; report-type=delivery-status.
    """
    if is_bounce_headers(msg.get("From"), msg.get("Content-Type")):
        return True
    try:
        ctype = (msg.get_content_type() or "").lower()
        report_type = msg.get_param("report-type")
        if isinstance(report_type, tuple):
            report_type = report_type[0]
        if ctype == "multipart/report" and str(report_type or "").lower() == "delivery-status":
            return True
    except Exception:
        pass
    return False


def _iter_part_payloads(msg: Message) -> list[str]:
    """Collect decoded text from interesting DSN / attached-header parts."""
    texts: list[str] = []
    interesting = {
        "message/delivery-status",
        "text/rfc822-headers",
        "message/rfc822-headers",
        "message/rfc822",
        "text/plain",
    }

    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            if ctype not in interesting and not ctype.startswith("message/"):
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    # Nested message as Message object
                    nested = part.get_payload()
                    if isinstance(nested, list):
                        for item in nested:
                            if isinstance(item, Message):
                                texts.append(item.as_string())
                    elif isinstance(nested, Message):
                        texts.append(nested.as_string())
                    elif isinstance(nested, str):
                        texts.append(nested)
                    continue
                if isinstance(payload, bytes):
                    texts.append(payload.decode(errors="ignore"))
                elif isinstance(payload, str):
                    texts.append(payload)
            except Exception:
                continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                texts.append(payload.decode(errors="ignore"))
            elif isinstance(payload, str):
                texts.append(payload)
        except Exception:
            pass

    # Always include full serialized message as a last-resort search surface
    try:
        texts.append(msg.as_string())
    except Exception:
        pass

    return texts


def extract_bounce_ids(msg: Message) -> Optional[Tuple[str, str]]:
    """
    Pull campaign_id / lead_id from our ``<EV-...@evecta>`` Message-ID embedded
    in the DSN's original-message headers (message/rfc822-headers, etc.).

    Returns ``(campaign_id, lead_id)`` strings or ``None``.
    """
    # Lazy import avoids circular dependency with reply_fetch_service
    from app.services.reply_fetch_service import IN_REPLY_TO_REGEX

    for blob in _iter_part_payloads(msg):
        match = IN_REPLY_TO_REGEX.search(blob)
        if match:
            return match.group(1), match.group(2)
    return None


def extract_final_recipient(msg: Message) -> Optional[str]:
    """Parse Final-Recipient / Original-Recipient from a delivery-status part."""
    for blob in _iter_part_payloads(msg):
        for pattern in (_FINAL_RECIPIENT_RE, _ORIGINAL_RECIPIENT_RE):
            m = pattern.search(blob)
            if m:
                addr = parseaddr(m.group(1).strip())[1].strip().lower()
                if addr and "@" in addr:
                    return addr
    return None


async def find_activity_for_bounce(
    db: AsyncSession,
    msg: Message,
    mailbox,
) -> Optional[EmailActivity]:
    """
    Resolve the EmailActivity that bounced.

    1. Prefer campaign/lead IDs from our embedded Message-ID in the DSN.
    2. Fallback: Final-Recipient matched to the most recent activity for this
       mailbox's sent_from / user when original headers were stripped.
    """
    ids = extract_bounce_ids(msg)
    if ids:
        campaign_id_str, lead_id_str = ids
        try:
            campaign_uuid = UUID(campaign_id_str)
            lead_uuid = UUID(lead_id_str)
        except ValueError:
            logger.warning(
                "[BOUNCE] Invalid UUIDs in DSN Message-ID: campaign=%s lead=%s",
                campaign_id_str,
                lead_id_str,
            )
        else:
            activity = (
                await db.execute(
                    select(EmailActivity)
                    .where(
                        EmailActivity.campaign_id == campaign_uuid,
                        EmailActivity.lead_id == lead_uuid,
                    )
                    .order_by(EmailActivity.sent_at.desc())
                )
            ).scalars().first()
            if activity:
                return activity
            logger.info(
                "[BOUNCE] No EmailActivity for campaign=%s lead=%s",
                campaign_uuid,
                lead_uuid,
            )

    recipient = extract_final_recipient(msg)
    if not recipient:
        return None

    mailbox_email = (getattr(mailbox, "email", None) or "").strip().lower()
    user_id = getattr(mailbox, "user_id", None)

    q = (
        select(EmailActivity)
        .where(EmailActivity.email == recipient)
        .order_by(EmailActivity.sent_at.desc())
    )
    if mailbox_email:
        q = q.where(EmailActivity.sent_from == mailbox_email)
    elif user_id is not None:
        q = q.where(EmailActivity.user_id == user_id)

    activity = (await db.execute(q)).scalars().first()
    if activity:
        logger.info(
            "[BOUNCE] Final-Recipient fallback matched activity=%s recipient=%s",
            activity.id,
            recipient,
        )
    return activity
