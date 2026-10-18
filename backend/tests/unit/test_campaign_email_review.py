"""Unit tests for Step 5 — per-lead email review."""
from __future__ import annotations

from app.models.campaign_lead_email import (
    CampaignLeadEmail,
    ComplianceStatus,
    GenerationStatus,
    ReviewStatus,
)
from app.services.campaign_email_review_service import (
    _review_summary,
    approved_lead_ids,
    get_launch_review_blocker,
)


def _row(
    *,
    gs=GenerationStatus.READY,
    cs=ComplianceStatus.PASSED,
    rs=ReviewStatus.PENDING,
    lead_id="lead-1",
):
    return CampaignLeadEmail(
        generation_status=gs,
        compliance_status=cs,
        review_status=rs,
        lead_id=lead_id,
    )


def test_review_summary_empty():
    s = _review_summary([])
    assert s["has_per_lead_emails"] is False
    assert s["can_launch"] is False


def test_review_summary_blocks_when_pending():
    rows = [
        _row(cs=ComplianceStatus.FAILED),
        _row(lead_id="lead-2", rs=ReviewStatus.APPROVED),
    ]
    s = _review_summary(rows)
    assert s["pending_review"] == 1
    assert s["approved"] == 1
    assert s["can_launch"] is False


def test_review_summary_outreach_ready_pending_counts_as_approved():
    rows = [_row(), _row(lead_id="lead-2", rs=ReviewStatus.APPROVED)]
    s = _review_summary(rows)
    assert s["approved"] == 2
    assert s["can_launch"] is True


def test_review_summary_can_launch_when_all_approved():
    rows = [_row(rs=ReviewStatus.APPROVED), _row(lead_id="lead-2", rs=ReviewStatus.REJECTED)]
    s = _review_summary(rows)
    assert s["approved"] == 1
    assert s["rejected"] == 1
    assert s["can_launch"] is True


def test_review_summary_blocks_while_generating():
    rows = [_row(gs=GenerationStatus.GENERATING)]
    s = _review_summary(rows)
    assert s["can_launch"] is False
    assert s["generation_in_progress"] == 1


def test_approved_lead_ids():
    rows = [
        _row(rs=ReviewStatus.APPROVED, lead_id="a"),
        _row(rs=ReviewStatus.REJECTED, lead_id="b"),
    ]
    assert approved_lead_ids(rows) == {"a"}


def test_get_launch_review_blocker_none_without_rows():
    assert get_launch_review_blocker([]) is None
