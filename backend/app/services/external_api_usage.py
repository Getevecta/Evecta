from __future__ import annotations

import logging
import uuid
from typing import Optional, Union
from uuid import UUID

from app.services.external_api_pricing import estimate_cost_usd, places_is_billable

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


async def record_external_api_usage(
    *,
    provider: str,
    api_name: str,
    feature: str = "unknown",
    user_id: Optional[Union[str, UUID]] = None,
    units: int = 0,
    status: str = "success",
    http_status: Optional[int] = None,
    latency_ms: Optional[int] = None,
    meta: Optional[str] = None,
) -> None:
    """Persist one metered external API call. Never raises to the caller."""
    try:
        cost, unit_cost = estimate_cost_usd(provider, api_name, int(units or 0))
        from app.database.session import async_session_factory
        from app.models.external_api_usage_event import ExternalApiUsageEvent

        async with async_session_factory() as session:
            event = ExternalApiUsageEvent(
                id=uuid.uuid4(),
                user_id=_coerce_user_id(user_id),
                provider=(provider or "unknown")[:32],
                api_name=(api_name or "unknown")[:64],
                feature=(feature or "unknown")[:64],
                units=max(0, int(units or 0)),
                unit_cost_usd=unit_cost,
                estimated_cost_usd=cost,
                latency_ms=latency_ms,
                http_status=http_status,
                status=(status or "success")[:16],
                meta=(meta[:256] if meta else None),
            )
            session.add(event)
            await session.commit()
    except Exception:
        logger.warning(
            "[EXT_API_USAGE] Failed to persist provider=%s api=%s feature=%s",
            provider,
            api_name,
            feature,
            exc_info=True,
        )


async def record_hunter_usage(
    *,
    api_name: str,
    http_status: Optional[int],
    latency_ms: int,
    feature: str = "email_enrichment",
    user_id: Optional[Union[str, UUID]] = None,
    meta: Optional[str] = None,
) -> None:
    """Hunter burns 1 credit on HTTP 200; other statuses are recorded as failed/0 units."""
    ok = http_status == 200
    await record_external_api_usage(
        provider="hunter",
        api_name=api_name,
        feature=feature,
        user_id=user_id,
        units=1 if ok else 0,
        status="success" if ok else "failed",
        http_status=http_status,
        latency_ms=latency_ms,
        meta=meta,
    )


async def record_places_usage(
    *,
    api_name: str,
    google_status: Optional[str],
    http_status: Optional[int],
    latency_ms: int,
    feature: str = "lead_search",
    user_id: Optional[Union[str, UUID]] = None,
    meta: Optional[str] = None,
) -> None:
    gs = (google_status or "").upper()
    billable = places_is_billable(gs)
    if gs == "ZERO_RESULTS":
        status = "zero_results"
    elif billable:
        status = "success"
    else:
        status = "failed"
    await record_external_api_usage(
        provider="google_places",
        api_name=api_name,
        feature=feature,
        user_id=user_id,
        units=1 if billable else 0,
        status=status,
        http_status=http_status,
        latency_ms=latency_ms,
        meta=meta,
    )
