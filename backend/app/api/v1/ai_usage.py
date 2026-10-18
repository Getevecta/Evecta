from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dependencies.auth import require_role
from app.models.ai_usage_event import AiUsageEvent
from app.models.credit import CreditTransaction, UserCreditPool
from app.models.user import User
from app.schemas.ai_usage import (
    AiUsageCreditsByUserItem,
    AiUsageEventRead,
    AiUsageEventsPage,
    AiUsageGroupedItem,
    AiUsageSummaryResponse,
)
from app.services.ai.dynamic_pricing import get_live_snapshot, refresh_live_prices
from app.services.ai.recompute_costs import recompute_ai_usage_costs
from app.services.ai.usage_analytics import (
    GroupByName,
    apply_usage_filters,
    fetch_usage_grouped,
    fetch_usage_totals,
)
from app.services.external_api_pricing import google_maps_pricing_catalog
from app.utils.day_bounds import day_bounds


class AiUsageRecomputeResponse(BaseModel):
    updated: int
    unchanged: int
    total_cost_before_usd: float
    total_cost_after_usd: float
    message: str
    pricing_source: Optional[str] = None
    pricing_source_url: Optional[str] = None
    pricing_fingerprint: Optional[str] = None
    pricing_error: Optional[str] = None


class GoogleMapsApiPriceItem(BaseModel):
    api_name: str
    label: str
    endpoint: str = ""
    unit_cost_usd: float
    unit_label: str = "per request"
    free_monthly: Optional[int] = None
    notes: str = ""


class AiUsagePricingStatusResponse(BaseModel):
    source: str
    source_url: Optional[str] = None
    fetched_at: Optional[float] = None
    age_seconds: Optional[float] = None
    model_count: int = 0
    fingerprint: str = ""
    error: Optional[str] = None
    models: dict[str, dict[str, float]] = {}
    google_maps_apis: list[GoogleMapsApiPriceItem] = []
    google_maps_source: str = (
        "Evecta unit rates from Google Maps Platform list prices "
        "(Geocoding Essentials + Places legacy SKUs)"
    )
    google_maps_source_url: str = "https://developers.google.com/maps/billing-and-pricing/pricing"


router = APIRouter(prefix="/ai-usage", tags=["AI Usage"])


def _pool_spend(pool: str):
    return case(
        (
            (CreditTransaction.amount < 0) & (CreditTransaction.pool == pool),
            -CreditTransaction.amount,
        ),
        else_=0,
    )


