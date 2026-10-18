"""Unit tests for Step 6 — campaign launch readiness."""
from __future__ import annotations

from app.services.campaign_launch_readiness_service import _build_response, _check_item


def test_check_item_structure():
    item = _check_item("draft", "Email draft", True, "OK")
    assert item["key"] == "draft"
    assert item["passed"] is True


def _mock_campaign():
    return type(
        "C",
        (),
        {
            "id": "x",
            "status": type("S", (), {"value": "draft"})(),
            "email_sending_mode": None,
        },
    )()


def test_build_response_can_launch_when_all_pass():
    checks = [
        _check_item("a", "A", True, "ok"),
        _check_item("b", "B", True, "ok"),
    ]
    result = _build_response(
        _mock_campaign(),
        checks,
        [],
        approved_to_send=3,
        skipped_rejected=1,
    )
    assert result["can_launch"] is True
    assert result["approved_to_send"] == 3
    assert result["skipped_rejected"] == 1


def test_build_response_blocked_with_blockers():
    checks = [_check_item("review", "Review", False, "pending")]
    result = _build_response(
        _mock_campaign(),
        checks,
        ["Review pending"],
        approved_to_send=0,
        skipped_rejected=0,
    )
    assert result["can_launch"] is False
    assert "Review pending" in result["launch_blockers"]
