from datetime import datetime, timezone
from sqlalchemy import Column, ForeignKey, DateTime, UniqueConstraint, Index, String, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.database.base import Base


class CampaignLead(Base):
    __tablename__ = "campaign_leads"


    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Snapshot fields to preserve lead data even after deletion
    business_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    industry = Column(String(100), nullable=True)
    address = Column(String(255), nullable=True)
    contact_number = Column(String(50), nullable=True)
    website = Column(String(255), nullable=True)
    lead_score = Column(Integer, nullable=True)
    # Personalization context snapshot (from lead enrichment at sync time)
    services = Column(Text, nullable=True)
    website_summary = Column(Text, nullable=True)
    business_description = Column(Text, nullable=True)

    campaign = relationship("Campaign", back_populates="leads", lazy="select")
    lead = relationship("Lead", backref="campaign_links", lazy="select")

    __table_args__ = (
        UniqueConstraint("campaign_id", "lead_id", name="uq_campaign_lead_pair"),
        Index("idx_campaignlead_campaign_lead", "campaign_id", "lead_id"),
    )