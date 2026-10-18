"""Operational alerts for security-sensitive failures.

Signature-forgery attempts against the SES/SNS webhook must be visible to
on-call: a stable CRITICAL log line (for CloudWatch/Datadog monitors) plus a
Redis counter that can be scraped. Persistence must never break the 403 path.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SNS_SIGNATURE_FAILURE_MARKER = "[SNS_SIGNATURE_FAILURE]"
_REDIS_COUNTER_KEY = "alert:sns_signature_failures"
_REDIS_COUNTER_TTL_SECONDS = 24 * 3600


def record_sns_signature_failure_sync(*, reason: str, detail: str = "") -> None:
    logger.critical(
        "%s reason=%s detail=%s",
        SNS_SIGNATURE_FAILURE_MARKER,
        reason,
        (detail or "")[:200],
    )
    try:
        from app.utils.redis_context import REDIS_AVAILABLE, redis_client

        if not REDIS_AVAILABLE or redis_client is None:
            return
        count = int(redis_client.incr(_REDIS_COUNTER_KEY) or 0)
        if count == 1:
            redis_client.expire(_REDIS_COUNTER_KEY, _REDIS_COUNTER_TTL_SECONDS)
    except Exception:
        logger.warning("Failed to increment SNS signature-failure counter", exc_info=True)


async def record_sns_signature_failure(*, reason: str, detail: str = "") -> None:
    from app.utils.redis_context import arun

    await arun(record_sns_signature_failure_sync, reason=reason, detail=detail)
