"""Long-term chat memory — small, user-scoped preference facts with provenance.

Not a transcript store. Do not put secrets, tokens, payment data, or full lead
tables here. Values are compact JSON suitable for selective prompt injection.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database.base import Base


class UserMemoryItem(Base):
    __tablename__ = "user_memory_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # identity | company | search_pref | conversational | correction | recent_search | familiarity
    category = Column(String(64), nullable=False)
    key = Column(String(128), nullable=False)
    value = Column(JSONB, nullable=False)

    # account_profile | company_profile | explicit_user_statement | repeated_behavior | system_derived
    source = Column(String(64), nullable=False)
    confidence = Column(Float, nullable=False, default=1.0)
    confirmed = Column(Boolean, nullable=False, default=False)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", backref="memory_items")

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_memory_items_user_key"),
        Index("ix_user_memory_items_user_category", "user_id", "category"),
    )
