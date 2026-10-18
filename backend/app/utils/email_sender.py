import logging
import uuid
import secrets
from email.utils import formataddr

import aiosmtplib
from aiosmtplib import errors as smtp_errors
import httpx
from fastapi import HTTPException
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.email_activity import EmailActivity, EmailStatus
from app.models.mailbox import MailboxType, MailboxProvider
from app.core.config import get_settings
from app.utils.crypto import decrypt_secret
from app.utils.google_gmail_sender import send_via_gmail_api
from app.utils.email_mime_builder import build_campaign_mime_bytes
from app.utils.ses_v2_sender import resolve_ses_region, send_via_ses_v2, ses_v2_api_available


settings = get_settings()
logger = logging.getLogger(__name__)


async def send_campaign_email(
    to_email: str,
    subject: str,
    html_content: str,
    campaign_id: str,
    lead_id: str,
    user_id: str,
    mailbox,
    domain=None,
    unsubscribe_url: str = None,
    db: AsyncSession | None = None,
    display_sender: str | None = None,
):
    """
    Sends a campaign email.
    IMPORTANT:
    - No DB writes here
    - No commit / rollback here
    - Safe for asyncio.gather
    """

    if mailbox is None:
        raise RuntimeError("Mailbox is required for sending email")


    # SYSTEM mailbox may use SES/SMTP with the mailbox's own verified identity (no Domain row).
    if mailbox.mailbox_type == MailboxType.SYSTEM:
        if domain is None and mailbox.domain_id:
            raise RuntimeError(
                "SYSTEM mailbox is linked to a domain record but the domain could not be loaded"
            )

    # USER mailbox must NOT have domain
    if mailbox.mailbox_type == MailboxType.USER:
        if domain is not None:
            raise RuntimeError(
                "USER mailbox must not be used with a domain"
            )
    # Basic validation
    if not to_email:
        return {
            "status": EmailStatus.FAILED,
            "email": None,
            "error": "Lead has no email address",
        }

    mailbox_email = mailbox.email
    mailbox_id = mailbox.id
    # Build message & tracking
    message_id = f"<EV-{uuid.uuid4()}-{campaign_id}-{lead_id}@evecta>"
    open_tracking_token = secrets.token_urlsafe(32)
    legacy_token = f"ev={campaign_id}|{lead_id}|{user_id}"

    # Inject tracking pixel if sending via user added account
    if mailbox.mailbox_type == MailboxType.USER:
        base_url = settings.EMAIL_TRACKING_BASE_URL.rstrip("/")
        tracking_pixel_url = f"{base_url}/api/email-accounts/email/open?t={open_tracking_token}"
        tracking_pixel = f'<img src="{tracking_pixel_url}" width="1" height="1" style="display:none;" />'
        html_content += tracking_pixel

    html_content_with_meta = f"""
    {html_content}
    <div style="display:none; opacity:0; font-size:1px;">
        {legacy_token}
    </div>
    """

    from_header = formataddr((display_sender, mailbox_email)) if display_sender else mailbox_email
    reply_to = mailbox.receive_email if mailbox.mailbox_type == MailboxType.SYSTEM else None

    try:
        raw_mime = build_campaign_mime_bytes(
            html_content=html_content_with_meta,
            subject=subject,
            from_addr=from_header,
            to_email=to_email,
            message_id=message_id,
            unsubscribe_url=unsubscribe_url,
            campaign_id=campaign_id,
            lead_id=lead_id,
            mailbox_type=mailbox.mailbox_type,
            reply_to=reply_to,
            lead_email=to_email,
        )
    except (ValueError, TypeError):
        return {
            "status": EmailStatus.FAILED,
            "email": None,
            "error": "Invalid email headers",
        }

    if unsubscribe_url:
        logger.info(
            "Campaign email List-Unsubscribe: url=%s mailbox_type=%s provider=%s",
            unsubscribe_url,
            mailbox.mailbox_type.value,
            mailbox.provider.value if mailbox.provider else "unknown",
        )

    # AWS-assigned MessageId from the SES v2 SendEmail response. SES events
    # reference this exact value in mail.messageId — storing it at send time
    # is what lets the webhook match events without header guessing.
    ses_message_id = None

    # Send email
    try:
        # GOOGLE MAILBOX → Gmail API
        if mailbox.provider == MailboxProvider.GOOGLE:
            await send_via_gmail_api(
                mailbox=mailbox,
                raw_mime=raw_mime,
                db=db,
            )

        # SYSTEM mailbox → SES v2 API when IAM credentials exist (DKIM-signs List-Unsubscribe)
        elif mailbox.mailbox_type == MailboxType.SYSTEM:
            ses_region = resolve_ses_region(mailbox.smtp_host, settings.AWS_SES_REGION)
            ses_config_set = settings.SES_CONFIGURATION_SET
            if ses_v2_api_available(ses_region):
                try:
                    ses_response = await send_via_ses_v2(
                        region=ses_region,
                        from_addr=from_header,
                        to_email=to_email,
                        subject=subject,
                        html_content=html_content_with_meta,
                        reply_to=reply_to,
                        unsubscribe_url=unsubscribe_url,
                        campaign_id=campaign_id,
                        message_id=message_id,
                        configuration_set=ses_config_set,
                    )
                    ses_message_id = (ses_response or {}).get("MessageId")
                    logger.info(
                        "SYSTEM mail sent via SES v2 API (List-Unsubscribe DKIM): "
                        "region=%s config_set=%s",
                        ses_region,
                        ses_config_set or "none",
                    )
                except Exception as ses_exc:
                    logger.error(
                        "SES v2 send failed for SYSTEM mail — falling back to SMTP. "
                        "Gmail hover Unsubscribe will likely NOT appear. Error: %s",
                        ses_exc,
                        exc_info=True,
                    )
                    smtp_password = decrypt_secret(mailbox.smtp_pass)
                    port = mailbox.port
                    await aiosmtplib.send(
                        raw_mime,
                        sender=mailbox_email,
                        recipients=[to_email],
                        hostname=mailbox.smtp_host,
                        port=port,
                        username=mailbox.smtp_user,
                        password=smtp_password,
                        use_tls=(port == 465),
                        start_tls=(port != 465),
                        timeout=90,
                    )
            else:
                logger.warning(
                    "SYSTEM mail using SMTP only (no AWS SES API credentials). "
                    "Set APP_AWS_SES_REGION + APP_AWS_ACCESS_KEY_ID + "
                    "APP_AWS_SECRET_ACCESS_KEY for Gmail hover Unsubscribe. region=%s",
                    ses_region,
                )
                smtp_password = decrypt_secret(mailbox.smtp_pass)
                port = mailbox.port
                await aiosmtplib.send(
                    raw_mime,
                    sender=mailbox_email,
                    recipients=[to_email],
                    hostname=mailbox.smtp_host,
                    port=port,
                    username=mailbox.smtp_user,
                    password=smtp_password,
                    use_tls=(port == 465),
                    start_tls=(port != 465),
                    timeout=90,
                )

        # OTHER SMTP MAILBOX
        else:
            smtp_password = decrypt_secret(mailbox.smtp_pass)
            port = mailbox.port

            await aiosmtplib.send(
                raw_mime,
                sender=mailbox_email,
                recipients=[to_email],
                hostname=mailbox.smtp_host,
                port=port,
                username=mailbox.smtp_user,
                password=smtp_password,
                use_tls=(port == 465),
                start_tls=(port != 465),
                timeout=90,
            )

    except Exception as e:
        logger.exception("Campaign email send failed to=%s", to_email)
        return {
            "status": EmailStatus.FAILED,
            "email": to_email,
            "error": "Failed to send email. Please try again.",
        }


    # Return success (DB logging later)
    return {
        "status": EmailStatus.SENT,
        "email": to_email,
        "sent_from": mailbox_email,
        "domain_id": domain.id if domain else None,
        "mailbox_id": mailbox_id,
        "sent_at": datetime.now(timezone.utc),
        "message_id": message_id,
        "ses_message_id": ses_message_id,
        "tracking_token": open_tracking_token,
    }


