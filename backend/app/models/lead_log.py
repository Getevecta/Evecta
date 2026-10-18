import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.base import Base


class LeadLog(Base):
    __tablename__ = "lead_logs"

    # Identifiers
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Chat Session Info
    chat_title = Column(String(200), nullable=False)
    query = Column(Text, nullable=False)
    promoted = Column(Boolean, default=False)
    status = Column(String(50), default="active", nullable=False)
    # Legacy field - will be removed by migration, but kept for backward compatibility
    is_read = Column(Boolean, default=False, server_default='false', nullable=True)

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

    user = relationship("User", backref="lead_logs", lazy="select")
    leads = relationship("LeadLogLead", back_populates="lead_log", cascade="all, delete-orphan")
