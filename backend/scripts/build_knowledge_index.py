"""
Build the shipped knowledge index.

    env/Scripts/python.exe scripts/build_knowledge_index.py           # rebuild
    env/Scripts/python.exe scripts/build_knowledge_index.py --check   # verify only
    env/Scripts/python.exe scripts/build_knowledge_index.py --dry-run # chunk, no embed

Run after any corpus edit and commit the regenerated artifact alongside the document.
`--check` re-verifies the hashes without embedding anything, so it is cheap enough to
run in CI as the gate that catches a corpus change committed without a rebuild.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge.index import ARTIFACT_PATH, ARTIFACT_VERSION, build_index  # noqa: E402
from app.knowledge.loader import (  # noqa: E402
    CorpusError,
    chunk_corpus,
    document_hashes,
    load_documents,
)


def _summarise(chunks) -> None:
    sizes = sorted(len(c.text) for c in chunks)
    if not sizes:
        return
    mid = sizes[len(sizes) // 2]
    print(
        f"  chunk sizes: min {sizes[0]}, median {mid}, max {sizes[-1]} chars "
        f"({len(sizes)} chunks)"
    )


def check() -> int:
    """Exit 0 when the artifact matches the corpus on disk."""
    index = build_index()
    if index.available:
        print(
            f"OK — index matches corpus ({len(index.chunks)} chunks, "
            f"model {index.embedding_model}, built {index.built_at})"
        )
        return 0
    print(f"DRIFT — {index.unavailable_reason}", file=sys.stderr)
    return 1


def build(dry_run: bool) -> int:
    try:
        documents = load_documents()
    except CorpusError as e:
        print(f"Corpus is invalid: {e}", file=sys.stderr)
        return 1

    if not documents:
        print(
            "No corpus documents found in app/knowledge/corpus/. "
            "Add at least one governed document before building the index.",
            file=sys.stderr,
        )
        return 1

    print(f"Loaded {len(documents)} document(s):")
    for doc in documents:
        print(f"  - {doc.filename}: {doc.title} (v{doc.version}, {doc.last_reviewed})")

    chunks = chunk_corpus()
    _summarise(chunks)
    if not chunks:
        print("Corpus produced no chunks.", file=sys.stderr)
        return 1

    if dry_run:
        print("--dry-run: stopping before embedding.")
        return 0

    # Imported here so --check and --dry-run stay usable without a Gemini key.
    from app.knowledge.embeddings import embed_documents, embedding_model_name

    print(f"Embedding {len(chunks)} chunk(s) with {embedding_model_name()}...")
    vectors = embed_documents([c.text for c in chunks])
    if len(vectors) != len(chunks):
        print(
            f"Provider returned {len(vectors)} vectors for {len(chunks)} chunks.",
            file=sys.stderr,
        )
        return 1

    payload = {
        "artifact_version": ARTIFACT_VERSION,
        "embedding_model": embedding_model_name(),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "documents": document_hashes(),
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
        "vectors": [[round(float(v), 6) for v in vec] for vec in vectors],
    }
    ARTIFACT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"Wrote {ARTIFACT_PATH.relative_to(Path.cwd())} ({len(chunks)} chunks).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify the artifact matches the corpus"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="chunk and report, but do not embed"
    )
    args = parser.parse_args()
    return check() if args.check else build(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
