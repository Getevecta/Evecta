from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MemoryItemRead(BaseModel):
    id: UUID
    category: str
    key: str
    value: Any
    source: str
    confidence: float
    confirmed: bool
    created_at: datetime
    updated_at: datetime
    last_used_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MemoryItemUpsert(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    key: str = Field(min_length=1, max_length=128)
    value: Any
    confirmed: bool = True
    source: str = "explicit_user_statement"


class MemoryConfirmBody(BaseModel):
    key: str
    confirm: bool = True
