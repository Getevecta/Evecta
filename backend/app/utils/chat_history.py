"""Bounds on durable chat transcripts and LLM prompt history."""
from __future__ import annotations

# Checkpointed transcript: enough for slot backfill, not unbounded growth.
CHAT_STORED_HISTORY_LIMIT = 40
# Prompt window: recent turns only. Older context lives in CURRENT CONTEXT + memory.
CHAT_PROMPT_HISTORY_LIMIT = 12
CHAT_HISTORY_MESSAGE_CHARS = 500


def compact_chat_history(
    history: list | None,
    *,
    limit: int = CHAT_STORED_HISTORY_LIMIT,
    max_chars: int = CHAT_HISTORY_MESSAGE_CHARS,
) -> list[dict]:
    """Keep the most recent `limit` turns and cap each message body."""
    if not history:
        return []
    trimmed = list(history)[-max(1, limit) :]
    out: list[dict] = []
    for entry in trimmed:
        if not isinstance(entry, dict):
            continue
        msg = entry.get("message")
        if not isinstance(msg, str):
            msg = "" if msg is None else str(msg)
        if len(msg) > max_chars:
            msg = msg[:max_chars] + "…"
        item = dict(entry)
        item["message"] = msg
        out.append(item)
    return out


def format_chat_history_for_prompt(
    history: list | None,
    *,
    limit: int = CHAT_PROMPT_HISTORY_LIMIT,
    max_chars: int = CHAT_HISTORY_MESSAGE_CHARS,
) -> str:
    """Recent turns only, for LLM prompts. Older context belongs in CURRENT CONTEXT."""
    compacted = compact_chat_history(history, limit=limit, max_chars=max_chars)
    if not compacted:
        return "No previous conversation."
    lines = []
    for entry in compacted:
        role = entry.get("role", "user")
        msg = entry.get("message", "")
        if role == "user":
            lines.append(f"User: {msg}")
        elif role == "assistant":
            lines.append(f"Assistant: {msg}")
    return "\n".join(lines) if lines else "No previous conversation."
