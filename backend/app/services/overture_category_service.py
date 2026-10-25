"""
Overture category taxonomy + alias resolution.

- seed_overture_categories_from_csv(): loads the official Overture category list
  (code + hierarchy) into overture_categories. Reused by the monthly refresh.
- seed_aliases_from_static_map(): one-time migration of the in-code OVERTURE_CATEGORY_MAP
  into overture_category_aliases seed rows.
- resolve_overture_categories(): the dynamic resolver (alias -> trigram -> LLM -> fallback).
"""

import asyncio
import csv
import io
import logging
import weakref

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Official Overture Places taxonomy, published per release on the docs site.
# The old schema-repo CSV (docs/schema/concepts/by-theme/places/overture_categories.csv)
# was deleted when `categories` was removed in the 2026-09-23 release.
OVERTURE_TAXONOMY_CSV_URL = "https://docs.overturemaps.org/taxonomy/{release}/taxonomy.csv"
# Used when the requested release has no published CSV (e.g. hotfix "2026-09-23.1"
# only publishes under "2026-09-23.0").
OVERTURE_TAXONOMY_FALLBACK_RELEASE = "2026-09-23.0"


def _parse_categories_csv(text_body: str) -> list[dict]:
    """Parse the 'taxonomy,primary,displayName,level,isBasic,basicCategory' CSV.

    `taxonomy` is the full path ("education > place_of_learning > school > preschool"),
    `primary` the leaf code, and `level` its depth (0 = top level).
    """
    rows: list[dict] = []
    for rec in csv.DictReader(io.StringIO(text_body)):
        code = (rec.get("primary") or "").strip()
        if not code:
            continue
        path = [p.strip() for p in (rec.get("taxonomy") or "").split(">") if p.strip()]
        ancestors = path[:-1] if path and path[-1] == code else path
        display_name = (rec.get("displayName") or "").strip() or code.replace("_", " ").title()
        rows.append(
            {
                "code": code[:128],
                "display_name": display_name[:255],
                "ancestors": ancestors,
                "is_primary_level": len(path) <= 1,
            }
        )
    return rows


def _taxonomy_csv_urls(release: str | None) -> list[str]:
    """Candidate CSV URLs: the exact release, its '.0' base, then the known-good one."""
    releases: list[str] = []
    if release:
        releases.append(release)
        base = release.rsplit(".", 1)[0] + ".0" if "." in release else release
        releases.append(base)
    releases.append(OVERTURE_TAXONOMY_FALLBACK_RELEASE)
    return [OVERTURE_TAXONOMY_CSV_URL.format(release=r) for r in dict.fromkeys(releases)]


async def seed_overture_categories_from_csv(db: AsyncSession, release: str | None = None) -> int:
    """Download the Overture category taxonomy and upsert it into overture_categories."""
    body = None
    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": "Evecta/1.0"}) as client:
        for url in _taxonomy_csv_urls(release):
            resp = await client.get(url)
            if resp.status_code == 404:
                logger.info("[OVERTURE_CAT] No taxonomy CSV at %s — trying next", url)
                continue
            resp.raise_for_status()
            body = resp.content.decode("utf-8-sig", "replace")
            break
    if body is None:
        raise RuntimeError(f"No Overture taxonomy CSV found for release={release!r}")

    rows = _parse_categories_csv(body)
    if not rows:
        logger.warning("[OVERTURE_CAT] CSV parsed to 0 rows — aborting seed")
        return 0

    stmt = text(
        """
        INSERT INTO overture_categories (code, display_name, ancestors, is_primary_level)
        VALUES (:code, :display_name, CAST(:ancestors AS varchar[]), :is_primary_level)
        ON CONFLICT (code) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            ancestors = EXCLUDED.ancestors,
            is_primary_level = EXCLUDED.is_primary_level
        """
    )
    for start in range(0, len(rows), 500):
        await db.execute(stmt, rows[start:start + 500])
    await db.commit()
    logger.info("[OVERTURE_CAT] Seeded %s categories from CSV", len(rows))
    return len(rows)


async def seed_aliases_from_static_map(db: AsyncSession) -> int:
    """One-time: migrate the in-code OVERTURE_CATEGORY_MAP into seed alias rows.

    Each map entry becomes alias=normalize(industry) -> its category tokens. The
    resolver learns everything else (variants, long-tail) on demand, so we only need
    the common base entries here.
    """
    from app.services.lead_generation_service import OVERTURE_CATEGORY_MAP, _normalize_overture_term

    rows: list[dict] = []
    seen: set[str] = set()
    for industry, tokens in OVERTURE_CATEGORY_MAP.items():
        alias = _normalize_overture_term(industry)[:160]
        if not alias or alias in seen or not tokens:
            continue
        seen.add(alias)
        rows.append({"alias": alias, "category_codes": list(tokens), "source": "seed", "confidence": 1.0})

    if not rows:
        return 0

    stmt = text(
        """
        INSERT INTO overture_category_aliases
            (alias, category_codes, source, confidence, hit_count, created_at, updated_at)
        VALUES (:alias, CAST(:category_codes AS varchar[]), :source, :confidence, 0, NOW(), NOW())
        ON CONFLICT (alias) DO UPDATE SET
            category_codes = EXCLUDED.category_codes,
            source = EXCLUDED.source,
            confidence = EXCLUDED.confidence,
            updated_at = NOW()
        """
    )
    await db.execute(stmt, rows)
    await db.commit()
    logger.info("[OVERTURE_CAT] Seeded %s aliases from static map", len(rows))
    return len(rows)


