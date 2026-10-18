"""Recompute estimated_cost_usd on ai_usage_events from current Gemini list prices."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decimal import Decimal

from app.models.ai_usage_event import AiUsageEvent
from app.services.ai.dynamic_pricing import refresh_live_prices
from app.services.ai.pricing import estimate_cost_from_event_fields
from app.utils.money import as_decimal

logger = logging.getLogger(__name__)

_BATCH = 500


async def recompute_ai_usage_costs(db: AsyncSession) -> dict[str, Any]:
    """
    Refresh live Gemini list prices, then rewrite estimated_cost_usd for every
    usage event. Keeps feature/model/token fields intact.
    """
    pricing = await refresh_live_prices(force=True)

    updated = 0
    unchanged = 0
    total_before = Decimal("0")
    total_after = Decimal("0")
    offset = 0

    while True:
        result = await db.execute(
            select(AiUsageEvent)
            .order_by(AiUsageEvent.created_at.asc())
            .offset(offset)
            .limit(_BATCH)
        )
        rows = list(result.scalars().all())
        if not rows:
            break

        for event in rows:
            before = as_decimal(event.estimated_cost_usd)
            total_before += before
            cost, in_rate, out_rate = estimate_cost_from_event_fields(
                provider=event.provider or "gemini",
                model=event.model or "gemini-2.5-flash",
                input_tokens=int(event.input_tokens or 0),
                output_tokens=int(event.output_tokens or 0),
                reasoning_tokens=int(event.reasoning_tokens or 0),
                cached_tokens=int(event.cached_tokens or 0),
                total_tokens=int(event.total_tokens or 0),
            )
            total_after += cost
            if (
                before != cost
                or event.input_rate_per_million != in_rate
                or event.output_rate_per_million != out_rate
            ):
                event.estimated_cost_usd = cost
                event.input_rate_per_million = in_rate
                event.output_rate_per_million = out_rate
                updated += 1
            else:
                unchanged += 1

        await db.commit()
        offset += len(rows)
        if len(rows) < _BATCH:
            break

    logger.info(
        "Recomputed AI usage costs: updated=%s unchanged=%s before=$%.6f after=$%.6f source=%s",
        updated,
        unchanged,
        total_before,
        total_after,
        pricing.source,
    )
    return {
        "updated": updated,
        "unchanged": unchanged,
        "total_cost_before_usd": float(total_before),
        "total_cost_after_usd": float(total_after),
        "pricing_source": pricing.source,
        "pricing_source_url": pricing.source_url,
        "pricing_fingerprint": pricing.fingerprint,
        "pricing_error": pricing.error,
    }
