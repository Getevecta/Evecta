import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from app.models.mailbox import MailboxType, MailboxProvider
from app.models.mailbox import Mailbox
from app.models.user import User
from app.models.email_activity import EmailActivity, EmailStatus
from app.schemas.mailbox import MailboxCreate, MailboxUpdate
from app.utils.crypto import decrypt_secret, encrypt_secret
from app.utils.outbound_host import assert_safe_outbound_port, resolve_public_ip
from app.enums.email_sending_mode import EmailSendingMode
import smtplib
import imaplib
import ssl
import socket
import asyncio
from functools import partial

MAILBOX_UPDATE_FIELD_MAP = {
    "smtp_host": "smtp_host",
    "smtp_port": "port",
    "imap_host": "imap_host",
    "imap_port": "imap_port",
    "is_active": "is_active",
}


class _PinnedSMTP(smtplib.SMTP):
    def __init__(self, hostname: str, port: int, pinned_ip: str, timeout: float = 15):
        self._pinned_ip = pinned_ip
        super().__init__(hostname, port, timeout=timeout)

    def _get_socket(self, host, port, timeout):
        return socket.create_connection((self._pinned_ip, port), timeout, self.source_address)


class _PinnedSMTP_SSL(smtplib.SMTP_SSL):
    def __init__(self, hostname: str, port: int, pinned_ip: str, context, timeout: float = 15):
        self._pinned_ip = pinned_ip
        super().__init__(hostname, port, timeout=timeout, context=context)

    def _get_socket(self, host, port, timeout):
        sock = socket.create_connection((self._pinned_ip, port), timeout, self.source_address)
        return self.context.wrap_socket(sock, server_hostname=self._host)


class _PinnedIMAP4(imaplib.IMAP4):
    def __init__(self, hostname: str, port: int, pinned_ip: str, timeout: float = 15):
        self._pinned_ip = pinned_ip
        super().__init__(hostname, port, timeout=timeout)

    def _create_socket(self, timeout):
        return socket.create_connection((self._pinned_ip, self.port), timeout)


