from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.database.base import Base

class CampaignCategory(Base):
    __tablename__ = "campaign_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    
    user = relationship("User", backref="campaign_categories", lazy="select")
    campaigns = relationship("Campaign", back_populates="category_ref", lazy="select")

    __table_args__ = (
        Index("idx_campaign_category_user_name", "user_id", "name"),
        UniqueConstraint("user_id", "name", name="uq_campaign_category_user_name"),
    )