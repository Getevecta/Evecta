from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Index
from sqlalchemy.dialects.postgresql import UUID

from app.database.base import Base


class AiUsageEvent(Base):
    """
    Provider-neutral AI token usage event.

    Stores metering metadata only — never prompts or generated content —
    so we can report daily/feature/model cost without retaining sensitive text.
    """

    __tablename__ = "ai_usage_events"
    # Analytics always date-filter, then optionally provider/feature/model/user,
    # and the events list orders by created_at DESC. Composite indexes match
    # those (filter, order) prefixes; created_at alone covers unfiltered ranges.
    __table_args__ = (
        Index("ix_ai_usage_events_created_at", "created_at"),
        Index("ix_ai_usage_events_provider_created", "provider", "created_at"),
        Index("ix_ai_usage_events_feature_created", "feature", "created_at"),
        Index("ix_ai_usage_events_model_created", "model", "created_at"),
        Index("ix_ai_usage_events_user_created", "user_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Nullable for guest chat / background-system jobs without an attributed user.
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    feature = Column(String(64), nullable=False)
    provider = Column(String(32), nullable=False)  # gemini | groq | openai | deepseek
    model = Column(String(128), nullable=False)

    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    reasoning_tokens = Column(Integer, nullable=False, default=0)
    cached_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)

    # Price snapshot applied at write time (USD per million tokens).
    input_rate_per_million = Column(Numeric(18, 10), nullable=True)
    output_rate_per_million = Column(Numeric(18, 10), nullable=True)
    estimated_cost_usd = Column(Numeric(18, 8), nullable=False, default=Decimal("0"))

    latency_ms = Column(Integer, nullable=True)
    status = Column(String(16), nullable=False, default="success")  # success | failed
    request_id = Column(String(128), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