class _PinnedIMAP4_SSL(imaplib.IMAP4_SSL):
    def __init__(self, hostname: str, port: int, pinned_ip: str, timeout: float = 15):
        self._pinned_ip = pinned_ip
        super().__init__(
            hostname,
            port,
            ssl_context=ssl.create_default_context(),
            timeout=timeout,
        )

    def _create_socket(self, timeout):
        sock = socket.create_connection((self._pinned_ip, self.port), timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def _validate_smtp_sync(host: str, port: int, username: str, password: str) -> None:
    assert_safe_outbound_port(port, "smtp")
    hostname, pinned_ip = resolve_public_ip(host)
    context = ssl.create_default_context()
    try:
        if port == 465:
            server = _PinnedSMTP_SSL(hostname, port, pinned_ip, context=context, timeout=15)
        else:
            server = _PinnedSMTP(hostname, port, pinned_ip, timeout=15)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
        server.login(username, password)
        server.quit()
    except HTTPException:
        raise
    except smtplib.SMTPAuthenticationError:
        raise ValueError("SMTP authentication failed: incorrect username or password.")
    except smtplib.SMTPConnectError:
        raise ValueError(f"Could not connect to SMTP server {hostname}:{port}. Check the host and port.")
    except smtplib.SMTPException as e:
        logger.warning("SMTP validation error for %s:%s: %s", hostname, port, e)
        raise ValueError("SMTP connection failed. Check host, port, and credentials.")
    except OSError as e:
        logger.warning("SMTP network error for %s:%s: %s", hostname, port, e)
        raise ValueError(f"Could not connect to SMTP server {hostname}:{port}. Check the host and port.")


def _validate_imap_sync(host: str, port: int, username: str, password: str) -> None:
    assert_safe_outbound_port(port, "imap")
    hostname, pinned_ip = resolve_public_ip(host)
    try:
        if port == 993:
            imap = _PinnedIMAP4_SSL(hostname, port, pinned_ip, timeout=15)
        else:
            imap = _PinnedIMAP4(hostname, port, pinned_ip, timeout=15)
            imap.starttls(ssl.create_default_context())
        imap.login(username, password)
        imap.logout()
    except HTTPException:
        raise
    except imaplib.IMAP4.error as e:
        err = str(e).lower()
        if "authenticate" in err or "login" in err or "invalid" in err or "credentials" in err:
            raise ValueError("IMAP authentication failed: incorrect username or password.")
        logger.warning("IMAP validation error for %s:%s: %s", hostname, port, e)
        raise ValueError("IMAP connection failed. Check host, port, and credentials.")
    except OSError as e:
        logger.warning("IMAP network error for %s:%s: %s", hostname, port, e)
        raise ValueError(f"Could not connect to IMAP server {hostname}:{port}. Check the host and port.")


async def validate_smtp_credentials(host: str, port: int, username: str, password: str) -> None:
    loop = asyncio.get_event_loop()
    last_error: Exception = Exception("Unknown error")
    for attempt in range(3):
        try:
            await loop.run_in_executor(None, partial(_validate_smtp_sync, host, port, username, password))
            return
        except ValueError as e:
            last_error = e
            # Don't retry auth failures — wrong password won't fix itself
            if "authentication failed" in str(e).lower():
                raise
            if attempt < 2:
                await asyncio.sleep(1)
    raise last_error


async def validate_imap_credentials(host: str, port: int, username: str, password: str) -> None:
    loop = asyncio.get_event_loop()
    last_error: Exception = Exception("Unknown error")
    for attempt in range(3):
        try:
            await loop.run_in_executor(None, partial(_validate_imap_sync, host, port, username, password))
            return
        except ValueError as e:
            last_error = e
            if "authentication failed" in str(e).lower():
                raise
            if attempt < 2:
                await asyncio.sleep(1)
    raise last_error


def raise_mailbox_credential_http(exc: ValueError) -> None:
    msg = str(exc)
    if any(
        key in msg
        for key in (
            "authentication failed",
            "Could not connect",
            "connection failed",
        )
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    logger.warning("Mailbox credential validation failed: %s", exc)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Could not verify mailbox credentials. Check host, port, username, and password.",
    )


def apply_mailbox_update_fields(mailbox: Mailbox, update_data: dict) -> None:
    if update_data.get("password"):
        mailbox.smtp_pass = encrypt_secret(update_data["password"])
    for src, dest in MAILBOX_UPDATE_FIELD_MAP.items():
        if src in update_data and update_data[src] is not None:
            setattr(mailbox, dest, update_data[src])


# -------------------------
# CREATE
# -------------------------
async def create_mailbox(
    *,
    payload: MailboxCreate,
    db: AsyncSession,
    user_id,
):
    email = payload.email.strip().lower()
    receive_email = payload.receive_email.strip().lower()

    # Prevent duplicate email usage (case-insensitive; DB unique index is the backstop)
    exists = await db.execute(
        select(Mailbox).where(func.lower(Mailbox.email) == email)
    )
    if exists.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mailbox already exists",
        )

    try:
        await validate_smtp_credentials(
            host=payload.smtp_host,
            port=payload.smtp_port,
            username=payload.username,
            password=payload.password,
        )

        await validate_imap_credentials(
            host=payload.imap_host,
            port=payload.imap_port,
            username=payload.imap_username,
            password=payload.imap_password,
        )
    except ValueError as e:
        raise_mailbox_credential_http(e)
    
    same_mailbox = email == receive_email

    mailbox = Mailbox(
        mailbox_type=MailboxType.USER,
        user_id=user_id,
        provider=payload.provider,
        domain_id=None,  # users never set domain
        email=email,

        smtp_user=payload.username,
        smtp_pass=encrypt_secret(payload.password),
        smtp_host=payload.smtp_host,
        port=payload.smtp_port,

        imap_host=payload.imap_host,
        imap_port=payload.imap_port,

        can_receive=not same_mailbox,

        receive_email=None if same_mailbox else receive_email,
        receive_username=None if same_mailbox else payload.imap_username,
        receive_password=None if same_mailbox else encrypt_secret(payload.imap_password),
        daily_limit=50,
        sent_today=0,
        is_active=True,
        last_used=datetime.now(timezone.utc),
    )

    db.add(mailbox)
    await db.commit()
    await db.refresh(mailbox)

    # Automatically set email_sending_mode to USER for all draft campaigns when a user mailbox is created
    # This allows users to launch campaigns after connecting their email accounts
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


