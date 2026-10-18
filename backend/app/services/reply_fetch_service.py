import email
import logging
import uuid as uuid_lib
import aioimaplib

logger = logging.getLogger(__name__)
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime, timezone
from email.utils import parseaddr
import traceback
from email_reply_parser import EmailReplyParser
from app.models.email_activity import EmailActivity
from app.models.email_thread import EmailThread
from app.models.email_message import EmailMessage, MessageDirection
from app.models.mailbox import Mailbox
from app.models.mailbox import MailboxProvider
from app.core.http_client import mailbox_cycle_client
from app.services.gmail_reply_fetch_service import fetch_gmail_replies
from app.utils.crypto import decrypt_secret
from app.utils.bounce_detector import find_activity_for_bounce, is_bounce_message
from app.services.email_event_service import EVENT_BOUNCE, apply_email_event


# ── Regex helpers ────────────────────────────────────────────────────────────

TRACKING_REGEX = re.compile(r"ev=([\w-]+)\|([\w-]+)\|([\w-]+)")

_UUID_PAT = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# Matches <EV-{rand_uuid}-{campaign_id}-{lead_id}@evecta>
# and     <EV-reply-{rand_uuid}-{campaign_id}-{lead_id}@evecta>
IN_REPLY_TO_REGEX = re.compile(
    rf"<EV-(?:reply-)?{_UUID_PAT}-({_UUID_PAT})-({_UUID_PAT})@evecta>",
    re.IGNORECASE,
)


def extract_ids_from_in_reply_to(in_reply_to: str):
    """
    Parse campaign_id and lead_id from our custom Message-ID format.
    Returns (campaign_id_str, lead_id_str) or (None, None).
    """
    match = IN_REPLY_TO_REGEX.search(in_reply_to)
    if match:
        return match.group(1), match.group(2)
    return None, None


# ── Email parsing helpers ─────────────────────────────────────────────────────

def hard_trim_reply(text: str) -> str:
    """
    Aggressively keep ONLY the user's reply.
    Everything below common reply markers is removed.
    """
    lines = text.splitlines()
    cleaned = []

    for line in lines:
        stripped = line.strip()

        if re.search(r'on .* wrote:', stripped, re.IGNORECASE):
            break
        if stripped.startswith(">"):
            break
        if "ev=" in stripped:
            break
        if stripped.lower().startswith(("from:", "sent:", "to:", "subject:")):
            break
        if "unsubscribe" in stripped.lower():
            break

        cleaned.append(line)

    final = []
    for line in cleaned:
        line = line.strip()
        if line and line not in final:
            final.append(line)

    return "\n".join(final).strip()


def extract_body_text(msg):
    """Extract plain text or HTML body from an email."""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    return part.get_payload(decode=True).decode(errors="ignore")
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    html = part.get_payload(decode=True).decode(errors="ignore")
                    return html.replace("<br>", "\n").replace("<BR>", "\n")
        return msg.get_payload(decode=True).decode(errors="ignore")
    except Exception as e:
        logger.error(f"[BODY EXTRACTION ERROR] {e}")
        return ""


def normalize_reply_text(text: str) -> str:
    """Prepare text so EmailReplyParser works correctly."""
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Core IMAP fetch ───────────────────────────────────────────────────────────

