"""Corpus governance — the metadata every document must carry, and what is excluded."""

from datetime import date
from pathlib import Path

import pytest

from app.knowledge import loader
from app.knowledge.loader import CORPUS_DIR, CorpusError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FIXTURE_CORPUS = FIXTURES / "knowledge"
INVALID_CORPUS = FIXTURES / "knowledge_invalid"


def test_every_shipped_document_carries_governance_metadata():
    """The real corpus must parse, and every document must be fully described."""
    for doc in loader.load_documents():
        assert doc.title, f"{doc.filename}: no title"
        assert doc.audience, f"{doc.filename}: no audience"
        assert doc.version, f"{doc.filename}: no version"
        assert isinstance(doc.last_reviewed, date), f"{doc.filename}: bad last_reviewed"


def test_corpus_contract_is_published():
    """The README states what may never go into the corpus; it must stay present."""
    readme = CORPUS_DIR / "README.md"
    assert readme.is_file()
    text = readme.read_text(encoding="utf-8").lower()
    for forbidden in ("secret", "customer data", "internal engineering notes"):
        assert forbidden in text


def test_readme_is_not_indexed(tmp_path):
    """The contract is not content — it must never become a retrievable passage."""
    (tmp_path / "README.md").write_text("# the contract\n", encoding="utf-8")
    (tmp_path / "topic.md").write_text(
        "---\ntitle: T\naudience: customer\nversion: 1\nlast_reviewed: 2026-01-01\n---\n\nbody\n",
        encoding="utf-8",
    )
    assert [p.name for p in loader.corpus_paths(tmp_path)] == ["topic.md"]


def test_missing_metadata_field_is_a_build_failure():
    with pytest.raises(CorpusError) as excinfo:
        loader.load_documents(INVALID_CORPUS)
    assert "last_reviewed" in str(excinfo.value)


def test_documents_are_chunked_on_headings():
    chunks = loader.chunk_corpus(FIXTURE_CORPUS)
    headings = {c.heading for c in chunks}
    assert any("Does searching use up my credits?" in h for h in headings)
    # Each chunk carries its document's governance metadata, not just its text.
    for chunk in chunks:
        assert chunk.document_title
        assert isinstance(chunk.last_reviewed, date)


def test_document_hash_changes_with_content(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text(
        "---\ntitle: T\naudience: customer\nversion: 1\nlast_reviewed: 2026-01-01\n---\n\nbody\n",
        encoding="utf-8",
    )
    before = loader.document_hashes(tmp_path)
    doc.write_text(
        "---\ntitle: T\naudience: customer\nversion: 2\nlast_reviewed: 2026-01-01\n---\n\nbody\n",
        encoding="utf-8",
    )
    assert loader.document_hashes(tmp_path) != before
