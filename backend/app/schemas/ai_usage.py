from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AiUsageTotals(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    request_count: int = 0
    failed_count: int = 0


class AiUsageSummaryResponse(AiUsageTotals):
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    provider: Optional[str] = None


class AiUsageGroupedItem(AiUsageTotals):
    """One bucket from ``fetch_usage_grouped``. Unused dimension fields stay null."""

    group_by: str
    key: str
    feature: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    day: Optional[date] = None
    month: Optional[str] = None
    year: Optional[int] = None
    month_number: Optional[int] = None
    user_id: Optional[UUID] = None
    email: Optional[str] = None
    username: Optional[str] = None


# Existing /by-* routes keep these names so OpenAPI and imports stay stable.
AiUsageByFeatureItem = AiUsageGroupedItem
AiUsageByModelItem = AiUsageGroupedItem
AiUsageByDayItem = AiUsageGroupedItem
AiUsageByMonthItem = AiUsageGroupedItem
AiUsageByUserItem = AiUsageGroupedItem
AiUsageByUserMonthItem = AiUsageGroupedItem


class AiUsageCreditsByUserItem(BaseModel):
    user_id: UUID
    email: Optional[str] = None
    username: Optional[str] = None
    credits_spent_lead: int = 0
    credits_spent_email_gen: int = 0
    credits_spent_outreach: int = 0
    credits_spent_total: int = 0
    credits_remaining_lead: int = 0
    credits_remaining_email_gen: int = 0
    credits_remaining_outreach: int = 0


class AiUsageEventRead(BaseModel):
    id: UUID
    user_id: Optional[UUID] = None
    feature: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    total_tokens: int
    input_rate_per_million: Optional[float] = None
    output_rate_per_million: Optional[float] = None
    estimated_cost_usd: float
    latency_ms: Optional[int] = None
    status: str
    request_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AiUsageEventsPage(BaseModel):
    items: list[AiUsageEventRead]
    total: int
    limit: int = Field(default=50)
    offset: int = Field(default=0)
