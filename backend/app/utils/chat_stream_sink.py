"""Live token sink for POST /chat/stream.

The chat graph drains LLM streams inside nodes (so history/state stay correct).
While a stream request is active we attach an asyncio.Queue via ContextVar so
``tracked_astream`` can push each chunk to the SSE response as it arrives —
instead of waiting for ``done`` with the full message.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Optional

_token_queue: ContextVar[Optional[asyncio.Queue]] = ContextVar(
    "chat_stream_token_queue",
    default=None,
)


def attach_token_queue(queue: asyncio.Queue):
    """Bind ``queue`` for the current task. Returns a token for ``detach_token_queue``."""
    return _token_queue.set(queue)


def detach_token_queue(token) -> None:
    _token_queue.reset(token)


async def emit_chat_token(text: str) -> None:
    """Push a visible text fragment to the active chat stream, if any."""
    if not text:
        return
    queue = _token_queue.get()
    if queue is None:
        return
    await queue.put(text)


def content_to_text(content) -> str:
    """Normalize LangChain / Gemini chunk content to a plain string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") == "text" or "text" in part:
                    parts.append(str(part.get("text") or ""))
                elif "content" in part:
                    parts.append(str(part.get("content") or ""))
            else:
                text = getattr(part, "text", None)
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(content)
