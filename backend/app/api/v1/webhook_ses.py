import base64
import json
import logging
import httpx
from datetime import datetime

logger = logging.getLogger(__name__)

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate
from fastapi import APIRouter, Request, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database.session import get_session
from app.models.email_activity import EmailActivity
from app.models.webhook_event import ProcessedWebhookEvent
from app.services.email_event_service import apply_email_event
from app.utils.open_classifier import OpenClassification, classify_open
from app.utils.sns_trust import (
    _is_trusted_sns_cert_url,
    _is_trusted_sns_host,
    parse_allowed_sns_topic_arns,
    sns_topic_is_permitted,
)
from app.utils.security_alert import record_sns_signature_failure

router = APIRouter(prefix="/webhook", tags=["SES Webhooks"])


def _build_sign_string(payload: dict) -> bytes:
    """
    Reconstruct the canonical string AWS signed.
    Fields and order differ by message type — follow AWS documentation exactly.
    """
    msg_type = payload.get("Type", "")
    if msg_type == "Notification":
        keys = ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"]
    else:
        # SubscriptionConfirmation / UnsubscribeConfirmation
        keys = ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"]

    parts = []
    for key in keys:
        if key in payload:
            parts.append(f"{key}\n{payload[key]}\n")
    return "".join(parts).encode("utf-8")


async def verify_sns_signature(payload: dict) -> None:
    """
    Verify the AWS SNS message signature.
    Raises HTTPException(403) if verification fails.
    """
    signing_cert_url = payload.get("SigningCertURL", "")
    signature_b64 = payload.get("Signature", "")

    if not signing_cert_url or not signature_b64:
        logger.warning("SNS payload missing SigningCertURL or Signature")
        await record_sns_signature_failure(reason="missing_fields")
        raise HTTPException(status_code=403, detail="Missing SNS signature fields")

    if not _is_trusted_sns_cert_url(signing_cert_url):
        logger.warning("SNS SigningCertURL not from trusted AWS domain: %s", signing_cert_url)
        await record_sns_signature_failure(
            reason="untrusted_cert_url",
            detail=signing_cert_url,
        )
        raise HTTPException(status_code=403, detail="Untrusted SNS certificate source")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(signing_cert_url)
            cert_pem = resp.content

        cert = load_pem_x509_certificate(cert_pem)
        public_key = cert.public_key()
        sign_string = _build_sign_string(payload)
        signature = base64.b64decode(signature_b64)

        public_key.verify(signature, sign_string, padding.PKCS1v15(), hashes.SHA1())  # noqa: S303 — AWS SNS uses SHA1
    except HTTPException:
        raise
    except Exception:
        logger.exception("SNS signature verification failed")
        await record_sns_signature_failure(reason="verify_failed")
        raise HTTPException(status_code=403, detail="SNS signature verification failed")


def is_sns_payload(payload: dict) -> bool:
    return payload.get("Type") in ("SubscriptionConfirmation", "Notification")


