"""
Compliance gate for per-lead email generation (Step 4).

Combines hard-blocked phrases from the email engine rules with the spam checker
LLM score gate used in campaign draft generation.
"""
from __future__ import annotations

import re
from typing import Any

from app.email_engine.loader import get_prohibited_phrases
from app.utils.spam_checker import check_email_spam

OUTREACH_READY_MIN_SCORE = 58  # inbox safety % (100 - spam_score)

_AGGRESSIVE_SALES_PATTERNS = [
    r"\bact\s+now\b",
    r"\blimited\s+time\b",
    r"\bguaranteed\s+results?\b",
    r"\b100%\s+free\b",
    r"\bclick\s+here\b",
    r"\bno\s+obligation\b",
    r"\bexclusive\s+offer\b",
]


def strip_html_for_check(html_text: str) -> str:
    text = re.sub(r"<[^>]+>", "", html_text or "")
    return (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .strip()
    )


def hard_phrase_violations(subject: str, body: str) -> list[str]:
    """Return prohibited phrases found in subject/body (case-insensitive)."""
    text = f"{subject} {body}".lower()
    violations: list[str] = []
    for phrase in get_prohibited_phrases():
        p = (phrase or "").strip().lower()
        if p and p in text:
            violations.append(phrase)
    return violations


def aggressive_sales_violations(subject: str, body: str) -> list[str]:
    text = f"{subject} {body}".lower()
    hits: list[str] = []
    for pattern in _AGGRESSIVE_SALES_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            hits.append(pattern)
    return hits


def draft_quality_violations(subject: str, body: str) -> list[str]:
    """Hard-block obvious AI glitches / broken grammar that spam score alone may miss."""
    text = f"{subject} {body}"
    violations: list[str] = []

    # Merged words: "Ifantastic" instead of "It's fantastic"
    if re.search(r"\bIf[a-z]{3,}\b", text) or re.search(
        r"\bIf(?![\s,.:;'\"])([a-z]{2,})", text
    ):
        violations.append(
            "typo: merged word starting with 'If' (e.g. 'Ifantastic' — use 'It's fantastic')"
        )

    # Broken clause: "If this like it could be helpful"
    if re.search(r"\bif this like\b", text, re.IGNORECASE):
        violations.append(
            "grammar: 'If this like' — likely missing a word (e.g. 'If this sounds like')"
        )

    return violations


async def evaluate_email_compliance(
    *,
    subject: str,
    body: str,
    user_profile: dict | None = None,
    company_profile: dict | None = None,
    fast_mode: bool = True,
    user_id=None,
) -> dict[str, Any]:
    """
    Run compliance checks on a draft email.

    Returns dict with keys: passed, spam_score, risk_level, inbox_safety_score,
    violations (list[str]).
    """
    plain_subject = strip_html_for_check(subject)
    plain_body = strip_html_for_check(body)
    violations: list[str] = []

    violations.extend(hard_phrase_violations(plain_subject, plain_body))
    violations.extend(aggressive_sales_violations(plain_subject, plain_body))
    violations.extend(draft_quality_violations(plain_subject, plain_body))

    if violations:
        return {
            "passed": False,
            "spam_score": None,
            "risk_level": "blocked",
            "inbox_safety_score": 0,
            "violations": violations,
        }

    # Fast path scores only. Strict retries (fast_mode=False) use the full
    # checker so rewrite + validate + regenerate can actually run.
    spam_result = await check_email_spam(
        subject=plain_subject,
        body=plain_body,
        user_profile=user_profile,
        company_profile=company_profile,
        fast_mode=fast_mode,
        score_only=fast_mode,
        user_id=user_id,
    )
    spam_score = int(spam_result.get("spam_score", 100))
    inbox_safety = 100 - spam_score
    risk_level = spam_result.get("risk_level") or "unknown"

    passed = inbox_safety >= OUTREACH_READY_MIN_SCORE
    if not passed:
        violations.append(
            f"inbox_safety_below_threshold ({inbox_safety}% < {OUTREACH_READY_MIN_SCORE}%)"
        )

    return {
        "passed": passed,
        "spam_score": spam_score,
        "risk_level": risk_level,
        "inbox_safety_score": inbox_safety,
        "violations": violations,
        "rewritten_subject": spam_result.get("rewritten_subject"),
        "rewritten_body": spam_result.get("rewritten_body"),
        "rewritten_spam_score": spam_result.get("rewritten_spam_score"),
        "rewritten_risk_level": spam_result.get("rewritten_risk_level"),
    }


def apply_compliance_rewrite_if_ready(
    *,
    subject: str,
    body: str,
    result: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Adopt a validated spam-checker rewrite when the original draft failed the gate."""
    if result.get("passed"):
        return subject, body, result

    rewritten_subject = (result.get("rewritten_subject") or "").strip()
    rewritten_body = (result.get("rewritten_body") or "").strip()
    rewritten_score = result.get("rewritten_spam_score")
    if rewritten_score is None or not rewritten_subject or not rewritten_body:
        return subject, body, result

    inbox_safety = 100 - int(rewritten_score)
    if inbox_safety < OUTREACH_READY_MIN_SCORE:
        return subject, body, result

    rewrite_violations: list[str] = []
    rewrite_violations.extend(hard_phrase_violations(rewritten_subject, rewritten_body))
    rewrite_violations.extend(aggressive_sales_violations(rewritten_subject, rewritten_body))
    rewrite_violations.extend(draft_quality_violations(rewritten_subject, rewritten_body))
    if rewrite_violations:
        return subject, body, result

    adopted = {
        **result,
        "passed": True,
        "spam_score": int(rewritten_score),
        "risk_level": result.get("rewritten_risk_level") or "Low",
        "inbox_safety_score": inbox_safety,
        "violations": [],
        "used_rewrite": True,
    }
    return rewritten_subject, rewritten_body, adopted
