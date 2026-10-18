"""The index: staleness, thresholds, and every way it degrades to unavailable."""

import json
import shutil
from datetime import date
from pathlib import Path

from app.knowledge.index import build_index
from tests.conftest import FIXTURE_CORPUS, write_fixture_index


def test_search_returns_the_matching_document(knowledge_index):
    index, embed = knowledge_index
    hits = index.search(embed("does searching use up my credits"), k=5, threshold=0.1)
    assert hits
    assert hits[0].document_title == "How lead credits work"


def test_search_respects_top_k(knowledge_index):
    index, embed = knowledge_index
    hits = index.search(embed("credits mailbox export leads"), k=2, threshold=0.0)
    assert len(hits) <= 2


def test_unrelated_question_clears_nothing(knowledge_index):
    """A control question shares no vocabulary, so it must retrieve nothing at all."""
    index, embed = knowledge_index
    assert index.search(embed("what is the capital of france"), k=5, threshold=0.1) == []


def test_stale_documents_are_excluded(knowledge_index):
    """BR-5: a document past the review horizon is silent, even on a direct hit."""
    index, embed = knowledge_index
    query = embed("legacy starter tier monthly lead credits flat fee")

    fresh_view = index.search(
        query, k=5, threshold=0.05, now=date(2026, 8, 6), stale_after_days=365
    )
    assert "Legacy pricing" not in {h.document_title for h in fresh_view}

    # Same query, same index — only the horizon differs.
    lenient = index.search(
        query, k=5, threshold=0.05, now=date(2026, 8, 6), stale_after_days=5000
    )
    assert "Legacy pricing" in {h.document_title for h in lenient}


def test_missing_artifact_is_unavailable(tmp_path):
    index = build_index(tmp_path / "nothing.json", FIXTURE_CORPUS)
    assert not index.available
    assert "not found" in index.unavailable_reason


def test_edited_corpus_makes_the_index_unavailable(tmp_path):
    """FR-8: editing a document without rebuilding must not answer from the old text."""
    corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE_CORPUS, corpus)
    artifact = tmp_path / "index_data.json"
    index, _ = write_fixture_index(artifact, corpus)
    assert index.available

    doc = corpus / "credits.md"
    doc.write_text(doc.read_text(encoding="utf-8") + "\nAn edit.\n", encoding="utf-8")

    reloaded = build_index(artifact, corpus)
    assert not reloaded.available
    assert "credits.md" in reloaded.unavailable_reason


def test_removed_corpus_document_makes_the_index_unavailable(tmp_path):
    """AC-5: deleting a document must stop the assistant using it, not go unnoticed."""
    corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE_CORPUS, corpus)
    artifact = tmp_path / "index_data.json"
    write_fixture_index(artifact, corpus)

    (corpus / "credits.md").unlink()

    reloaded = build_index(artifact, corpus)
    assert not reloaded.available
    assert "credits.md" in reloaded.unavailable_reason


def test_artifact_version_mismatch_is_unavailable(tmp_path):
    artifact = tmp_path / "index_data.json"
    write_fixture_index(artifact, FIXTURE_CORPUS)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["artifact_version"] = 999
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    index = build_index(artifact, FIXTURE_CORPUS)
    assert not index.available
    assert "rebuild" in index.unavailable_reason


def test_unavailable_index_searches_to_nothing(tmp_path):
    index = build_index(tmp_path / "missing.json", FIXTURE_CORPUS)
    assert index.search([0.1, 0.2], k=5, threshold=0.0) == []
