"""Grounded product knowledge: a governed local corpus and retrieval over it."""

from app.knowledge.index import ScoredChunk, index_status
from app.knowledge.retriever import RetrievalResult, retrieve

__all__ = ["RetrievalResult", "ScoredChunk", "index_status", "retrieve"]
