"""Objects reused across Celery tasks must not be bound to one event loop.

Each Celery task runs in a fresh event loop that is closed afterwards. The Gemini
client binds its async channel to the loop of its first call, and pooled asyncpg
connections to the loop that opened them, so a process-wide instance worked for the
first task and failed every later one — per-lead AI emails ended "Failed" with
"500: Spam check failed. Please try again."
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.utils import spam_checker


class LoopBoundLLM:
    """Behaves like the Gemini client: usable only in the loop of its first call."""

    instances = 0

    def __init__(self, **kwargs):
        LoopBoundLLM.instances += 1
        self.model = kwargs.get("model", "gemini-test")
        self.max_output_tokens = kwargs.get("max_output_tokens")
        self._loop = None

    async def ainvoke(self, prompt, *args, **kwargs):
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("Future attached to a different loop")
        return SimpleNamespace(content='{"spam_score": 20, "risk_level": "Low"}',
                               usage_metadata={}, response_metadata={})


@pytest.fixture
def loop_bound_spam_llm(monkeypatch):
    monkeypatch.setattr(spam_checker, "ChatGoogleGenerativeAI", LoopBoundLLM)
    monkeypatch.setattr(spam_checker, "_spam_llms_by_loop", spam_checker.weakref.WeakKeyDictionary())
    LoopBoundLLM.instances = 0
    with patch("app.services.ai.tracked_llm._persist_usage_event", AsyncMock()):
        yield


def test_spam_check_works_in_consecutive_event_loops(loop_bound_spam_llm):
    """Two Celery tasks = two event loops. The second used to fail."""
    for task in range(3):
        result = asyncio.run(spam_checker.check_email_spam(
            subject=f"Quick question {task}", body=f"Hello, a short note number {task}.",
            fast_mode=True, score_only=True,
        ))
        assert result["spam_score"] == 20


def test_spam_clients_are_reused_within_one_loop(loop_bound_spam_llm):
    async def two_lookups():
        return spam_checker._spam_check_llm(), spam_checker._spam_check_llm(), spam_checker._spam_score_only_llm()

    full_a, full_b, score_only = asyncio.run(two_lookups())
    assert full_a is full_b                     # the API's single loop keeps one client
    assert full_a is not score_only
    assert (full_a.max_output_tokens, score_only.max_output_tokens) == (8192, 1024)
    assert LoopBoundLLM.instances == 2


def test_spam_clients_differ_between_loops(loop_bound_spam_llm):
    async def lookup():
        return spam_checker._spam_check_llm()

    assert asyncio.run(lookup()) is not asyncio.run(lookup())


def test_overture_category_client_is_per_loop(monkeypatch):
    import langchain_google_genai
    from app.services import overture_category_service as cats

    monkeypatch.setattr(langchain_google_genai, "ChatGoogleGenerativeAI", LoopBoundLLM)
    monkeypatch.setattr(cats, "_category_llm_by_loop", cats.weakref.WeakKeyDictionary())

    async def lookup_twice():
        return cats._get_category_llm(), cats._get_category_llm()

    first_a, first_b = asyncio.run(lookup_twice())
    second_a, _ = asyncio.run(lookup_twice())
    assert first_a is not None and first_a is first_b
    assert second_a is not first_a


@pytest.mark.parametrize("argv, expected", [
    (["/usr/local/bin/celery", "-A", "app.core.celery_app", "worker"], True),
    ([r"C:\venv\Scripts\celery.exe", "-A", "app.core.celery_app", "worker"], True),
    (["/usr/lib/python3.11/site-packages/celery/__main__.py", "worker"], True),
    (["/usr/local/bin/uvicorn", "app.cloudrun:app"], False),
    (["-c"], False),          # python -c (worker guard, Beat runner)
    (["pytest"], False),
    ([], False),
])
def test_running_in_celery_process(argv, expected):
    from app.database.session import running_in_celery_process
    assert running_in_celery_process(argv) is expected


def test_api_process_keeps_connection_pool():
    from sqlalchemy.pool import NullPool
    from app.database.session import engine
    assert not isinstance(engine.pool, NullPool)  # tests, like the API, are not celery
