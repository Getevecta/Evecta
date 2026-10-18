import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    Index,
    Boolean
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.base import Base


class Lead(Base):
    __tablename__ = "leads"

    # Identifiers
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Link to the master catalog (overture_places.overture_id), carried through
    # promotion from lead_log_leads. NULL for imported/manual/Google leads — they
    # skip the enrichment gate. Plain indexed column, not a hard FK.
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
    # Used for deeper email personalization; nullable. `services` is comma-joined text.
    services = Column(Text, nullable=True)
    website_summary = Column(Text, nullable=True)
    business_description = Column(Text, nullable=True)

    starred = Column(Boolean, default=False, nullable=False, index=True)
    email_subscribed = Column(Boolean, default=True, nullable=False, index=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_log_id = Column(
        UUID(as_uuid=True),
        ForeignKey("lead_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    user = relationship("User", backref="leads", lazy="select")
    lead_log = relationship("LeadLog", backref="linked_leads", lazy="select")

    # Indexes for performance
    __table_args__ = (
        Index("idx_leads_industry_score", "industry", "lead_score"),
        Index("idx_leads_email", "email"),
        Index("idx_leads_website", "website"),
        Index("idx_leads_user_created_id", "user_id", "created_at", "id"),
        Index("idx_leads_user_overture", "user_id", "overture_id"),
    )

