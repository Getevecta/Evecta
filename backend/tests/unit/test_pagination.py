"""Unit tests for shared campaign list pagination bounds."""
from __future__ import annotations

from app.core.pagination import (
    DEFAULT_PAGE,
    DEFAULT_PER_PAGE,
    MAX_PER_PAGE,
    clamp_page,
    clamp_per_page,
    normalize_pagination,
    paginated_payload,
)


def test_clamp_page_rejects_zero_and_negative():
    assert clamp_page(0) == DEFAULT_PAGE
    assert clamp_page(-3) == DEFAULT_PAGE
    assert clamp_page(4) == 4


def test_clamp_per_page_enforces_max():
    assert clamp_per_page(0) == 1
    assert clamp_per_page(-10) == 1
    assert clamp_per_page(50) == 50
    assert clamp_per_page(1000) == MAX_PER_PAGE
    assert MAX_PER_PAGE == 200


def test_normalize_pagination_offset():
    page, per_page, offset = normalize_pagination(3, 50)
    assert page == 3
    assert per_page == 50
    assert offset == 100


def test_normalize_pagination_caps_huge_page_size():
    page, per_page, offset = normalize_pagination(1, 10_000)
    assert page == 1
    assert per_page == MAX_PER_PAGE
    assert offset == 0


def test_paginated_payload_shape():
    payload = paginated_payload(["a", "b"], total_items=201, page=1, per_page=200)
    assert payload["current_page"] == 1
    assert payload["per_page"] == 200
    assert payload["total_items"] == 201
    assert payload["total_pages"] == 2
    assert payload["data"] == ["a", "b"]


def test_paginated_payload_empty():
    payload = paginated_payload([], total_items=0, page=1, per_page=DEFAULT_PER_PAGE)
    assert payload["total_pages"] == 0
    assert payload["data"] == []
