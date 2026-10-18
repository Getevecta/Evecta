"""
Thread Reply Service — send a reply to a specific lead from the inbox thread view.
"""
import uuid
import base64
import aiosmtplib
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.utils import formatdate

from fastapi import HTTPException
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_thread import EmailThread
from app.models.email_message import EmailMessage, MessageDirection
from app.models.mailbox import Mailbox, MailboxProvider
from app.models.lead import Lead
from app.models.campaign import Campaign
from app.services.google_gmail_token_service import google_access_token_plain, refresh_google_token
from app.core.http_client import mailbox_cycle_client
from app.utils.crypto import decrypt_secret


# ── Helpers ───────────────────────────────────────────────────────────────────

def _personalize(template: str, lead: Lead) -> str:
    """Replace {{ field }} placeholders with lead values for the reply subject."""
    content = template
    for attr, value in lead.__dict__.items():
        if not attr.startswith("_") and value is not None:
            content = content.replace(f"{{{{ {attr} }}}}", str(value))
    return content


async def _get_reply_mailbox(
    db: AsyncSession,
    latest_inbound: EmailMessage,
    user_id: uuid.UUID,
) -> Mailbox | None:
    """
    Pick the mailbox to send the reply from.

    Priority:
    1. The exact mailbox that received the lead's reply (has both IMAP + SMTP)
       Stored as latest_inbound.mailbox_id — set during reply fetch (Phase 3).
    2. User's Gmail mailbox (send via Gmail API).
    3. Any active system mailbox (least recently used — last resort).
    """
    # 1. Mailbox that received the inbound reply
    if latest_inbound.mailbox_id:
        mailbox = await db.get(Mailbox, latest_inbound.mailbox_id)
        if mailbox and mailbox.is_active:
            return mailbox

    # 2. User's Gmail mailbox
    gmail = await db.scalar(
        select(Mailbox).where(
            Mailbox.user_id == user_id,
            Mailbox.provider == MailboxProvider.GOOGLE,
            Mailbox.is_active == True,
        )
    )
    if gmail:
        return gmail

    # 3. Any active system mailbox (LRU)
    return await db.scalar(
        select(Mailbox)
        .where(Mailbox.user_id.is_(None), Mailbox.is_active == True)
        .order_by(Mailbox.last_used.asc())
    )


async def _send_smtp_reply(
    *,
    from_email: str,
    receive_email: str | None,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    to_email: str,
    subject: str,
    body: str,
    message_id: str,
    in_reply_to: str | None,
    references: str | None,
) -> None:
    """Send reply via SMTP with proper RFC822 threading headers."""
    msg = MIMEText(body, "html")
    msg["From"]       = from_email
    msg["To"]         = to_email
    msg["Subject"]    = subject
    msg["Message-ID"] = message_id
    msg["Date"]       = formatdate(localtime=True)

    # Ensure lead's next reply comes back to the receive mailbox (not SES which has no inbox)
    if receive_email:
        msg["Reply-To"] = receive_email

    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    await aiosmtplib.send(
        msg,
        hostname=smtp_host,
        port=smtp_port,
        username=smtp_user,
        password=smtp_password,
        use_tls=(smtp_port == 465),
        start_tls=(smtp_port != 465),
        timeout=90,
    )


async def _send_gmail_reply(
    *,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
    message_id: str,
    in_reply_to: str | None,
    references: str | None,
    access_token: str,
) -> None:
    """Send reply via Gmail API with proper RFC822 threading headers.

    Does not take a DB session — token refresh must happen before this call.
    """
    msg = MIMEText(body, "html")
    msg["From"]       = from_email
    msg["To"]         = to_email
    msg["Subject"]    = subject
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    client = mailbox_cycle_client()
    res = await client.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"raw": raw},
        timeout=90.0,
    )
    res.raise_for_status()


# ── Main entry point ──────────────────────────────────────────────────────────

