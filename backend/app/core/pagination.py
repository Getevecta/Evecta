"""Shared list pagination: page + per_page, with a hard maximum page size.

Campaign list endpoints previously mixed unbounded ``per_page`` values with
unpaginated full-table reads. All campaign lists go through these helpers.
"""
from __future__ import annotations

from math import ceil
from typing import Annotated, Any

from fastapi import Query

DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200

PageQuery = Annotated[int, Query(ge=1, description="1-based page number")]
PerPageQuery = Annotated[
    int,
    Query(ge=1, le=MAX_PER_PAGE, description=f"Page size (max {MAX_PER_PAGE})"),
]


def clamp_page(page: int) -> int:
    try:
        page = int(page)
    except (TypeError, ValueError):
        return DEFAULT_PAGE
    return max(DEFAULT_PAGE, page)


def clamp_per_page(per_page: int) -> int:
    try:
        per_page = int(per_page)
    except (TypeError, ValueError):
        return DEFAULT_PER_PAGE
    return min(max(1, per_page), MAX_PER_PAGE)


def normalize_pagination(page: int = DEFAULT_PAGE, per_page: int = DEFAULT_PER_PAGE) -> tuple[int, int, int]:
    """Return (page, per_page, offset) with bounds applied."""
    page = clamp_page(page)
    per_page = clamp_per_page(per_page)
    offset = (page - 1) * per_page
    return page, per_page, offset


def paginated_payload(
    items: list[Any],
    *,
    total_items: int,
    page: int,
    per_page: int,
) -> dict[str, Any]:
    total_pages = ceil(total_items / per_page) if total_items > 0 and per_page > 0 else 0
    return {
        "current_page": page,
        "per_page": per_page,
        "total_items": int(total_items),
        "total_pages": total_pages,
        "data": items,
    }
