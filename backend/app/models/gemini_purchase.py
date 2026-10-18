from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Numeric, String, Text, Index
from sqlalchemy.dialects.postgresql import UUID

from app.database.base import Base


class GeminiPurchase(Base):
    """
    Admin-logged Google Gemini / AI Studio prepaid purchase.

    Estimated spend from ai_usage_events (provider=gemini) is allocated FIFO
    so admins can track when each purchase is used up without opening Google.
    """

    __tablename__ = "gemini_purchases"
    __table_args__ = (
        Index("ix_gemini_purchases_purchased_at", "purchased_at"),
        Index("ix_gemini_purchases_is_cancelled", "is_cancelled"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    amount_usd = Column(Numeric(18, 8), nullable=False)
    purchased_at = Column(DateTime(timezone=True), nullable=False)

    # Optional Google invoice / order / payment reference.
    reference = Column(String(128), nullable=True)
    note = Column(Text, nullable=True)

    # Soft-exclude from burn-down (wrong entry, refunded, etc.).
    is_cancelled = Column(Boolean, nullable=False, default=False)
    # Admin can mark complete when Google shows the prepaid balance as exhausted
    # even if local estimated cost has not fully caught up.
    manually_completed = Column(Boolean, nullable=False, default=False)

    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
