"""Unit tests for email compliance / quality gate."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.services.compliance_gate import (
    OUTREACH_READY_MIN_SCORE,
    apply_compliance_rewrite_if_ready,
    draft_quality_violations,
    evaluate_email_compliance,
)


def test_draft_quality_flags_ifantastic_typo():
    body = "Ifantastic to see the energy you bring to the community."
    hits = draft_quality_violations("", body)
    assert any("Ifantastic" in h or "merged word" in h for h in hits)


def test_draft_quality_flags_if_this_like():
    body = "If this like it could be helpful for your store."
    hits = draft_quality_violations("", body)
    assert any("If this like" in h for h in hits)


def test_draft_quality_clean_copy():
    body = (
        "It's fantastic to see the energy you bring. "
        "If this sounds like it could be helpful, just reply yes."
    )
    assert draft_quality_violations("", body) == []


def test_outreach_ready_threshold_is_58():
    assert OUTREACH_READY_MIN_SCORE == 58


_CLEAN_BODY = (
    "Hello {{ business_name }}, I noticed your work in {{ industry }} and thought a "
    "short introduction might be useful. If this sounds relevant, just reply yes."
)


def test_fast_compliance_uses_score_only_spam_check():
    captured: dict = {}

    async def fake_check(**kwargs):
        captured.update(kwargs)
        return {"spam_score": 10, "risk_level": "Low"}

    async def run():
        with patch("app.services.compliance_gate.check_email_spam", fake_check):
            return await evaluate_email_compliance(
                subject="Introducing a partnership",
                body=_CLEAN_BODY,
                fast_mode=True,
            )

    result = asyncio.run(run())
    assert captured["fast_mode"] is True
    assert captured["score_only"] is True
    assert result["passed"] is True


def test_strict_compliance_uses_full_spam_checker():
    captured: dict = {}

    async def fake_check(**kwargs):
        captured.update(kwargs)
        return {
            "spam_score": 50,
            "risk_level": "Medium",
            "rewritten_subject": "Partnership idea",
            "rewritten_body": _CLEAN_BODY,
            "rewritten_spam_score": 12,
            "rewritten_risk_level": "Low",
        }

    async def run():
        with patch("app.services.compliance_gate.check_email_spam", fake_check):
            return await evaluate_email_compliance(
                subject="Introducing a partnership",
                body=_CLEAN_BODY,
                fast_mode=False,
            )

    result = asyncio.run(run())
    assert captured["fast_mode"] is False
    assert captured["score_only"] is False
    assert result["passed"] is False
    assert result["rewritten_spam_score"] == 12


def test_apply_rewrite_when_original_failed_and_rewrite_is_ready():
    result = {
        "passed": False,
        "spam_score": 80,
        "rewritten_subject": "Partnership idea",
        "rewritten_body": _CLEAN_BODY,
        "rewritten_spam_score": 12,
        "rewritten_risk_level": "Low",
        "violations": ["inbox_safety_below_threshold (20% < 58%)"],
    }
    subject, body, adopted = apply_compliance_rewrite_if_ready(
        subject="Act now for free money",
        body="Click here",
        result=result,
    )
    assert subject == "Partnership idea"
    assert body == _CLEAN_BODY
    assert adopted["passed"] is True
    assert adopted["used_rewrite"] is True
    assert adopted["spam_score"] == 12


def test_apply_rewrite_skips_when_score_only_left_rewrite_unvalidated():
    result = {
        "passed": False,
        "spam_score": 80,
        "rewritten_subject": "Partnership idea",
        "rewritten_body": _CLEAN_BODY,
        "rewritten_spam_score": None,
        "violations": ["inbox_safety_below_threshold"],
    }
    subject, body, adopted = apply_compliance_rewrite_if_ready(
        subject="Original subject",
        body="Original body",
        result=result,
    )
    assert subject == "Original subject"
    assert body == "Original body"
    assert adopted["passed"] is False
