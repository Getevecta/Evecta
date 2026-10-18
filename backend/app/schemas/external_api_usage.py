from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ExternalApiUsageTotals(BaseModel):
    total_units: int = 0
    estimated_cost_usd: float = 0.0
    request_count: int = 0
    failed_count: int = 0


class ExternalApiUsageSummary(ExternalApiUsageTotals):
    provider: str
    success_count: int = 0


class ExternalApiUsageGroupedItem(ExternalApiUsageTotals):
    group_by: str
    key: str
    api_name: Optional[str] = None
    day: Optional[date] = None


ExternalApiUsageByApiItem = ExternalApiUsageGroupedItem
ExternalApiUsageByDayItem = ExternalApiUsageGroupedItem


class ExternalApiUsageEventRead(BaseModel):
    id: UUID
    provider: str
    api_name: str
    feature: str
    units: int
    unit_cost_usd: Optional[float] = None
    estimated_cost_usd: float
    latency_ms: Optional[int] = None
    http_status: Optional[int] = None
    status: str
    meta: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExternalApiUsageEventsPage(BaseModel):
    items: list[ExternalApiUsageEventRead]
    total: int
    limit: int
    offset: int


class ExternalApiUsageTrack(BaseModel):
    """Combined payload for the admin Hunter / Places tabs."""

    provider: str
    summary: ExternalApiUsageSummary
    by_api: list[ExternalApiUsageByApiItem]
    by_day: list[ExternalApiUsageByDayItem]
    recent_events: list[ExternalApiUsageEventRead]
