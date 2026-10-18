"""Unit tests for Step 4 — per-lead email generation + compliance gate."""
from __future__ import annotations

import pytest

from app.email_engine.repetition import is_too_similar
from app.models.campaign import Campaign, DraftType
from app.models.campaign_lead_email import (
    CampaignLeadEmail,
    ComplianceStatus,
    GenerationStatus,
)
from app.services.campaign_email_generation_service import (
    _campaign_uses_ai_per_lead_generation,
    _generation_status_summary,
)
from app.utils.ai_email_generator import (
    _apply_lead_placeholders,
    _apply_sender_name_to_email,
    _flatten_lead_context,
    _format_lead_facts_block,
    _prior_emails_avoid_section,
    resolve_sender_display_name,
)
from app.services.compliance_gate import (
    aggressive_sales_violations,
    hard_phrase_violations,
    strip_html_for_check,
)


def test_strip_html_for_check():
    assert strip_html_for_check("<p>Hello <b>world</b></p>") == "Hello world"


def test_hard_phrase_violations_detects_blocked_phrases():
    violations = hard_phrase_violations("Free money", "Click here now for guaranteed results")
    assert violations  # at least one prohibited phrase from rules


def test_aggressive_sales_violations():
    hits = aggressive_sales_violations("Act now!", "Limited time offer inside")
    assert hits


def test_is_too_similar_flags_near_duplicates():
    a = "We help {{ business_name }} grow in {{ industry }} with proven outreach."
    b = "We help {{ business_name }} grow in {{ industry }} with proven outreach."
    assert is_too_similar(a, [b])


def test_is_too_similar_allows_distinct_emails():
    a = "Quick idea for {{ business_name }} in {{ industry }} — partnership angle."
    b = "Noticed {{ business_name }} serves {{ address }} — thought a short intro might help."
    assert not is_too_similar(a, [b])


def test_generation_status_summary_empty():
    summary = _generation_status_summary([])
    assert summary["total"] == 0
    assert summary["is_complete"] is False


def test_generation_status_summary_expected_total_includes_missing_leads():
    rows = [
        CampaignLeadEmail(
            generation_status=GenerationStatus.READY,
            compliance_status=ComplianceStatus.PASSED,
        ),
        CampaignLeadEmail(
            generation_status=GenerationStatus.READY,
            compliance_status=ComplianceStatus.PASSED,
        ),
    ]
    summary = _generation_status_summary(rows, expected_total=3)
    assert summary["total"] == 3
    assert summary["ready"] == 2
    assert summary["queued"] == 1
    assert summary["is_complete"] is False


def test_generation_status_summary_complete():
    rows = [
        CampaignLeadEmail(
            generation_status=GenerationStatus.READY,
            compliance_status=ComplianceStatus.PASSED,
        ),
        CampaignLeadEmail(
            generation_status=GenerationStatus.FAILED,
            compliance_status=ComplianceStatus.FAILED,
        ),
    ]
    summary = _generation_status_summary(rows)
    assert summary["total"] == 2
    assert summary["complete"] == 2
    assert summary["is_complete"] is True
    assert summary["ready"] == 1
    assert summary["failed"] == 1


def test_generation_status_summary_not_complete_while_generating():
    rows = [
        CampaignLeadEmail(
            generation_status=GenerationStatus.READY,
            compliance_status=ComplianceStatus.PASSED,
        ),
        CampaignLeadEmail(
            generation_status=GenerationStatus.GENERATING,
            compliance_status=ComplianceStatus.PENDING,
        ),
    ]
    summary = _generation_status_summary(rows)
    assert summary["is_complete"] is False
    assert summary["generating"] == 1


def test_flatten_lead_context_merges_nested_context():
    flat = _flatten_lead_context(
        {
            "business_name": "Acme Ltd",
            "industry": "Retail",
            "context": {"website_summary": "Independent bookshop in London"},
        }
    )
    assert flat["business_name"] == "Acme Ltd"
    assert flat["website_summary"] == "Independent bookshop in London"


def test_format_lead_facts_block_includes_enrichment():
    block = _format_lead_facts_block(
        {
            "business_name": "ICA Bookshop",
            "address": "London",
            "context": {"services": "Contemporary art books"},
        }
    )
    assert "ICA Bookshop" in block
    assert "London" in block
    assert "Contemporary art books" in block


def test_apply_lead_placeholders_replaces_merge_fields():
    out = _apply_lead_placeholders(
        "<p>Hi {{ business_name }}, welcome from {{ address }}</p>",
        {"business_name": "The Comedy Store UK", "address": "London"},
    )
    assert "The Comedy Store UK" in out
    assert "London" in out
    assert "{{" not in out


def test_prior_emails_avoid_section_lists_snippets():
    section = _prior_emails_avoid_section(
        ["<p>First unique outreach about comedy venues.</p>"]
    )
    assert "OTHER LEADS" in section
    assert "comedy venues" in section


def test_campaign_uses_ai_per_lead_generation():
    campaign = Campaign()
    campaign.draft_type = DraftType.AI
    assert _campaign_uses_ai_per_lead_generation(campaign) is True
    campaign.draft_type = DraftType.TEMPLATE
    assert _campaign_uses_ai_per_lead_generation(campaign) is False


def test_chunk_ranges_for_pending_splits_contiguous_leads():
    from app.services.campaign_email_generation_service import (
        GENERATION_CHUNK_SIZE,
        _chunk_ranges_for_pending,
    )

    pending = list(range(500))
    ranges = _chunk_ranges_for_pending(pending, GENERATION_CHUNK_SIZE)
    assert ranges[0] == (0, 25)
    assert ranges[1] == (25, 25)
    assert ranges[-1] == (475, 25)
    assert len(ranges) == 20


def test_chunk_ranges_for_pending_skips_gaps():
    from app.services.campaign_email_generation_service import _chunk_ranges_for_pending

    ranges = _chunk_ranges_for_pending([10, 11, 200], 25)
    assert ranges == [(10, 25), (200, 25)]


def test_chunk_ranges_empty():
    from app.services.campaign_email_generation_service import _chunk_ranges_for_pending

    assert _chunk_ranges_for_pending([], 25) == []


def test_generation_chunk_concurrency_is_bounded():
    from app.services.campaign_email_generation_service import GENERATION_CHUNK_CONCURRENCY

    assert 3 <= GENERATION_CHUNK_CONCURRENCY <= 5


def test_instant_lead_count_is_background_only():
    """POST /generate must not block on inline LLM work (gateway 504 risk)."""
    from app.services.campaign_email_generation_service import INSTANT_LEAD_COUNT

    assert INSTANT_LEAD_COUNT == 0


def test_resolve_sender_display_name_prefers_full_name_then_username():
    assert resolve_sender_display_name({"full_name": "Sushma Sharma"}) == "Sushma Sharma"
    assert resolve_sender_display_name({"username": "sushma"}) == "sushma"
    assert (
        resolve_sender_display_name({"email": "sushma.sharma.tech.np@gmail.com"})
        == "Sushma Sharma Tech Np"
    )


def test_apply_sender_name_to_email_replaces_signature_placeholder():
    subject, body = _apply_sender_name_to_email(
        "Hello",
        "<p>Best regards,</p>\n<p>[Your Name]</p>",
        "sushma",
    )
    assert subject == "Hello"
    assert "<p>sushma</p>" in body
    assert "[Your Name]" not in body
