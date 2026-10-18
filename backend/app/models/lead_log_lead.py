import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    Boolean,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database.base import Base


class LeadLogLead(Base):
    __tablename__ = "lead_log_leads"

    # Identifiers
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Link to the master catalog (overture_places.overture_id). NULL for
    # non-Overture leads (Google fallback / manual) — those keep the legacy
    # snapshot path. Plain indexed column, NOT a hard FK, so the log stays
    # prunable without touching the master.
    overture_id = Column(String(64), nullable=True, index=True)

    # Lead Details
    business_name = Column(String(255), nullable=False, index=True)
    industry = Column(String(100), nullable=True, index=True)
    email = Column(String(255), nullable=True, index=True)
    contact_number = Column(String(50), nullable=True)
    address = Column(String(255), nullable=True)
    website = Column(String(255), nullable=True)
    lead_score = Column(Integer, default=0, index=True)

    # Context fields scraped from the lead's website during enrichment.
    # Used for deeper email personalization; nullable — leads degrade gracefully
    # when a site is missing/unscrapeable. `services` is comma-joined text.
    services = Column(Text, nullable=True)
    website_summary = Column(Text, nullable=True)
    business_description = Column(Text, nullable=True)

    enrichment_status = Column(
        String(20),
        default="processing",
        nullable=False,
        index=True,
    )
    
    promoted = Column(Boolean, default=False, nullable=False)
    hunter_data = Column(JSONB, nullable=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    lead_log_id = Column(
        UUID(as_uuid=True),
        ForeignKey("lead_logs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    lead_log = relationship("LeadLog", back_populates="leads")

    __table_args__ = (
        Index("idx_lead_log_leads_log_promoted", "lead_log_id", "promoted"),
    )

