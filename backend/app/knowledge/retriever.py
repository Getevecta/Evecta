"""
The retrieval façade the chat calls.

Two properties matter more than anything else in here:

1. ``retrieve()`` never raises. A missing artifact, a corpus that has drifted from
   it, a failed embedding call — every one of them comes back as an empty result with
   ``unavailable=True`` so the chat turn completes with the honest non-answer instead
   of erroring (FR-10).
2. Nothing in this module takes, reads, or filters on who is asking. The corpus is
   product knowledge with no customer data in it (BR-1), so every user gets the same
   documents for the same question (FR-11). That holds here by construction, which is
   a stronger guarantee than a scoping filter that could be written wrong.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.knowledge import embeddings
from app.knowledge.index import ScoredChunk, get_index

logger = logging.getLogger(__name__)

settings = get_settings()


@dataclass
class RetrievalResult:
    """What retrieval found, and whether it was able to look at all."""

    chunks: list[ScoredChunk] = field(default_factory=list)
    unavailable: bool = False
    reason: str | None = None
    elapsed_ms: int = 0

    @property
    def has_matches(self) -> bool:
        return bool(self.chunks)

    @property
    def top_score(self) -> float | None:
        return self.chunks[0].score if self.chunks else None

    @property
    def document_titles(self) -> list[str]:
        """Distinct source titles, best match first — what FR-2 attribution names."""
        seen: list[str] = []
        for chunk in self.chunks:
            if chunk.document_title not in seen:
                seen.append(chunk.document_title)
        return seen


async def retrieve(question: str, *, about_assistant: bool = False) -> RetrievalResult:
    """Passages for a product question. Never raises.

    `about_assistant` marks a question about the assistant itself, which uses a
    softer coverage gate — see KNOWLEDGE_ASSISTANT_MIN_SCORE for why that does not
    weaken abstention. The caller decides; nothing here inspects the question text.
    """
    started = time.perf_counter()

    def _elapsed() -> int:
        return int((time.perf_counter() - started) * 1000)

    if not settings.KNOWLEDGE_RAG_ENABLED:
        return RetrievalResult(unavailable=True, reason="disabled", elapsed_ms=_elapsed())

    if not (question or "").strip():
        return RetrievalResult(elapsed_ms=_elapsed())

    index = get_index()
    if not index.available:
        return RetrievalResult(
            unavailable=True, reason=index.unavailable_reason, elapsed_ms=_elapsed()
        )

    try:
        query_vector = await embeddings.embed_query(question)
    except Exception as e:
        # The provider being down must not take the conversation down with it.
        logger.warning("[KNOWLEDGE] query embedding failed: %s", e)
        return RetrievalResult(
            unavailable=True, reason=f"embedding failed: {e}", elapsed_ms=_elapsed()
        )

    chunks = index.search(
        query_vector,
        k=settings.KNOWLEDGE_TOP_K,
        threshold=(
            settings.KNOWLEDGE_ASSISTANT_MIN_SCORE
            if about_assistant
            else settings.KNOWLEDGE_MIN_SCORE
        ),
        stale_after_days=settings.KNOWLEDGE_STALE_AFTER_DAYS,
        neighbour_margin=settings.KNOWLEDGE_NEIGHBOUR_MARGIN,
    )
    return RetrievalResult(chunks=chunks, elapsed_ms=_elapsed())
