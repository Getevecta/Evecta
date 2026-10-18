"""
Repetition Guard.

A secondary safety net (the round-robin in variation.py already spreads recipes). It
compares a freshly generated email against the other emails already drafted for the same
campaign; if it's too similar to any of them, the caller (stage #4's generation loop)
re-rolls the variation and regenerates.

Similarity uses word-level **shingles** (k-word sequences), not a bag of words — that
captures phrasing/order, so "we help X do Y" and "we help Y do X" are not treated as
identical. Jaccard over the shingle sets gives a score in [0, 1].

Pure stdlib; operates on the draft text (HTML and {{ merge_fields }} are stripped before
comparison so shared placeholders don't inflate the score). For very large campaigns a
MinHash/LSH index would scale better than pairwise comparison, but that's a later concern.
"""
from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")
_MERGE_RE = re.compile(r"\{\{.*?\}\}")
_WORD_RE = re.compile(r"[a-z0-9']+")

DEFAULT_SHINGLE_K = 3
DEFAULT_THRESHOLD = 0.6


def _tokens(text: str) -> list[str]:
    """Lowercase word tokens with HTML tags and {{ merge fields }} removed."""
    if not text:
        return []
    text = _TAG_RE.sub(" ", text)
    text = _MERGE_RE.sub(" ", text)
    return _WORD_RE.findall(text.lower())


def _shingles(tokens: list[str], k: int) -> set[tuple[str, ...]]:
    """Set of k-word sequences. Falls back to single words when text is shorter than k."""
    if len(tokens) < k:
        return {(t,) for t in tokens}
    return {tuple(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def jaccard_similarity(a: str, b: str, k: int = DEFAULT_SHINGLE_K) -> float:
    """Shingle-based Jaccard similarity of two texts, in [0, 1]."""
    sa = _shingles(_tokens(a), k)
    sb = _shingles(_tokens(b), k)
    if not sa or not sb:
        return 0.0
    union = len(sa | sb)
    return len(sa & sb) / union if union else 0.0


def most_similar(
    candidate: str, others: list[str], k: int = DEFAULT_SHINGLE_K
) -> tuple[float, int]:
    """Highest similarity of `candidate` against `others`; returns (score, index) or (0.0, -1)."""
    best_score = 0.0
    best_index = -1
    for i, other in enumerate(others):
        score = jaccard_similarity(candidate, other, k)
        if score > best_score:
            best_score = score
            best_index = i
    return best_score, best_index


def is_too_similar(
    candidate: str,
    others: list[str],
    threshold: float = DEFAULT_THRESHOLD,
    k: int = DEFAULT_SHINGLE_K,
) -> bool:
    """True if `candidate` is at least `threshold` similar to any email in `others`."""
    if not others:
        return False
    score, _ = most_similar(candidate, others, k)
    return score >= threshold
