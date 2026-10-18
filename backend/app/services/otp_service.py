import logging
import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from fastapi import HTTPException, status
from app.models.otp import OTP
from app.models.user import User
# Email imports removed for now - using console output for development
# import smtplib
# from email.mime.text import MimeText
# from email.mime.multipart import MimeMultipart
import os


def generate_otp_code(length: int = 6) -> str:
    """Generate a cryptographically secure OTP code."""
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def hash_otp_code(code: str) -> str:
    """Keyed HMAC-SHA256 so a 6-digit OTP is not trivially reversible offline."""
    from app.core.config import get_settings

    key = get_settings().SECRET_KEY.encode("utf-8")
    return hmac.new(key, code.encode("utf-8"), hashlib.sha256).hexdigest()


def otp_code_matches(stored_hash: str, code: str) -> bool:
    """Timing-safe compare against the HMAC stored in the OTP table."""
    if len(stored_hash) != 64:
        return False
    return secrets.compare_digest(stored_hash, hash_otp_code(code))


@dataclass(frozen=True)
class OTPCreateResult:
    """Persisted OTP (hashed in DB) plus plaintext for email only — never expose in API responses or logs."""

    otp: OTP
    plaintext_code: str


async def create_otp(
    session: AsyncSession,
    user_id: str,
    email: str,
    expires_minutes: int = 30,
) -> OTPCreateResult:
    """Create a new OTP for email verification."""
    
    # Delete any existing OTPs for this user
    await session.execute(delete(OTP).where(OTP.user_id == user_id))

    # Generate OTP code and hash it before storing
    code = generate_otp_code()

    # Calculate expiration time
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

    # Create OTP record — store hash, never plaintext
    otp = OTP(
        code=hash_otp_code(code),
        email=email,
        user_id=user_id,
        expires_at=expires_at,
        is_used=False,
        is_verified=False,
        attempts=0,
        max_attempts=3
    )
    
    session.add(otp)
    await session.commit()
    await session.refresh(otp)
    return OTPCreateResult(otp=otp, plaintext_code=code)


async def get_otp_by_user_id(session: AsyncSession, user_id: str) -> Optional[OTP]:
    """Get the latest OTP for a user."""
    result = await session.execute(
        select(OTP)
        .where(OTP.user_id == user_id)
        .order_by(OTP.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def verify_otp(
    session: AsyncSession, 
    user_id: str, 
    code: str, 
    mark_as_used: bool = True
) -> bool:
    """Verify an OTP code."""
    otp = await get_otp_by_user_id(session, user_id)
    
    if not otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP is invalid or expired. Please request a new one."
        )

    if not otp.is_valid():
        if otp.attempts >= otp.max_attempts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum attempts exceeded. Please request a new OTP."
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP is invalid or expired. Please request a new one."
        )
    
    # Increment attempts
    otp.attempts += 1
    
    if otp_code_matches(otp.code, code):
        # Mark as verified
        otp.is_verified = True
        
        if mark_as_used:
            otp.is_used = True
            # Update user's email_verified status
            user = await session.get(User, user_id)
            if user:
                user.email_verified = True
        
        await session.commit()
        return True
    else:
        await session.commit()
        return False


async def can_resend_otp(session: AsyncSession, user_id: str, cooldown_minutes: int = 1) -> bool:
    """Check if user can resend OTP (respecting cooldown)."""
    otp = await get_otp_by_user_id(session, user_id)
    
    if not otp:
        return True
    
    # Check if enough time has passed since last OTP creation
    time_since_creation = datetime.now(timezone.utc) - otp.created_at
    return time_since_creation.total_seconds() >= (cooldown_minutes * 60)


def _log_dev_otp_fallback(email: str, otp_code: str, reason: str) -> None:
    """Log OTP locally when outbound mail fails — local/dev only."""
    from app.services.session_service import is_local_dev

    if not is_local_dev():
        return
    logger.warning(
        "📧 OTP email could not be sent (%s). Local dev fallback for %s: %s",
        reason,
        email,
        otp_code,
    )


def send_otp_email(email: str, otp_code: str) -> bool:
    """Send OTP code via email."""
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from app.core.config import get_settings
        
        settings = get_settings()
        
        # Check if email settings are configured
        if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
            logger.info(f"📧 SMTP not configured — OTP email not sent to {email}.")
            _log_dev_otp_fallback(email, otp_code, "SMTP not configured")
            return True
        
        # Create email message with proper headers
        msg = MIMEMultipart()
        msg['From'] = settings.SMTP_FROM_EMAIL
        msg['To'] = email
        msg['Subject'] = "Evecta - Email Verification Code"
        
        # Create email body
        body = f"""Your 6-digit verification code: {otp_code}

Please enter this code in the app. It will expire in 30 minutes.

If this request was not made by you, please disregard this message.

Best regards,

The Evecta Team"""
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Send email with better error handling
        # Support both SSL (port 465) and TLS (port 587)
        if settings.SMTP_PORT == 465:
            # Use SSL for port 465
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:
            # Use TLS for port 587 (or other ports)
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()
        
        smtp_password = settings.SMTP_PASSWORD.strip()
        server.login(settings.SMTP_USERNAME, smtp_password)
        server.sendmail(settings.SMTP_FROM_EMAIL, email, msg.as_string())
        server.quit()
        logger.info("✅ OTP email sent to %s", email)
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(
            "❌ SMTP Authentication failed for OTP email: %s. "
            "Check APP_SMTP_USERNAME and APP_SMTP_PASSWORD in .env "
            "(for Gmail use an App Password, not your regular account password).",
            e,
        )
        _log_dev_otp_fallback(email, otp_code, "SMTP authentication failed")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"❌ SMTP Error sending OTP email: {e}")
        _log_dev_otp_fallback(email, otp_code, "SMTP error")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to send OTP email: {e}")
        _log_dev_otp_fallback(email, otp_code, str(e))
        return False


def send_payment_failed_email(email: str) -> bool:
    """Notify user that their Stripe payment failed."""
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from app.core.config import get_settings

        settings = get_settings()

        if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
            return True  # not configured — skip silently

        msg = MIMEMultipart()
        msg['From'] = settings.SMTP_FROM_EMAIL
        msg['To'] = email
        msg['Subject'] = "Evecta - Payment Failed"

        body = """We were unable to process your latest payment for your Evecta subscription.

Please update your payment method to avoid any interruption to your service:
https://evecta.io/billing

If you need help, reply to this email and we'll assist you.

Best regards,
The Evecta Team"""

        msg.attach(MIMEText(body, 'plain'))

        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()

        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM_EMAIL, email, msg.as_string())
        server.quit()
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ SMTP Authentication failed for payment-failed email: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"❌ SMTP error sending payment-failed email: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to send payment-failed email: {e}")
        return False


async def cleanup_expired_otps(session: AsyncSession) -> int:
    """Clean up expired OTPs from the database."""
    result = await session.execute(
        delete(OTP).where(OTP.expires_at < datetime.now(timezone.utc))
    )
    await session.commit()
    return result.rowcount
