"""New Chat hard-deletes the abandoned checkpointer thread (not long-term memory)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.chat_graph import delete_chat_thread


@pytest.mark.asyncio
async def test_delete_chat_thread_calls_adelete_thread():
    checkpointer = SimpleNamespace(adelete_thread=AsyncMock())
    graph = SimpleNamespace(checkpointer=checkpointer)

    ok = await delete_chat_thread(graph, "user-1:conv-abc")

    assert ok is True
    checkpointer.adelete_thread.assert_awaited_once_with("user-1:conv-abc")


@pytest.mark.asyncio
async def test_delete_chat_thread_returns_false_on_failure():
    checkpointer = SimpleNamespace(adelete_thread=AsyncMock(side_effect=RuntimeError("boom")))
    graph = SimpleNamespace(checkpointer=checkpointer)

    ok = await delete_chat_thread(graph, "user-1:conv-abc")

    assert ok is False


@pytest.mark.asyncio
async def test_delete_chat_thread_noop_without_graph():
    assert await delete_chat_thread(None, "any-thread") is False
    assert await delete_chat_thread(SimpleNamespace(checkpointer=None), "t") is False
    assert await delete_chat_thread(SimpleNamespace(checkpointer=AsyncMock()), "") is False
