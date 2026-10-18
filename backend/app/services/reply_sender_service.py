import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import aiosmtplib

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from uuid import UUID

from app.models.email_activity import EmailActivity, EmailStatus
from app.models.mailbox import Mailbox
from app.utils.crypto import decrypt_secret
from app.models.campaign import Campaign
import traceback

# ----------------------------------------------------------
# SEND REPLY EMAIL
# ----------------------------------------------------------
async def send_reply_email(
    activity_id: str,
    reply_text: str,
    user_id,
    db: AsyncSession,
):
    """
    Sends a threaded REPLY using original mailbox.
    Cleans reply_text so quoted emails are removed.
    Outbound replies are logged but NOT marked as replied.
    """

    try:
        try:
            activity_uuid = UUID(activity_id) if isinstance(activity_id, str) else activity_id
        except (ValueError, TypeError):
            raise HTTPException(status_code=404, detail="Email activity not found")

        row = (
            await db.execute(
                select(EmailActivity, Campaign)
                .join(Campaign, EmailActivity.campaign_id == Campaign.id)
                .where(
                    EmailActivity.id == activity_uuid,
                    Campaign.user_id == user_id,
                )
            )
        ).one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Email activity not found")

        activity, campaign = row

        lead_email = activity.email
        original_message_id = activity.message_id
        activity_user_id = activity.user_id

        subject = f"Re: {campaign.email_subject or 'Your message'}"

        # 3. Load SAME mailbox
        stmt = select(Mailbox).where(
            func.lower(Mailbox.email) == (activity.sent_from or "").strip().lower()
        )
        mailbox = (await db.scalars(stmt)).one_or_none()
        if not mailbox:
            raise Exception(f"No mailbox found for: {activity.sent_from}")

        # 5. Build tracking token + thread headers
        tracking_token = f"ev={activity.campaign_id}|{activity.lead_id}|{activity_user_id}"

        msg = MIMEMultipart("alternative")
        msg["From"] = mailbox.email
        msg["To"] = lead_email
        msg["Subject"] = subject

        if original_message_id:
            msg["In-Reply-To"] = original_message_id
            msg["References"] = original_message_id

        new_message_id = f"<EV-reply-{uuid.uuid4()}@evecta>"
        msg["Message-ID"] = new_message_id

        # 6. Build HTML content (with hidden tracking token)
        cleaned_html=reply_text.replace("\n","<br>")
        html_body = f"""
        <div>
            <p>{cleaned_html}</p>
            <div style="display:none; opacity:0; font-size:1px;">
                {tracking_token}
            </div>
        </div>
        """

        msg.attach(MIMEText(html_body, "html"))

        mailbox_host = mailbox.smtp_host
        mailbox_port = mailbox.port
        mailbox_user = mailbox.smtp_user
        mailbox_pass = decrypt_secret(mailbox.smtp_pass)
        mailbox_email = mailbox.email
        campaign_id = activity.campaign_id
        lead_id = activity.lead_id

        # Release the pool connection before the (up to 90s) SMTP wait.
        await db.commit()

        # 7. SEND EMAIL
        try:
            await aiosmtplib.send(
                msg,
                hostname=mailbox_host,
                port=mailbox_port,
                username=mailbox_user,
                password=mailbox_pass,
                use_tls=(mailbox_port == 465),
                start_tls=(mailbox_port != 465),
                timeout=90
            )
        except Exception as e:
            raise Exception("SMTP send failed") from e

        # 8. Log outbound reply (NOT inbound)
        try:
            reply_activity = EmailActivity(
                id=uuid.uuid4(),
                campaign_id=campaign_id,
                lead_id=lead_id,
                user_id=activity_user_id,
                email=lead_email,
                message_id=new_message_id,
                status=EmailStatus.SENT,
                sent_from=mailbox_email,
                sent_at=datetime.now(timezone.utc),

                # outbound reply → do not mark inbound fields
                replied=False,
                replied_at=None,
                reply_text=None
            )

            db.add(reply_activity)
            await db.commit()

        except Exception as e:
            await db.rollback()
            raise Exception("Failed to log reply activity") from e

        return reply_activity

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"[SEND REPLY ERROR] {e}")
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Something went wrong. Please try again."
        )
