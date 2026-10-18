"""
The shipped knowledge index.

The corpus travels with the application (spec BR-6), so its vectors travel with it
too: scripts/build_knowledge_index.py writes index_data.json, this module loads it
once per process into a numpy matrix, and scoring a question is one matvec over a few
hundred rows. That is exact rather than approximate, costs well under a millisecond,
and needs no extension on the database.

Drift guard
-----------
The artifact records a SHA-256 per source document. On load those are compared with
the corpus on disk, and any mismatch — an edited document, a deleted one, a new one,
a missing artifact — marks the whole index unavailable. The alternative is worse than
being unavailable: an assistant answering confidently out of content that has been
edited or deleted (FR-8). Rebuilding the index is therefore a required step of any
corpus change, which corpus/README.md says in as many words.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from app.knowledge.loader import CorpusError, document_hashes

logger = logging.getLogger(__name__)

ARTIFACT_PATH = Path(__file__).parent / "index_data.json"

# Bumped when the artifact layout changes so a stale file fails loudly on load
# instead of being half-understood.
ARTIFACT_VERSION = 1


@dataclass(frozen=True)
class ScoredChunk:
    """One retrieved passage and how well it matched."""

    document_title: str
    filename: str
    version: str
    last_reviewed: str
    heading: str
    text: str
    score: float


@dataclass
class KnowledgeIndex:
    """A loaded index, or the reason there isn't one."""

    vectors: Optional[np.ndarray] = None
    chunks: tuple[dict, ...] = ()
    embedding_model: str = ""
    built_at: str = ""
    unavailable_reason: Optional[str] = None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None and self.vectors is not None

    def search(
        self,
        query_vector: list[float],
        *,
        k: int,
        threshold: float,
        now: Optional[date] = None,
        stale_after_days: int = 365,
        neighbour_margin: float = 0.05,
    ) -> list[ScoredChunk]:
        """Top `k` chunks for a covered question, stale documents excluded.

        `threshold` decides coverage against the best-scoring chunk; `neighbour_margin`
        then decides how far below that best score a chunk may sit and still be worth
        handing to the model.
        """
        if not self.available:
            return []

        query = np.asarray(query_vector, dtype=np.float32)
        norm = float(np.linalg.norm(query))
        if norm == 0.0:
            return []
        query /= norm

        # Stored vectors are already unit length, so the dot product is the cosine.
        scores = self.vectors @ query

        today = now or datetime.now(timezone.utc).date()
        fresh = np.fromiter(
            (
                (today - date.fromisoformat(c["last_reviewed"])).days <= stale_after_days
                for c in self.chunks
            ),
            dtype=bool,
            count=len(self.chunks),
        )
        # Exclude stale documents before ranking (BR-5) rather than filtering the top
        # k afterwards, which would let one stale chunk crowd out a fresh answer.
        scores = np.where(fresh, scores, -np.inf)

        # `threshold` gates whether the corpus covers this question at all, and only
        # the best chunk has to clear it. Re-applying it to every chunk afterwards
        # discards near-miss neighbours while keeping a marginal winner: on "How do u
        # find the leads" a credits passage took the top slot at 0.7207 and the
        # passage that actually answers it sat at 0.7077, so the only thing handed to
        # the model was about credit accounting and the reply was a refusal. Once the
        # gate is passed, keep what scored close to the best instead.
        #
        # Abstention is unaffected by construction: the gate is still top-1 against
        # `threshold`, so a question that retrieves nothing today still retrieves
        # nothing. This only widens what a question already judged covered gets to
        # answer from.
        if not bool((scores >= threshold).any()):
            return []

        top_score = float(scores.max())
        near = int(np.count_nonzero(scores >= top_score - neighbour_margin))
        top = np.argsort(-scores)[: min(k, near)]
        return [
            ScoredChunk(
                document_title=self.chunks[i]["document_title"],
                filename=self.chunks[i]["filename"],
                version=self.chunks[i]["version"],
                last_reviewed=self.chunks[i]["last_reviewed"],
                heading=self.chunks[i]["heading"],
                text=self.chunks[i]["text"],
                score=float(scores[i]),
            )
            for i in top
        ]


def build_index(
    artifact_path: Path | None = None, corpus_dir: Path | None = None
) -> KnowledgeIndex:
    """Read and verify the artifact. Returns an unavailable index rather than raising."""
    path = artifact_path or ARTIFACT_PATH

    if not path.is_file():
        return KnowledgeIndex(
            unavailable_reason=(
                f"index artifact not found at {path.name} — "
                "run scripts/build_knowledge_index.py"
            )
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return KnowledgeIndex(unavailable_reason=f"index artifact unreadable: {e}")

    if payload.get("artifact_version") != ARTIFACT_VERSION:
        return KnowledgeIndex(
            unavailable_reason=(
                f"index artifact version {payload.get('artifact_version')!r} "
                f"!= expected {ARTIFACT_VERSION} — rebuild the index"
            )
        )

    try:
        on_disk = document_hashes(corpus_dir)
    except (CorpusError, OSError) as e:
        return KnowledgeIndex(unavailable_reason=f"corpus unreadable: {e}")

    recorded = payload.get("documents") or {}
    if recorded != on_disk:
        changed = sorted(
            set(recorded) ^ set(on_disk)
            | {f for f in set(recorded) & set(on_disk) if recorded[f] != on_disk[f]}
        )
        return KnowledgeIndex(
            unavailable_reason=(
                "corpus has changed since the index was built "
                f"({', '.join(changed)}) — run scripts/build_knowledge_index.py"
            )
        )

    chunks = payload.get("chunks") or []
    raw_vectors = payload.get("vectors") or []
    if len(chunks) != len(raw_vectors) or not chunks:
        return KnowledgeIndex(
            unavailable_reason="index artifact has no usable chunks"
        )

    vectors = np.asarray(raw_vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    vectors /= norms

    return KnowledgeIndex(
        vectors=vectors,
        chunks=tuple(chunks),
        embedding_model=payload.get("embedding_model", ""),
        built_at=payload.get("built_at", ""),
    )


_index: Optional[KnowledgeIndex] = None
_lock = threading.Lock()


def get_index() -> KnowledgeIndex:
    """The process-wide index, loaded on first use."""
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                _index = build_index()
                if _index.available:
                    logger.info(
                        "[KNOWLEDGE] index loaded: %d chunks, model=%s, built %s",
                        len(_index.chunks),
                        _index.embedding_model,
                        _index.built_at,
                    )
                else:
                    # Loud: every product question will fall back until this is fixed.
                    logger.error(
                        "[KNOWLEDGE] index unavailable — %s", _index.unavailable_reason
                    )
    return _index


def reset_index_cache() -> None:
    """Drop the loaded index (tests, and after a rebuild in a long-lived process)."""
    global _index
    with _lock:
        _index = None


def index_status() -> dict:
    """Operational snapshot of the index, safe to log or expose to an admin view."""
    idx = get_index()
    return {
        "available": idx.available,
        "reason": idx.unavailable_reason,
        "chunks": len(idx.chunks),
        "embedding_model": idx.embedding_model,
        "built_at": idx.built_at,
    }
