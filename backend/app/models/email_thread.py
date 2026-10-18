from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.base import Base
import uuid


class EmailThread(Base):
    __tablename__ = "email_threads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # One thread per campaign
    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    subject = Column(String(255), nullable=True)

    # Counters
    total_recipients = Column(Integer, default=0, nullable=False)
    unread_reply_count = Column(Integer, default=0, nullable=False)

    # State
    is_starred = Column(Boolean, default=False, nullable=False)

    # Timestamps
    last_message_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    campaign = relationship("Campaign", backref="email_thread", lazy="select")
    user = relationship("User", backref="email_threads", lazy="select")
    messages = relationship(
        "EmailMessage",
        back_populates="thread",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="EmailMessage.sent_at",
    )

    __table_args__ = (
        Index("idx_email_thread_user_last_msg", "user_id", "last_message_at"),
    )
