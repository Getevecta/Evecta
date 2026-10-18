from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional
from uuid import UUID

from app.database.session import get_session
from app.models.mailbox import Mailbox, MailboxType
from app.models.domain import Domain
from app.utils.crypto import decrypt_secret, encrypt_secret
from app.schemas.system_mailbox import (
    SystemMailboxCreate,
    SystemMailboxRead,
    SystemMailboxUpdate,
)
from app.services.mailbox_service import (
    raise_mailbox_credential_http,
    validate_imap_credentials,
    validate_smtp_credentials,
)
from app.dependencies.auth import require_role


router = APIRouter(
    prefix="/system/mailboxes",
    tags=["System · Mailboxes"],
)


async def _get_system_mailbox(db: AsyncSession, mailbox_id: str) -> Mailbox:
    try:
        mid = UUID(str(mailbox_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid mailbox id") from exc

    mailbox = await db.get(Mailbox, mid)
    if not mailbox or mailbox.mailbox_type != MailboxType.SYSTEM:
        raise HTTPException(status_code=404, detail="System mailbox not found")
    return mailbox


async def _assert_domain_limit(
    db: AsyncSession,
    *,
    domain: Domain,
    new_daily_limit: int,
    exclude_mailbox_id: Optional[UUID] = None,
) -> None:
    used_q = select(func.coalesce(func.sum(Mailbox.daily_limit), 0)).where(
        Mailbox.domain_id == domain.id,
        Mailbox.mailbox_type == MailboxType.SYSTEM,
    )
    if exclude_mailbox_id is not None:
        used_q = used_q.where(Mailbox.id != exclude_mailbox_id)
    used_limit = await db.scalar(used_q) or 0
    if used_limit + new_daily_limit > domain.daily_limit:
        raise HTTPException(
            status_code=400,
            detail="Mailbox limits exceed domain daily limit",
        )


@router.post("/", response_model=SystemMailboxRead, dependencies=[Depends(require_role("admin"))])
async def create_system_mailbox(
    payload: SystemMailboxCreate,
    db: AsyncSession = Depends(get_session),
):
    try:
        domain = await db.get(Domain, payload.domain_id)
        if not domain:
            raise HTTPException(status_code=400, detail="Invalid domain")

        await _assert_domain_limit(
            db,
            domain=domain,
            new_daily_limit=payload.daily_limit,
        )

        email = payload.email.strip().lower()
        clash = await db.scalar(
            select(Mailbox.id).where(func.lower(Mailbox.email) == email)
        )
        if clash:
            raise HTTPException(status_code=400, detail="Email already in use")

        try:
            await validate_smtp_credentials(
                host=payload.smtp_host,
                port=payload.smtp_port,
                username=payload.smtp_user,
                password=payload.smtp_password,
            )
            await validate_imap_credentials(
                host=payload.imap_host,
                port=payload.imap_port,
                username=payload.receive_username,
                password=payload.receive_password,
            )
        except ValueError as e:
            raise_mailbox_credential_http(e)

        mailbox = Mailbox(
            mailbox_type=MailboxType.SYSTEM,
            user_id=None,
            domain_id=payload.domain_id,
            provider=payload.provider,
            email=email,
            smtp_host=payload.smtp_host,
            smtp_user=payload.smtp_user,
            smtp_pass=encrypt_secret(payload.smtp_password),
            port=payload.smtp_port,
            imap_host=payload.imap_host,
            imap_port=payload.imap_port,
            receive_email=payload.receive_email.strip().lower(),
            receive_username=payload.receive_username,
            receive_password=encrypt_secret(payload.receive_password),
            can_receive=payload.can_receive,
            daily_limit=payload.daily_limit,
            sent_today=0,
            is_active=payload.is_active,
            last_used=datetime.now(timezone.utc),
        )

        db.add(mailbox)
        await db.commit()
        await db.refresh(mailbox)
        return mailbox

    except HTTPException:
        raise
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to create mailbox. Please try again.",
        )


@router.get(
    "/",
    response_model=list[SystemMailboxRead],
    dependencies=[Depends(require_role("admin"))],
)
async def list_system_mailboxes(
    db: AsyncSession = Depends(get_session),
):
    try:
        result = await db.execute(
            select(Mailbox)
            .where(Mailbox.mailbox_type == MailboxType.SYSTEM)
            .order_by(Mailbox.last_used.desc())
        )
        return result.scalars().all()

    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=500,
            detail="Database error while fetching mailboxes",
        ) from e

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Unexpected error occurred",
        ) from e


