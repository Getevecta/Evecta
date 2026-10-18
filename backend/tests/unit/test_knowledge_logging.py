"""FR-12: every knowledge turn is recorded, and recording it can never break the turn."""

import asyncio
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.knowledge.index import ScoredChunk
from app.knowledge.retriever import RetrievalResult
from app.services import chat_knowledge_log as log_mod
from app.services.chat_knowledge_log import _retrieved_payload, log_retrieval


def _chunk(title="How lead credits work", score=0.81):
    return ScoredChunk(
        document_title=title,
        filename="credits.md",
        version="2",
        last_reviewed="2026-07-01",
        heading="Does searching use up my credits?",
        text="Running a search does not spend credits.",
        score=score,
    )


class _CapturingSession:
    """Stands in for an AsyncSession, keeping whatever was added to it."""

    added: list = []

    def __init__(self):
        type(self).added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, obj):
        type(self).added.append(obj)

    async def commit(self):
        return None


def test_payload_records_sources_in_rank_order():
    result = RetrievalResult(
        chunks=[_chunk(score=0.81), _chunk("Connecting a mailbox", score=0.62)]
    )
    payload = _retrieved_payload(result)

    assert [p["document_title"] for p in payload] == [
        "How lead credits work",
        "Connecting a mailbox",
    ]
    assert payload[0]["score"] == 0.81
    assert payload[0]["heading"] == "Does searching use up my credits?"
    # The answer text is not stored — only which documents were consulted.
    assert "answer" not in payload[0]


def test_a_hit_is_recorded_with_its_sources():
    user_id = uuid4()
    result = RetrievalResult(chunks=[_chunk()], elapsed_ms=42)

    with patch.object(log_mod, "async_session_factory", _CapturingSession):
        asyncio.run(
            log_retrieval("do searches cost credits?", result, fallback_fired=False, user_id=user_id)
        )

    event = _CapturingSession.added[0]
    assert event.question == "do searches cost credits?"
    assert event.user_id == user_id
    assert event.fallback_fired is False
    assert event.index_unavailable is False
    assert event.top_score == 0.81
    assert event.retrieval_ms == 42


def test_a_fallback_turn_is_recorded_as_one():
    """The evaluation set grows out of these rows, so a miss has to be legible."""
    result = RetrievalResult(chunks=[], elapsed_ms=7)

    with patch.object(log_mod, "async_session_factory", _CapturingSession):
        asyncio.run(log_retrieval("what is your uptime SLA?", result, fallback_fired=True))

    event = _CapturingSession.added[0]
    assert event.fallback_fired is True
    assert event.retrieved == []
    assert event.top_score is None
    assert event.user_id is None  # guests are recorded too


def test_degraded_index_is_distinguished_from_a_corpus_miss():
    result = RetrievalResult(chunks=[], unavailable=True, reason="index artifact not found")

    with patch.object(log_mod, "async_session_factory", _CapturingSession):
        asyncio.run(log_retrieval("do searches cost credits?", result, fallback_fired=True))

    assert _CapturingSession.added[0].index_unavailable is True


def test_a_failing_write_does_not_raise():
    """A telemetry outage must not take the conversation down with it."""
    broken = MagicMock(side_effect=RuntimeError("database is down"))
    result = RetrievalResult(chunks=[_chunk()])

    with patch.object(log_mod, "async_session_factory", broken):
        asyncio.run(log_retrieval("q", result, fallback_fired=False))  # must not raise
