from datetime import datetime, timezone
import uuid
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Enum, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.base import Base


class MailboxType(PyEnum):
    SYSTEM = "SYSTEM"
    USER = "USER"

class MailboxProvider(PyEnum):
    ANY_PROVIDER = "ANY_PROVIDER"
    GOOGLE = "GOOGLE"

class Mailbox(Base):
    __tablename__ = "mailboxes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    mailbox_type = Column(
        Enum(MailboxType),
        nullable=False
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )

    provider = Column(
        Enum(
            MailboxProvider,
            name="mailboxprovider",
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=MailboxProvider.ANY_PROVIDER,
    )

    # FK → domains.id
    domain_id = Column(
        UUID(as_uuid=True),
        ForeignKey("domains.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )

    # Uniqueness is case-insensitive via ix_mailboxes_email_lower.
    email = Column(String, index=True, nullable=False)
    smtp_user = Column(String, nullable=False)
    smtp_pass = Column(String, nullable=False)
    smtp_host = Column(String, nullable=False)
    port = Column(Integer, default=587)

    receive_email = Column(String, nullable=True, index=True)
    can_receive = Column(Boolean, default=False, nullable=False) 
    receive_username = Column(String, nullable=True)
    receive_password = Column(String, nullable=True)
    imap_host = Column(String, nullable=False)
    imap_port = Column(Integer, default=993)
    daily_limit = Column(Integer, default=50)
    sent_today = Column(Integer, default=0)

    google_access_token = Column(String, nullable=True)
    google_refresh_token = Column(String, nullable=True)
    google_token_expires_at = Column(DateTime(timezone=True), nullable=True)

    last_used = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    is_active = Column(Boolean, default=True)

    # Reverse relationship → mailbox belongs to a domain
    domain = relationship(
        "Domain",
        back_populates="mailboxes",
        lazy="select",
    )

    user = relationship("User", back_populates="mailboxes", lazy="select")

    __table_args__ = (
        Index("ix_mailboxes_email_lower", func.lower(email), unique=True),
    )