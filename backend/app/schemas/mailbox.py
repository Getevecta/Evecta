from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from uuid import UUID
from datetime import datetime
from app.models.mailbox import MailboxProvider
from app.enums.email_sending_mode import EmailSendingMode

# -------------------------------------------------
# CREATE
# -------------------------------------------------
class MailboxCreate(BaseModel):
    """
    Single-form schema for Any Provider mailbox creation.
    """

    email: EmailStr

    provider: MailboxProvider = MailboxProvider.ANY_PROVIDER

    # System-only (optional)
    domain_id: Optional[UUID] = None

    # Shared credentials (SMTP + IMAP)
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)

    # SMTP
    smtp_host: str = Field(..., min_length=1)
    smtp_port: int = Field(default=587, ge=1, le=65535)

    # IMAP
    receive_email: EmailStr
    imap_username: str = Field(..., min_length=1)
    imap_password: str = Field(..., min_length=1)
    imap_host: str = Field(..., min_length=1)
    imap_port: int = Field(default=993, ge=1, le=65535)

    @field_validator("provider")
    @classmethod
    def only_any_provider_allowed(cls, v):
        if v != MailboxProvider.ANY_PROVIDER:
            raise ValueError("Only any_provider is supported for now")
        return v

    @field_validator(
        "username",
        "password",
        "imap_username",
        "imap_password",
        "smtp_host",
        "imap_host",
    )
    @classmethod
    def strip_and_validate(cls, v: str):
        v = v.strip()
        if not v:
            raise ValueError("Field cannot be empty")
        return v


# -------------------------------------------------
# UPDATE
# -------------------------------------------------
class MailboxUpdate(BaseModel):
    """
    Limited update — credentials & config only.
    """

    smtp_host: Optional[str] = Field(default=None, min_length=1)
    smtp_port: Optional[int] = Field(default=None, ge=1, le=65535)
    imap_host: Optional[str] = Field(default=None, min_length=1)
    imap_port: Optional[int] = Field(default=None, ge=1, le=65535)
    password: Optional[str] = Field(default=None, min_length=1)
    is_active: Optional[bool] = None

    @field_validator("smtp_host", "imap_host", "password")
    @classmethod
    def strip_optional(cls, v: Optional[str]):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Field cannot be empty")
        return v


# -------------------------------------------------
# READ
# -------------------------------------------------
class MailboxRead(BaseModel):
    id: UUID
    email: EmailStr
    provider: MailboxProvider
    domain_id: Optional[UUID]

    smtp_host: str
    port: int
    imap_host: str
    imap_port: int

    daily_limit: int
    sent_today: int
    is_active: bool

    last_used: datetime

    class Config:
        from_attributes = True


class EmailSendingModeUpdate(BaseModel):
    email_sending_mode: EmailSendingMode