async def fetch_replies_for_mailbox(db: AsyncSession, mailbox: Mailbox):

    if mailbox.can_receive:
        username = mailbox.receive_username
        password = decrypt_secret(mailbox.receive_password)
        imap_host = mailbox.imap_host
        imap_port = mailbox.imap_port
    else:
        username = mailbox.email
        password = decrypt_secret(mailbox.smtp_pass)
        imap_host = getattr(mailbox, "imap_host", "imap.mxroute.com")
        imap_port = getattr(mailbox, "imap_port", 993)

    logger.info(f"[IMAP] Connecting to {imap_host}:{imap_port} for {username}")

    # Connect
    try:
        client = aioimaplib.IMAP4_SSL(imap_host, imap_port)
        await client.wait_hello_from_server()
    except Exception as e:
        logger.error(f"[IMAP ERROR] Could not connect: {e}")
        traceback.print_exc()
        return

    # Login
    try:
        resp = await client.login(username, password)
        if "OK" not in str(resp).upper():
            logger.error(f"[IMAP] Login failed → {resp}")
            return
    except Exception as e:
        logger.error(f"[IMAP LOGIN ERROR] {e}")
        traceback.print_exc()
        return

    # Select INBOX
    try:
        await client.select("INBOX")
    except Exception as e:
        logger.error(f"[IMAP ERROR] Could not select INBOX: {e}")
        traceback.print_exc()
        await client.logout()
        return

    # Get unread messages
    try:
        _, data = await client.search("UNSEEN")
        if not data or not data[0]:
            logger.info(f"[IMAP] No unread messages in {username}")
            await client.logout()
            return
    except Exception as e:
        logger.error(f"[IMAP ERROR] Could not search UNSEEN: {e}")
        traceback.print_exc()
        await client.logout()
        return

    msg_ids = data[0].decode().split()
    logger.info(f"[IMAP] {len(msg_ids)} unread messages found.")

    for msg_id in msg_ids:
        try:
            _, msg_data = await client.fetch(msg_id, "(RFC822)")
        except Exception as e:
            logger.error(f"[IMAP ERROR] Could not fetch msg_id {msg_id}: {e}")
            traceback.print_exc()
            continue

        # ── Extract raw bytes ───────────────────────────────────────────────
        raw_email = None
        try:
            for part in msg_data:
                if isinstance(part, tuple):
                    for item in part:
                        if isinstance(item, (bytes, bytearray)):
                            raw_email = bytes(item)
                            break

            if raw_email is None:
                for part in msg_data:
                    if isinstance(part, bytearray):
                        raw_email = bytes(part)
                        break

            if raw_email is None:
                combined = b"".join(
                    p for p in msg_data if isinstance(p, (bytes, bytearray))
                )
                if combined:
                    raw_email = combined

            if raw_email is None:
                logger.error(f"[IMAP ERROR] Could not extract RFC822 payload for msg_id {msg_id}")
                continue

        except Exception as e:
            logger.error(f"[IMAP ERROR] Extracting raw email failed for msg_id {msg_id}: {e}")
            traceback.print_exc()
            continue

        # ── Parse message ───────────────────────────────────────────────────
        try:
            msg = email.message_from_bytes(raw_email)
            body = extract_body_text(msg) or ""

            if msg.is_multipart():
                all_text = body
                for part in msg.walk():
                    try:
                        if part.get_content_type() == "text/plain":
                            part_body = part.get_payload(decode=True)
                            if part_body:
                                all_text += "\n" + part_body.decode(errors="ignore")
                        elif part.get_content_type() == "text/html":
                            part_body = part.get_payload(decode=True)
                            if part_body:
                                html_text = part_body.decode(errors="ignore")
                                html_text = re.sub(r'<[^>]+>', '', html_text)
                                all_text += "\n" + html_text
                    except Exception:
                        pass
                body = all_text
        except Exception as e:
            logger.error(f"[EMAIL PARSING ERROR] msg_id {msg_id}: {e}")
            traceback.print_exc()
            continue

        # ── Bounce DSN (same as SES Bounce — no soft/hard split) ────────────
        # Intercept before reply-matching so a DSN is never treated as a lead reply.
        try:
            if is_bounce_message(msg):
                activity = await find_activity_for_bounce(db, msg, mailbox)
                if activity:
                    apply_email_event(activity, EVENT_BOUNCE)
                    await db.commit()
                    logger.info(
                        "[IMAP] Bounce applied activity=%s campaign=%s lead=%s",
                        activity.id,
                        activity.campaign_id,
                        activity.lead_id,
                    )
                else:
                    logger.warning(
                        "[IMAP] Bounce DSN could not be matched to an EmailActivity (msg_id=%s)",
                        msg_id,
                    )
                continue
        except Exception as e:
            logger.error(f"[IMAP BOUNCE ERROR] msg_id {msg_id}: {e}")
            traceback.print_exc()
            continue

        # ── Match: In-Reply-To header (primary) → DB lookup → References → tracking token ─
        try:
            in_reply_to_header = msg.get("In-Reply-To", "").strip()
            references_header  = msg.get("References", "").strip()
            lead_message_id    = msg.get("Message-ID", "").strip()
            sender_from        = msg.get("From", "").strip()

            # Our own outbound mail also matches below (its body carries the
            # tracking token), so a campaign match alone doesn't prove a reply.
            # A message whose own Message-ID is one we generated is our send.
            if lead_message_id and IN_REPLY_TO_REGEX.search(lead_message_id):
                logger.info(f"[IMAP] Skipping own outbound message {lead_message_id}")
                continue

            if lead_message_id:
                own_outbound = await db.scalar(
                    select(EmailMessage.id).where(
                        EmailMessage.message_id == lead_message_id,
                        EmailMessage.direction == MessageDirection.OUTBOUND,
                    )
                )
                if own_outbound:
                    logger.info(f"[IMAP] Skipping message already stored as outbound: {lead_message_id}")
                    continue

            campaign_id_str = None
            lead_id_str     = None

            # Priority 1 — parse our custom Message-ID from In-Reply-To
            if in_reply_to_header:
                campaign_id_str, lead_id_str = extract_ids_from_in_reply_to(in_reply_to_header)
                if campaign_id_str:
                    logger.info(f"[IMAP] In-Reply-To match → campaign={campaign_id_str}, lead={lead_id_str}")

            # Priority 2 — DB lookup by message_id == In-Reply-To
            # Handles replies to our system replies when Gmail/SES assigns their own Message-ID
            # (our stored message_id matches what SES actually sent)
            if not campaign_id_str and in_reply_to_header:
                stored = await db.scalar(
                    select(EmailMessage).where(EmailMessage.message_id == in_reply_to_header)
                )
                if stored:
                    campaign_id_str = str(stored.campaign_id)
                    lead_id_str     = str(stored.lead_id)
                    logger.info(f"[IMAP] DB message_id match → campaign={campaign_id_str}, lead={lead_id_str}")

            # Priority 3 — scan References header (full thread chain)
            if not campaign_id_str and references_header:
                ref_ids = re.findall(r'<[^>]+>', references_header)
                for ref_id in ref_ids:
                    campaign_id_str, lead_id_str = extract_ids_from_in_reply_to(ref_id)
                    if campaign_id_str:
                        logger.info(f"[IMAP] References regex match → campaign={campaign_id_str}, lead={lead_id_str}")
                        break
                if not campaign_id_str:
                    for ref_id in ref_ids:
                        stored = await db.scalar(
                            select(EmailMessage).where(EmailMessage.message_id == ref_id)
                        )
                        if stored:
                            campaign_id_str = str(stored.campaign_id)
                            lead_id_str     = str(stored.lead_id)
                            logger.info(f"[IMAP] DB references match → campaign={campaign_id_str}, lead={lead_id_str}")
                            break

            # Priority 4 — tracking token in quoted body (last resort)
            if not campaign_id_str:
                match = re.search(r"ev=([\w-]+)\|([\w-]+)\|([\w-]+)", body)
                if match:
                    campaign_id_str = match.group(1)
                    lead_id_str     = match.group(2)
                    logger.info(f"[IMAP] Token match → campaign={campaign_id_str}, lead={lead_id_str}")

            if not campaign_id_str or not lead_id_str:
                logger.warning(f"[IMAP] ⚠️ Could not match msg_id {msg_id} to any campaign/lead. Skipping.")
                continue

        except Exception as e:
            logger.error(f"[MATCH ERROR] msg_id {msg_id}: {e}")
            traceback.print_exc()
            continue

        # ── Resolve UUIDs ───────────────────────────────────────────────────
        try:
            campaign_uuid = uuid_lib.UUID(campaign_id_str)
            lead_uuid     = uuid_lib.UUID(lead_id_str)
        except ValueError as e:
            logger.error(f"[IMAP] Invalid UUID in match: {e}")
            continue

        # ── Find EmailActivity ──────────────────────────────────────────────
        try:
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

            if not activity:
                logger.info(f"[IMAP] No EmailActivity found for campaign={campaign_uuid}, lead={lead_uuid}")
                continue

        except Exception as e:
            logger.error(f"[DB ERROR] Could not fetch EmailActivity: {e}")
            traceback.print_exc()
            continue

        # Secondary self-mail guard: a message From the identity the campaign
        # was sent from is our own send, not a lead reply.
        sender_addr = parseaddr(sender_from)[1].lower()
        if sender_addr and sender_addr == (activity.sent_from or "").lower():
            logger.info(f"[IMAP] Skipping message from our own sender {sender_addr}")
            continue

        # ── Parse + clean reply body ────────────────────────────────────────
        try:
            normalized   = normalize_reply_text(body)
            parsed_reply = EmailReplyParser.parse_reply(normalized)
            clean_reply  = hard_trim_reply(parsed_reply)
        except Exception as e:
            logger.error(f"[PARSE ERROR] msg_id {msg_id}: {e}")
            clean_reply = body[:2000]  # safe fallback

        # ── Store reply ─────────────────────────────────────────────────────
        try:
            now = datetime.now(timezone.utc)

            # Find EmailThread for this campaign
            thread = await db.scalar(
                select(EmailThread).where(EmailThread.campaign_id == campaign_uuid)
            )

            if thread:
                # Dedup: this message may already be stored — re-fetches happen
                # when the mailbox re-syncs or a message stays unseen.
                duplicate_id = None
                if lead_message_id:
                    duplicate_id = await db.scalar(
                        select(EmailMessage.id).where(
                            EmailMessage.thread_id  == thread.id,
                            EmailMessage.lead_id    == lead_uuid,
                            EmailMessage.message_id == lead_message_id,
                            EmailMessage.direction  == MessageDirection.INBOUND,
                        )
                    )
                if duplicate_id is not None:
                    logger.info(f"[IMAP] Inbound message {lead_message_id} already stored — skipping")
                    continue

                # ON CONFLICT DO NOTHING closes the race between concurrent
                # fetches (arbitrated by the partial unique inbound index)
                insert_stmt = (
                    pg_insert(EmailMessage)
                    .values(
                        thread_id       = thread.id,
                        lead_id         = lead_uuid,
                        campaign_id     = campaign_uuid,
                        direction       = MessageDirection.INBOUND,
                        sender_email    = sender_from,
                        recipient_email = username,       # the receive mailbox address
                        body            = clean_reply,
                        message_id      = lead_message_id or None,   # lead's own Message-ID
                        in_reply_to     = in_reply_to_header or None,
                        sent_at         = now,
                        is_read         = False,
                        mailbox_id      = mailbox.id,
                        email_activity_id = activity.id,
                    )
                    .on_conflict_do_nothing()
                    .returning(EmailMessage.id)
                )
                inserted_id = (await db.execute(insert_stmt)).scalar_one_or_none()
                if inserted_id is None:
                    logger.info(f"[IMAP] Inbound message {lead_message_id} lost insert race — skipping")
                    await db.commit()
                    continue

                # Update thread: bump timestamp + unread counter
                await db.execute(
                    update(EmailThread)
                    .where(EmailThread.id == thread.id)
                    .values(
                        last_message_at   = now,
                        unread_reply_count = EmailThread.__table__.c.unread_reply_count + 1,
                    )
                )
            else:
                logger.warning(f"[IMAP] ⚠️ No EmailThread for campaign {campaign_uuid} — activity updated, message not threaded")

            # Update EmailActivity (backward compat — all analytics unchanged);
            # only reached for genuinely new replies, so no double-count
            was_already_replied = activity.replied
            activity.replied      = True
            activity.replied_at   = now
            activity.reply_text   = clean_reply
            activity.replied_from = username
            db.add(activity)

            await db.commit()

            if was_already_replied:
                logger.info(f"[IMAP] Updated existing reply for lead {lead_uuid}")
            else:
                logger.info(f"[IMAP] New reply stored for lead {lead_uuid}")

        except Exception as e:
            logger.error(f"[DB ERROR] Could not store reply for lead {lead_uuid}: {e}")
            traceback.print_exc()
            await db.rollback()
            continue

    try:
        await client.logout()
        logger.info(f"[IMAP] Logout complete for {username}")
    except Exception as e:
        logger.error(f"[IMAP ERROR] Logout failed for {username}: {e}")
        traceback.print_exc()


