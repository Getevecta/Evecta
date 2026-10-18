from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Index
from sqlalchemy.dialects.postgresql import UUID

from app.database.base import Base


class ExternalApiUsageEvent(Base):
    """
    Metered external provider calls (Hunter.io credits, Google Places/Maps).

    Stores cost metadata only — never request/response payloads — so admins can
    track estimated USD and Hunter credits without retaining sensitive content.
    """

    __tablename__ = "external_api_usage_events"
    # Every admin query filters provider then created_at (and orders newest-first).
    # api_name is the next most common filter / GROUP BY.
    __table_args__ = (
        Index("ix_external_api_usage_events_provider_created", "provider", "created_at"),
        Index(
            "ix_external_api_usage_events_provider_api_created",
            "provider",
            "api_name",
            "created_at",
        ),
        Index("ix_external_api_usage_events_user_id", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # hunter | google_places
    provider = Column(String(32), nullable=False)
    # domain_search | company_find | geocode | nearby_search | place_details | text_search
    api_name = Column(String(64), nullable=False)
    feature = Column(String(64), nullable=False, default="unknown")

    # Hunter: credits burned. Places: billable request count (usually 1).
    units = Column(Integer, nullable=False, default=0)
    unit_cost_usd = Column(Numeric(18, 10), nullable=True)
    estimated_cost_usd = Column(Numeric(18, 8), nullable=False, default=Decimal("0"))

    latency_ms = Column(Integer, nullable=True)
    http_status = Column(Integer, nullable=True)
    # success | failed | zero_results
    status = Column(String(16), nullable=False, default="success")
    # Short non-sensitive label (domain / place_id / address truncated).
    meta = Column(String(256), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
