"""
Embedding access for the knowledge corpus.

Both the build script and the query path go through here so the vectors in the
shipped index and the vector a question is scored with can never come from different
models — a mismatch there produces silently terrible retrieval rather than an error.

Query embeddings are cached in Redis under a hash of the normalised question. The
same product question arrives from many users, and one avoided round trip is the
cheapest lever there is on the FR-9 latency budget.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.core.config import get_settings
from app.utils.redis_context import REDIS_AVAILABLE, redis_client

logger = logging.getLogger(__name__)

settings = get_settings()

_QUERY_CACHE_TTL = 24 * 3600
_QUERY_CACHE_PREFIX = "kq:"

_embedders: dict[str, GoogleGenerativeAIEmbeddings] = {}


def embedding_model_name() -> str:
    return settings.KNOWLEDGE_EMBEDDING_MODEL


def _get_embedder(task_type: str) -> GoogleGenerativeAIEmbeddings:
    """One embedder per task type.

    Gemini embeds asymmetrically: a short question and the long passage that
    answers it only land near each other when the query is embedded as
    RETRIEVAL_QUERY and the passage as RETRIEVAL_DOCUMENT. Embedding both the
    same way collapses every score into a narrow band and short questions stop
    matching the section that answers them.
    """
    if task_type not in _embedders:
        _embedders[task_type] = GoogleGenerativeAIEmbeddings(
            model=embedding_model_name(),
            google_api_key=settings.GEMINI_API_KEY,
            task_type=task_type,
        )
    return _embedders[task_type]


def _cache_key(text: str) -> str:
    digest = hashlib.sha256(
        f"{embedding_model_name()}|{text.strip().lower()}".encode("utf-8")
    ).hexdigest()
    return f"{_QUERY_CACHE_PREFIX}{digest}"


def _get_cached(text: str) -> Optional[list[float]]:
    if not (REDIS_AVAILABLE and redis_client):
        return None
    try:
        raw = redis_client.get(_cache_key(text))
        if raw:
            return [float(v) for v in raw.split(",")]
    except Exception as e:
        logger.error("[KNOWLEDGE] query embedding cache read failed: %s", e)
    return None


def _set_cached(text: str, vector: list[float]) -> None:
    if not (REDIS_AVAILABLE and redis_client):
        return
    try:
        redis_client.setex(
            _cache_key(text), _QUERY_CACHE_TTL, ",".join(repr(v) for v in vector)
        )
    except Exception as e:
        logger.error("[KNOWLEDGE] query embedding cache write failed: %s", e)


async def embed_query(text: str) -> list[float]:
    """Embed one user question. Raises on provider failure — the caller decides."""
    cached = _get_cached(text)
    if cached is not None:
        return cached
    vector = await _get_embedder("RETRIEVAL_QUERY").aembed_query(text)
    _set_cached(text, vector)
    return vector


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed corpus chunks. Build-time only, so synchronous and uncached."""
    return _get_embedder("RETRIEVAL_DOCUMENT").embed_documents(texts)
