"""
Records one row per knowledge-backed chat turn (FR-12).

Writes on its own session rather than borrowing the request's. Two reasons: the
streaming chat route deliberately takes no ``Depends(get_session)`` and the guest
path has no session at all, so there is nothing to borrow on either of the paths
that need this; and a telemetry insert must never be able to roll back a chat turn.

Every failure in here is logged and swallowed for the same reason — the honest
non-answer promised by FR-10 must not depend on the analytics table being writable.
"""
from __future__ import annotations

import logging
from typing import Optional, Union
from uuid import UUID

from app.database.session import async_session_factory
from app.knowledge.retriever import RetrievalResult
from app.models.chat_knowledge_event import ChatKnowledgeRetrievalEvent

logger = logging.getLogger(__name__)


def _retrieved_payload(result: RetrievalResult) -> list[dict]:
    return [
        {
            "document_title": c.document_title,
            "filename": c.filename,
            "version": c.version,
            "heading": c.heading,
            "score": round(c.score, 4),
        }
        for c in result.chunks
    ]


async def log_retrieval(
    question: str,
    result: RetrievalResult,
    *,
    fallback_fired: bool,
    user_id: Optional[Union[str, UUID]] = None,
) -> None:
    """Record a knowledge turn. Never raises."""
    try:
        event = ChatKnowledgeRetrievalEvent(
            user_id=user_id,
            question=question,
            retrieved=_retrieved_payload(result),
            top_score=result.top_score,
            fallback_fired=fallback_fired,
            index_unavailable=result.unavailable,
            retrieval_ms=result.elapsed_ms,
        )
        async with async_session_factory() as session:
            session.add(event)
            await session.commit()
    except Exception as e:
        logger.warning("[KNOWLEDGE] failed to record retrieval event: %s", e)