# -------------------------
# LIST (USER ONLY)
# -------------------------
async def get_user_mailboxes(user_id, db: AsyncSession):
    result = await db.execute(
        select(Mailbox)
        .where(
            Mailbox.user_id == user_id,
            Mailbox.is_active == True,
        )
    )
    return result.scalars().all()


# -------------------------
# LIST BY DOMAIN
# -------------------------
async def get_mailboxes_by_domain(domain_id: str, user_id, db: AsyncSession):
    """Get mailboxes for a specific domain that belong to the user."""
    result = await db.execute(
        select(Mailbox)
        .where(
            Mailbox.domain_id == domain_id,
            Mailbox.user_id == user_id,
            Mailbox.is_active == True,
        )
    )
    return result.scalars().all()


# -------------------------
# GET BY ID (OWNERSHIP SAFE)
# -------------------------
async def get_mailbox_by_id(
    mailbox_id: str,
    user_id,
    db: AsyncSession,
):
    mailbox = await db.get(Mailbox, mailbox_id)

    if not mailbox or mailbox.user_id != user_id:
        raise HTTPException(404, "Mailbox not found")

    return mailbox


# -------------------------
# UPDATE (LIMITED)
# -------------------------
async def update_mailbox(
    mailbox_id: str,
    payload: MailboxUpdate,
    user_id,
    db: AsyncSession,
):
    mailbox = await db.get(Mailbox, mailbox_id)

    if not mailbox or mailbox.user_id != user_id:
        raise HTTPException(status_code=404, detail="Mailbox not found")

    update_data = payload.model_dump(exclude_none=True)
    if mailbox.provider == MailboxProvider.GOOGLE:
        update_data = {k: v for k, v in update_data.items() if k == "is_active"}

    smtp_changed = any(k in update_data for k in ("smtp_host", "smtp_port", "password"))
    imap_changed = any(k in update_data for k in ("imap_host", "imap_port"))

    if smtp_changed or imap_changed:
        smtp_host = update_data.get("smtp_host", mailbox.smtp_host)
        smtp_port = update_data.get("smtp_port", mailbox.port)
        smtp_password = update_data.get("password") or decrypt_secret(mailbox.smtp_pass)
        imap_host = update_data.get("imap_host", mailbox.imap_host)
        imap_port = update_data.get("imap_port", mailbox.imap_port)
        imap_user = mailbox.receive_username or mailbox.smtp_user
        if mailbox.receive_password:
            imap_password = decrypt_secret(mailbox.receive_password)
        else:
            imap_password = smtp_password
        try:
            if smtp_changed:
                await validate_smtp_credentials(
                    host=smtp_host,
                    port=smtp_port,
                    username=mailbox.smtp_user,
                    password=smtp_password,
                )
            if imap_changed:
                await validate_imap_credentials(
                    host=imap_host,
                    port=imap_port,
                    username=imap_user,
                    password=imap_password,
                )
        except ValueError as e:
            raise_mailbox_credential_http(e)

    apply_mailbox_update_fields(mailbox, update_data)

    await db.commit()
    await db.refresh(mailbox)

    return mailbox