# ── Resolver ───────────────────────────────────────────────────────────────────

# Trailing words that add no category meaning — stripped so "childcare centre"
# normalizes to "childcare" and hits the same alias.
_ALIAS_NOISE_SUFFIXES = {"centre", "center", "centres", "centers", "co", "ltd", "inc", "llc"}

# One client per event loop: the Gemini client binds its async channel to the loop of
# its first call, and Celery tasks each run (and close) their own loop, so a single
# process-wide client fails every task after the first.
_category_llm_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, object]" = weakref.WeakKeyDictionary()


def _get_category_llm():
    """Gemini client for category mapping in the running event loop (None if no API key)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop in _category_llm_by_loop:
        return _category_llm_by_loop[loop]
    llm = None
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from app.core.config import get_settings
        s = get_settings()
        if s.GEMINI_API_KEY:
            llm = ChatGoogleGenerativeAI(
                model=s.GEMINI_MODEL, google_api_key=s.GEMINI_API_KEY, temperature=0,
            )
    except Exception:
        logger.warning("[OVERTURE_CAT] Could not init category LLM", exc_info=True)
    if loop is not None:
        _category_llm_by_loop[loop] = llm
    return llm


def _alias_normalize(value: str | None) -> str:
    from app.services.lead_generation_service import _normalize_overture_term
    norm = _normalize_overture_term(value)
    words = norm.split()
    while words and words[-1] in _ALIAS_NOISE_SUFFIXES:
        words.pop()
    return " ".join(words) if words else norm


async def _llm_pick_categories(
    norm: str,
    candidates: list,
    user_id=None,
) -> list[str]:
    """Ask Gemini to pick the best category code(s) for `norm` from the candidates.

    candidates rows: (code, display_name, is_primary, similarity). Umbrella/top-level
    categories (is_primary) are dropped when a specific category is also picked — so
    e.g. "chocolate factory" → ['chocolatier'] rather than ['chocolatier','retail',
    'business_to_business'] which would match hundreds of unrelated businesses.
    """
    llm = _get_category_llm()
    if llm is None:
        return []
    cand_list = "\n".join(f"- {row[0]} ({row[1]})" for row in candidates)
    broad = {row[0] for row in candidates if row[2]}  # is_primary_level (umbrella) codes
    prompt = (
        "You map a user's business-type query to Overture Maps category codes.\n"
        f'Business type: "{norm}"\n'
        "Choose the 1-2 MOST SPECIFIC matching codes. Rules:\n"
        "- Strongly prefer a specific business type (e.g. chocolatier, bakery, gym) over\n"
        "  broad umbrella categories (e.g. retail, business_to_business, shopping,\n"
        "  professional_services, manufacturing).\n"
        "- Use a broad/umbrella category ONLY if no specific one fits.\n"
        "- Return [] if nothing genuinely fits — do NOT force a match.\n"
        f"Candidates:\n{cand_list}\n"
        'Return ONLY a JSON array of code strings, e.g. ["chocolatier"].'
    )
    try:
        from app.services.ai.tracked_llm import tracked_ainvoke, llm_model_name
        from app.core.config import get_settings
        s = get_settings()
        resp = await tracked_ainvoke(
            llm=llm,
            prompt=prompt,
            provider="gemini",
            model=llm_model_name(llm, fallback=s.GEMINI_MODEL),
            feature="category_resolution",
            user_id=user_id,
        )
        content = resp.content if hasattr(resp, "content") else str(resp)
        import json
        import re
        match = re.search(r"\[.*\]", content, re.S)
        if not match:
            return []
        picked = json.loads(match.group(0))
        valid = {row[0] for row in candidates}
        picked = [c for c in picked if isinstance(c, str) and c in valid]
        # If the LLM picked any specific category, drop the umbrella ones (they'd
        # pollute results with unrelated businesses).
        specific = [c for c in picked if c not in broad]
        return (specific or picked)[:2]
    except Exception:
        logger.warning("[OVERTURE_CAT] LLM category pick failed for %r", norm, exc_info=True)
        return []


async def _resolve_and_learn(db: AsyncSession, norm: str, user_id=None) -> list[str]:
    """Resolve a not-yet-aliased term via trigram + LLM, and store it as a learned alias.

    Candidates = trigram matches (lexically close leaves) UNION the broad top-level
    categories. The broad set means even a term with NO lexical overlap to any leaf
    (e.g. "artisan candle workshop") can still be mapped by the LLM to a sensible
    parent category — instead of falling through to name-only matching.
    """
    if not norm:
        return []
    # Whole-phrase similarity() alone misses multi-word phrases: "dental clinics"
    # vs "Dentist" scores ~0.21, under the 0.3 `%` threshold, so no dental leaf
    # ever reached the LLM. strict_word_similarity() scores the best word-bounded
    # portion of the phrase instead ("dental" vs "Dentist" = 0.36), letting
    # word-level matches qualify as candidates too.
    candidates = (
        await db.execute(
            text(
                """
                SELECT code, display_name, bool_or(is_primary) AS is_primary, MAX(s) AS s FROM (
                    (SELECT code, display_name, is_primary_level AS is_primary,
                            GREATEST(similarity(display_name, :q),
                                     strict_word_similarity(display_name, :q)) AS s
                     FROM overture_categories
                     WHERE display_name % :q OR code % :q
                        OR strict_word_similarity(display_name, :q) >= 0.3
                     ORDER BY s DESC
                     LIMIT 12)
                    UNION
                    (SELECT code, display_name, is_primary_level AS is_primary, 0.0 AS s
                     FROM overture_categories
                     WHERE is_primary_level = true)
                ) c
                GROUP BY code, display_name
                ORDER BY s DESC
                """
            ),
            {"q": norm},
        )
    ).fetchall()
    if not candidates:
        return []

    codes = await _llm_pick_categories(norm, candidates, user_id=user_id)
    if not codes:
        top = candidates[0]
        if top[3] and top[3] >= 0.45 and not top[2]:  # strong trigram match to a SPECIFIC leaf
            codes = [top[0]]
    if codes:
        await db.execute(
            text(
                """
                INSERT INTO overture_category_aliases
                    (alias, category_codes, source, confidence, hit_count, created_at, updated_at)
                VALUES (:a, CAST(:codes AS varchar[]), 'learned', 0.7, 1, NOW(), NOW())
                ON CONFLICT (alias) DO UPDATE SET
                    category_codes = EXCLUDED.category_codes, updated_at = NOW()
                """
            ),
            {"a": norm[:160], "codes": codes},
        )
        logger.info("[OVERTURE_CAT] Learned alias %r -> %s", norm, codes)
    return codes


async def resolve_overture_categories(
    db: AsyncSession,
    industry: str,
    search_terms: list[str] | None = None,
    learn: bool = True,
    user_id=None,
) -> dict:
    """
    Dynamic, DB-backed category resolution. Drop-in replacement for the static
    resolve_overture_filter — same dict shape plus a stable `category_key`.

    alias lookup (fast) → trigram + LLM on miss (learn it) → name fallback.
    Phrasing variants resolve to the same codes → same category_key → warm hits.

    learn=True  (background paths): on an alias miss, run trigram + LLM and STORE
                the result as a learned alias.
    learn=False (request path): alias-lookup ONLY — no LLM, no DB learning. On a
                miss the category_key falls back to the normalized industry (the
                area is cold anyway). Once the background fill learns the alias, the
                next request hits it → consistent key, no LLM in the request path.
    """
    from app.services.lead_generation_service import (
        OVERTURE_CATEGORY_MAP,
        _is_strict_overture_intent,
        _strip_overture_strict_markers,
    )

    strict = _is_strict_overture_intent(industry, search_terms)
    terms = [industry] if strict else [industry, *(search_terms or [])]

    codes: list[str] = []
    for term in terms:
        norm = _alias_normalize(_strip_overture_strict_markers(term))
        if not norm:
            continue
        static_codes = OVERTURE_CATEGORY_MAP.get(norm)
        if static_codes:
            for code in static_codes:
                if code not in codes:
                    codes.append(code)
            continue
        row = (
            await db.execute(
                text("SELECT category_codes FROM overture_category_aliases WHERE alias = :a"),
                {"a": norm},
            )
        ).first()
        if row:
            await db.execute(
                text("UPDATE overture_category_aliases SET hit_count = hit_count + 1 WHERE alias = :a"),
                {"a": norm},
            )
            for code in row[0]:
                if code not in codes:
                    codes.append(code)

    if not codes and learn:
        # Background path only: resolve novel terms via trigram + LLM and store them.
        # Industry phrase first, then each search term — the first one that resolves
        # unblocks the search and is learned as an alias for next time.
        attempted: set[str] = set()
        for term in terms:
            norm = _alias_normalize(_strip_overture_strict_markers(term))
            if not norm or norm in attempted:
                continue
            attempted.add(norm)
            learned = await _resolve_and_learn(db, norm, user_id=user_id)
            if learned:
                for code in learned:
                    if code not in codes:
                        codes.append(code)
                break

    await db.commit()  # persist hit_count bumps + any learned alias

    keyword_terms = [
        _strip_overture_strict_markers(term) for term in terms if _strip_overture_strict_markers(term)
    ]
    if not keyword_terms and industry:
        keyword_terms = [_strip_overture_strict_markers(industry)]

    category_key = (
        "|".join(sorted(dict.fromkeys(codes)))[:128]
        if codes
        else _alias_normalize(industry)[:128]
    )
    return {
        "category_codes": codes,
        "category_patterns": [f"%{code}%" for code in codes],
        "keyword_patterns": [f"%{term}%" for term in dict.fromkeys(keyword_terms)],
        "has_category": bool(codes),
        "category_key": category_key,
        "strict_intent": strict,
    }