async def claim_processed_webhook_event(
    db: AsyncSession,
    event_id: str | None,
    event_type: str,
) -> bool:
    """Claim an SNS/Stripe-style event id. False means a replay of a known id."""
    if not event_id:
        return True
    claim = await db.execute(
        pg_insert(ProcessedWebhookEvent)
        .values(
            event_id=event_id,
            event_type=(event_type or "unknown")[:64],
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
    )
    await db.commit()
    return (claim.rowcount or 0) != 0


@router.post("/ses", status_code=status.HTTP_200_OK)
async def handle_ses_webhook(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """
    AWS SES → SNS webhook handler.

    Handles:
    - SNS subscription confirmation
    - SES delivery / bounce / complaint / open / click events

    IMPORTANT:
    - Matches emails using Message-ID header (provider-agnostic)
    - Updates existing EmailActivity (idempotent)
    """

    # ----------------------------
    # Parse incoming JSON
    # ----------------------------

    try:
        raw_body = await request.body()
    except Exception:
        logger.exception("Failed to read SES webhook request body")
        raise HTTPException(status_code=400, detail="Failed to read request body")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not is_sns_payload(payload):
        return {"status": "ignored_non_sns_payload"}

    # ----------------------------
    # Verify AWS SNS Signature
    # ----------------------------
    await verify_sns_signature(payload)

    # ----------------------------
    # Verify TopicArn allowlist
    # ----------------------------
    from app.core.config import get_settings as _get_settings
    _settings = _get_settings()
    if not sns_topic_is_permitted(payload.get("TopicArn"), _settings.SNS_ALLOWED_TOPIC_ARNS):
        if not parse_allowed_sns_topic_arns(_settings.SNS_ALLOWED_TOPIC_ARNS):
            logger.error("SNS_ALLOWED_TOPIC_ARNS is not configured — rejecting all SNS webhook traffic")
            raise HTTPException(status_code=403, detail="SNS webhook not configured")
        logger.warning("SNS TopicArn not in allowlist: %s", payload.get("TopicArn", ""))
        raise HTTPException(status_code=403, detail="Untrusted SNS topic")

    # ----------------------------
    # SNS Subscription Confirmation
    # ----------------------------
    if payload.get("Type") == "SubscriptionConfirmation":
        subscribe_url = payload.get("SubscribeURL")
        if not subscribe_url:
            raise HTTPException(
                status_code=400,
                detail="Missing SubscribeURL in SNS confirmation",
            )

        if not _is_trusted_sns_host(subscribe_url):
            logger.warning("SNS SubscribeURL not from trusted AWS domain: %s", subscribe_url)
            raise HTTPException(status_code=403, detail="Untrusted SNS SubscribeURL")

        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(subscribe_url)

        return {"status": "sns_subscription_confirmed"}

    # ----------------------------
    # Handle SES Notification
    # ----------------------------
    if payload.get("Type") != "Notification":
        return {"status": "ignored_non_notification"}

    try:
        ses_message = json.loads(payload["Message"])
    except (json.JSONDecodeError, KeyError):
        logger.exception("Failed to parse SES Message field | payload keys: %s", list(payload.keys()))
        raise HTTPException(status_code=400, detail="Invalid SES Message payload")

    event_type =  (
        ses_message.get("eventType")
        or ses_message.get("notificationType")
    )
    logger.info("SES webhook event: %s", event_type)
    mail_data = ses_message.get("mail", {})
    headers = mail_data.get("headers", [])

    # ----------------------------
    # Idempotency: claim the SNS MessageId before any side effects.
    # SNS delivers at-least-once, so duplicates are guaranteed eventually.
    # ----------------------------
    sns_message_id = payload.get("MessageId")
    claimed = await claim_processed_webhook_event(
        db,
        sns_message_id,
        f"ses:{event_type or 'unknown'}",
    )
    if not claimed:
        return {"status": "duplicate_sns_event"}

    # ----------------------------
    # Identify the EmailActivity.
    # Primary key: the AWS-assigned MessageId captured from the SES v2
    # SendEmail response at send time. It appears in every event as
    # mail.messageId at TOP level — never truncated, never mutated.
    # ----------------------------
    ses_msg_id = mail_data.get("messageId")

    # Header fallbacks for legacy rows / SMTP sends (where the RFC
    # Message-ID is our own <EV-...> header). mail.headers can be
    # truncated by SES, so these are best-effort only.
    message_id_header = next(
        (h["value"] for h in headers if h.get("name", "").lower() == "message-id"),
        None,
    )
    evecta_message_id = next(
        (h["value"] for h in headers if h.get("name", "").lower() == "x-evecta-message-id"),
        None,
    )

    if not ses_msg_id and not message_id_header and not evecta_message_id:
        return {"status": "missing_message_id"}

    email_activity = None
    if ses_msg_id:
        result = await db.execute(
            select(EmailActivity).where(EmailActivity.ses_message_id == ses_msg_id)
        )
        email_activity = result.scalars().first()

    if email_activity is None:
        for candidate in (evecta_message_id, message_id_header):
            if not candidate:
                continue
            result = await db.execute(
                select(EmailActivity).where(EmailActivity.message_id == candidate)
            )
            email_activity = result.scalars().first()
            if email_activity:
                break

    if not email_activity:
        # Possible reasons: old emails, test sends, DB cleanup
        return {"status": "email_activity_not_found"}

    # Backfill ses_message_id on rows sent before it was captured at send
    # time, so subsequent events match directly. Write-once: only when empty.
    # NOTE: message_id itself is never mutated anymore.
    if ses_msg_id and email_activity.ses_message_id is None:
        email_activity.ses_message_id = ses_msg_id

    # ----------------------------
    # Apply the event (single state machine — email_event_service).
    # Open/Click events are classified first: scanner, crawler and
    # Apple-MPP prefetch loads must NOT count as engagement.
    # ----------------------------
    def _parse_ts(value: str | None):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    if event_type == "Delivery":
        occurred = _parse_ts(ses_message.get("delivery", {}).get("timestamp"))
        apply_email_event(email_activity, "delivery", occurred_at=occurred)

    elif event_type == "Bounce":
        apply_email_event(email_activity, "bounce")

    elif event_type == "Complaint":
        apply_email_event(email_activity, "complaint")

    elif event_type in ("Open", "Click"):
        detail = ses_message.get(event_type.lower()) or {}
        user_agent = detail.get("userAgent")
        ip_address = detail.get("ipAddress")
        occurred = _parse_ts(detail.get("timestamp"))
        reference = email_activity.delivered_at or email_activity.sent_at

        classification = classify_open(
            user_agent,
            ip_address,
            occurred_at=occurred,
            delivered_at=reference,
        )
        if classification != OpenClassification.HUMAN:
            logger.info(
                "SES %s ignored as %s | ua=%r ip=%s activity=%s",
                event_type, classification.value, user_agent, ip_address, email_activity.id,
            )
            # A prefetch still proves the mail reached the mailbox.
            apply_email_event(email_activity, "delivery", occurred_at=occurred)
            db.add(email_activity)
            await db.commit()
            return {"status": f"ignored_machine_{event_type.lower()}:{classification.value}"}

        apply_email_event(email_activity, event_type.lower(), occurred_at=occurred)

    else:
        # Ignore unsupported events: Reject, RenderingFailure, DeliveryDelay, etc.
        await db.commit()  # persist ses_message_id backfill if any
        return {"status": f"ignored_event:{event_type}"}

    db.add(email_activity)
    await db.commit()

    return {
        "status": "success",
        "event": event_type,
        "ses_message_id": ses_msg_id,
    }
