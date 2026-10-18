from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database.base import Base


class ChatKnowledgeRetrievalEvent(Base):
    """
    One chat turn that consulted the product knowledge corpus.

    Unlike ``AiUsageEvent``, which deliberately stores metering metadata only, this
    table stores the user's question. That is the point of it: the evaluation set
    behind the retrieval quality floor has to grow out of what users actually ask,
    and a row without the question cannot tell you why retrieval missed. It is kept
    in its own table rather than as columns on the metering one so that the metering
    table's "never prompts or generated content" guarantee stays true.

    Answers are not stored — only which documents were consulted.
    """

    __tablename__ = "chat_knowledge_retrieval_events"
    __table_args__ = (
        Index("ix_chat_knowledge_events_created_at", "created_at"),
        Index("ix_chat_knowledge_events_fallback_fired", "fallback_fired"),
        Index("ix_chat_knowledge_events_user_id", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Nullable: the guest chat path has no account behind it.
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    question = Column(Text, nullable=False)

    # [{document_title, filename, version, heading, score}], best match first.
    retrieved = Column(JSONB, nullable=False, default=list)

    top_score = Column(Float, nullable=True)  # null when nothing was retrieved
    fallback_fired = Column(Boolean, nullable=False, default=False)
    # Separates a genuine corpus miss from a degraded turn — both answer the user the
    # same way, but only one of them is a gap in the documentation.
    index_unavailable = Column(Boolean, nullable=False, default=False)

    retrieval_ms = Column(Integer, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
