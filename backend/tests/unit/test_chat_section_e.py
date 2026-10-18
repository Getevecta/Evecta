"""Section E: chat history compaction, Redis off-loop, insufficient-credits recovery."""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.services.understanding import _format_history
from app.utils.chat_history import (
    CHAT_HISTORY_MESSAGE_CHARS,
    CHAT_PROMPT_HISTORY_LIMIT,
    CHAT_STORED_HISTORY_LIMIT,
    compact_chat_history,
    format_chat_history_for_prompt,
)
from app.utils.chat_recovery import (
    build_chat_timeout_recovery,
    build_enrichment_timeout_recovery,
    build_insufficient_credits_recovery,
)
from app.utils.redis_context import arun


def test_compact_chat_history_keeps_last_n():
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "message": f"turn-{i}"}
        for i in range(50)
    ]
    out = compact_chat_history(history, limit=10)
    assert len(out) == 10
    assert out[0]["message"] == "turn-40"
    assert out[-1]["message"] == "turn-49"


def test_compact_chat_history_default_stored_limit():
    history = [{"role": "user", "message": str(i)} for i in range(CHAT_STORED_HISTORY_LIMIT + 15)]
    out = compact_chat_history(history)
    assert len(out) == CHAT_STORED_HISTORY_LIMIT
    assert out[0]["message"] == "15"
    assert out[-1]["message"] == str(CHAT_STORED_HISTORY_LIMIT + 14)


def test_compact_chat_history_truncates_long_messages():
    long_msg = "x" * (CHAT_HISTORY_MESSAGE_CHARS + 300)
    capped = compact_chat_history([{"role": "user", "message": long_msg}])
    assert capped[0]["message"].startswith("x" * CHAT_HISTORY_MESSAGE_CHARS)
    assert capped[0]["message"].endswith("…")
    assert len(capped[0]["message"]) == CHAT_HISTORY_MESSAGE_CHARS + 1


def test_format_chat_history_for_prompt_uses_prompt_window():
    history = [{"role": "user", "message": f"m{i}"} for i in range(30)]
    text = format_chat_history_for_prompt(history)
    assert "m0" not in text
    assert "m29" in text
    assert text.count("User:") == CHAT_PROMPT_HISTORY_LIMIT


def test_understanding_history_excludes_current_and_caps_window():
    history = [{"role": "user", "message": f"m{i}"} for i in range(30)]
    history.append({"role": "user", "message": "current-turn"})
    text = _format_history(history)
    assert "current-turn" not in text
    assert "m0" not in text
    assert "m29" in text
    assert text.count("User:") == CHAT_PROMPT_HISTORY_LIMIT


def test_insufficient_credits_recovery_opens_billing():
    payload = build_insufficient_credits_recovery(
        {"industry": "dentists", "location": "Melbourne"}
    )
    assert payload["recovery_kind"] == "insufficient_credits"
    assert payload["status"] == "insufficient_credits"
    assert any(action["id"] == "open_billing" for action in payload["actions"])
    assert "Melbourne" in payload["message"]


def test_enrichment_timeout_recovery_offers_retry():
    payload = build_enrichment_timeout_recovery(
        {"industry": "dentists", "location": "Melbourne"}
    )
    assert payload["recovery_kind"] == "enrichment_timeout"
    assert payload["status"] == "error"
    assert any(action["id"] == "retry_same" for action in payload["actions"])
    assert "Melbourne" in payload["message"]
    assert "enrichment" in payload["message"].lower()


def test_chat_timeout_uses_enrichment_when_search_already_saved():
    payload = build_chat_timeout_recovery(
        {"industry": "dentists", "location": "Melbourne"},
        user_message="dentists in Melbourne",
        saved_log_id="log-123",
    )
    assert payload["recovery_kind"] == "enrichment_timeout"
    assert payload["log_id"] == "log-123"


def test_chat_timeout_uses_search_when_no_log_saved():
    payload = build_chat_timeout_recovery(
        {"industry": "dentists", "location": "Melbourne"},
        user_message="dentists in Melbourne",
    )
    assert payload["recovery_kind"] == "search_timeout"
    assert "log_id" not in payload


def test_arun_runs_sync_fn_off_loop():
    def add(a, b, extra=0):
        return a + b + extra

    assert asyncio.run(arun(add, 1, 2, extra=3)) == 6


def test_ready_does_not_await_sync_get_redis():
    source = Path(__file__).resolve().parents[2].joinpath("app", "main.py").read_text()
    assert "await get_redis()" not in source
    assert "redis = get_redis()" in source
    assert "await redis.ping()" in source
