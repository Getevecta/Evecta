"""One grouped-usage query and row mapper for every admin analytics dimension.

Adding a cost field or changing filters happens here — not in six endpoint copies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Literal, Optional
from uuid import UUID

from sqlalchemy import Date, Select, cast, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import ColumnElement

from app.models.ai_usage_event import AiUsageEvent
from app.models.user import User
from app.utils.day_bounds import day_bounds

GroupByName = Literal["feature", "model", "day", "month", "user", "user_month"]
OrderKind = Literal["cost_desc", "first_asc", "first_desc", "first_desc_cost_desc"]

_METRIC_KEYS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_tokens",
    "total_tokens",
    "estimated_cost_usd",
    "request_count",
    "failed_count",
)


def failed_count_expr():
    return func.coalesce(
        func.sum(case((AiUsageEvent.status == "failed", 1), else_=0)),
        0,
    ).label("failed_count")


def usage_metric_columns() -> tuple:
    return (
        func.coalesce(func.sum(AiUsageEvent.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(AiUsageEvent.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(AiUsageEvent.reasoning_tokens), 0).label("reasoning_tokens"),
        func.coalesce(func.sum(AiUsageEvent.cached_tokens), 0).label("cached_tokens"),
        func.coalesce(func.sum(AiUsageEvent.total_tokens), 0).label("total_tokens"),
        func.coalesce(func.sum(AiUsageEvent.estimated_cost_usd), 0.0).label(
            "estimated_cost_usd"
        ),
        func.count(AiUsageEvent.id).label("request_count"),
        failed_count_expr(),
    )


def apply_usage_filters(
    stmt: Select,
    *,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    provider: Optional[str] = None,
    feature: Optional[str] = None,
    model: Optional[str] = None,
    user_id: Optional[UUID] = None,
) -> Select:
    start, end = day_bounds(from_date, to_date)
    if start is not None:
        stmt = stmt.where(AiUsageEvent.created_at >= start)
    if end is not None:
        stmt = stmt.where(AiUsageEvent.created_at <= end)
    if provider:
        stmt = stmt.where(AiUsageEvent.provider == provider)
    if feature:
        stmt = stmt.where(AiUsageEvent.feature == feature)
    if model:
        stmt = stmt.where(AiUsageEvent.model == model)
    if user_id is not None:
        stmt = stmt.where(AiUsageEvent.user_id == user_id)
    return stmt


def select_usage_metrics(*group_cols: ColumnElement[Any]) -> Select:
    if group_cols:
        return select(*group_cols, *usage_metric_columns())
    return select(*usage_metric_columns())


def with_usage_group(stmt: Select, *group_cols: ColumnElement[Any]) -> Select:
    if group_cols:
        return stmt.group_by(*group_cols)
    return stmt


def totals_kwargs(row: Any) -> dict[str, Any]:
    cost = row.estimated_cost_usd
    return {
        "input_tokens": int(row.input_tokens or 0),
        "output_tokens": int(row.output_tokens or 0),
        "reasoning_tokens": int(row.reasoning_tokens or 0),
        "cached_tokens": int(row.cached_tokens or 0),
        "total_tokens": int(row.total_tokens or 0),
        "estimated_cost_usd": round(float(cost or 0.0), 6),
        "request_count": int(row.request_count or 0),
        "failed_count": int(row.failed_count or 0),
    }


def day_column():
    return cast(AiUsageEvent.created_at, Date).label("day")


def month_start_column():
    return func.date_trunc("month", AiUsageEvent.created_at).label("month_start")


def year_month_from_trunc(value: Any) -> tuple[str, int, int] | None:
    if isinstance(value, datetime):
        year, month = value.year, value.month
    elif isinstance(value, date):
        year, month = value.year, value.month
    else:
        return None
    return f"{year:04d}-{month:02d}", year, month


def user_join_columns() -> tuple:
    return (AiUsageEvent.user_id, User.email, User.username)


def _map_feature(row: Any) -> dict[str, Any] | None:
    return {"key": str(row.feature), "feature": row.feature}


def _map_model(row: Any) -> dict[str, Any] | None:
    return {
        "key": f"{row.provider}:{row.model}",
        "provider": row.provider,
        "model": row.model,
    }


def _map_day(row: Any) -> dict[str, Any] | None:
    return {"key": str(row.day), "day": row.day}


def _map_month(row: Any) -> dict[str, Any] | None:
    parsed = year_month_from_trunc(row.month_start)
    if parsed is None:
        return None
    month, year, month_number = parsed
    return {
        "key": month,
        "month": month,
        "year": year,
        "month_number": month_number,
    }


def _map_user(row: Any) -> dict[str, Any] | None:
    key = str(row.user_id) if row.user_id is not None else (row.email or "unknown")
    return {
        "key": key,
        "user_id": row.user_id,
        "email": row.email,
        "username": row.username,
    }


def _map_user_month(row: Any) -> dict[str, Any] | None:
    month_dims = _map_month(row)
    if month_dims is None:
        return None
    user_dims = _map_user(row) or {}
    return {
        **user_dims,
        **month_dims,
        "key": f"{month_dims['key']}:{user_dims.get('key')}",
    }


@dataclass(frozen=True)
class GroupSpec:
    name: GroupByName
    columns: Callable[[], tuple]
    order: OrderKind
    join_user: bool = False
    map_row: Callable[[Any], dict[str, Any] | None] = lambda _row: None


GROUP_SPECS: dict[GroupByName, GroupSpec] = {
    "feature": GroupSpec(
        name="feature",
        columns=lambda: (AiUsageEvent.feature,),
        order="cost_desc",
        map_row=_map_feature,
    ),
    "model": GroupSpec(
        name="model",
        columns=lambda: (AiUsageEvent.provider, AiUsageEvent.model),
        order="cost_desc",
        map_row=_map_model,
    ),
    "day": GroupSpec(
        name="day",
        columns=lambda: (day_column(),),
        order="first_asc",
        map_row=_map_day,
    ),
    "month": GroupSpec(
        name="month",
        columns=lambda: (month_start_column(),),
        order="first_desc",
        map_row=_map_month,
    ),
    "user": GroupSpec(
        name="user",
        columns=user_join_columns,
        order="cost_desc",
        join_user=True,
        map_row=_map_user,
    ),
    "user_month": GroupSpec(
        name="user_month",
        columns=lambda: (month_start_column(), *user_join_columns()),
        order="first_desc_cost_desc",
        join_user=True,
        map_row=_map_user_month,
    ),
}


def _apply_group_order(stmt: Select, spec: GroupSpec, cols: tuple) -> Select:
    cost_desc = func.sum(AiUsageEvent.estimated_cost_usd).desc()
    if spec.order == "cost_desc":
        return stmt.order_by(cost_desc)
    if spec.order == "first_asc":
        return stmt.order_by(cols[0].asc())
    if spec.order == "first_desc":
        return stmt.order_by(cols[0].desc())
    return stmt.order_by(cols[0].desc(), cost_desc)


def grouped_usage_statement(
    group_by: GroupByName,
    **filters: Any,
) -> Select:
    spec = GROUP_SPECS[group_by]
    cols = spec.columns()
    stmt = select_usage_metrics(*cols)
    if spec.join_user:
        stmt = stmt.outerjoin(User, User.id == AiUsageEvent.user_id)
    stmt = with_usage_group(stmt, *cols)
    stmt = apply_usage_filters(stmt, **filters)
    return _apply_group_order(stmt, spec, cols)


def grouped_item_from_row(group_by: GroupByName, row: Any) -> dict[str, Any] | None:
    spec = GROUP_SPECS[group_by]
    dims = spec.map_row(row)
    if dims is None:
        return None
    return {"group_by": spec.name, **dims, **totals_kwargs(row)}


async def fetch_usage_totals(
    session: AsyncSession,
    **filters: Any,
) -> dict[str, Any]:
    stmt = apply_usage_filters(select_usage_metrics(), **filters)
    row = (await session.execute(stmt)).one()
    return totals_kwargs(row)


async def fetch_usage_grouped(
    session: AsyncSession,
    group_by: GroupByName,
    **filters: Any,
) -> list[dict[str, Any]]:
    """Sum usage metrics bucketed by ``group_by`` (feature, model, day, …)."""
    rows = (await session.execute(grouped_usage_statement(group_by, **filters))).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = grouped_item_from_row(group_by, row)
        if item is not None:
            items.append(item)
    return items


METRIC_KEYS = _METRIC_KEYS
