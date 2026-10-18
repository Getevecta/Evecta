from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Enum, DateTime, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from enum import Enum as PyEnum
from app.database.base import Base
from app.enums.email_sending_mode import EmailSendingMode


class CampaignStatus(PyEnum):
    DRAFT = "draft"
    ONGOING = "ongoing"
    COMPLETED = "completed"


class DraftType(PyEnum):
    TEMPLATE = "template"
    AI = "ai"
    MANUAL = "manual"


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    ai_email_prompt = Column(Text, nullable=True)
    goal_id = Column(UUID(as_uuid=True), ForeignKey("campaign_goals.id", ondelete="SET NULL"), nullable=True, index=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("campaign_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    tags = Column(Text, nullable=True)

    draft_type = Column(Enum(DraftType), nullable=True, index=True)
    template_id = Column(UUID(as_uuid=True), ForeignKey("email_templates.id", ondelete="SET NULL"), nullable=True)
    email_subject = Column(String(255), nullable=True)
    email_content = Column(Text, nullable=True)
    tone = Column(String(50), nullable=True)
    email_sending_mode = Column(Enum(EmailSendingMode), nullable=True, index=True)

    status = Column(Enum(CampaignStatus), nullable=False, default=CampaignStatus.DRAFT, index=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    launched_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", backref="campaigns", lazy="select")
    goal_ref = relationship("CampaignGoal", back_populates="campaigns", lazy="select")
    category_ref = relationship("CampaignCategory", back_populates="campaigns", lazy="select")
    # Explicit selectinload(Campaign.leads) where the collection is needed
    leads = relationship("CampaignLead", back_populates="campaign", cascade="all, delete-orphan", lazy="select")
    template_ref = relationship("EmailTemplate", lazy="select")
    
    __table_args__ = (
        Index("idx_campaign_user_status", "user_id", "status"),
        Index("idx_campaign_goal_category", "goal_id", "category_id"),
        # Removed UniqueConstraint to allow duplicate campaign names
    )