async def send_thread_reply(
    *,
    thread_id: uuid.UUID,
    lead_id: uuid.UUID,
    user_id: uuid.UUID,
    body: str,
    db: AsyncSession,
) -> EmailMessage:
    """
    Send a reply to a specific lead inside a thread.

    Flow:
    1.  Validate thread ownership
    2.  Load lead + campaign
    3.  Get latest INBOUND message → its message_id becomes our In-Reply-To
    4.  Build RFC822 References chain (all prior message IDs, oldest first)
    5.  Generate parseable Message-ID: <EV-reply-{uuid}-{campaign_id}-{lead_id}@evecta>
        — so if the lead replies again, In-Reply-To parsing still works
    6.  Pick reply mailbox (exact receive mailbox → user Gmail → system fallback)
    7.  Commit/release the DB connection, then send via SMTP or Gmail API
    8.  Persist OUTBOUND EmailMessage
    9.  Update EmailThread.last_message_at
    """

    # ── 1–2. Thread, campaign, and lead in one ownership-scoped join ──────────
    row = (
        await db.execute(
            select(EmailThread, Campaign, Lead)
            .join(Campaign, Campaign.id == EmailThread.campaign_id)
            .join(Lead, and_(Lead.id == lead_id, Lead.user_id == user_id))
            .where(
                EmailThread.id == thread_id,
                EmailThread.user_id == user_id,
            )
        )
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Thread not found")

    thread, campaign, lead = row
    if not lead.email:
        raise HTTPException(status_code=404, detail="Lead not found or has no email")

    # ── 3. Get latest INBOUND from this lead ──────────────────────────────────
    latest_inbound = (
        await db.execute(
            select(EmailMessage)
            .where(
                EmailMessage.thread_id == thread_id,
                EmailMessage.lead_id   == lead_id,
                EmailMessage.direction == MessageDirection.INBOUND,
            )
            .order_by(EmailMessage.sent_at.desc())
        )
    ).scalars().first()

    if not latest_inbound:
        raise HTTPException(
            status_code=400,
            detail="No reply from this lead yet — nothing to respond to",
        )

    # ── 4. Build RFC822 References chain ─────────────────────────────────────
    # Collect all message IDs in this lead's conversation (oldest → newest)
    prior_msg_ids = (
        await db.execute(
            select(EmailMessage.message_id)
            .where(
                EmailMessage.thread_id  == thread_id,
                EmailMessage.lead_id    == lead_id,
                EmailMessage.message_id.isnot(None),
            )
            .order_by(EmailMessage.sent_at.asc())
        )
    ).scalars().all()

    references_chain = " ".join(mid for mid in prior_msg_ids if mid)

    # ── 5. Generate parseable reply Message-ID ────────────────────────────────
    new_message_id = f"<EV-reply-{uuid.uuid4()}-{thread.campaign_id}-{lead_id}@evecta>"

    # ── 6. Build subject ──────────────────────────────────────────────────────
    base_subject  = _personalize(campaign.email_subject or "", lead)
    reply_subject = base_subject if base_subject.lower().startswith("re:") else f"Re: {base_subject}"

    # ── 7. Pick reply mailbox ─────────────────────────────────────────────────
    reply_mailbox = await _get_reply_mailbox(db, latest_inbound, user_id)
    if not reply_mailbox:
        raise HTTPException(
            status_code=503,
            detail="No available mailbox to send reply from",
        )

    google_access_token = None
    smtp_host = reply_mailbox.smtp_host
    smtp_port = reply_mailbox.port
    smtp_user = reply_mailbox.smtp_user
    smtp_password = ""
    receive_email = reply_mailbox.receive_email
    if reply_mailbox.provider == MailboxProvider.GOOGLE:
        if (
            reply_mailbox.google_token_expires_at is None
            or reply_mailbox.google_token_expires_at
            <= datetime.now(timezone.utc) + timedelta(minutes=2)
        ):
            await refresh_google_token(mailbox=reply_mailbox, db=db)
        google_access_token = google_access_token_plain(reply_mailbox)
    elif reply_mailbox.smtp_pass:
        smtp_password = decrypt_secret(reply_mailbox.smtp_pass)

    lead_email = lead.email
    inbound_message_id = latest_inbound.message_id
    campaign_id = thread.campaign_id
    mailbox_id = reply_mailbox.id
    mailbox_email = reply_mailbox.email
    mailbox_provider = reply_mailbox.provider

    # Release the pool connection before the (up to 90s) provider wait.
    await db.commit()

    # ── 8. Send ───────────────────────────────────────────────────────────────
    try:
        if mailbox_provider == MailboxProvider.GOOGLE:
            await _send_gmail_reply(
                from_email = mailbox_email,
                to_email   = lead_email,
                subject    = reply_subject,
                body       = body,
                message_id = new_message_id,
                in_reply_to = inbound_message_id,
                references  = references_chain,
                access_token = google_access_token,
            )
        else:
            await _send_smtp_reply(
                from_email = mailbox_email,
                receive_email = receive_email,
                smtp_host  = smtp_host,
                smtp_port  = smtp_port,
                smtp_user  = smtp_user,
                smtp_password = smtp_password,
                to_email   = lead_email,
                subject    = reply_subject,
                body       = body,
                message_id = new_message_id,
                in_reply_to = inbound_message_id,
                references  = references_chain,
            )
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to send reply. Please try again.")

    # ── 9. Persist OUTBOUND EmailMessage ──────────────────────────────────────
    now = datetime.now(timezone.utc)
    out_message = EmailMessage(
        thread_id       = thread_id,
        lead_id         = lead_id,
        campaign_id     = campaign_id,
        direction       = MessageDirection.OUTBOUND,
        sender_email    = mailbox_email,
        recipient_email = lead_email,
        body            = body,
        message_id      = new_message_id,
        in_reply_to     = inbound_message_id,
        references      = references_chain,
        sent_at         = now,
        is_read         = True,
        mailbox_id      = mailbox_id,
    )
    db.add(out_message)

    # ── 10. Update thread timestamp ───────────────────────────────────────────
    # Note: unread_reply_count is NOT incremented — this is our outbound message,
    # not a new inbound reply from the lead.
    await db.execute(
        update(EmailThread)
        .where(EmailThread.id == thread_id)
        .values(last_message_at=now)
    )

    await db.commit()
    await db.refresh(out_message)
    return out_message
