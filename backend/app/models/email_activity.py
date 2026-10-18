from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Enum, Boolean, DateTime, ForeignKey, Index, Integer, text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from enum import Enum as PyEnum
import uuid
from app.database.base import Base

class EmailStatus(PyEnum):
    SENT = "sent"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    FAILED = "failed"


class EmailActivity(Base):
    __tablename__ = "email_activities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Relationships
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


    # Email details
    email = Column(String(255), nullable=False)
    # Our own RFC Message-ID (<EV-...@evecta>). Write-once — never mutated by webhooks.
    message_id = Column(String(255), nullable=True, index=True)
    # AWS-assigned MessageId returned by the SES v2 SendEmail response.
    # SES events carry this exact value in mail.messageId — the primary event-matching key.
    ses_message_id = Column(String(255), nullable=True, unique=True, index=True)

    # Secure token used in tracking pixel URL (opaque, not guessable)
    tracking_token = Column(String(64), nullable=True, unique=True, index=True)

    # Tracking info — booleans are the source of truth; status is derived
    # (see app/services/email_event_service.py, the only writer).
    status = Column(Enum(EmailStatus), nullable=False, default=EmailStatus.SENT)
    opened = Column(Boolean, default=False)
    clicked = Column(Boolean, default=False)
    bounced = Column(Boolean, default=False)
    delivered = Column(Boolean, default=False)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    first_opened_at = Column(DateTime(timezone=True), nullable=True)
    open_count = Column(Integer, default=0, server_default="0", nullable=False)
    
    sent_from = Column(String, nullable=True)
    replied_from = Column(String, nullable=True)

    replied = Column(Boolean, default=False)
    replied_at = Column(DateTime(timezone=True), nullable=True)
    reply_text = Column(String, nullable=True)
    
    starred = Column(Boolean, default=False, nullable=False, index=True)
    
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


    # Relationships for easier joins later
    campaign = relationship("Campaign", backref="email_activities", lazy="select")
    lead = relationship("Lead", backref="email_activities", lazy="select")
    user = relationship("User", back_populates="email_activities", lazy="select")

    __table_args__ = (
        # Existing single-column indexes
        Index("idx_email_activity_campaign", "campaign_id"),
        Index("idx_email_activity_lead", "lead_id"),
        Index("idx_email_activity_status", "status"),
        # Composite indexes for real query shapes
        Index("idx_email_activity_user_sent_at", "user_id", "sent_at"),           # insight/dashboard filters
        Index("idx_email_activity_user_sent_from", "user_id", "sent_from"),       # per-mailbox health queries
        Index("idx_email_activity_campaign_lead", "campaign_id", "lead_id"),      # campaign lead status lookup
        Index("idx_email_activity_user_replied_at", "user_id", "replied_at"),     # inbox sort by reply time
        # One non-failed send per campaign+lead — Celery at-least-once redelivery
        Index(
            "uq_email_activity_campaign_lead_success",
            "campaign_id",
            "lead_id",
            unique=True,
            postgresql_where=text("status != 'FAILED'"),
        ),
    )