# -------------------------
# DELETE
# -------------------------
async def delete_mailbox(
    mailbox_id: str,
    user_id,
    db: AsyncSession,
):
    mailbox = await db.get(Mailbox, mailbox_id)

    if not mailbox or mailbox.user_id != user_id:
        raise HTTPException(404, "Mailbox not found")

    await db.delete(mailbox)
    await db.commit()


async def update_user_email_sending_mode(
    *,
    user_id: str,
    mode: EmailSendingMode,
    db: AsyncSession,
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # ----------------------------
    # VALIDATE MODE AVAILABILITY
    # ----------------------------
    if mode == EmailSendingMode.SYSTEM:
        result = await db.execute(
            select(func.count(Mailbox.id))
            .where(
                Mailbox.mailbox_type == MailboxType.SYSTEM,
                Mailbox.is_active.is_(True),
            )
        )
        system_mailbox_count = result.scalar() or 0

        if system_mailbox_count == 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    "System email is not available at the moment. "
                    "Please contact support or try again later."
                )
            )

    elif mode == EmailSendingMode.USER:
        result = await db.execute(
            select(func.count(Mailbox.id))
            .where(
                Mailbox.mailbox_type == MailboxType.USER,
                Mailbox.user_id == user_id,
                Mailbox.is_active.is_(True),
            )
        )
        user_mailbox_count = result.scalar() or 0

        if user_mailbox_count == 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No active email account found. "
                    "Please add an email account before switching to this mode."
                )
            )

    else:
        # Safety net (should never happen)
        raise HTTPException(
            status_code=400,
            detail="Invalid email sending mode."
        )

    # ----------------------------
    # APPLY MODE CHANGE
    # ----------------------------
    user.email_sending_mode = mode

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to update email sending mode.",
        )

    return {"email_sending_mode": mode.value}


# -------------------------
# STATISTICS
# -------------------------
async def get_email_statistics(user_id, db: AsyncSession):
    """Get email statistics for the user: sent today, delivery rate, bounce rate."""
    
    # Get today's date range (start and end of today in UTC)
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_end = datetime.now(timezone.utc).replace(
        hour=23, minute=59, second=59, microsecond=999999
    )
    
    # Calculate sent today: sum of sent_today from all active mailboxes
    mailboxes_result = await db.execute(
        select(func.sum(Mailbox.sent_today))
        .where(
            Mailbox.user_id == user_id,
            Mailbox.is_active == True,
        )
    )
    sent_today = mailboxes_result.scalar() or 0
    
    # Get email activity statistics for all time (for delivery and bounce rates)
    # Total sent emails
    total_sent_result = await db.execute(
        select(func.count(EmailActivity.id))
        .where(EmailActivity.user_id == user_id)
    )
    total_sent = total_sent_result.scalar() or 0
    
    # Delivered emails (status is SENT or has delivered=True)
    delivered_result = await db.execute(
        select(func.count(EmailActivity.id))
        .where(
            EmailActivity.user_id == user_id,
            EmailActivity.delivered == True
        )
    )
    total_delivered = delivered_result.scalar() or 0
    
    # Bounced emails (status is BOUNCED or has bounced=True)
    bounced_result = await db.execute(
        select(func.count(EmailActivity.id))
        .where(
            EmailActivity.user_id == user_id,
            EmailActivity.bounced == True
        )
    )
    total_bounced = bounced_result.scalar() or 0
    
    # Calculate rates
    delivery_rate = 0.0
    bounce_rate = 0.0
    
    if total_sent > 0:
        delivery_rate = round((total_delivered / total_sent) * 100, 2)
        bounce_rate = round((total_bounced / total_sent) * 100, 2)
    
    return {
        "sent_today": sent_today,
        "delivery_rate": delivery_rate,
        "bounce_rate": bounce_rate,
        "total_sent": total_sent,
        "total_delivered": total_delivered,
        "total_bounced": total_bounced,
    }
