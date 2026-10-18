from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.dialects.postgresql import UUID

from app.database.base import Base


class GeminiApiStatusEvent(Base):
    """
    Gemini API error/status snapshots from live calls (chat, drafts, etc.).

    Used so admins can see credit/quota exhaustion from Gemini status codes
    without opening the Google / Gemini console.
    """

    __tablename__ = "gemini_api_status_events"
    __table_args__ = (
        Index("ix_gemini_api_status_events_created_at", "created_at"),
        Index("ix_gemini_api_status_events_error_kind", "error_kind"),
        Index("ix_gemini_api_status_events_http_status", "http_status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    http_status = Column(Integer, nullable=True)
    # quota_exhausted | billing | rate_limit | unavailable | ok
    error_kind = Column(String(32), nullable=False)
    message = Column(Text, nullable=True)
    feature = Column(String(64), nullable=True)
    model = Column(String(128), nullable=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
