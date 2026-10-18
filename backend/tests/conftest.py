"""
Shared fixtures for the knowledge-retrieval tests.

Two things every test in this area needs and must never do for real:

* **An index.** Built here from ``tests/fixtures/knowledge/`` through the same
  loader, chunker and artifact format the shipped index uses, so a change to any of
  those is caught. Only the embedder is substituted.
* **An embedder.** ``fake_embedder`` is a bag-of-words vector over the fixture
  corpus's own vocabulary: a question sharing wording with a passage scores high, an
  unrelated question scores zero. Deterministic, offline, and close enough in shape
  to a real embedding that thresholds and staleness behave the way they will in
  production.

No test constructs a ChatGoogleGenerativeAI or reaches Google.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.knowledge import loader
from app.knowledge.index import ARTIFACT_VERSION, build_index

FIXTURE_CORPUS = Path(__file__).parent / "fixtures" / "knowledge"


# Function words carry no topic signal. A real embedding barely keys on them; a raw
# bag-of-words keys on them heavily, which would let "what is the capital of france"
# score against every passage through "the" and "of" alone.
_STOPWORDS = frozenset(
    """a an and are as at be been but by can do does for from has have how i if in
    is it its me my no not of on or so than that the their them then there these
    they this to up us was were what when where which who why will with you your"""
    .split()
)


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOPWORDS]


def make_fake_embedder(vocabulary: list[str]):
    """Bag-of-words embedding over a fixed vocabulary. Unknown words are ignored."""
    position = {word: i for i, word in enumerate(vocabulary)}

    def embed(text: str) -> list[float]:
        vector = [0.0] * len(vocabulary)
        for token in _tokens(text):
            if token in position:
                vector[position[token]] += 1.0
        return vector

    return embed


def write_fixture_index(
    artifact_path: Path,
    corpus_dir: Path = FIXTURE_CORPUS,
    *,
    only: list[str] | None = None,
):
    """Build an index artifact from a fixture corpus. Returns (index, embed)."""
    chunks = loader.chunk_corpus(corpus_dir)
    if only is not None:
        chunks = [c for c in chunks if c.filename in only]

    vocabulary = sorted({t for c in chunks for t in _tokens(c.text)})
    embed = make_fake_embedder(vocabulary)

    hashes = loader.document_hashes(corpus_dir)
    if only is not None:
        hashes = {name: h for name, h in hashes.items() if name in only}

    payload = {
        "artifact_version": ARTIFACT_VERSION,
        "embedding_model": "fake-bag-of-words",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "documents": hashes,
        "chunks": [
            {
                "document_title": c.document_title,
                "filename": c.filename,
                "version": c.version,
                "last_reviewed": c.last_reviewed.isoformat(),
                "heading": c.heading,
                "text": c.text,
            }
            for c in chunks
        ],
        "vectors": [embed(c.text) for c in chunks],
    }
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    return build_index(artifact_path, corpus_dir), embed


@pytest.fixture
def knowledge_index(tmp_path):
    """A loaded index over the whole fixture corpus, plus its embedder."""
    return write_fixture_index(tmp_path / "index_data.json")
