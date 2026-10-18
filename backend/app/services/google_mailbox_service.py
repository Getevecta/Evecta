import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.models.mailbox import Mailbox, MailboxProvider, MailboxType
from app.models.email_activity import EmailActivity, EmailStatus
from app.core.google_gmail import GOOGLE_OAUTH_CONFIG
from app.core.http_client import get_http_client
from app.services.google_gmail_token_service import store_google_access_token
from app.utils.crypto import encrypt_secret


async def handle_google_callback(
    *,
    code: str,
    user_id: str,
    db: AsyncSession,
):
    client = get_http_client()
    token_res = await client.post(
        GOOGLE_OAUTH_CONFIG["token_uri"],
        data={
            "client_id": GOOGLE_OAUTH_CONFIG["client_id"],
            "client_secret": GOOGLE_OAUTH_CONFIG["client_secret"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": GOOGLE_OAUTH_CONFIG["redirect_uri"],
        },
    )

    if token_res.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail="Failed to exchange Google authorization code",
        )

    token_data = token_res.json()

    if "access_token" not in token_data:
        raise HTTPException(
            status_code=400,
            detail="Google did not return access token",
        )

    if "refresh_token" not in token_data:
        raise HTTPException(
            status_code=400,
            detail="Google did not return refresh token. Please re-consent.",
        )

    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=token_data["expires_in"]
        )

    # Fetch Gmail profile to get REAL email address
    profile_res = await client.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/profile",
        headers={
            "Authorization": f"Bearer {token_data['access_token']}",
        },
    )

    if profile_res.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail="Failed to fetch Gmail profile",
        )

    profile = profile_res.json()
    gmail_email = str(profile["emailAddress"]).strip().lower()

    # Check if mailbox with this email already exists
    result = await db.execute(
        select(Mailbox).where(func.lower(Mailbox.email) == gmail_email)
        )
    existing_mailbox = result.scalar_one_or_none()

    if existing_mailbox:
        # Check if this mailbox has been used to send emails.
        # Must NOT filter status == SENT: status moves to OPENED/CLICKED/BOUNCED
        # on engagement, which would make used mailboxes look unused.
        email_activity_result = await db.execute(
            select(func.count(EmailActivity.id))
            .where(
                func.lower(EmailActivity.sent_from) == gmail_email,
                EmailActivity.status != EmailStatus.FAILED
            )
        )
        sent_count = email_activity_result.scalar() or 0

        # If mailbox has been used to send emails, prevent reconnection
        if sent_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"This Gmail account ({gmail_email}) has already been used to send emails and cannot be reconnected. Please use a different Gmail account that hasn't been used for sending."
            )

        # If mailbox exists but hasn't been used, update it with new tokens
        store_google_access_token(existing_mailbox, token_data["access_token"])
        existing_mailbox.google_refresh_token = encrypt_secret(token_data["refresh_token"])
        existing_mailbox.google_token_expires_at = expires_at
        existing_mailbox.provider = MailboxProvider.GOOGLE
        existing_mailbox.is_active = True
        existing_mailbox.user_id = user_id
        existing_mailbox.mailbox_type = MailboxType.USER
        
        await db.commit()
        await db.refresh(existing_mailbox)
        
        # Automatically set email_sending_mode to USER for all draft campaigns when a Google mailbox is reconnected
        try:
            from app.services.campaign_service import auto_set_email_sending_mode_for_draft_campaigns
            from app.enums.email_sending_mode import EmailSendingMode
            from app.models.user import User
            
            # Set for campaigns
            await auto_set_email_sending_mode_for_draft_campaigns(
                user_id=user_id,
                email_sending_mode=EmailSendingMode.USER,
                db=db
            )
            
            # Also set user preference to USER mode
            user = await db.get(User, user_id)
            if user:
                user.email_sending_mode = EmailSendingMode.USER
                await db.commit()
        except Exception as e:
            # Don't fail mailbox update if this fails - just log it
            logger.warning(f"Warning: Failed to auto-set email_sending_mode for draft campaigns: {str(e)}")
        
        return existing_mailbox
    else:
        # Create new mailbox (only if it hasn't been used)
        mailbox = Mailbox(
            mailbox_type=MailboxType.USER,
            provider=MailboxProvider.GOOGLE,
            user_id=user_id,
            email=gmail_email,               
            smtp_user="google",
            smtp_pass="google",
            smtp_host="google",
            port=0,
            imap_host="google",
            imap_port=0,
            daily_limit=50,
            google_access_token=encrypt_secret(token_data["access_token"]),
            google_refresh_token=encrypt_secret(token_data["refresh_token"]),
            google_token_expires_at=expires_at,
            is_active=True,
        )

        db.add(mailbox)
        await db.commit()
        await db.refresh(mailbox)
        
        # Automatically set email_sending_mode to USER for all draft campaigns when a Google mailbox is created
        try:
            from app.services.campaign_service import auto_set_email_sending_mode_for_draft_campaigns
            from app.enums.email_sending_mode import EmailSendingMode
            from app.models.user import User
            
            # Set for campaigns
            await auto_set_email_sending_mode_for_draft_campaigns(
                user_id=user_id,
                email_sending_mode=EmailSendingMode.USER,
                db=db
            )
            
            # Also set user preference to USER mode
            user = await db.get(User, user_id)
            if user:
                user.email_sending_mode = EmailSendingMode.USER
                await db.commit()
        except Exception as e:
            # Don't fail mailbox creation if this fails - just log it
            logger.warning(f"Warning: Failed to auto-set email_sending_mode for draft campaigns: {str(e)}")
        
        return mailbox
