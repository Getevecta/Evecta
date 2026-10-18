import base64
import email
import logging
import re
import httpx

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from email.utils import parseaddr
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from email_reply_parser import EmailReplyParser

from app.services.google_gmail_token_service import google_access_token_plain, refresh_google_token
from app.core.http_client import mailbox_cycle_client
from app.models.email_activity import EmailActivity
from app.models.email_thread import EmailThread
from app.models.email_message import EmailMessage, MessageDirection
from app.utils.bounce_detector import (
    find_activity_for_bounce,
    is_bounce_headers,
)
from app.services.email_event_service import EVENT_BOUNCE, apply_email_event


# ── Regex helpers ────────────────────────────────────────────────────────────

TRACKING_REGEX = re.compile(r"ev=([\w-]+)\|([\w-]+)\|([\w-]+)")

_UUID_PAT = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
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


def get_gmail_header(headers: list, name: str) -> str:
    """Extract a header value from Gmail API payload.headers list."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "").strip()
    return ""


def decode_gmail_payload(payload: dict) -> str:
    """Extract plain text body from Gmail payload."""
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    return base64.urlsafe_b64decode(data).decode(errors="ignore")

    data = payload.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data).decode(errors="ignore")

    return ""


# ── Core Gmail fetch ──────────────────────────────────────────────────────────

async def fetch_gmail_replies(*, db: AsyncSession, mailbox, client: httpx.AsyncClient | None = None):
    """
    Fetch unread Gmail replies for a user mailbox.

    Reuse *client* for every API call in this mailbox cycle (list / get / raw /
    modify). Callers should pass mailbox_cycle_client() once per mailbox.
    """
    try:
        client = client or mailbox_cycle_client()
        # Refresh token if expired
        if mailbox.google_token_expires_at <= datetime.now(timezone.utc):
            await refresh_google_token(mailbox=mailbox, db=db)

        headers = {"Authorization": f"Bearer {google_access_token_plain(mailbox)}"}

        res = await client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=headers,
            params={"q": "is:unread", "maxResults": 20},
        )

        if res.status_code != 200:
            return

        messages = res.json().get("messages", [])

        for msg in messages:
            gmail_msg_id = msg["id"]

            try:
                msg_res = await client.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{gmail_msg_id}",
                    headers=headers,
                    params={"format": "full"},
                )

                msg_data    = msg_res.json()
                payload     = msg_data.get("payload", {})
                msg_headers = payload.get("headers", [])
                body        = decode_gmail_payload(payload)

                # ── Bounce DSN (same as SES Bounce — no soft/hard split) ────
                # Check before empty-body skip: DSNs often have no text/plain part.
                from_hdr = get_gmail_header(msg_headers, "From")
                content_type = get_gmail_header(msg_headers, "Content-Type")
                if is_bounce_headers(from_hdr, content_type):
                    try:
                        raw_res = await client.get(
                            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{gmail_msg_id}",
                            headers=headers,
                            params={"format": "raw"},
                        )
                        raw_b64 = (raw_res.json() or {}).get("raw") if raw_res.status_code == 200 else None
                        if raw_b64:
                            bounce_msg = email.message_from_bytes(
                                base64.urlsafe_b64decode(raw_b64)
                            )
                            activity = await find_activity_for_bounce(db, bounce_msg, mailbox)
                            if activity:
                                apply_email_event(activity, EVENT_BOUNCE)
                                await db.commit()
                                logger.info(
                                    "[GMAIL] Bounce applied activity=%s campaign=%s lead=%s",
                                    activity.id,
                                    activity.campaign_id,
                                    activity.lead_id,
                                )
                            else:
                                logger.warning(
                                    "[GMAIL] Bounce DSN unmatched (gmail_msg_id=%s)",
                                    gmail_msg_id,
                                )
                        else:
                            logger.warning(
                                "[GMAIL] Bounce headers seen but raw MIME unavailable (gmail_msg_id=%s)",
                                gmail_msg_id,
                            )
                    except Exception as e:
                        logger.error(f"[GMAIL BOUNCE ERROR] gmail_msg_id={gmail_msg_id}: {e}")
                    continue

                if not body:
                    continue

                # ── Match: In-Reply-To (primary) → DB lookup → References → tracking token ─

                in_reply_to_header = get_gmail_header(msg_headers, "In-Reply-To")
                references_header  = get_gmail_header(msg_headers, "References")
                lead_message_id    = get_gmail_header(msg_headers, "Message-ID")
                sender_from        = from_hdr or get_gmail_header(msg_headers, "From")

                # Our own outbound mail also matches below (its body carries the
                # tracking token), so a campaign match alone doesn't prove a reply.
                # A message whose own Message-ID is one we generated is our send.
                if lead_message_id and IN_REPLY_TO_REGEX.search(lead_message_id):
                    logger.info(f"[GMAIL] Skipping own outbound message {lead_message_id}")
                    continue

                if lead_message_id:
                    own_outbound = await db.scalar(
                        select(EmailMessage.id).where(
                            EmailMessage.message_id == lead_message_id,
                            EmailMessage.direction == MessageDirection.OUTBOUND,
                        )
                    )
                    if own_outbound:
                        logger.info(f"[GMAIL] Skipping message already stored as outbound: {lead_message_id}")
                        continue

                campaign_id_str = None
                lead_id_str     = None

                # Priority 1 — parse our Message-ID from In-Reply-To header
                if in_reply_to_header:
                    campaign_id_str, lead_id_str = extract_ids_from_in_reply_to(in_reply_to_header)
                    if campaign_id_str:
                        logger.info(f"[GMAIL] In-Reply-To match → campaign={campaign_id_str}, lead={lead_id_str}")

                # Priority 2 — DB lookup by message_id == In-Reply-To
                # Handles replies to our system replies when Gmail reassigns Message-ID
                if not campaign_id_str and in_reply_to_header:
                    stored = await db.scalar(
                        select(EmailMessage).where(EmailMessage.message_id == in_reply_to_header)
                    )
                    if stored:
                        campaign_id_str = str(stored.campaign_id)
                        lead_id_str     = str(stored.lead_id)
                        logger.info(f"[GMAIL] DB message_id match → campaign={campaign_id_str}, lead={lead_id_str}")

                # Priority 3 — scan References header (full thread chain)
                if not campaign_id_str and references_header:
                    ref_ids = re.findall(r'<[^>]+>', references_header)
                    for ref_id in ref_ids:
                        campaign_id_str, lead_id_str = extract_ids_from_in_reply_to(ref_id)
                        if campaign_id_str:
                            logger.info(f"[GMAIL] References regex match → campaign={campaign_id_str}, lead={lead_id_str}")
                            break
                    if not campaign_id_str:
                        for ref_id in ref_ids:
                            stored = await db.scalar(
                                select(EmailMessage).where(EmailMessage.message_id == ref_id)
                            )
                            if stored:
                                campaign_id_str = str(stored.campaign_id)
                                lead_id_str     = str(stored.lead_id)
                                logger.info(f"[GMAIL] DB references match → campaign={campaign_id_str}, lead={lead_id_str}")
                                break

                # Priority 4 — tracking token in quoted body (last resort)
                if not campaign_id_str:
                    token_match = TRACKING_REGEX.search(body)
                    if token_match:
                        campaign_id_str = token_match.group(1)
                        lead_id_str     = token_match.group(2)
                        logger.info(f"[GMAIL] Token match → campaign={campaign_id_str}, lead={lead_id_str}")

                if not campaign_id_str or not lead_id_str:
                    logger.warning(f"[GMAIL] ⚠️ Could not match gmail_msg_id={gmail_msg_id}. Skipping.")
                    continue

                # ── Resolve UUIDs ──────────────────────────────────────────
                import uuid as uuid_lib
                try:
                    campaign_uuid = uuid_lib.UUID(campaign_id_str)
                    lead_uuid     = uuid_lib.UUID(lead_id_str)
                except ValueError:
                    logger.error(f"[GMAIL] Invalid UUID in match: campaign={campaign_id_str}, lead={lead_id_str}")
                    continue

                # ── Find EmailActivity ─────────────────────────────────────
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
                    logger.info(f"[GMAIL] No EmailActivity for campaign={campaign_uuid}, lead={lead_uuid}")
                    continue

                # Secondary self-mail guard: a message From the identity the
                # campaign was sent from is our own send threaded back into
                # the inbox, not a lead reply.
                sender_addr = parseaddr(sender_from)[1].lower()
                if sender_addr and sender_addr == (activity.sent_from or "").lower():
                    logger.info(f"[GMAIL] Skipping message from our own sender {sender_addr}")
                    continue

                # ── Parse + clean reply body ───────────────────────────────
                try:
                    parsed_reply = EmailReplyParser.parse_reply(body).strip()
                except Exception:
                    parsed_reply = body[:2000]

                # ── Store reply ────────────────────────────────────────────
                now = datetime.now(timezone.utc)

                # Find EmailThread for this campaign
                thread = await db.scalar(
                    select(EmailThread).where(EmailThread.campaign_id == campaign_uuid)
                )

                if thread:
                    # Dedup: this message may already be stored — re-fetches happen
                    # when the UNREAD label can't be removed or the user re-syncs.
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
                        logger.info(f"[GMAIL] Inbound message {lead_message_id} already stored — skipping")
                    else:
                        # ON CONFLICT DO NOTHING closes the race between concurrent
                        # fetches (arbitrated by the partial unique inbound index)
                        insert_stmt = (
                            pg_insert(EmailMessage)
                            .values(
                                thread_id         = thread.id,
                                lead_id           = lead_uuid,
                                campaign_id       = campaign_uuid,
                                direction         = MessageDirection.INBOUND,
                                sender_email      = sender_from,
                                recipient_email   = mailbox.email,
                                body              = parsed_reply,
                                message_id        = lead_message_id or None,
                                in_reply_to       = in_reply_to_header or None,
                                sent_at           = now,
                                is_read           = False,
                                mailbox_id        = mailbox.id,
                                email_activity_id = activity.id,
                            )
                            .on_conflict_do_nothing()
                            .returning(EmailMessage.id)
                        )
                        inserted_id = (await db.execute(insert_stmt)).scalar_one_or_none()

                        if inserted_id is not None:
                            # Only a genuinely new reply updates analytics + unread count
                            activity.replied      = True
                            activity.replied_at   = now
                            activity.reply_text   = parsed_reply
                            activity.replied_from = mailbox.email
                            db.add(activity)

                            await db.execute(
                                update(EmailThread)
                                .where(EmailThread.id == thread.id)
                                .values(
                                    last_message_at    = now,
                                    unread_reply_count = EmailThread.__table__.c.unread_reply_count + 1,
                                )
                            )
                        else:
                            logger.info(f"[GMAIL] Inbound message {lead_message_id} lost insert race — skipping")
                else:
                    logger.warning(f"[GMAIL] ⚠️ No EmailThread for campaign {campaign_uuid} — activity updated, message not threaded")
                    activity.replied      = True
                    activity.replied_at   = now
                    activity.reply_text   = parsed_reply
                    activity.replied_from = mailbox.email
                    db.add(activity)

                await db.commit()

                # Mark Gmail message as read so the next fetch skips it
                modify_res = await client.post(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{gmail_msg_id}/modify",
                    headers=headers,
                    json={"removeLabelIds": ["UNREAD"]},
                )
                if modify_res.status_code != 200:
                    logger.warning(
                        f"[GMAIL] Could not mark message {gmail_msg_id} as read "
                        f"(HTTP {modify_res.status_code}) — mailbox likely connected "
                        f"without gmail.modify scope; reconnect the account"
                    )

            except (httpx.HTTPError, SQLAlchemyError):
                await db.rollback()
                continue

            except Exception:
                await db.rollback()
                continue

    except SQLAlchemyError:
        await db.rollback()

    except httpx.HTTPError:
        return

    except Exception:
        await db.rollback()