@router.get("/summary", response_model=AiUsageSummaryResponse)
async def ai_usage_summary(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    provider: Optional[str] = Query(None),
    feature: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    user_id: Optional[UUID] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    totals = await fetch_usage_totals(
        session,
        from_date=from_date,
        to_date=to_date,
        provider=provider,
        feature=feature,
        model=model,
        user_id=user_id,
    )
    return AiUsageSummaryResponse(
        **totals,
        from_date=from_date,
        to_date=to_date,
        provider=provider,
    )


@router.get("/grouped", response_model=list[AiUsageGroupedItem])
async def ai_usage_grouped(
    group_by: GroupByName = Query(
        ...,
        description="feature | model | day | month | user | user_month",
    ),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    provider: Optional[str] = Query(None),
    feature: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    rows = await fetch_usage_grouped(
        session,
        group_by,
        from_date=from_date,
        to_date=to_date,
        provider=provider,
        feature=feature,
    )
    return [AiUsageGroupedItem(**row) for row in rows]


async def _grouped_alias(
    session: AsyncSession,
    group_by: GroupByName,
    *,
    from_date: Optional[date],
    to_date: Optional[date],
    provider: Optional[str],
    feature: Optional[str] = None,
) -> list[AiUsageGroupedItem]:
    rows = await fetch_usage_grouped(
        session,
        group_by,
        from_date=from_date,
        to_date=to_date,
        provider=provider,
        feature=feature,
    )
    return [AiUsageGroupedItem(**row) for row in rows]


@router.get("/by-feature", response_model=list[AiUsageGroupedItem])
async def ai_usage_by_feature(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    provider: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    return await _grouped_alias(
        session, "feature", from_date=from_date, to_date=to_date, provider=provider
    )


@router.get("/by-model", response_model=list[AiUsageGroupedItem])
async def ai_usage_by_model(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    provider: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    return await _grouped_alias(
        session, "model", from_date=from_date, to_date=to_date, provider=provider
    )


@router.get("/by-day", response_model=list[AiUsageGroupedItem])
async def ai_usage_by_day(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    provider: Optional[str] = Query(None),
    feature: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    return await _grouped_alias(
        session,
        "day",
        from_date=from_date,
        to_date=to_date,
        provider=provider,
        feature=feature,
    )


@router.get("/by-month", response_model=list[AiUsageGroupedItem])
async def ai_usage_by_month(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    provider: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    """Monthly Gemini token + cost totals (platform-wide)."""
    return await _grouped_alias(
        session, "month", from_date=from_date, to_date=to_date, provider=provider
    )


@router.get("/by-user", response_model=list[AiUsageGroupedItem])
async def ai_usage_by_user(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    provider: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    """Gemini token usage grouped by user (for admin cost attribution)."""
    return await _grouped_alias(
        session, "user", from_date=from_date, to_date=to_date, provider=provider
    )


@router.get("/by-user-month", response_model=list[AiUsageGroupedItem])
async def ai_usage_by_user_month(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    provider: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    """Per-user Gemini usage broken down by calendar month."""
    return await _grouped_alias(
        session, "user_month", from_date=from_date, to_date=to_date, provider=provider
    )


@router.get("/credits-by-user", response_model=list[AiUsageCreditsByUserItem])
async def credits_by_user(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    """
    Product credit spend by user (lead / email_gen / outreach pools).

    Spent = sum of negative credit_transactions amounts (absolute value).
    Remaining balances come from user_credit_pools.
    """
    start, end = day_bounds(from_date, to_date)

    spent_lead = func.coalesce(func.sum(_pool_spend("lead")), 0)
    spent_email = func.coalesce(func.sum(_pool_spend("email_gen")), 0)
    spent_outreach = func.coalesce(func.sum(_pool_spend("outreach")), 0)
    spent_total = func.coalesce(
        func.sum(
            case(
                (CreditTransaction.amount < 0, -CreditTransaction.amount),
                else_=0,
            )
        ),
        0,
    )

    spend_stmt = (
        select(
            CreditTransaction.user_id,
            User.email,
            User.username,
            spent_lead.label("credits_spent_lead"),
            spent_email.label("credits_spent_email_gen"),
            spent_outreach.label("credits_spent_outreach"),
            spent_total.label("credits_spent_total"),
        )
        .join(User, User.id == CreditTransaction.user_id)
        .group_by(CreditTransaction.user_id, User.email, User.username)
    )
    if start is not None:
        spend_stmt = spend_stmt.where(CreditTransaction.created_at >= start)
    if end is not None:
        spend_stmt = spend_stmt.where(CreditTransaction.created_at <= end)
    spend_stmt = spend_stmt.order_by(spent_total.desc())

    spend_rows = (await session.execute(spend_stmt)).all()

    bal_stmt = select(
        UserCreditPool.user_id,
        UserCreditPool.pool,
        (
            UserCreditPool.subscription_balance + UserCreditPool.topup_balance
        ).label("remaining"),
    )
    remaining: dict[UUID, dict[str, int]] = {}
    for uid, pool, rem in (await session.execute(bal_stmt)).all():
        remaining.setdefault(uid, {"lead": 0, "email_gen": 0, "outreach": 0})
        if pool in remaining[uid]:
            remaining[uid][pool] = int(rem or 0)

    items: list[AiUsageCreditsByUserItem] = []
    for r in spend_rows:
        uid = r[0]
        rem = remaining.get(uid, {"lead": 0, "email_gen": 0, "outreach": 0})
        items.append(
            AiUsageCreditsByUserItem(
                user_id=uid,
                email=r[1],
                username=r[2],
                credits_spent_lead=int(r[3] or 0),
                credits_spent_email_gen=int(r[4] or 0),
                credits_spent_outreach=int(r[5] or 0),
                credits_spent_total=int(r[6] or 0),
                credits_remaining_lead=rem["lead"],
                credits_remaining_email_gen=rem["email_gen"],
                credits_remaining_outreach=rem["outreach"],
            )
        )
    return items


@router.get("/events", response_model=AiUsageEventsPage)
async def ai_usage_events(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    provider: Optional[str] = Query(None),
    feature: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    user_id: Optional[UUID] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    base = apply_usage_filters(
        select(AiUsageEvent),
        from_date=from_date,
        to_date=to_date,
        provider=provider,
        feature=feature,
        model=model,
        user_id=user_id,
    )
    count_stmt = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(count_stmt)).scalar() or 0)
    rows = (
        await session.execute(
            base.order_by(AiUsageEvent.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return AiUsageEventsPage(
        items=[AiUsageEventRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/pricing", response_model=AiUsagePricingStatusResponse)
async def ai_usage_pricing_status(
    refresh: bool = Query(False, description="Force refresh from Google pricing page"),
    _: User = Depends(require_role("admin")),
):
    """Return live Gemini rates plus Google Maps/Places unit prices used at Evecta."""
    if refresh or not get_live_snapshot().models:
        snap = await refresh_live_prices(force=refresh)
    else:
        snap = get_live_snapshot()
    maps_catalog = [
        GoogleMapsApiPriceItem(**row) for row in google_maps_pricing_catalog()
    ]
    return AiUsagePricingStatusResponse(
        **snap.as_status(),
        google_maps_apis=maps_catalog,
    )


@router.post("/recompute-costs", response_model=AiUsageRecomputeResponse)
async def ai_usage_recompute_costs(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    """
    Refresh live Gemini rates from Google's pricing page, then recalculate
    estimated_cost_usd for every AI usage event.
    Feature and token totals are unchanged; only dollar estimates are rewritten.
    """
    result = await recompute_ai_usage_costs(session)
    source = result.get("pricing_source") or "static"
    return AiUsageRecomputeResponse(
        **result,
        message=(
            f"Recalculated {result['updated']} events using live Gemini pricing ({source}). "
            f"Total cost ${result['total_cost_before_usd']:.4f} → ${result['total_cost_after_usd']:.4f}."
        ),
    )
