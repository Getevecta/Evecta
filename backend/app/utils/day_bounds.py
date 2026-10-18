from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Optional


def day_bounds(
    from_date: Optional[date],
    to_date: Optional[date],
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Inclusive UTC datetime window for a from/to calendar date filter."""
    start = (
        datetime.combine(from_date, time.min, tzinfo=timezone.utc)
        if from_date
        else None
    )
    end = (
        datetime.combine(to_date, time.max, tzinfo=timezone.utc)
        if to_date
        else None
    )
    return start, end