# ── Scheduler entry points ────────────────────────────────────────────────────

async def fetch_replies_for_all_mailboxes(db: AsyncSession):
    """
    Background scheduler:
    Fetch replies for all active system mailboxes (user_id IS NULL).
    """
    try:
        mailboxes = (
            await db.scalars(
                select(Mailbox).where(
                    Mailbox.user_id.is_(None),
                    Mailbox.is_active.is_(True),
                )
            )
        ).all()
    except Exception as e:
        logger.error(f"[DB ERROR] Could not fetch system mailboxes: {e}")
        traceback.print_exc()
        return

    if not mailboxes:
        logger.info("[IMAP] No system mailboxes found")
        return

    for mailbox in mailboxes:
        try:
            logger.info(mailbox.email)
            await fetch_replies_for_mailbox(db, mailbox)
        except Exception as e:
            logger.error(f"[IMAP ERROR] {mailbox.email}: {e}")
            traceback.print_exc()


async def fetch_replies_for_user_mailboxes(db: AsyncSession, user_id: str):
    """
    API-triggered fetch for a single user's mailboxes.
    """
    try:
        mailboxes = (
            await db.scalars(
                select(Mailbox).where(
                    Mailbox.user_id == user_id,
                    Mailbox.is_active.is_(True),
                )
            )
        ).all()
    except Exception as e:
        logger.error(f"[DB ERROR] Could not fetch user mailboxes: {e}")
        traceback.print_exc()
        return

    if not mailboxes:
        logger.info(f"[IMAP] No mailboxes found for user {user_id}")
        return

    for mailbox in mailboxes:
        try:
            if mailbox.provider == MailboxProvider.GOOGLE:
                logger.info(f"[GMAIL] Fetching replies for {mailbox.email}")
                await fetch_gmail_replies(
                    db=db,
                    mailbox=mailbox,
                    client=mailbox_cycle_client(),
                )
            else:
                logger.info(f"[IMAP] Fetching replies for {mailbox.email}")
                await fetch_replies_for_mailbox(db, mailbox)
        except Exception as e:
            logger.error(f"[IMAP ERROR] {mailbox.email}: {e}")
            traceback.print_exc()
