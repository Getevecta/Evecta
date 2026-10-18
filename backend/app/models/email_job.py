import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Enum, DateTime, ForeignKey, Integer, Text,
    Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import Base


class EmailJobStatus(PyEnum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


class EmailJob(Base):
    __tablename__ = "email_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Relationships
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Job payload
    email = Column(String(255), nullable=False)

    # State
    status = Column(Enum(EmailJobStatus,name="emailjobstatus",values_callable=lambda enum: [e.value for e in enum]), nullable=False, default=EmailJobStatus.QUEUED)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)

    # Scheduling (defaults to "send now")
    scheduled_for = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Filled at send-time (optional)
    mailbox_id = Column(UUID(as_uuid=True), ForeignKey("mailboxes.id", ondelete="SET NULL"), nullable=True)
    domain_id = Column(UUID(as_uuid=True), ForeignKey("domains.id", ondelete="SET NULL"), nullable=True)
    # Set immediately before SMTP. Redelivery of a SENDING job must not send again.
    smtp_started_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Optional relationships for joins
    campaign = relationship("Campaign", lazy="select")
    lead = relationship("Lead", lazy="select")
    user = relationship("User", lazy="select")

    __table_args__ = (
        # Prevent duplicates if launch happens twice
        UniqueConstraint("campaign_id", "lead_id", name="uq_email_jobs_campaign_lead"),

        # Worker queries
        Index("idx_email_jobs_status", "status"),
        Index("idx_email_jobs_campaign", "campaign_id"),
        Index("idx_email_jobs_user", "user_id"),
        Index("idx_email_jobs_campaign_status", "campaign_id", "status"),

        # Best for "next due queued jobs"
        Index("idx_email_jobs_status_scheduled", "status", "scheduled_for"),
    )
