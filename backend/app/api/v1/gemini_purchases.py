"""Admin Gemini API status tracking from live Gemini response / error codes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dependencies.auth import require_role
from app.models.user import User
from app.services.gemini_status_service import build_gemini_status_track

router = APIRouter(prefix="/gemini-purchases", tags=["Gemini Status"])


class GeminiStatusEventItem(BaseModel):
    id: UUID
    http_status: Optional[int] = None
    error_kind: str
    message: Optional[str] = None
    feature: Optional[str] = None
    model: Optional[str] = None
    user_id: Optional[UUID] = None
    created_at: datetime


class GeminiStatusTrackResponse(BaseModel):
    status: Literal["ok", "credit_exhausted", "rate_limited", "unavailable"]
    title: str
    message: str
    http_status: Optional[int] = None
    error_kind: Optional[str] = None
    last_success_at: Optional[datetime] = None
    last_error_at: Optional[datetime] = None
    events: list[GeminiStatusEventItem]


@router.get("/track", response_model=GeminiStatusTrackResponse)
async def gemini_status_track(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_role("admin")),
):
    """
    Current Gemini health from API status codes captured during chat/LLM calls.

    When prepaid credit is depleted, Gemini typically returns 429 / RESOURCE_EXHAUSTED
    (or billing prepay errors). Those are recorded here so admins do not need the
    Google console to see that purchase credit is finished.
    """
    data = await build_gemini_status_track(session)
    return GeminiStatusTrackResponse(**data)


@router.get("/summary", response_model=GeminiStatusTrackResponse)
async def gemini_status_summary(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_role("admin")),
):
    data = await build_gemini_status_track(session)
    return GeminiStatusTrackResponse(**data)
