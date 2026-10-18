from datetime import datetime, timezone
from enum import Enum as PyEnum
import uuid

from sqlalchemy import (
    Column,
    String,
    Text,
    Enum,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import Base


class GenerationStatus(PyEnum):
    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class ComplianceStatus(PyEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class ReviewStatus(PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CampaignLeadEmail(Base):
    """Per-lead outreach email draft produced by Step 4 generation."""

    __tablename__ = "campaign_lead_emails"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_lead_id = Column(
        UUID(as_uuid=True),
        ForeignKey("campaign_leads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    lead_id = Column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    lead_index = Column(Integer, nullable=False, default=0)

    subject = Column(String(255), nullable=True)
    body = Column(Text, nullable=True)

    generation_status = Column(
        Enum(
            GenerationStatus,
            name="generationstatus",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=GenerationStatus.PENDING,
        index=True,
    )
    compliance_status = Column(
        Enum(
            ComplianceStatus,
            name="compliancestatus",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=ComplianceStatus.PENDING,
        index=True,
    )
    spam_score = Column(Integer, nullable=True)
    risk_level = Column(String(32), nullable=True)

    review_status = Column(
        Enum(
            ReviewStatus,
            name="reviewstatus",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=ReviewStatus.PENDING,
    )
    regeneration_count = Column(Integer, nullable=False, default=0)
    variant_metadata = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    campaign = relationship("Campaign", backref="lead_emails", lazy="select")
    campaign_lead = relationship("CampaignLead", lazy="select")
    lead = relationship("Lead", lazy="select")

    __table_args__ = (
        UniqueConstraint("campaign_id", "lead_id", name="uq_campaign_lead_email_pair"),
        Index("idx_campaign_lead_email_status", "campaign_id", "generation_status"),
    )
