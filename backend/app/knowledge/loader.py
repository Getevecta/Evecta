"""
Loader for the product knowledge corpus.

Each corpus/*.md file is a markdown document with a YAML frontmatter block carrying
the governance metadata every document must have:

    ---
    title: How credits work
    audience: customer
    version: 1
    last_reviewed: 2026-08-01
    ---
    # Prose the assistant is allowed to answer from

A document missing any of those four fields is a build failure, not a document with
defaults — `load_documents()` raises. Governance that degrades quietly is not
governance.

This mirrors app/email_engine/loader.py (same frontmatter convention, same
`split_frontmatter`); the difference is that the email rules are read at request time
while this corpus is read at build time by scripts/build_knowledge_index.py and, at
runtime, only to verify that the shipped index still matches the corpus on disk.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.email_engine.loader import split_frontmatter

CORPUS_DIR = Path(__file__).parent / "corpus"

REQUIRED_FIELDS = ("title", "audience", "version", "last_reviewed")

# Split on headings first so a chunk is a coherent section, then hard-split any
# section that is still too large to score precisely. 1200 chars keeps a chunk well
# inside the embedding window while staying big enough to carry a whole answer.
_MAX_CHUNK_CHARS = 1200
_CHUNK_OVERLAP = 120


class CorpusError(Exception):
    """A corpus document is missing, malformed, or missing required metadata."""


@dataclass(frozen=True)
class CorpusDocument:
    """One governed markdown document."""

    filename: str
    title: str
    audience: str
    version: str
    last_reviewed: date
    body: str
    sha256: str


@dataclass(frozen=True)
class Chunk:
    """A retrievable passage, carrying the governance metadata of its document."""

    document_title: str
    filename: str
    version: str
    last_reviewed: date
    heading: str
    text: str


def _parse_last_reviewed(value, filename: str) -> date:
    # PyYAML already turns an unquoted YYYY-MM-DD into a date; a quoted one stays a str.
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise CorpusError(
            f"{filename}: last_reviewed must be an ISO date (YYYY-MM-DD), got {value!r}"
        ) from exc


def _build_document(path: Path) -> CorpusDocument:
    raw = path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(raw)

    missing = [f for f in REQUIRED_FIELDS if not meta.get(f)]
    if missing:
        raise CorpusError(
            f"{path.name}: missing required frontmatter field(s): {', '.join(missing)}. "
            "Every corpus document needs title, audience, version and last_reviewed."
        )
    if not body.strip():
        raise CorpusError(f"{path.name}: document body is empty")

    return CorpusDocument(
        filename=path.name,
        title=str(meta["title"]).strip(),
        audience=str(meta["audience"]).strip(),
        version=str(meta["version"]).strip(),
        last_reviewed=_parse_last_reviewed(meta["last_reviewed"], path.name),
        body=body,
        # Hash the whole file, frontmatter included: a version bump with no body change
        # is still a change the index must be rebuilt for.
        sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def corpus_paths(corpus_dir: Path | None = None) -> list[Path]:
    """Every corpus document, sorted. README.md is the contract, not content."""
    directory = corpus_dir or CORPUS_DIR
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.md") if p.name.lower() != "readme.md")


def load_documents(corpus_dir: Path | None = None) -> list[CorpusDocument]:
    """Parse and validate every corpus document. Raises CorpusError on any bad one."""
    return [_build_document(p) for p in corpus_paths(corpus_dir)]


def document_hashes(corpus_dir: Path | None = None) -> dict[str, str]:
    """{filename: sha256} for the corpus on disk — the input to the drift guard."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in corpus_paths(corpus_dir)
    }


def chunk_document(doc: CorpusDocument) -> list[Chunk]:
    """Split one document into retrievable passages, heading-aware."""
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
        strip_headers=False,
    )
    sections = header_splitter.split_text(doc.body)
    if not sections:
        return []

    overlong = RecursiveCharacterTextSplitter(
        chunk_size=_MAX_CHUNK_CHARS, chunk_overlap=_CHUNK_OVERLAP
    )
    pieces = overlong.split_documents(sections)

    chunks: list[Chunk] = []
    for piece in pieces:
        text = piece.page_content.strip()
        if not text:
            continue
        heading = " > ".join(
            str(piece.metadata[key])
            for key in ("h1", "h2", "h3")
            if piece.metadata.get(key)
        )
        chunks.append(
            Chunk(
                document_title=doc.title,
                filename=doc.filename,
                version=doc.version,
                last_reviewed=doc.last_reviewed,
                heading=heading,
                text=text,
            )
        )
    return chunks


def chunk_corpus(corpus_dir: Path | None = None) -> list[Chunk]:
    """Every chunk of every document, in document order."""
    chunks: list[Chunk] = []
    for doc in load_documents(corpus_dir):
        chunks.extend(chunk_document(doc))
    return chunks
