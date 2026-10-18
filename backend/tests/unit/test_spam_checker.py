"""score_only spam checks must honor fast_mode so try-harder retries see more text."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.utils import spam_checker
from app.utils.spam_checker import (
    _BODY_MAX_FAST,
    _BODY_MAX_FULL,
    _truncate_for_spam_llm,
    check_email_spam,
)


def test_truncate_fast_is_stricter_than_full():
    subject = "S" * 400
    body = "B" * 8000
    fast_s, fast_b = _truncate_for_spam_llm(subject, body, True)
    full_s, full_b = _truncate_for_spam_llm(subject, body, False)
    assert len(fast_s) < len(full_s)
    assert len(fast_b) < len(full_b)
    assert "…[truncated]" in fast_b
    assert "…[truncated]" not in full_b
    assert len(fast_b) <= _BODY_MAX_FAST + len("\n…[truncated]")
    assert len(full_b) <= _BODY_MAX_FULL + len("\n…[truncated]")


def test_score_only_strict_mode_sends_uncapped_fast_window():
    spam_checker._spam_check_cache.clear()
    captured: dict[str, str] = {}

    class _Resp:
        content = '{"spam_score":18,"risk_level":"Low"}'

    async def fake_invoke(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        return _Resp()

    # Long enough to hit the fast body cap but still under the full cap.
    body = "Hello {{ business_name }}, here is a detailed B2B note. " + ("value " * 900)

    async def run(fast_mode: bool) -> None:
        captured.clear()
        await check_email_spam(
            "Introducing our partnership offer",
            body,
            fast_mode=fast_mode,
            score_only=True,
        )

    with patch("app.utils.spam_checker.tracked_ainvoke", fake_invoke):
        asyncio.run(run(True))
        assert "…[truncated]" in captured["prompt"]
        asyncio.run(run(False))
        assert "…[truncated]" not in captured["prompt"]
        assert "value " * 20 in captured["prompt"]
