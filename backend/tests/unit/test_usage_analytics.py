"""Usage analytics query builder, indexes, and non-blocking pricing refresh."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.ai_usage_event import AiUsageEvent
from app.models.external_api_usage_event import ExternalApiUsageEvent
from app.services.ai import dynamic_pricing as dp
from app.services.ai.pricing import get_model_prices
from app.services.ai.usage_analytics import (
    GROUP_SPECS,
    apply_usage_filters,
    grouped_item_from_row,
    grouped_usage_statement,
    totals_kwargs,
    year_month_from_trunc,
)
from app.services.external_api_usage_analytics import (
    GROUP_SPECS as EXTERNAL_GROUP_SPECS,
    grouped_usage_statement as external_grouped_statement,
)


def _compile(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()


def _index_columns(table, name: str) -> tuple[str, ...]:
    for idx in table.indexes:
        if idx.name == name:
            return tuple(col.name for col in idx.columns)
    raise AssertionError(f"missing index {name}")


def test_ai_usage_indexes_match_filter_and_order_prefixes():
    table = AiUsageEvent.__table__
    assert _index_columns(table, "ix_ai_usage_events_created_at") == ("created_at",)
    assert _index_columns(table, "ix_ai_usage_events_provider_created") == (
        "provider",
        "created_at",
    )
    assert _index_columns(table, "ix_ai_usage_events_feature_created") == (
        "feature",
        "created_at",
    )
    assert _index_columns(table, "ix_ai_usage_events_model_created") == (
        "model",
        "created_at",
    )
    assert _index_columns(table, "ix_ai_usage_events_user_created") == (
        "user_id",
        "created_at",
    )


def test_external_usage_indexes_match_provider_then_created_at():
    table = ExternalApiUsageEvent.__table__
    assert _index_columns(table, "ix_external_api_usage_events_provider_created") == (
        "provider",
        "created_at",
    )
    assert _index_columns(
        table, "ix_external_api_usage_events_provider_api_created"
    ) == ("provider", "api_name", "created_at")


def test_ai_events_query_uses_provider_and_created_at():
    stmt = apply_usage_filters(
        select(AiUsageEvent),
        provider="gemini",
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 31),
    ).order_by(AiUsageEvent.created_at.desc())
    sql = _compile(stmt)
    assert "ai_usage_events" in sql
    assert "provider" in sql
    assert "created_at" in sql
    assert "order by" in sql


def test_group_specs_cover_admin_dimensions():
    assert set(GROUP_SPECS) == {
        "feature",
        "model",
        "day",
        "month",
        "user",
        "user_month",
    }
    assert set(EXTERNAL_GROUP_SPECS) == {"api", "day"}


def test_grouped_usage_queries_share_metric_select_list():
    feature_sql = _compile(grouped_usage_statement("feature", provider="gemini"))
    day_sql = _compile(grouped_usage_statement("day", provider="gemini"))
    month_sql = _compile(grouped_usage_statement("month", provider="gemini"))
    for sql in (feature_sql, day_sql, month_sql):
        assert "sum(ai_usage_events.input_tokens)" in sql
        assert "sum(ai_usage_events.estimated_cost_usd)" in sql
        assert "group by" in sql
    assert "ai_usage_events.feature" in feature_sql
    assert "cast(ai_usage_events.created_at as date)" in day_sql
    assert "date_trunc" in month_sql


def test_by_user_query_joins_then_groups():
    sql = _compile(grouped_usage_statement("user", provider="gemini"))
    assert "left outer join users" in sql
    assert "group by" in sql
    assert "ai_usage_events.user_id" in sql


def test_external_grouped_queries_share_metric_select_list():
    by_api = _compile(
        external_grouped_statement(
            "api",
            provider="hunter",
            from_date=date(2026, 1, 1),
        )
    )
    assert "external_api_usage_events.provider" in by_api
    assert "group by" in by_api
    assert "sum(external_api_usage_events.units)" in by_api
    assert "api_name" in by_api


def test_grouped_item_from_row_keeps_dimension_fields():
    class Row:
        feature = "spam_score"
        input_tokens = 10
        output_tokens = 2
        reasoning_tokens = 0
        cached_tokens = 0
        total_tokens = 12
        estimated_cost_usd = 0.5
        request_count = 3
        failed_count = 1

    item = grouped_item_from_row("feature", Row())
    assert item is not None
    assert item["group_by"] == "feature"
    assert item["key"] == "spam_score"
    assert item["feature"] == "spam_score"
    assert item["request_count"] == 3


def test_year_month_from_trunc():
    parsed = year_month_from_trunc(datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert parsed == ("2026-08", 2026, 8)
    assert year_month_from_trunc("nope") is None


def test_totals_kwargs_rounds_cost():
    class Row:
        input_tokens = 10
        output_tokens = 2
        reasoning_tokens = 0
        cached_tokens = 0
        total_tokens = 12
        estimated_cost_usd = 0.1234567
        request_count = 1
        failed_count = 0

    kwargs = totals_kwargs(Row())
    assert kwargs["estimated_cost_usd"] == 0.123457
    assert kwargs["input_tokens"] == 10


def test_async_cost_path_does_not_call_sync_http_refresh():
    async def run():
        dp._refresh_task = None
        with (
            patch.object(dp, "_in_pytest", return_value=False),
            patch.object(dp, "_cache_is_fresh", return_value=False),
            patch.object(dp, "refresh_live_prices_sync") as sync_fn,
            patch.object(dp, "refresh_live_prices", new_callable=AsyncMock) as async_fn,
        ):
            get_model_prices("gemini", "gemini-2.5-flash")
            sync_fn.assert_not_called()
            await asyncio.sleep(0)
            async_fn.assert_awaited()
            if dp._refresh_task is not None:
                await dp._refresh_task

    asyncio.run(run())


def test_sync_cost_path_still_refreshes_inline():
    dp._refresh_task = None
    with (
        patch.object(dp, "_in_pytest", return_value=False),
        patch.object(dp, "_cache_is_fresh", return_value=False),
        patch.object(dp, "refresh_live_prices_sync") as sync_fn,
        patch.object(dp, "refresh_live_prices", new_callable=AsyncMock) as async_fn,
    ):
        get_model_prices("gemini", "gemini-2.5-flash")
        sync_fn.assert_called_once()
        async_fn.assert_not_called()
