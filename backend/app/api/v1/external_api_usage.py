from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dependencies.auth import require_role
from app.models.external_api_usage_event import ExternalApiUsageEvent
from app.models.user import User
from app.schemas.external_api_usage import (
    ExternalApiUsageEventRead,
    ExternalApiUsageEventsPage,
    ExternalApiUsageGroupedItem,
    ExternalApiUsageSummary,
    ExternalApiUsageTrack,
)
from app.services.external_api_usage_analytics import (
    ALLOWED_PROVIDERS,
    apply_usage_filters,
    fetch_usage_grouped,
    select_usage_metrics,
    totals_kwargs,
)

router = APIRouter(prefix="/external-api-usage", tags=["External API Usage"])


def _default_from(from_date: Optional[date]) -> Optional[date]:
    if from_date is not None:
        return from_date
    return datetime.now(timezone.utc).date() - timedelta(days=30)


def _empty_summary(provider: str) -> ExternalApiUsageSummary:
    return ExternalApiUsageSummary(
        provider=provider,
        total_units=0,
        estimated_cost_usd=0.0,
        request_count=0,
        failed_count=0,
        success_count=0,
    )


async def _load_summary(
    session: AsyncSession,
    *,
    provider: str,
    from_date: Optional[date],
    to_date: Optional[date],
    api_name: Optional[str] = None,
    feature: Optional[str] = None,
) -> ExternalApiUsageSummary:
    if provider not in ALLOWED_PROVIDERS:
        return _empty_summary(provider)
    stmt = apply_usage_filters(
        select_usage_metrics(include_success=True),
        provider=provider,
        from_date=from_date,
        to_date=to_date,
        api_name=api_name,
        feature=feature,
    )
    row = (await session.execute(stmt)).one()
    return ExternalApiUsageSummary(
        provider=provider,
        success_count=int(row.success_count or 0),
        **totals_kwargs(row),
    )


async def _load_by_api(
    session: AsyncSession,
    *,
    provider: str,
    from_date: Optional[date],
    to_date: Optional[date],
) -> list[ExternalApiUsageGroupedItem]:
    rows = await fetch_usage_grouped(
        session, "api", provider=provider, from_date=from_date, to_date=to_date
    )
    return [ExternalApiUsageGroupedItem(**row) for row in rows]


async def _load_by_day(
    session: AsyncSession,
    *,
    provider: str,
    from_date: Optional[date],
    to_date: Optional[date],
) -> list[ExternalApiUsageGroupedItem]:
    rows = await fetch_usage_grouped(
        session, "day", provider=provider, from_date=from_date, to_date=to_date
    )
    return [ExternalApiUsageGroupedItem(**row) for row in rows]


async def _load_events(
    session: AsyncSession,
    *,
    provider: str,
    from_date: Optional[date],
    to_date: Optional[date],
    limit: int,
    offset: int,
) -> ExternalApiUsageEventsPage:
    if provider not in ALLOWED_PROVIDERS:
        return ExternalApiUsageEventsPage(items=[], total=0, limit=limit, offset=offset)

    base = apply_usage_filters(
        select(ExternalApiUsageEvent),
        provider=provider,
        from_date=from_date,
        to_date=to_date,
    )
    total = int(
        (
            await session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        or 0
    )
    rows = (
        await session.execute(
            base.order_by(ExternalApiUsageEvent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return ExternalApiUsageEventsPage(
        items=[ExternalApiUsageEventRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/summary", response_model=ExternalApiUsageSummary)
async def external_api_usage_summary(
    provider: str = Query(..., description="hunter | google_places"),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    api_name: Optional[str] = Query(None),
    feature: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    return await _load_summary(
        session,
        provider=provider,
        from_date=from_date,
        to_date=to_date,
        api_name=api_name,
        feature=feature,
    )


@router.get("/by-api", response_model=list[ExternalApiUsageGroupedItem])
async def external_api_usage_by_api(
    provider: str = Query(...),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    return await _load_by_api(
        session, provider=provider, from_date=from_date, to_date=to_date
    )


@router.get("/by-day", response_model=list[ExternalApiUsageGroupedItem])
async def external_api_usage_by_day(
    provider: str = Query(...),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    return await _load_by_day(
        session, provider=provider, from_date=from_date, to_date=to_date
    )


@router.get("/events", response_model=ExternalApiUsageEventsPage)
async def external_api_usage_events(
    provider: str = Query(...),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    return await _load_events(
        session,
        provider=provider,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


@router.get("/track", response_model=ExternalApiUsageTrack)
async def external_api_usage_track(
    provider: str = Query(..., description="hunter | google_places"),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    """One-shot payload for admin Hunter / Places tabs (last 30 days by default)."""
    from_date = _default_from(from_date)
    summary = await _load_summary(
        session, provider=provider, from_date=from_date, to_date=to_date
    )
    by_api = await _load_by_api(
        session, provider=provider, from_date=from_date, to_date=to_date
    )
    by_day = await _load_by_day(
        session, provider=provider, from_date=from_date, to_date=to_date
    )
    events_page = await _load_events(
        session,
        provider=provider,
        from_date=from_date,
        to_date=to_date,
        limit=50,
        offset=0,
    )
    return ExternalApiUsageTrack(
        provider=provider,
        summary=summary,
        by_api=by_api,
        by_day=by_day,
        recent_events=events_page.items,
    )
