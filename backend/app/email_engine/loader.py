"""
Loader for the markdown rules knowledge base.

Each rules/*.md file is a markdown document with a YAML frontmatter block:

    ---
    variants:
      - "..."
    ---
    # Human-readable prose continues here

The structured data (variant lists, prohibited phrases, structures) lives in the
frontmatter and is parsed with PyYAML — robust and validatable, no custom regex. The
prose body is human guidance for whoever edits the file. Tone files under rules/tones/
are plain prose with no frontmatter; their whole body is returned as the tone block.

Files are cached and re-read only when their mtime changes (cheap hot-reload in dev;
no per-email disk IO).
"""
from __future__ import annotations

import threading
from pathlib import Path

import yaml

RULES_DIR = Path(__file__).parent / "rules"
TONES_DIR = RULES_DIR / "tones"

# Cache: path -> (mtime, parsed_value)
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a `---`-delimited YAML frontmatter block from the markdown body."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        # parts == ['', '<yaml>', '<body>'] when a well-formed block is present
        if len(parts) == 3:
            meta = yaml.safe_load(parts[1]) or {}
            if not isinstance(meta, dict):
                meta = {}
            return meta, parts[2].lstrip("\n")
    return {}, text


def _load_cached(path: Path, builder) -> object:
    """Return builder(path), re-running it only when the file mtime changes."""
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return builder(path)  # let builder decide how to handle a missing file
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        value = builder(path)
        _cache[key] = (mtime, value)
        return value


def _build_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    meta, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    return meta


def get_meta(filename: str) -> dict:
    """Parsed YAML frontmatter for rules/<filename> (cached). Empty dict if absent."""
    return _load_cached(RULES_DIR / filename, _build_meta)  # type: ignore[return-value]


def get_list(filename: str, key: str) -> list[str]:
    """A list value from rules/<filename>'s frontmatter (empty list if missing)."""
    value = get_meta(filename).get(key, [])
    return list(value) if isinstance(value, list) else []


# --- Convenience accessors used by variation / spec_builder -----------------

def get_prohibited_phrases() -> list[str]:
    """HARD blocklist — emails containing any of these should be rejected by stage #4."""
    return get_list("spam_safe.md", "prohibited_phrases")


def get_spam_trigger_words() -> list[str]:
    """SOFT list — generator avoids; gate flags (does not reject) on these alone."""
    return get_list("spam_safe.md", "spam_trigger_words")


def get_harmful_claim_phrases() -> list[str]:
    return get_list("spam_safe.md", "harmful_claim_phrases")


def get_aggressive_sales_phrases() -> list[str]:
    return get_list("spam_safe.md", "aggressive_sales_phrases")


def get_openings_to_avoid() -> list[str]:
    return get_list("spam_safe.md", "openings_to_avoid")


def get_deliverability_rules() -> list[str]:
    return get_list("spam_safe.md", "deliverability_rules")


def get_required_merge_fields() -> list[str]:
    return get_list("spam_safe.md", "required_merge_fields")


def get_greeting_variants() -> list[str]:
    return get_list("greetings.md", "variants")


def get_cta_variants() -> list[str]:
    return get_list("ctas.md", "variants")


def get_closing_variants() -> list[str]:
    return get_list("closings.md", "variants")


def get_phrasing_hints() -> list[str]:
    """Baseline quality hints (sentence_patterns + tone_hygiene) applied to every email."""
    meta = get_meta("phrasing.md")
    hints: list[str] = []
    for key in ("sentence_patterns", "tone_hygiene"):
        value = meta.get(key, [])
        if isinstance(value, list):
            hints.extend(value)
    return hints


def get_rhythm_variants() -> list[str]:
    """Per-email rhythm/feel variants; the variation engine picks one."""
    return get_list("phrasing.md", "rhythm_variants")


def get_structures() -> dict[str, dict]:
    """All email structures as {structure_id: {label, description, steps}}."""
    value = get_meta("structures.md").get("structures", {})
    return value if isinstance(value, dict) else {}


def get_structure_ids() -> list[str]:
    """The selectable structure ids (catalogue keys)."""
    return list(get_structures().keys())


def get_structure_steps(structure_id: str) -> list[str]:
    """Paragraph-order steps for one structure ([] if unknown)."""
    s = get_structures().get(structure_id, {})
    steps = s.get("steps", []) if isinstance(s, dict) else []
    return list(steps) if isinstance(steps, list) else []


def get_tone(tone_key: str) -> str:
    """Body text of a tone file (e.g. 'professional'). '' if unknown."""
    safe = "".join(c for c in (tone_key or "").strip().lower() if c.isalnum() or c == "_")
    path = TONES_DIR / f"{safe}.md"

    def _build(p: Path) -> str:
        if not p.exists():
            return ""
        _, body = split_frontmatter(p.read_text(encoding="utf-8"))
        return body.strip()

    return _load_cached(path, _build)  # type: ignore[return-value]


def clear_cache() -> None:
    """Drop all cached parses (used by tests)."""
    with _lock:
        _cache.clear()
