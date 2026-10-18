from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.base import Base
import uuid


class CampaignGoal(Base):
    __tablename__ = "campaign_goals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User", backref="campaign_goals", lazy="select")
    campaigns = relationship("Campaign", back_populates="goal_ref", lazy="select")

    __table_args__ = (
        Index("idx_campaign_goal_user_name", "user_id", "name"),
        UniqueConstraint("user_id", "name", name="uq_campaign_goal_user_name"),
    )