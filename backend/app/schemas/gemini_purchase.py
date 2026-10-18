from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class GeminiPurchaseCreate(BaseModel):
    amount_usd: float = Field(..., gt=0, le=1_000_000)
    purchased_at: datetime
    reference: Optional[str] = Field(None, max_length=128)
    note: Optional[str] = Field(None, max_length=2000)


class GeminiPurchaseUpdate(BaseModel):
    amount_usd: Optional[float] = Field(None, gt=0, le=1_000_000)
    purchased_at: Optional[datetime] = None
    reference: Optional[str] = Field(None, max_length=128)
    note: Optional[str] = Field(None, max_length=2000)
    is_cancelled: Optional[bool] = None
    manually_completed: Optional[bool] = None


class GeminiPurchaseItem(BaseModel):
    id: UUID
    amount_usd: float
    purchased_at: datetime
    reference: Optional[str] = None
    note: Optional[str] = None
    is_cancelled: bool
    manually_completed: bool
    created_by_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    spent_usd: float
    remaining_usd: float
    progress_pct: float
    status: Literal["active", "completed", "cancelled"]

    class Config:
        from_attributes = True


class GeminiPurchaseSummary(BaseModel):
    purchase_count: int
    active_count: int
    completed_count: int
    cancelled_count: int
    total_purchased_usd: float
    total_spent_usd: float
    total_allocated_usd: float
    remaining_usd: float
    progress_pct: float
    unallocated_spend_usd: float
    purchases: list[GeminiPurchaseItem]

    # Admin billing alerts: none | ok | warning | critical | exhausted
    alert_level: Literal["none", "ok", "warning", "critical", "exhausted"] = "none"
    alert_title: Optional[str] = None
    alert_message: Optional[str] = None
    current_purchase_id: Optional[UUID] = None
    current_progress_pct: float = 0.0
    current_remaining_usd: float = 0.0
    latest_completed_amount_usd: Optional[float] = None
    latest_completed_at: Optional[datetime] = None
