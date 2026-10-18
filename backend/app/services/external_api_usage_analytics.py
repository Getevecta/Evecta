"""Shared Hunter / Places usage analytics query builder."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Literal, Optional

from sqlalchemy import Date, Select, cast, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import ColumnElement

from app.models.external_api_usage_event import ExternalApiUsageEvent
from app.utils.day_bounds import day_bounds

ALLOWED_PROVIDERS = frozenset({"hunter", "google_places"})
ExternalGroupBy = Literal["api", "day"]
OrderKind = Literal["cost_desc", "first_asc"]


def failed_count_expr():
    return func.coalesce(
        func.sum(case((ExternalApiUsageEvent.status == "failed", 1), else_=0)),
        0,
    ).label("failed_count")


def success_count_expr():
    return func.coalesce(
        func.sum(case((ExternalApiUsageEvent.status == "success", 1), else_=0)),
        0,
    ).label("success_count")


def usage_metric_columns(*, include_success: bool = False) -> tuple:
    cols = (
        func.coalesce(func.sum(ExternalApiUsageEvent.units), 0).label("total_units"),
        func.coalesce(func.sum(ExternalApiUsageEvent.estimated_cost_usd), 0.0).label(
            "estimated_cost_usd"
        ),
        func.count(ExternalApiUsageEvent.id).label("request_count"),
        failed_count_expr(),
    )
    if include_success:
        cols = (*cols, success_count_expr())
    return cols


def apply_usage_filters(
    stmt: Select,
    *,
    provider: str,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    api_name: Optional[str] = None,
    feature: Optional[str] = None,
) -> Select:
    stmt = stmt.where(ExternalApiUsageEvent.provider == provider)
    start, end = day_bounds(from_date, to_date)
    if start is not None:
        stmt = stmt.where(ExternalApiUsageEvent.created_at >= start)
    if end is not None:
        stmt = stmt.where(ExternalApiUsageEvent.created_at <= end)
    if api_name:
        stmt = stmt.where(ExternalApiUsageEvent.api_name == api_name)
    if feature:
        stmt = stmt.where(ExternalApiUsageEvent.feature == feature)
    return stmt


def select_usage_metrics(
    *group_cols: ColumnElement[Any],
    include_success: bool = False,
) -> Select:
    metrics = usage_metric_columns(include_success=include_success)
    if group_cols:
        return select(*group_cols, *metrics).group_by(*group_cols)
    return select(*metrics)


def totals_kwargs(row: Any) -> dict[str, Any]:
    return {
        "total_units": int(row.total_units or 0),
        "estimated_cost_usd": float(row.estimated_cost_usd or 0.0),
        "request_count": int(row.request_count or 0),
        "failed_count": int(row.failed_count or 0),
    }


def day_column():
    return cast(ExternalApiUsageEvent.created_at, Date).label("day")


def _map_api(row: Any) -> dict[str, Any] | None:
    return {"key": str(row.api_name), "api_name": row.api_name}


def _map_day(row: Any) -> dict[str, Any] | None:
    return {"key": str(row.day), "day": row.day}


@dataclass(frozen=True)
class GroupSpec:
    name: ExternalGroupBy
    columns: Callable[[], tuple]
    order: OrderKind
    map_row: Callable[[Any], dict[str, Any] | None]


GROUP_SPECS: dict[ExternalGroupBy, GroupSpec] = {
    "api": GroupSpec(
        name="api",
        columns=lambda: (ExternalApiUsageEvent.api_name,),
        order="cost_desc",
        map_row=_map_api,
    ),
    "day": GroupSpec(
        name="day",
        columns=lambda: (day_column(),),
        order="first_asc",
        map_row=_map_day,
    ),
}


def grouped_usage_statement(
    group_by: ExternalGroupBy,
    *,
    provider: str,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> Select:
    spec = GROUP_SPECS[group_by]
    cols = spec.columns()
    stmt = apply_usage_filters(
        select_usage_metrics(*cols),
        provider=provider,
        from_date=from_date,
        to_date=to_date,
    )
    if spec.order == "cost_desc":
        return stmt.order_by(func.sum(ExternalApiUsageEvent.estimated_cost_usd).desc())
    return stmt.order_by(cols[0].asc())


async def fetch_usage_grouped(
    session: AsyncSession,
    group_by: ExternalGroupBy,
    *,
    provider: str,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> list[dict[str, Any]]:
    if provider not in ALLOWED_PROVIDERS:
        return []
    spec = GROUP_SPECS[group_by]
    rows = (
        await session.execute(
            grouped_usage_statement(
                group_by, provider=provider, from_date=from_date, to_date=to_date
            )
        )
    ).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        dims = spec.map_row(row)
        if dims is None:
            continue
        items.append({"group_by": spec.name, **dims, **totals_kwargs(row)})
    return items
