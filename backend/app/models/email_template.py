from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, UniqueConstraint, Enum, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.database.base import Base
import enum


class TemplateCategory(str, enum.Enum):
    PROFESSIONAL = "professional"
    VALUE_PROPOSITION = "value-proposition"
    NETWORK_OUTREACH = "network-outreach"
   
class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(Enum(TemplateCategory, values_callable=lambda x: [e.value for e in x]), nullable=True, index=True)
    is_favorite = Column(Boolean, nullable=False, default=False, server_default='false')

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", backref="email_templates", lazy="select")

    __table_args__ = (
        Index("idx_emailtemplate_user_name", "user_id", "name"),
        UniqueConstraint("user_id", "name", name="uq_emailtemplate_user_name"),
    )