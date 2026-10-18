"""Persist and report Gemini API status from live response / error codes."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Union
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.llm_errors import classify_llm_error, is_llm_unavailable

logger = logging.getLogger(__name__)


def _coerce_user_id(user_id: Optional[Union[str, UUID]]) -> Optional[UUID]:
    if user_id is None:
        return None
    if isinstance(user_id, UUID):
        return user_id
    try:
        return UUID(str(user_id))
    except (TypeError, ValueError):
        return None


async def record_gemini_api_error(
    *,
    exc: BaseException,
    feature: str = "unknown",
    model: Optional[str] = None,
    user_id: Optional[Union[str, UUID]] = None,
) -> None:
    """Store a Gemini failure status event. Never raises to the caller."""
    if not is_llm_unavailable(exc):
        return
    try:
        info = classify_llm_error(exc)
        from app.database.session import async_session_factory
        from app.models.gemini_api_status_event import GeminiApiStatusEvent

        async with async_session_factory() as session:
            session.add(
                GeminiApiStatusEvent(
                    id=uuid.uuid4(),
                    http_status=info.http_status,
                    error_kind=info.kind,
                    message=info.message,
                    feature=(feature or "unknown")[:64],
                    model=(model or None),
                    user_id=_coerce_user_id(user_id),
                )
            )
            await session.commit()
        logger.warning(
            "[GEMINI_STATUS] recorded kind=%s http=%s feature=%s",
            info.kind,
            info.http_status,
            feature,
        )
    except Exception:
        logger.warning("[GEMINI_STATUS] failed to persist status event", exc_info=True)


async def build_gemini_status_track(session: AsyncSession) -> dict[str, Any]:
    from app.models.ai_usage_event import AiUsageEvent
    from app.models.gemini_api_status_event import GeminiApiStatusEvent

    events_result = await session.execute(
        select(GeminiApiStatusEvent)
        .order_by(desc(GeminiApiStatusEvent.created_at))
        .limit(50)
    )
    events = list(events_result.scalars().all())

    last_ok_result = await session.execute(
        select(func.max(AiUsageEvent.created_at)).where(
            AiUsageEvent.provider == "gemini",
            AiUsageEvent.status == "success",
        )
    )
    last_success_at = last_ok_result.scalar_one_or_none()

    latest = events[0] if events else None
    status = "ok"
    title = "Gemini is responding"
    message = "No recent Gemini credit/quota errors recorded from API responses."
    http_status = None
    error_kind = None

    if latest:
        http_status = latest.http_status
        error_kind = latest.error_kind
        recovered = bool(
            last_success_at
            and latest.created_at
            and last_success_at > latest.created_at
        )
        if recovered:
            status = "ok"
            title = "Gemini recovered"
            message = (
                f"Last error was {latest.error_kind}"
                f"{f' (HTTP {latest.http_status})' if latest.http_status else ''}, "
                "but Gemini calls succeeded again after that."
            )
        elif latest.error_kind in ("quota_exhausted", "billing"):
            status = "credit_exhausted"
            title = "Gemini purchase / credit exhausted"
            message = (
                f"Gemini returned "
                f"{f'HTTP {latest.http_status}' if latest.http_status else 'a quota/billing error'} "
                f"({latest.error_kind}). Chat may fail until you top up on Google / Gemini."
            )
        elif latest.error_kind == "rate_limit":
            status = "rate_limited"
            title = "Gemini rate limited"
            message = (
                f"Gemini returned HTTP {latest.http_status or 429}. "
                "This may be temporary throttling, not empty prepaid credit."
            )
        else:
            status = "unavailable"
            title = "Gemini unavailable"
            message = (
                f"Gemini error recorded"
                f"{f' (HTTP {latest.http_status})' if latest.http_status else ''}."
            )

    return {
        "status": status,
        "title": title,
        "message": message,
        "http_status": http_status,
        "error_kind": error_kind,
        "last_success_at": last_success_at,
        "last_error_at": latest.created_at if latest else None,
        "events": [
            {
                "id": e.id,
                "http_status": e.http_status,
                "error_kind": e.error_kind,
                "message": e.message,
                "feature": e.feature,
                "model": e.model,
                "user_id": e.user_id,
                "created_at": e.created_at,
            }
            for e in events
        ],
    }
