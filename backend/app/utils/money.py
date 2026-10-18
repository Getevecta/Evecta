"""Exact decimal helpers for stored USD rates and estimated costs."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

# Matches Numeric(18, 8) / Numeric(18, 10) columns.
COST_QUANTUM = Decimal("0.00000001")
RATE_QUANTUM = Decimal("0.0000000001")


def as_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_cost(value) -> Decimal:
    return as_decimal(value).quantize(COST_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_rate(value) -> Optional[Decimal]:
    if value is None:
        return None
    return as_decimal(value).quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)
