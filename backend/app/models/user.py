from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import (
    Column,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    func,
    Enum,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.base import Base
from app.enums.email_sending_mode import EmailSendingMode

# Avoid circular import
if TYPE_CHECKING:
    from app.models.refresh_token import RefreshToken


class User(Base):
    """
    Represents an application user.
    Passwords are stored securely using bcrypt hashing.
    """

    __tablename__ = "users"

    # Primary key (UUID for scalability and global uniqueness)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # Core identity. Uniqueness is case-insensitive via ix_users_email_lower.
    email = Column(String(255), index=True, nullable=False)
    username = Column(String(100), index=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)

    # Profile fields
    full_name = Column(String(255), nullable=True)
    department = Column(String(100), nullable=True)
    location = Column(String(255), nullable=True)
    website = Column(String(255), nullable=True)
    bio = Column(String(500), nullable=True)
    profile_image = Column(Text, nullable=True)
    
    # Flags
    is_active = Column(Boolean, default=True, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)
    # Email sending preference (SYSTEM | USER | NULL)
    email_sending_mode = Column(Enum(EmailSendingMode),nullable=True)

    role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    # Relationship to Role
    role_obj = relationship("Role", back_populates="users")

    # Timestamps (UTC-aware)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    first_login_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_login_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_queue_served_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # Subscription / billing
    plan = Column(String(20), default="free", nullable=False, server_default="free")
    # Stripe recurring interval for the active subscription price: month | year
    plan_billing_interval = Column(String(10), nullable=True)
    stripe_customer_id = Column(String(50), nullable=True, unique=True)
    stripe_subscription_id = Column(String(50), nullable=True)
    # Set when user cancels — cleared when subscription.deleted webhook fires
    subscription_cancel_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    refresh_tokens = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    otps = relationship(
        "OTP",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    company = relationship(
        "Company",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )

    permission_overrides = relationship(
        "UserPermissionOverride",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    email_activities = relationship(
        "EmailActivity",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    mailboxes = relationship(
        "Mailbox",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    __table_args__ = (
        Index("ix_users_email_lower", func.lower(email), unique=True),
    )