# Test Email Function (for preview without tracking)
async def send_test_email(
    to_email: str,
    subject: str,
    html_content: str,
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
    unsubscribe_url: str = None,
    lead_id: str = None,
    sending_mode=None,
    display_sender: str | None = None,
):
    """
    Send a campaign test email through the same mailbox path as production sends
    so List-Unsubscribe headers and footer/top unsubscribe UI match live mail.
    """
    from app.enums.email_sending_mode import EmailSendingMode
    from app.models.campaign import Campaign
    from app.models.mailbox import Mailbox, MailboxType
    from app.models.user import User
    from app.services.mailbox_selector_service import get_next_available_mailbox
    from sqlalchemy import select, func

    if not to_email:
        raise HTTPException(status_code=400, detail="Email address is required.")

    campaign = await db.get(Campaign, campaign_id)

    if sending_mode is None and campaign:
        sending_mode = campaign.email_sending_mode

    if sending_mode is None:
        user_mailbox_count = await db.scalar(
            select(func.count(Mailbox.id)).where(
                Mailbox.user_id == user_id,
                Mailbox.mailbox_type == MailboxType.USER,
                Mailbox.is_active.is_(True),
            )
        ) or 0
        user = await db.get(User, user_id)
        user_preferred_mode = user.email_sending_mode if user else None

        if user_mailbox_count > 0:
            sending_mode = EmailSendingMode.USER
        elif user_preferred_mode == EmailSendingMode.SYSTEM:
            sending_mode = EmailSendingMode.SYSTEM

    if sending_mode is None:
        raise HTTPException(
            status_code=400,
            detail="Email sending mode is not configured for this campaign.",
        )

    mailbox = await get_next_available_mailbox(
        db=db,
        user_id=user_id,
        sending_mode=sending_mode,
    )
    if not mailbox:
        raise HTTPException(
            status_code=503,
            detail="No mailbox available to send the test email. Check your email account or system mail setup.",
        )

    domain = None
    if sending_mode == EmailSendingMode.SYSTEM and mailbox.domain_id:
        from app.models.domain import Domain
        domain = await db.get(Domain, mailbox.domain_id)

    from app.services.google_gmail_token_service import refresh_google_token

    if mailbox.provider == MailboxProvider.GOOGLE:
        if (
            mailbox.google_token_expires_at is None
            or mailbox.google_token_expires_at
            <= datetime.now(timezone.utc) + timedelta(minutes=2)
        ):
            await refresh_google_token(mailbox=mailbox, db=db)

    await db.commit()

    result = await send_campaign_email(
        to_email=to_email,
        subject=subject,
        html_content=html_content,
        campaign_id=campaign_id,
        lead_id=lead_id or str(uuid.uuid4()),
        user_id=user_id,
        mailbox=mailbox,
        domain=domain,
        unsubscribe_url=unsubscribe_url,
        db=None,
        display_sender=display_sender,
    )

    if result.get("status") == EmailStatus.FAILED:
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Test email send failed"),
        )

    return result