@router.put(
    "/{mailbox_id}",
    response_model=SystemMailboxRead,
    dependencies=[Depends(require_role("admin"))],
)
async def update_system_mailbox(
    mailbox_id: str,
    payload: SystemMailboxUpdate,
    db: AsyncSession = Depends(get_session),
):
    try:
        mailbox = await _get_system_mailbox(db, mailbox_id)
        data = payload.model_dump(exclude_unset=True)

        smtp_password = data.pop("smtp_password", None)
        receive_password = data.pop("receive_password", None)

        target_domain_id = data.get("domain_id", mailbox.domain_id)
        domain = await db.get(Domain, target_domain_id)
        if not domain:
            raise HTTPException(status_code=400, detail="Invalid domain")

        new_daily_limit = data.get("daily_limit", mailbox.daily_limit)
        await _assert_domain_limit(
            db,
            domain=domain,
            new_daily_limit=new_daily_limit,
            exclude_mailbox_id=mailbox.id,
        )

        if "email" in data and data["email"]:
            data["email"] = data["email"].strip().lower()
            clash = await db.scalar(
                select(Mailbox.id).where(
                    func.lower(Mailbox.email) == data["email"],
                    Mailbox.id != mailbox.id,
                )
            )
            if clash:
                raise HTTPException(status_code=400, detail="Email already in use")
        if "receive_email" in data and data["receive_email"]:
            data["receive_email"] = data["receive_email"].strip().lower()

        field_map = {
            "domain_id": "domain_id",
            "email": "email",
            "smtp_host": "smtp_host",
            "smtp_user": "smtp_user",
            "smtp_port": "port",
            "imap_host": "imap_host",
            "imap_port": "imap_port",
            "receive_email": "receive_email",
            "receive_username": "receive_username",
            "daily_limit": "daily_limit",
            "is_active": "is_active",
            "can_receive": "can_receive",
            "provider": "provider",
        }
        for src, dest in field_map.items():
            if src in data and data[src] is not None:
                setattr(mailbox, dest, data[src])

        if smtp_password:
            mailbox.smtp_pass = encrypt_secret(smtp_password)
        if receive_password:
            mailbox.receive_password = encrypt_secret(receive_password)

        smtp_changed = any(k in data for k in ("smtp_host", "smtp_user", "smtp_port")) or bool(smtp_password)
        imap_changed = any(k in data for k in ("imap_host", "imap_port", "receive_username")) or bool(receive_password)
        if smtp_changed or imap_changed:
            try:
                if smtp_changed:
                    await validate_smtp_credentials(
                        host=mailbox.smtp_host,
                        port=mailbox.port,
                        username=mailbox.smtp_user,
                        password=smtp_password or decrypt_secret(mailbox.smtp_pass),
                    )
                if imap_changed:
                    imap_pass = receive_password
                    if not imap_pass:
                        if not mailbox.receive_password:
                            raise HTTPException(
                                status_code=400,
                                detail="IMAP password is required",
                            )
                        imap_pass = decrypt_secret(mailbox.receive_password)
                    await validate_imap_credentials(
                        host=mailbox.imap_host,
                        port=mailbox.imap_port,
                        username=mailbox.receive_username,
                        password=imap_pass,
                    )
            except ValueError as e:
                raise_mailbox_credential_http(e)

        mailbox.last_used = datetime.now(timezone.utc)
        db.add(mailbox)
        await db.commit()
        await db.refresh(mailbox)
        return mailbox

    except HTTPException:
        raise
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to update mailbox. Please try again.",
        )


@router.delete("/{mailbox_id}", dependencies=[Depends(require_role("admin"))])
async def delete_system_mailbox(
    mailbox_id: str,
    db: AsyncSession = Depends(get_session),
):
    try:
        mailbox = await _get_system_mailbox(db, mailbox_id)
        await db.delete(mailbox)
        await db.commit()
        return {"status": "deleted"}

    except HTTPException:
        raise
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to delete mailbox. Please try again.",
        )
