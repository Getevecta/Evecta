"""Unit tests for grouped campaign status counts (poll/readiness paths)."""
from __future__ import annotations

from app.models.campaign_lead_email import (
    CampaignLeadEmail,
    ComplianceStatus,
    GenerationStatus,
    ReviewStatus,
)
from app.models.email_job import EmailJobStatus
from app.services.campaign_email_generation_service import _generation_status_summary
from app.services.campaign_email_review_service import _review_summary
from app.services.campaign_status_counts import (
    fold_generation_counts,
    generation_status_summary_from_counts,
    review_summary_from_groups,
    send_status_from_counts,
)


def test_generation_summary_from_counts_matches_row_summary():
    rows = [
        CampaignLeadEmail(
            generation_status=GenerationStatus.READY,
            compliance_status=ComplianceStatus.PASSED,
        ),
        CampaignLeadEmail(
            generation_status=GenerationStatus.FAILED,
            compliance_status=ComplianceStatus.FAILED,
        ),
        CampaignLeadEmail(
            generation_status=GenerationStatus.PENDING,
            compliance_status=ComplianceStatus.PENDING,
        ),
    ]
    from_rows = _generation_status_summary(rows, expected_total=4)
    groups = [
        (GenerationStatus.READY, ComplianceStatus.PASSED, ReviewStatus.PENDING, 1),
        (GenerationStatus.FAILED, ComplianceStatus.FAILED, ReviewStatus.PENDING, 1),
        (GenerationStatus.PENDING, ComplianceStatus.PENDING, ReviewStatus.PENDING, 1),
    ]
    by_gen, by_comp, row_count = fold_generation_counts(groups)
    from_counts = generation_status_summary_from_counts(
        by_gen, by_comp, row_count=row_count, expected_total=4
    )
    assert from_counts == from_rows
    assert from_counts["queued"] == 2  # 1 pending + 1 missing lead
    assert from_counts["ready"] == 1
    assert from_counts["failed"] == 1
    assert from_counts["is_complete"] is False


def test_review_summary_from_groups_matches_row_summary():
    rows = [
        CampaignLeadEmail(
            generation_status=GenerationStatus.READY,
            compliance_status=ComplianceStatus.PASSED,
            review_status=ReviewStatus.PENDING,
        ),
        CampaignLeadEmail(
            generation_status=GenerationStatus.READY,
            compliance_status=ComplianceStatus.PASSED,
            review_status=ReviewStatus.REJECTED,
        ),
        CampaignLeadEmail(
            generation_status=GenerationStatus.GENERATING,
            compliance_status=ComplianceStatus.PENDING,
            review_status=ReviewStatus.PENDING,
        ),
    ]
    from_rows = _review_summary(rows)
    groups = [
        (GenerationStatus.READY, ComplianceStatus.PASSED, ReviewStatus.PENDING, 1),
        (GenerationStatus.READY, ComplianceStatus.PASSED, ReviewStatus.REJECTED, 1),
        (GenerationStatus.GENERATING, ComplianceStatus.PENDING, ReviewStatus.PENDING, 1),
    ]
    from_groups = review_summary_from_groups(groups)
    assert from_groups == from_rows
    assert from_groups["approved"] == 1
    assert from_groups["rejected"] == 1
    assert from_groups["generation_in_progress"] == 1
    assert from_groups["can_launch"] is False


def test_review_summary_from_groups_empty():
    summary = review_summary_from_groups([])
    assert summary["has_per_lead_emails"] is False
    assert summary["total"] == 0
    assert summary["can_launch"] is False


def test_send_status_from_counts():
    result = send_status_from_counts(
        {
            EmailJobStatus.QUEUED.value: 146,
            EmailJobStatus.SENDING.value: 0,
            EmailJobStatus.SENT.value: 342,
            EmailJobStatus.FAILED.value: 12,
        },
        campaign_id="camp-1",
        campaign_status="ongoing",
    )
    assert result["total_jobs"] == 500
    assert result["queued"] == 146
    assert result["sent"] == 342
    assert result["failed"] == 12
    assert result["in_progress"] == 146
    assert result["is_complete"] is False
    assert result["progress_percent"] == 71


def test_send_status_complete_when_all_terminal():
    result = send_status_from_counts(
        {
            EmailJobStatus.QUEUED.value: 0,
            EmailJobStatus.SENDING.value: 0,
            EmailJobStatus.SENT.value: 8,
            EmailJobStatus.FAILED.value: 2,
        },
        campaign_id="camp-1",
        campaign_status="ongoing",
    )
    assert result["is_complete"] is True
    assert result["progress_percent"] == 100
