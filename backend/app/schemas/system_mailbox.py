from pydantic import BaseModel, EmailStr, Field
from app.models.mailbox import MailboxProvider, MailboxType
from uuid import UUID
from datetime import datetime
from typing import Optional


class SystemMailboxCreate(BaseModel):
    domain_id: str
    email: EmailStr

    smtp_host: str
    smtp_user: str
    smtp_password: str
    smtp_port: int = Field(default=465, ge=1, le=65535)

    receive_email: EmailStr
    receive_username: str
    receive_password: str

    imap_host: str
    imap_port: int = Field(default=993, ge=1, le=65535)

    daily_limit: int = 2
    provider: MailboxProvider = MailboxProvider.ANY_PROVIDER
    can_receive: bool = True
    is_active: bool = True


class SystemMailboxUpdate(BaseModel):
    """Partial update. Password fields omitted/empty leave existing secrets unchanged."""

    domain_id: Optional[str] = None
    email: Optional[EmailStr] = None

    smtp_host: Optional[str] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_port: Optional[int] = Field(default=None, ge=1, le=65535)

    receive_email: Optional[EmailStr] = None
    receive_username: Optional[str] = None
    receive_password: Optional[str] = None

    imap_host: Optional[str] = None
    imap_port: Optional[int] = Field(default=None, ge=1, le=65535)

    daily_limit: Optional[int] = Field(default=None, gt=0)
    is_active: Optional[bool] = None
    can_receive: Optional[bool] = None
    provider: Optional[MailboxProvider] = None


class SystemMailboxRead(BaseModel):
    id: UUID
    mailbox_type: MailboxType
    domain_id: UUID
    email: str
    provider: MailboxProvider
    smtp_host: str
    smtp_user: str
    port: int
    imap_host: str
    imap_port: int
    receive_email: str
    receive_username: str
    can_receive: bool
    daily_limit: int
    sent_today: int
    is_active: bool
    last_used: datetime

    class Config:
        from_attributes = True
