import logging
import httpx
import asyncio
import itertools
import math
import time

logger = logging.getLogger(__name__)
from app.core.config import get_settings
from fastapi import HTTPException
from app.database.session import async_session_factory
from sqlalchemy import func, update, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.lead_log_lead import LeadLogLead
from app.models.lead import Lead
from app.models.overture_place import OverturePlace
from datetime import datetime, timezone
from app.utils.chat_helper import clean_domain
from app.utils.redis_context import (
    arun,
    get_cached_leads,
    set_cached_leads,
    get_cached_geocode,
    set_cached_geocode,
)
from app.services.external_api_usage import record_places_usage
from uuid import UUID

settings = get_settings()
GOOGLE_MAPS_API_KEY = settings.GOOGLE_MAPS_API_KEY

MAX_PAGES = 3
PAGE_DELAY = 2.2
ENRICH_COMMIT_BATCH_SIZE = 30
MIN_LOCAL_SEARCH_RADIUS_KM = 5.0
TINY_STRICT_LOCATION_RADIUS_KM = 1.5
TINY_STRICT_LOCATION_MAX_LEADS = 5

# Overture's taxonomy.primary values are flat snake_case leaves
# (e.g. "child_care_and_day_care", "pizza_restaurant", "automotive_repair"),
# NOT a dotted hierarchy. Granularity is mixed — some rows use a parent like
# "eat_and_drink". We therefore map each user term to one or more *substring
# tokens* and match them as `%token%` against (taxonomy.primary + its hierarchy).
# Substrings catch sibling leaves: "%restaurant%" → pizza_restaurant, thai_restaurant, …
OVERTURE_CATEGORY_MAP: dict[str, list[str]] = {
    "accountant": ["accounting", "accountant"],
    "accountants": ["accounting", "accountant"],
    "accounting": ["accounting", "accountant"],
    "auto repair": ["automotive_repair", "auto_repair", "car_repair"],
    "automotive": ["automotive"],
    "bakery": ["bakery"],
    "bakeries": ["bakery"],
    "bar": ["bar", "pub"],
    "bars": ["bar", "pub"],
    "beauty salon": ["beauty_salon", "beauty"],
    "beauty salons": ["beauty_salon", "beauty"],
    "cafe": ["cafe", "coffee"],
    "cafes": ["cafe", "coffee"],
    "childcare": ["child_care", "day_care", "preschool"],
    "child care": ["child_care", "day_care", "preschool"],
    "daycare": ["child_care", "day_care", "preschool"],
    "clinic": ["clinic", "medical_clinic"],
    "clinics": ["clinic", "medical_clinic"],
    "coffee shop": ["cafe", "coffee"],
    "coffee shops": ["cafe", "coffee"],
    "construction": ["construction", "contractor"],
    "dentist": ["dentist"],
    "dentists": ["dentist"],
    "doctor": ["doctor", "physician"],
    "doctors": ["doctor", "physician"],
    "education": ["education", "school"],
    "electrician": ["electrician", "electrical"],
    "electricians": ["electrician", "electrical"],
    "fitness": ["gym", "fitness"],
    "fitness center": ["gym", "fitness"],
    "fitness centers": ["gym", "fitness"],
    "fitness centre": ["gym", "fitness"],
    "fitness centres": ["gym", "fitness"],
    "fitness club": ["gym", "fitness"],
    "fitness clubs": ["gym", "fitness"],
    "gym": ["gym", "fitness"],
    "gyms": ["gym", "fitness"],
    "health club": ["gym", "fitness"],
    "health clubs": ["gym", "fitness"],
    "hair salon": ["hair_salon", "hairdresser", "barber"],
    "hotel": ["hotel"],
    "hotels": ["hotel"],
    "lawyer": ["lawyer", "law_firm", "attorney", "legal"],
    "lawyers": ["lawyer", "law_firm", "attorney", "legal"],
    "law firm": ["lawyer", "law_firm", "attorney", "legal"],
    "law firms": ["lawyer", "law_firm", "attorney", "legal"],
    "medical": ["medical", "health"],
    "motel": ["motel"],
    "motels": ["motel"],
    "pharmacy": ["pharmacy", "drugstore"],
    "pharmacies": ["pharmacy", "drugstore"],
    "plumber": ["plumber", "plumbing"],
    "plumbers": ["plumber", "plumbing"],
    "preschool": ["preschool"],
    "real estate": ["real_estate"],
    "restaurant": ["restaurant"],
    "restaurants": ["restaurant"],
    "resort": ["resort"],
    "resorts": ["resort"],
    "retail": ["retail", "store", "shop"],
    "school": ["school"],
    "schools": ["school"],
    "spa": ["spa"],
    "spas": ["spa"],
}

OVERTURE_STRICT_INTENT_MARKERS = ("only", "exact", "exactly", "just", "strict")


def _normalize_overture_term(value: str | None) -> str:
    return " ".join((value or "").strip().lower().replace("-", " ").replace("_", " ").split())


def _strip_overture_strict_markers(value: str | None) -> str:
    words = [
        word
        for word in _normalize_overture_term(value).split()
        if word not in OVERTURE_STRICT_INTENT_MARKERS
    ]
    return " ".join(words)


def _is_strict_overture_intent(industry: str, search_terms: list[str] | None = None) -> bool:
    terms = [industry, *(search_terms or [])]
    for term in terms:
        words = set(_normalize_overture_term(term).split())
        if words.intersection(OVERTURE_STRICT_INTENT_MARKERS):
            return True
    return False


def resolve_overture_filter(industry: str, search_terms: list[str] | None = None) -> dict:
    """
    Resolve user-facing industry/search terms to Overture category prefixes.

    Overture uses a fixed taxonomy, unlike Google Places keyword search. Unknown
    terms intentionally fall back to name matching so long-tail searches still
    have a chance to return rows once an area is loaded.
    """
    categories: list[str] = []
    seen_categories: set[str] = set()
    strict_intent = _is_strict_overture_intent(industry, search_terms)
    terms = [industry] if strict_intent else [industry, *(search_terms or [])]

    for term in terms:
        normalized = _strip_overture_strict_markers(term)
        if not normalized:
            continue
        for category in OVERTURE_CATEGORY_MAP.get(normalized, []):
            if category not in seen_categories:
                categories.append(category)
                seen_categories.add(category)

    keyword_terms = [
        _strip_overture_strict_markers(term)
        for term in terms
        if _strip_overture_strict_markers(term)
    ]
    if not keyword_terms and industry:
        keyword_terms = [_strip_overture_strict_markers(industry)]

    return {
        "category_codes": categories,
        # Kept for callers that still read patterns. Matching itself is token-based
        # (see _overture_match_sql), so "%bar%" no longer reaches "barber".
        "category_patterns": [f"%{category}%" for category in categories],
        "keyword_patterns": [f"%{term}%" for term in dict.fromkeys(keyword_terms)],
        "has_category": bool(categories),
        "strict_intent": strict_intent,
    }


def _overture_codes(resolved_filter: dict) -> list[str]:
    """Raw category codes, tolerating older filters that only carry "%code%" patterns."""
    codes = [
        str(code).strip().lower()
        for code in (resolved_filter.get("category_codes") or [])
        if str(code).strip()
    ]
    if codes:
        return codes
    return [
        stripped
        for pattern in resolved_filter.get("category_patterns", [])
        if (stripped := str(pattern).strip().lower().strip("%"))
    ]


def _overture_token_haystack(primary_col: str, taxonomy_col: str, hierarchy_col: str) -> str:
    """A '|'-delimited view of a place's primary category plus its taxonomy ancestry.

    Overture codes are flat snake_case, so splitting on "_" gives us segment
    boundaries: "pizza_restaurant" -> "|pizza|restaurant|".
    """
    parts = [
        f"replace(lower(coalesce({primary_col}, '')), '_', '|')",
        f"replace(lower(coalesce({taxonomy_col}, '')), '_', '|')",
        f"replace(lower(coalesce(array_to_string({hierarchy_col}, '|'), '')), '_', '|')",
    ]
    return "('|' || " + " || '|' || ".join(parts) + " || '|')"


def _overture_token_patterns(code: str) -> list[str]:
    """LIKE patterns matching `code` on segment boundaries.

    A SINGLE-token code may also land as a suffix or a simple plural, because Overture
    writes `bookstore`, `drugstore`, `gastropub`, `architecture_schools`, and — for
    spas — only the plural `spas`. Anchoring both ends would silently drop those: it
    cost 31 legitimate codes across 8 industries when first measured.

    A MULTI-token code stays anchored at both ends, so `pet_store` cannot reach
    `carpet_store`. Suffix matching is safe for single tokens because the trailing
    delimiter still has to line up: `%bar|%` clears `cocktail_bar` and rejects
    `barber`, `bartender` and `cabaret`.
    """
    if "_" in code:
        return [f"%|{code.replace('_', '|')}|%"]
    return [f"%{code}|%", f"%{code}s|%", f"%{code}es|%"]


def _pg_binder(params: dict):
    """Bind values as :p0, :p1, ... into `params` (Postgres)."""
    counter = itertools.count()

    def bind(value):
        key = f"p{next(counter)}"
        params[key] = value
        return f":{key}"

    return bind


def _duckdb_binder(values: list):
    """Append values positionally for DuckDB's `?` placeholders."""

    def bind(value):
        values.append(value)
        return "?"

    return bind


def _overture_match_sql(
    resolved_filter: dict,
    *,
    primary_col: str,
    taxonomy_col: str,
    hierarchy_col: str,
    name_col: str,
    bind,
) -> str:
    """Category/keyword match clause, shared by the DuckDB (S3) and Postgres (cache) queries.

    Two rules keep results on-topic. Both were live bugs, measured 2026-07-23 against
    a 500-lead "restaurants in Kathmandu" search:

    1. PRIMARY ONLY. Overture's `taxonomy.alternates` lists everything a business
       *also* does, and it used to sit in the same haystack as the primary category —
       so a bus stop with a momo counter scored exactly as well as a restaurant.
       69 of the 74 explainable off-target rows arrived this way. We now match the
       primary category and its taxonomy ancestry (which is primary-derived) only.
    2. TOKEN, NOT SUBSTRING. Codes are flat snake_case, so "%bar%" used to match
       `barber`, `bartender`, `public_school` and `public_toilet` — 26 of the 69
       seeded aliases were affected. We compare "_"->"|" normalised strings so a code
       must line up on segment boundaries. "|" is the delimiter because "_" is a
       single-character wildcard in LIKE: an underscore-delimited boundary check
       silently matches everything.

    Places Overture never categorised still match on name, which rescues real
    listings like "waah restaurant & cafe". When nothing resolved to a category at
    all (long-tail industries), name matching is the only available signal and stays
    unrestricted — narrowing it there would return zero rows instead of loose ones.
    """
    codes = _overture_codes(resolved_filter)
    haystack = _overture_token_haystack(primary_col, taxonomy_col, hierarchy_col)
    name_expr = f"lower(coalesce({name_col}, ''))"

    conditions = [
        f"{haystack} LIKE {bind(pattern)}"
        for code in codes
        for pattern in _overture_token_patterns(code)
    ]
    for pattern in resolved_filter.get("keyword_patterns", []):
        placeholder = bind(str(pattern).lower())
        if codes:
            # A categorised place must earn its spot on the category, not on a word
            # that happens to appear in its name.
            conditions.append(f"({primary_col} IS NULL AND {name_expr} LIKE {placeholder})")
        else:
            conditions.append(f"{name_expr} LIKE {placeholder}")

    return "(" + " OR ".join(conditions) + ")" if conditions else "TRUE"


def bbox_around(center_lat: float, center_lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """Return min_lng, min_lat, max_lng, max_lat for a radius around a point."""
    lat_delta = radius_km / 111.32
    cos_lat = max(math.cos(math.radians(center_lat)), 0.01)
    lng_delta = radius_km / (111.32 * cos_lat)
    return (
        center_lng - lng_delta,
        center_lat - lat_delta,
        center_lng + lng_delta,
        center_lat + lat_delta,
    )


def _overture_setting(name: str, default):
    return getattr(settings, name, default)


# Cached auto-detected Overture release so cold-loads track the latest available
# release instead of a hardcoded env pin (which breaks when Overture purges it).
# Detection runs only inside background DuckDB threads, cached for 24h.
_EFFECTIVE_RELEASE_TTL_S = 24 * 60 * 60
_effective_release_cache: dict = {"value": None, "ts": 0.0}


def _latest_release_via_glob() -> str | None:
    """Detect the newest Overture release by globbing the S3 release prefix (slow)."""
    try:
        import duckdb
    except ImportError:
        return None
    conn = duckdb.connect()
    try:
        conn.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
        base = _overture_setting("OVERTURE_S3_BASE", "s3://overturemaps-us-west-2/release").rstrip("/")
        rows = conn.execute(
            f"""
            SELECT DISTINCT regexp_extract(file, 'release/([^/]+)/', 1) AS rel
            FROM glob('{base}/*/theme=places/type=place/part-00000-*.parquet')
            ORDER BY rel DESC
            """
        ).fetchall()
    except Exception:
        logger.warning("[OVERTURE] Release auto-detect failed; using fallback", exc_info=True)
        return None
    finally:
        conn.close()
    return rows[0][0] if rows else None


def _effective_overture_release() -> str:
    """Latest auto-detected release (cached 24h), falling back to the env value."""
    import time
    now = time.time()
    cached = _effective_release_cache.get("value")
    if cached and (now - _effective_release_cache.get("ts", 0)) < _EFFECTIVE_RELEASE_TTL_S:
        return cached
    detected = _latest_release_via_glob()
    if detected:
        _effective_release_cache["value"] = detected
        _effective_release_cache["ts"] = now
        return detected
    # Detection failed → fall back to the env-pinned release (safety net / override).
    return cached or _overture_setting("OVERTURE_RELEASE", "2026-05-20.0")


def _overture_s3_path(release: str | None = None) -> str:
    base = _overture_setting("OVERTURE_S3_BASE", "s3://overturemaps-us-west-2/release").rstrip("/")
    release = release or _effective_overture_release()
    return f"{base}/{release}/theme=places/type=place/*.parquet"


def _duckdb_value(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if hasattr(value, "as_py"):
        return value.as_py()
    return value


def _first_overture_value(value):
    value = _duckdb_value(value)
    if not value:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _overture_address_to_text(address) -> str | None:
    address = _duckdb_value(_first_overture_value(address))
    if not address:
        return None
    if isinstance(address, str):
        return address
    if not isinstance(address, dict):
        return str(address)

    parts = []
    for key in ("freeform", "locality", "region", "postcode", "country"):
        value = address.get(key)
        if value and value not in parts:
            parts.append(str(value))
    return ", ".join(parts) if parts else None


def _duckdb_pull_overture_sync(
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    center_lat: float,
    center_lng: float,
    radius_km: float,
    resolved_filter: dict,
    limit: int,
) -> list[dict]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "duckdb is not installed. Add duckdb to backend requirements before using Overture direct pulls."
        ) from exc

    # Build the category/keyword match clause as bound SQL (NOT string-interpolated
    # user input) so the LIMIT applies to *matching* rows, not arbitrary bbox rows.
    filter_params: list = []
    match_clause = _overture_match_sql(
        resolved_filter,
        primary_col="taxonomy.primary",
        taxonomy_col="taxonomy.primary",
        hierarchy_col="taxonomy.hierarchy",
        name_col="names.primary",
        bind=_duckdb_binder(filter_params),
    )

    # Over-fetch a little so the post-query radius trim (bbox is wider than the
    # circle) can still yield up to `limit` results.
    fetch_limit = max(limit * 3, 50)

    conn = duckdb.connect(database=":memory:")
    try:
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute("SET s3_region='us-west-2';")
        # Overture parquet files are large; raise the per-request HTTP timeout and
        # add retries so a slow S3 response doesn't abort the read (default is ~30s).
        conn.execute("SET http_timeout=300000;")       # 300s per request
        conn.execute("SET http_retries=5;")
        conn.execute("SET http_retry_wait_ms=1000;")

        rows = conn.execute(
            f"""
            SELECT
                names.primary AS name,
                websites[1] AS website,
                emails[1] AS email,
                phones[1] AS phone,
                addresses AS addresses,
                ST_Y(geometry) AS lat,
                ST_X(geometry) AS lng
            FROM read_parquet(?, filename=false)
            WHERE bbox.xmin >= ?
              AND bbox.xmax <= ?
              AND bbox.ymin >= ?
              AND bbox.ymax <= ?
              AND confidence >= ?
              AND (operating_status IS NULL OR operating_status <> 'closed')
              AND {match_clause}
            ORDER BY ST_Distance(geometry, ST_Point(?, ?)) ASC
            LIMIT ?
            """,
            [
                _overture_s3_path(),
                min_lng,
                max_lng,
                min_lat,
                max_lat,
                _overture_setting("OVERTURE_MIN_CONFIDENCE", 0.5),
                *filter_params,
                center_lng,
                center_lat,
                fetch_limit,
            ],
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
    finally:
        conn.close()

    leads: list[dict] = []
    for raw_row in rows:
        row = dict(zip(columns, raw_row))
        lat = row.get("lat")
        lng = row.get("lng")
        if lat is None or lng is None:
            continue
        # Exact radius enforcement — bbox is padded/square, this clamps to the circle.
        if haversine_distance(center_lat, center_lng, lat, lng) > radius_km:
            continue

        name = row.get("name")
        if not name:
            continue
        leads.append(
            {
                "business_name": name,
                "address": _overture_address_to_text(row.get("addresses")) or "N/A",
                "website": _first_overture_value(row.get("website")) or "N/A",
                "email": _first_overture_value(row.get("email")) or None,
                "contact_number": _first_overture_value(row.get("phone")) or "N/A",
            }
        )
        if len(leads) >= limit:
            break

    return leads


async def duckdb_pull_overture(
    bbox: tuple[float, float, float, float],
    center_lat: float,
    center_lng: float,
    radius_km: float,
    resolved_filter: dict,
    limit: int,
) -> list[dict]:
    """
    Pull matching Overture places directly from S3 with DuckDB.

    This returns lead-shaped dict fragments and does not write anything to our
    database. It is the temporary path before overture_places/overture_loaded_areas
    are created.
    """
    return await asyncio.to_thread(
        _duckdb_pull_overture_sync,
        bbox[0],
        bbox[1],
        bbox[2],
        bbox[3],
        center_lat,
        center_lng,
        radius_km,
        resolved_filter,
        limit,
    )


def _overture_category_key(resolved_filter: dict, industry: str) -> str:
    """Stable key identifying which category set is loaded for an area.

    Built from the resolved category tokens (e.g. "child_care|day_care|preschool"),
    falling back to the keyword/industry for long-tail searches with no category.
    """
    def _tokens(patterns):
        return [p.strip("%").strip().lower() for p in (patterns or []) if p.strip("%").strip()]

    tokens = _tokens(resolved_filter.get("category_patterns"))
    if not tokens:
        tokens = _tokens(resolved_filter.get("keyword_patterns"))
    if not tokens:
        tokens = [_normalize_overture_term(industry)]
    return "|".join(sorted(dict.fromkeys(tokens)))[:128]


def _duckdb_fetch_area_rows_sync(
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    center_lat: float,
    center_lng: float,
    min_confidence: float,
    resolved_filter: dict,
    max_rows: int,
    release: str | None = None,
) -> list[dict]:
    """Pull the searched category's nearest places in a bbox — for caching.

    Category-scoped (not all categories) and capped at `max_rows`, ordered by
    distance from the center so the cap keeps the NEAREST matches.
    """
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "duckdb is not installed. Add duckdb to backend requirements before using Overture."
        ) from exc

    filter_params: list = []
    match_clause = _overture_match_sql(
        resolved_filter,
        primary_col="taxonomy.primary",
        taxonomy_col="taxonomy.primary",
        hierarchy_col="taxonomy.hierarchy",
        name_col="names.primary",
        bind=_duckdb_binder(filter_params),
    )

    conn = duckdb.connect(database=":memory:")
    try:
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute("SET s3_region='us-west-2';")
        # Overture parquet files are large; raise the per-request HTTP timeout and
        # add retries so a slow S3 response doesn't abort the read (default is ~30s).
        conn.execute("SET http_timeout=300000;")       # 300s per request
        conn.execute("SET http_retries=5;")
        conn.execute("SET http_retry_wait_ms=1000;")
        rows = conn.execute(
            f"""
            SELECT
                id AS overture_id,
                names.primary AS name,
                -- Overture removed `categories` in 2026-09-23 (schema v2); the
                -- taxonomy struct carries the primary leaf + alternates instead.
                taxonomy.primary AS category_primary,
                taxonomy.alternates AS category_alternate,
                taxonomy.primary AS taxonomy_primary,
                taxonomy.hierarchy AS taxonomy_hierarchy,
                websites[1] AS website,
                emails[1] AS email,
                phones[1] AS phone,
                addresses AS addresses,
                operating_status,
                confidence,
                ST_Y(geometry) AS lat,
                ST_X(geometry) AS lng
            FROM read_parquet(?, filename=false)
            WHERE bbox.xmin >= ?
              AND bbox.xmax <= ?
              AND bbox.ymin >= ?
              AND bbox.ymax <= ?
              AND confidence >= ?
              AND (operating_status IS NULL OR operating_status <> 'closed')
              AND {match_clause}
            ORDER BY ST_Distance(geometry, ST_Point(?, ?)) ASC
            LIMIT ?
            """,
            [
                _overture_s3_path(release),
                min_lng,
                max_lng,
                min_lat,
                max_lat,
                min_confidence,
                *filter_params,
                center_lng,
                center_lat,
                max_rows,
            ],
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
    finally:
        conn.close()
    return [dict(zip(columns, raw)) for raw in rows]


async def _fetch_overture_area_rows(
    bbox: tuple[float, float, float, float],
    center_lat: float,
    center_lng: float,
    min_confidence: float,
    resolved_filter: dict,
    max_rows: int,
    release: str | None = None,
) -> list[dict]:
    return await asyncio.to_thread(
        _duckdb_fetch_area_rows_sync,
        bbox[0], bbox[1], bbox[2], bbox[3],
        center_lat, center_lng,
        min_confidence, resolved_filter, max_rows, release,
    )


def _overture_country_code(addresses) -> str | None:
    addr = _duckdb_value(_first_overture_value(addresses))
    if isinstance(addr, dict):
        country = addr.get("country")
        if country:
            return str(country)[:2].upper()
    return None


def _overture_locality(addresses) -> str | None:
    """City/municipality from Overture's address struct (addresses[0].locality)."""
    addr = _duckdb_value(_first_overture_value(addresses))
    if isinstance(addr, dict):
        loc = addr.get("locality")
        if loc:
            return str(loc)[:128]
    return None


def _overture_categories_list(row: dict) -> list[str]:
    cats: list[str] = []
    primary = _duckdb_value(row.get("category_primary"))
    if primary:
        cats.append(str(primary))
    alternate = _duckdb_value(row.get("category_alternate")) or []
    if isinstance(alternate, list):
        for category in alternate:
            category = _duckdb_value(category)
            if category and str(category) not in cats:
                cats.append(str(category))
    return cats


async def _persist_overture_rows(db: AsyncSession, rows: list[dict]) -> int:
    """Bulk upsert Overture rows into overture_places (keyed by overture_id)."""
    now = datetime.now(timezone.utc)
    payload: list[dict] = []
    for row in rows:
        overture_id = _duckdb_value(row.get("overture_id"))
        name = _duckdb_value(row.get("name"))
        lat = row.get("lat")
        lng = row.get("lng")
        if not overture_id or not name or lat is None or lng is None:
            continue
        category_primary = _duckdb_value(row.get("category_primary"))
        website = _first_overture_value(row.get("website"))
        phone = _first_overture_value(row.get("phone"))
        address = _overture_address_to_text(row.get("addresses"))
        email = _first_overture_value(row.get("email"))
        operating_status = _duckdb_value(row.get("operating_status"))
        taxonomy_primary = _duckdb_value(row.get("taxonomy_primary"))
        taxonomy_hierarchy = _duckdb_value(row.get("taxonomy_hierarchy"))
        if not isinstance(taxonomy_hierarchy, list):
            taxonomy_hierarchy = []
        # Pre-score from Overture-known signals (§5.7 option (a)) so leads show a
        # real score before enrichment runs; enrichment re-scores with scraped data.
        pre_score = (
            (40 if email else 0)
            + (30 if website else 0)
            + (15 if phone else 0)
            + (10 if address else 0)
        )
        payload.append(
            {
                "overture_id": str(overture_id)[:64],
                "name": str(name)[:255],
                "category_primary": str(category_primary)[:128] if category_primary else None,
                "categories": _overture_categories_list(row),
                # Truncate to the column limits — some Overture URLs/addresses are very
                # long (UTM tails). The domain (needed for enrichment) is at the start.
                "website": str(website)[:512] if website else None,
                "email": str(email)[:320] if email else None,
                "phone": str(phone)[:64] if phone else None,
                "address": str(address)[:512] if address else None,
                "locality": _overture_locality(row.get("addresses")),
                "operating_status": str(operating_status)[:32] if operating_status else None,
                "taxonomy_primary": str(taxonomy_primary)[:128] if taxonomy_primary else None,
                "taxonomy_hierarchy": [str(t) for t in taxonomy_hierarchy if t],
                "country_code": _overture_country_code(row.get("addresses")),
                "confidence": row.get("confidence"),
                "lat": lat,
                "lng": lng,
                "loaded_at": now,
                # Provenance + enrichment seed (master-catalog design, doc §5.7):
                # email_source labels Overture-provided emails from the very first
                # write; enrichment_status 'pending' marks the row enrichment-eligible.
                "email_source": "overture" if email else None,
                "enrichment_status": "pending",
                "lead_score": pre_score,
            }
        )
    if not payload:
        return 0

    # ON CONFLICT updates Overture-PROVIDED fields only. CONTACT fields (email/phone/
    # website) use COALESCE — keep the last-known-good value if a new release drops it
    # (the catalog is a kept asset; don't lose hard-won contact data). DESCRIPTIVE
    # fields follow the source (so a rename / recategorize / "closed" status updates).
    # ENRICHMENT fields (refresh safety, doc §7): scraped_email/hunter_data/context are
    # NEVER touched here; email_source/lead_score only FILL when absent (COALESCE with
    # the existing value first); enrichment_status is INSERT-only (never reset a row
    # that enrichment already marked done/processing).
    stmt = text(
        """
        INSERT INTO overture_places
            (overture_id, name, category_primary, categories, website, email, phone,
             address, locality, operating_status, taxonomy_primary, taxonomy_hierarchy,
             country_code, confidence, source, geom, loaded_at,
             email_source, enrichment_status, lead_score)
        VALUES
            (:overture_id, :name, :category_primary, CAST(:categories AS varchar[]),
             :website, :email, :phone, :address, :locality, :operating_status, :taxonomy_primary,
             CAST(:taxonomy_hierarchy AS varchar[]), :country_code, :confidence, 'overture',
             ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), :loaded_at,
             :email_source, :enrichment_status, :lead_score)
        ON CONFLICT (overture_id) DO UPDATE SET
            name = EXCLUDED.name,
            category_primary = EXCLUDED.category_primary,
            categories = EXCLUDED.categories,
            website = COALESCE(EXCLUDED.website, overture_places.website),
            email = COALESCE(EXCLUDED.email, overture_places.email),
            phone = COALESCE(EXCLUDED.phone, overture_places.phone),
            address = EXCLUDED.address,
            locality = COALESCE(EXCLUDED.locality, overture_places.locality),
            operating_status = EXCLUDED.operating_status,
            taxonomy_primary = EXCLUDED.taxonomy_primary,
            taxonomy_hierarchy = EXCLUDED.taxonomy_hierarchy,
            country_code = EXCLUDED.country_code,
            confidence = EXCLUDED.confidence,
            geom = EXCLUDED.geom,
            loaded_at = EXCLUDED.loaded_at,
            email_source = COALESCE(overture_places.email_source, EXCLUDED.email_source),
            lead_score = COALESCE(overture_places.lead_score, EXCLUDED.lead_score)
        WHERE overture_places.source = 'overture'
        """
    )
    for start in range(0, len(payload), 1000):
        await db.execute(stmt, payload[start:start + 1000])
    return len(payload)


async def overture_area_is_warm(
    db: AsyncSession,
    center_lat: float,
    center_lng: float,
    radius_km: float,
    resolved_filter: dict,
    industry: str,
) -> bool:
    """Cheap registry check: is this (area, category) already cached & fresh? No loading."""
    if not resolved_filter.get("has_category"):
        # No category resolved → the lookup key falls back to the raw phrase, so any
        # registry row it matches is a legacy name-only load whose tiny frozen result
        # set must not be served warm. Answering cold re-runs the background load —
        # the only path that can LEARN the phrase's alias and resolve it properly.
        return False
    load_radius_km = radius_km + settings.OVERTURE_AREA_BUFFER_KM
    min_lng, min_lat, max_lng, max_lat = bbox_around(center_lat, center_lng, load_radius_km)
    category_key = resolved_filter.get("category_key") or _overture_category_key(resolved_filter, industry)
    covered = (
        await db.execute(
            text(
                """
                SELECT id FROM overture_loaded_areas
                WHERE category_key = :category_key
                  AND place_count > 0
                  AND ST_Contains(bbox, ST_MakeEnvelope(:min_lng, :min_lat, :max_lng, :max_lat, 4326))
                  AND loaded_at > (NOW() - (:ttl_days * INTERVAL '1 day'))
                LIMIT 1
                """
            ),
            {
                "min_lng": min_lng, "min_lat": min_lat, "max_lng": max_lng, "max_lat": max_lat,
                "category_key": category_key,
                "ttl_days": settings.OVERTURE_AREA_TTL_DAYS,
            },
        )
    ).scalar_one_or_none()
    return covered is not None


async def load_overture_area_background(
    industry: str,
    location: str,
    search_radius_km: float,
    search_terms: list[str] | None,
    session_factory,
    user_id=None,
) -> None:
    """Cold-load an area's category into overture_places. Called by the Celery task."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        coords = await geocode_location(client, location)
    if not coords:
        logger.warning("[OVERTURE] Background load skipped — geocode failed for %s", location)
        return
    center_lat, center_lng, _ = coords
    from app.services.overture_category_service import resolve_overture_categories
    async with session_factory() as db:
        resolved_filter = await resolve_overture_categories(
            db, industry, search_terms, user_id=user_id
        )
        await ensure_overture_area_loaded(
            db, center_lat, center_lng, search_radius_km, resolved_filter, industry
        )


async def ensure_overture_area_loaded(
    db: AsyncSession,
    center_lat: float,
    center_lng: float,
    radius_km: float,
    resolved_filter: dict,
    industry: str,
    country_code: str | None = None,
) -> dict:
    """
    Make sure the searched (area, category) is cached in overture_places.

    If a fresh loaded bbox already covers this box FOR THIS CATEGORY, do nothing
    (the warm PostGIS query serves it). Otherwise cold-load just this category's
    nearest places (capped at OVERTURE_CACHE_PER_CATEGORY) and record the area.
    """
    load_radius_km = radius_km + settings.OVERTURE_AREA_BUFFER_KM
    min_lng, min_lat, max_lng, max_lat = bbox_around(center_lat, center_lng, load_radius_km)
    envelope = {"min_lng": min_lng, "min_lat": min_lat, "max_lng": max_lng, "max_lat": max_lat}
    category_key = resolved_filter.get("category_key") or _overture_category_key(resolved_filter, industry)

    # place_count > 0: an empty pull (often a bad geocode centroid like Lumbini
    # Province instead of the town) must NOT freeze the area as warm, or every
    # retry returns zero without reloading / trying a better center.
    coverage_sql = text(
        """
        SELECT id FROM overture_loaded_areas
        WHERE category_key = :category_key
          AND place_count > 0
          AND ST_Contains(bbox, ST_MakeEnvelope(:min_lng, :min_lat, :max_lng, :max_lat, 4326))
          AND loaded_at > (NOW() - (:ttl_days * INTERVAL '1 day'))
        LIMIT 1
        """
    )
    coverage_params = {**envelope, "category_key": category_key, "ttl_days": settings.OVERTURE_AREA_TTL_DAYS}

    # Registry rows are only trustworthy for code-based keys. With no category
    # resolved, category_key falls back to the raw phrase — any row it matches is a
    # legacy name-only load (pre-guard) whose frozen result set must not shortcut
    # the load, or the learn path never gets to re-resolve the phrase.
    trust_registry = bool(resolved_filter.get("has_category"))

    covered = (await db.execute(coverage_sql, coverage_params)).scalar_one_or_none() if trust_registry else None
    if covered is not None:
        return {"status": "already_loaded", "needs_load": False, "loaded_area_id": covered}

    # Not covered → cold-load, guarded by a distributed lock so two workers don't
    # pull the same (area, category) from S3 at once. No Redis → lock is a no-op.
    from app.utils.redis_context import arun, acquire_search_lock, release_search_lock

    area_key = f"{round(center_lat, 2)}_{round(center_lng, 2)}"
    lock_industry = f"ovload:{area_key}"
    lock_acquired = await arun(acquire_search_lock, lock_industry, category_key, ttl=600)
    if not lock_acquired and trust_registry:
        # Another worker is loading this area+category — wait for it (up to ~5 min).
        # (Name-only loads never register coverage, so there is nothing to wait on;
        # loading concurrently is safe — _persist_overture_rows upserts by overture_id.)
        for _ in range(150):
            await asyncio.sleep(2)
            covered = (await db.execute(coverage_sql, coverage_params)).scalar_one_or_none()
            if covered is not None:
                return {"status": "already_loaded", "needs_load": False, "loaded_area_id": covered}
        # Timed out waiting → fall through and load it ourselves (best effort).

    try:
        # Re-check under the lock — another worker may have just finished.
        if trust_registry:
            covered = (await db.execute(coverage_sql, coverage_params)).scalar_one_or_none()
            if covered is not None:
                return {"status": "already_loaded", "needs_load": False, "loaded_area_id": covered}

        logger.info(
            "[OVERTURE] Cold-loading | lat=%s lng=%s radius_km=%s category=%s",
            center_lat, center_lng, radius_km, category_key,
        )
        pull_limit = settings.OVERTURE_CACHE_PER_CATEGORY
        rows = await _fetch_overture_area_rows(
            (min_lng, min_lat, max_lng, max_lat),
            center_lat,
            center_lng,
            settings.OVERTURE_MIN_CONFIDENCE,
            resolved_filter,
            pull_limit,
        )
        # Hitting the cap means Overture had at least this many for the box → probably
        # more than we took. A short pull means we got everything (§6.11 top-up).
        has_more = len(rows) >= pull_limit
        inserted = await _persist_overture_rows(db, rows)

        if not resolved_filter.get("has_category"):
            # Name-only fallback load (no category resolved): registering the area
            # would mark this (area, phrase) warm for OVERTURE_AREA_TTL_DAYS,
            # freezing its tiny name-matched result set AND skipping the background
            # learn path that could resolve the phrase properly next time. Keep the
            # loaded places, skip the registry row.
            await db.commit()
            logger.info(
                "[OVERTURE] Name-only load NOT registered as warm | area_key=%s category=%s places=%s",
                area_key, category_key, inserted,
            )
            return {"status": "loaded", "needs_load": True, "place_count": inserted}

        if inserted == 0:
            # Empty pull — do not register as warm. Also clear any prior empty
            # registry row for this key so retries are not short-circuited.
            await db.execute(
                text(
                    """
                    DELETE FROM overture_loaded_areas
                    WHERE area_key = :area_key
                      AND category_key = :category_key
                      AND place_count = 0
                    """
                ),
                {"area_key": area_key, "category_key": category_key},
            )
            await db.commit()
            logger.info(
                "[OVERTURE] Empty cold-load NOT registered as warm | area_key=%s category=%s",
                area_key, category_key,
            )
            return {"status": "loaded", "needs_load": True, "place_count": 0}

        await db.execute(
            text(
                """
                INSERT INTO overture_loaded_areas
                    (area_key, category_key, country_code, bbox, place_count, has_more, loaded_at, overture_release)
                VALUES
                    (:area_key, :category_key, :country_code,
                     ST_MakeEnvelope(:min_lng, :min_lat, :max_lng, :max_lat, 4326),
                     :place_count, :has_more, :loaded_at, :release)
                ON CONFLICT (area_key, category_key) DO UPDATE SET
                    bbox = ST_Envelope(ST_Union(overture_loaded_areas.bbox, EXCLUDED.bbox)),
                    country_code = EXCLUDED.country_code,
                    place_count = EXCLUDED.place_count,
                    has_more = EXCLUDED.has_more,
                    loaded_at = EXCLUDED.loaded_at,
                    overture_release = EXCLUDED.overture_release
                """
            ),
            {
                **envelope,
                "area_key": area_key,
                "category_key": category_key,
                "country_code": country_code,
                "place_count": inserted,
                "has_more": has_more,
                "loaded_at": datetime.now(timezone.utc),
                "release": _effective_overture_release(),
            },
        )
        await db.commit()
        logger.info(
            "[OVERTURE] Cold-load complete | area_key=%s category=%s places=%s",
            area_key, category_key, inserted,
        )
        return {"status": "loaded", "needs_load": True, "place_count": inserted}
    finally:
        if lock_acquired:
            await arun(release_search_lock, lock_industry, category_key)


async def _covering_loaded_area(
    db: AsyncSession, min_lng, min_lat, max_lng, max_lat, category_key: str,
):
    """The fresh loaded-area row (id, place_count, has_more) whose bbox covers this box
    for this category — the same coverage test the cold-load uses. None if uncached."""
    return (
        await db.execute(
            text(
                """
                SELECT id, place_count, has_more FROM overture_loaded_areas
                WHERE category_key = :category_key
                  AND place_count > 0
                  AND ST_Contains(bbox, ST_MakeEnvelope(:min_lng, :min_lat, :max_lng, :max_lat, 4326))
                  AND loaded_at > (NOW() - (:ttl_days * INTERVAL '1 day'))
                ORDER BY loaded_at DESC
                LIMIT 1
                """
            ),
            {
                "category_key": category_key,
                "min_lng": min_lng, "min_lat": min_lat,
                "max_lng": max_lng, "max_lat": max_lat,
                "ttl_days": settings.OVERTURE_AREA_TTL_DAYS,
            },
        )
    ).first()


def _load_bbox_and_key(center_lat, center_lng, radius_km, resolved_filter, industry):
    """Shared (bbox, category_key) for an area — mirrors ensure_overture_area_loaded."""
    load_radius_km = radius_km + settings.OVERTURE_AREA_BUFFER_KM
    bbox = bbox_around(center_lat, center_lng, load_radius_km)
    category_key = resolved_filter.get("category_key") or _overture_category_key(resolved_filter, industry)
    return bbox, category_key


async def _area_has_more(
    db: AsyncSession, center_lat: float, center_lng: float, radius_km: float,
    resolved_filter: dict, industry: str,
) -> bool:
    """Does the cached area covering this search still have more upstream? §6.11.

    Only meaningful for code-based categories — name-only loads aren't registered.
    """
    if not resolved_filter.get("has_category"):
        return False
    (min_lng, min_lat, max_lng, max_lat), category_key = _load_bbox_and_key(
        center_lat, center_lng, radius_km, resolved_filter, industry
    )
    row = await _covering_loaded_area(db, min_lng, min_lat, max_lng, max_lat, category_key)
    return bool(row and row.has_more)


async def topup_overture_area(
    db: AsyncSession, center_lat: float, center_lng: float, radius_km: float,
    resolved_filter: dict, industry: str,
) -> dict:
    """Pull the NEXT batch of nearest places for an already-cached (area, category)
    whose upstream is not exhausted, into the SHARED cache — so every user benefits.

    Re-pulls the nearest (place_count + OVERTURE_TOPUP_BATCH); the upsert dedups by
    overture_id and never clobbers enrichment, so overlap with the existing cache is
    harmless. `has_more` flips False once a pull comes back short. §6.11.

    Returns {"pulled": int, "has_more": bool}.
    """
    if not resolved_filter.get("has_category"):
        return {"pulled": 0, "has_more": False}

    (min_lng, min_lat, max_lng, max_lat), category_key = _load_bbox_and_key(
        center_lat, center_lng, radius_km, resolved_filter, industry
    )
    area = await _covering_loaded_area(db, min_lng, min_lat, max_lng, max_lat, category_key)
    if area is None or not area.has_more:
        return {"pulled": 0, "has_more": bool(area.has_more) if area else False}

    new_limit = int(area.place_count or 0) + settings.OVERTURE_TOPUP_BATCH

    from app.utils.redis_context import arun, acquire_search_lock, release_search_lock

    area_key = f"{round(center_lat, 2)}_{round(center_lng, 2)}"
    lock_industry = f"ovload:{area_key}"
    lock_acquired = await arun(acquire_search_lock, lock_industry, category_key, ttl=600)
    if not lock_acquired:
        # Another worker is already pulling this (area, category) — let it finish.
        return {"pulled": 0, "has_more": True}
    try:
        logger.info(
            "[OVERTURE_TOPUP] Pulling next batch | area_key=%s category=%s new_limit=%s",
            area_key, category_key, new_limit,
        )
        rows = await _fetch_overture_area_rows(
            (min_lng, min_lat, max_lng, max_lat),
            center_lat, center_lng,
            settings.OVERTURE_MIN_CONFIDENCE, resolved_filter, new_limit,
        )
        await _persist_overture_rows(db, rows)
        has_more = len(rows) >= new_limit  # short pull → upstream exhausted
        await db.execute(
            text(
                """
                UPDATE overture_loaded_areas
                SET place_count = :pc, has_more = :hm, loaded_at = :now
                WHERE id = :id
                """
            ),
            {"pc": len(rows), "hm": has_more, "now": datetime.now(timezone.utc), "id": area.id},
        )
        await db.commit()
        logger.info(
            "[OVERTURE_TOPUP] Done | area_key=%s pulled=%s has_more=%s",
            area_key, len(rows), has_more,
        )
        return {"pulled": len(rows), "has_more": has_more}
    finally:
        if lock_acquired:
            await arun(release_search_lock, lock_industry, category_key)


def _shape_overture_row(row) -> dict:
    """Shape one overture_places row (SELECT column order below) into a lead dict.

    Serves the FULL master record — enrichment included — so a warm search reuses
    scraped emails + context directly (single reuse source; §6.4/4.1). email =
    COALESCE(scraped, overture); `_enriched` lets the chat save path store
    already-done businesses as 'done' and skip re-enrichment.
    """
    return {
        "business_name": row[0],
        "address": row[3] or "N/A",
        "website": row[1] or "N/A",
        "email": row[7] or row[4] or None,           # scraped_email → overture email
        "contact_number": row[2] or "N/A",
        # Master-catalog identity — carried into lead_log_leads so enrichment
        # and reuse key back to overture_places. Internal, not an API field.
        "overture_id": row[5],
        "source": row[6],
        "email_source": row[8] or ("overture" if (not row[7] and row[4]) else None),
        "lead_score": row[9] if row[9] is not None else 0,
        "services": row[11],
        "website_summary": row[12],
        "business_description": row[13],
        "_enriched": row[10] == "done",
    }


# One contactable business per email address. Overture lists each OYO property and each
# Marriott venue as its own place, but they share one corporate inbox — so a 500-row batch
# could carry only 497 usable addresses, and the save step would silently drop the rest.
OVERTURE_EMAIL_KEY = "lower(nullif(trim(coalesce(scraped_email, email)), ''))"
# Counts one entry per distinct email plus every row that has no email at all
# (overture_id is unique, so email-less rows never collapse into each other).
OVERTURE_DEDUPED_COUNT = f"count(DISTINCT coalesce({OVERTURE_EMAIL_KEY}, overture_id))"

# A lead needs at least one way to reach it — an email to campaign, a website to scrape an
# email from, or a phone to call. A row with none of the three can never be actioned and
# only takes up a slot the plan promised the user. Phone-only leads ARE kept (product
# decision 2026-07-24): the user can call them even though they can't be email-campaigned.
# Trade-off: this readmits businesses Overture mislabelled into a food category when they're
# phone-only (e.g. "Skin Care Nepal") — accepted as a small, eyeball-able noise (~2 rows)
# for the ~172 real callable leads it adds. Detecting mislabels needs an LLM name-vs-category
# check, deferred. See §6.9.
OVERTURE_CONTACTABLE = (
    "(coalesce(scraped_email, email) IS NOT NULL OR website IS NOT NULL OR phone IS NOT NULL)"
)


async def _query_overture_warm(
    db: AsyncSession,
    center_lat: float,
    center_lng: float,
    radius_km: float,
    resolved_filter: dict,
    limit: int,
    city_for_tier: str | None = None,
    user_id=None,
    industry: str | None = None,
    spillover_ratio: float = 0.2,
) -> list[dict]:
    """Query the cached overture_places via PostGIS (ST_DWithin + category match).

    Geographic precision (fixes §GEO-1/2):
      - Mode A (city_for_tier set, e.g. "colleges in Kathmandu"): same-city leads
        (address names the city) fill first; neighboring-city leads are allowed only
        up to `spillover_ratio` of the batch (default 20%), then we stop — never pad
        the plan limit with other-city rows.
      - Mode B (city_for_tier None, e.g. an anchor like "near Shankhamul"): pure
        nearest-first, city tier relaxed, so nearby cross-border leads surface.
    Fresh leads (fix §GEO-3): when user_id is given, exclude businesses this user
      already pulled for `industry` (so repeat searches return the NEXT batch).
    """
    params: dict = {
        "lng": center_lng,
        "lat": center_lat,
        "radius_m": radius_km * 1000.0,
        "min_conf": settings.OVERTURE_MIN_CONFIDENCE,
        "limit": limit,
    }
    match_clause = _overture_match_params(resolved_filter, params)

    # Fix §GEO-3: exclude businesses this user already RECEIVED for this industry
    # (appeared in ANY past search log), so repeat searches return fresh leads and
    # credits are never wasted on duplicates. Previously keyed on `promoted` only,
    # which let unsaved leads return and charge credits over and over.
    exclude_seen = ""
    if user_id is not None:
        ind_filter = ""
        if industry:
            ind_filter = "AND lower(coalesce(ll.industry, '')) = lower(:industry)"
            params["industry"] = industry
        exclude_seen = f"""
              AND NOT EXISTS (
                  SELECT 1 FROM lead_log_leads ll
                  JOIN lead_logs lg ON lg.id = ll.lead_log_id
                  WHERE lg.user_id = CAST(:uid AS uuid)
                    AND ll.overture_id = overture_places.overture_id
                    {ind_filter}
              )
        """
        params["uid"] = str(user_id)  # accept str (Celery) or UUID

    # City tier (Mode A) vs pure distance (Mode B) — fix §GEO-2. First-segment
    # convention: "Kathmandu, Nepal" → "kathmandu". Addresses carry the municipality
    # name ~90-99% of the time (measured), so the contains-match is reliable.
    city = (city_for_tier or "").split(",")[0].strip().lower()
    mode_a = bool(city)
    distance = "geom <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)"
    if mode_a:
        params["city_pattern"] = f"%{city}%"
        is_city_sel = "CASE WHEN lower(coalesce(address, '')) LIKE :city_pattern THEN 1 ELSE 0 END"
        priority = f"{is_city_sel} DESC, {distance}"
        order_by = "is_city DESC, dist"
    else:
        is_city_sel = "1"
        priority = distance
        order_by = "dist"

    # Collapse same-email places (see OVERTURE_EMAIL_KEY) before the LIMIT, ranking them
    # by the same priority that orders the batch so the in-city, nearest one survives.
    # Doing it here rather than at save time means a 500-lead plan delivers 500 usable
    # leads, and nothing appears in the log that would silently vanish on save.
    rows = (
        await db.execute(
            text(
                f"""
                SELECT name, website, phone, address, email, overture_id, source,
                       scraped_email, email_source, lead_score, enrichment_status,
                       services, website_summary, business_description, is_city
                FROM (
                    SELECT name, website, phone, address, email, overture_id, source,
                           scraped_email, email_source, lead_score, enrichment_status,
                           services, website_summary, business_description,
                           {is_city_sel} AS is_city,
                           {distance} AS dist,
                           CASE WHEN {OVERTURE_EMAIL_KEY} IS NULL THEN 1
                                ELSE row_number() OVER (
                                    PARTITION BY {OVERTURE_EMAIL_KEY}
                                    ORDER BY {priority}
                                )
                           END AS email_rank
                    FROM overture_places
                    WHERE ST_DWithin(
                            geom::geography,
                            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                            :radius_m
                          )
                      AND confidence >= :min_conf
                      AND (operating_status IS NULL OR operating_status <> 'closed')
                      AND {OVERTURE_CONTACTABLE}
                      AND {match_clause}
                      {exclude_seen}
                ) ranked
                WHERE email_rank = 1
                ORDER BY {order_by}
                LIMIT :limit
                """
            ),
            params,
        )
    ).fetchall()

    if not mode_a:
        return [_shape_overture_row(r) for r in rows]

    # Fix §GEO-1: spillover cap. Same-city rows (is_city=1) come first; keep them
    # all, then allow neighbor rows only up to `spillover_ratio` of the batch
    # (neighbor ≤ ratio/(1-ratio) × city_count → ≤20% share at ratio=0.2). We do
    # NOT pad the limit with more neighbors than that — honest count over volume.
    city_rows = [r for r in rows if r[14] == 1]
    neighbor_rows = [r for r in rows if r[14] == 0]
    if not city_rows:
        # No address matched the city (rare — ~90-99% carry it). Don't return empty:
        # fall back to nearest-first (treat as if the city signal is absent here).
        return [_shape_overture_row(r) for r in rows[:limit]]
    neighbor_cap = int(len(city_rows) * spillover_ratio / (1.0 - spillover_ratio))
    kept = city_rows + neighbor_rows[:neighbor_cap]
    return [_shape_overture_row(r) for r in kept[:limit]]


# ── GEO-4 exhaustion helpers ───────────────────────────────────────────────────
# Extra radius (km) beyond the search radius when scanning for nearby cities to
# suggest at exhaustion. Kathmandu core + 15km reaches Lalitpur/Bhaktapur.
NEARBY_EXTRA_KM = 15.0


def _overture_match_params(resolved_filter: dict, params: dict) -> str:
    """Build the category/keyword match clause, filling p0.. into `params`."""
    return _overture_match_sql(
        resolved_filter,
        primary_col="category_primary",
        taxonomy_col="taxonomy_primary",
        hierarchy_col="taxonomy_hierarchy",
        name_col="name",
        bind=_pg_binder(params),
    )


async def _count_overture_matches(
    db: AsyncSession, center_lat: float, center_lng: float, radius_km: float,
    resolved_filter: dict,
) -> int:
    """How many businesses match this search in-radius, ignoring exclude-seen.

    Used to tell EXHAUSTED (count > 0, but the user has pulled them all) from
    EMPTY (count == 0, the area genuinely has none). GEO-4.
    """
    params: dict = {
        "lng": center_lng, "lat": center_lat, "radius_m": radius_km * 1000.0,
        "min_conf": settings.OVERTURE_MIN_CONFIDENCE,
    }
    match_clause = _overture_match_params(resolved_filter, params)
    return int(
        await db.scalar(
            text(
                f"""
                SELECT {OVERTURE_DEDUPED_COUNT} FROM overture_places
                WHERE ST_DWithin(geom::geography,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :radius_m)
                  AND confidence >= :min_conf
                  AND (operating_status IS NULL OR operating_status <> 'closed')
                  AND {OVERTURE_CONTACTABLE}
                  AND {match_clause}
                """
            ),
            params,
        ) or 0
    )


async def _nearby_cities_with_counts(
    db: AsyncSession, center_lat: float, center_lng: float, radius_km: float,
    resolved_filter: dict, exclude_city: str | None, limit: int = 3,
    user_id=None, industry: str | None = None,
) -> list[dict]:
    """Nearby cities (by locality) that have this category, for exhaustion suggestions.

    Scans a WIDER radius (search + NEARBY_EXTRA_KM), groups by `locality`, excludes the
    searched city, returns the top few with counts. Only sees already-cached areas —
    an uncached neighbor simply won't appear (caller falls back to generic suggestions).

    `available` is FRESH-FOR-THIS-USER when user_id is given: businesses the user has
    already pulled (same exclude-seen as the search) are subtracted, so a city they've
    fully pulled drops off the chips instead of promising leads they already have.
    Returns [{city, available}]. GEO-4.
    """
    city = (exclude_city or "").split(",")[0].strip().lower()
    params: dict = {
        "lng": center_lng, "lat": center_lat,
        "radius_m": (radius_km + NEARBY_EXTRA_KM) * 1000.0,
        "min_conf": settings.OVERTURE_MIN_CONFIDENCE,
        "limit": limit,
    }
    match_clause = _overture_match_params(resolved_filter, params)
    exclude_sql = ""
    if city:
        exclude_sql = "AND lower(coalesce(locality, '')) NOT LIKE :exclude_city"
        params["exclude_city"] = f"%{city}%"
    # Fresh-for-user: drop businesses this user already owns (same exclude-seen as the
    # warm search — keyed on `promoted`), so counts reflect what a tap would deliver.
    exclude_seen = ""
    if user_id is not None:
        ind_filter = ""
        if industry:
            ind_filter = "AND lower(coalesce(ll.industry, '')) = lower(:industry)"
            params["industry"] = industry
        exclude_seen = f"""
              AND NOT EXISTS (
                  SELECT 1 FROM lead_log_leads ll
                  JOIN lead_logs lg ON lg.id = ll.lead_log_id
                  WHERE lg.user_id = CAST(:uid AS uuid)
                    AND ll.overture_id = overture_places.overture_id
                    AND ll.promoted IS TRUE
                    {ind_filter}
              )
        """
        params["uid"] = str(user_id)
    rows = (
        await db.execute(
            text(
                f"""
                SELECT locality, {OVERTURE_DEDUPED_COUNT} AS n FROM overture_places
                WHERE ST_DWithin(geom::geography,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :radius_m)
                  AND confidence >= :min_conf
                  AND (operating_status IS NULL OR operating_status <> 'closed')
                  AND locality IS NOT NULL AND locality <> ''
                  AND {OVERTURE_CONTACTABLE}
                  {exclude_sql}
                  {exclude_seen}
                  AND {match_clause}
                GROUP BY locality
                ORDER BY n DESC
                LIMIT :limit
                """
            ),
            params,
        )
    ).fetchall()
    return [{"city": r[0], "available": int(r[1])} for r in rows]


def _normalize_places_search_terms(industry: str, search_terms: list[str] | None = None) -> list[str]:
    """Return up to 3 unique Places keywords, falling back to the canonical industry."""
    terms: list[str] = []
    candidates = search_terms if isinstance(search_terms, list) else []

    for term in candidates:
        if not isinstance(term, str):
            continue
        cleaned = term.strip()
        if not cleaned or cleaned.lower() == "null":
            continue
        if cleaned.lower() not in {existing.lower() for existing in terms}:
            terms.append(cleaned)
        if len(terms) >= 3:
            break

    if not terms and industry:
        terms.append(industry.strip())

    return terms


# Grid search configuration
GRID_CONFIG = {
    "dense_urban": {
        "grid_spacing": 3.0,  # km
        "radius": 1600,  # meters — overlaps by 200m each side, no coverage gaps
        "description": "Dense city areas (Thamel, Baneshwor, New Road)"
    },
    "medium_urban": {
        "grid_spacing": 3.5,  # km
        "radius": 1800,  # meters — overlaps by 50m each side, no coverage gaps
        "description": "Medium density areas"
    },
    "suburban": {
        "grid_spacing": 4.0,  # km
        "radius": 2100,  # meters — overlaps by 100m each side, no coverage gaps
        "description": "Suburban areas"
    }
}

async def fetch_nearby_page(client, params, semaphores):
    async with semaphores.google_maps:
        started = time.perf_counter()
        resp = await client.get(
            "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
            params=params,
            timeout=10.0
        )
        data = resp.json()
        await record_places_usage(
            api_name="nearby_search",
            google_status=data.get("status"),
            http_status=resp.status_code,
            latency_ms=int((time.perf_counter() - started) * 1000),
            feature="lead_search",
            meta=str(params.get("keyword") or params.get("pagetoken") or "")[:256] or None,
        )
        return data

async def fetch_all_nearby_pages(
    client: httpx.AsyncClient,
    base_params: dict,
    limit: int | None,
    semaphores
) -> list[dict]:
    """
    Fetch up to 3 Google Places nearby pages using next_page_token.
    Max realistic results: ~40–60.
    """
    all_places = []
    params = base_params.copy()
    next_page_token = None

    for _ in range(MAX_PAGES):
        if next_page_token:
            await asyncio.sleep(PAGE_DELAY)
            params = {
                "pagetoken": next_page_token,
                "key": GOOGLE_MAPS_API_KEY,
            }

        data = await fetch_nearby_page(client, params, semaphores)
        status = data.get("status")
        error_message = data.get("error_message")
        if status and status != "OK":
            log_params = {
                "location": params.get("location"),
                "radius": params.get("radius"),
                "keyword": params.get("keyword"),
                "pagetoken": bool(params.get("pagetoken")),
            }
            if status == "ZERO_RESULTS":
                logger.info("[GOOGLE PLACES] Nearby Search returned ZERO_RESULTS | params=%s", log_params)
            else:
                logger.warning(
                    "[GOOGLE PLACES] Nearby Search status=%s error=%r | params=%s",
                    status,
                    error_message,
                    log_params,
                )
        results = data.get("results", [])
        all_places.extend(results)

        if limit and len(all_places) >= limit:
            return all_places[:limit]

        next_page_token = data.get("next_page_token")
        if not next_page_token:
            break

    return all_places

def haversine_distance(lat1, lng1, lat2, lng2):
    """Calculate distance between two coordinates in km"""
    R = 6371  # Earth radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = math.sin(delta_phi/2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _is_city_sized_bounds(bounds: dict | None) -> bool:
    if not bounds:
        return False
    ne = bounds.get("northeast", {})
    sw = bounds.get("southwest", {})
    if not ne or not sw:
        return False

    lat_span = abs(ne.get("lat", 0) - sw.get("lat", 0))
    lng_span = abs(ne.get("lng", 0) - sw.get("lng", 0))
    return lat_span < 3.0 and lng_span < 3.0


def _is_city_sized_country_shape(shape: dict | None) -> bool:
    return bool(
        shape
        and "country" in shape.get("types", [])
        and _is_city_sized_bounds(shape.get("bounds"))
    )


def _country_short_name(address_components: list[dict]) -> str | None:
    for component in address_components or []:
        if "country" in component.get("types", []):
            return component.get("short_name")
    return None


def _nearby_location_names(address_components: list[dict]) -> list[str]:
    priority_types = (
        "neighborhood",
        "sublocality",
        "sublocality_level_1",
        "locality",
    )
    names = []
    for type_name in priority_types:
        for component in address_components or []:
            if type_name in component.get("types", []):
                name = component.get("long_name")
                if name and name.lower().startswith("municipio"):
                    continue
                if name and name.lower() == "rome":
                    name = "Roma"
                if name and name not in names:
                    names.append(name)
        if names:
            break
    return names


def _nearby_text_location_names(*values: str | None) -> list[str]:
    text = " ".join(value or "" for value in values).lower()
    names = []
    if "roma" in text or "rome" in text:
        names.append("Roma")
    if "prati" in text:
        names.append("Prati")
    return names


def _rank_nearby_suggestions(leads: list[dict], limit: int = 2) -> list[str]:
    counts: dict[str, int] = {}
    for lead in leads:
        for name in lead.get("_nearby_location_names", []):
            counts[name] = counts.get(name, 0) + 1

    return [
        name
        for name, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    ][:limit]


def _complete_nearby_suggestions(country_code: str | None, suggestions: list[str]) -> list[str]:
    completed = list(suggestions)
    if country_code == "VA":
        for name in ("Roma", "Prati"):
            if name not in completed:
                completed.append(name)
            if len(completed) >= 2:
                break
    return completed[:2]


def _location_sort_key(lead: dict, location: str) -> tuple[int, str]:
    city = (location or "").split(",")[0].strip().lower()
    address = (lead.get("address") or "").lower()
    business_name = (lead.get("business_name") or "").lower()
    exact_city_match = city and (city in address or city in business_name)
    return (0 if exact_city_match else 1, business_name)


def prioritize_location_matches(leads: list[dict], location: str) -> list[dict]:
    """Keep all leads but show exact city/address matches first."""
    return sorted(leads, key=lambda lead: _location_sort_key(lead, location))


def _place_inside_bounds(place: dict, bounds: dict | None) -> bool:
    if not bounds:
        return True

    place_location = place.get("geometry", {}).get("location", {})
    lat = place_location.get("lat")
    lng = place_location.get("lng")
    if lat is None or lng is None:
        return False

    ne = bounds.get("northeast", {})
    sw = bounds.get("southwest", {})
    return (
        sw.get("lat", lat) <= lat <= ne.get("lat", lat)
        and sw.get("lng", lng) <= lng <= ne.get("lng", lng)
    )


def _filter_places_by_bounds(places: list[dict], bounds: dict | None, location: str) -> list[dict]:
    if not bounds:
        return places

    filtered = [place for place in places if _place_inside_bounds(place, bounds)]
    if len(filtered) != len(places):
        logger.info(
            "[LEAD FILTER] Removed %s places outside %s bounds; kept %s",
            len(places) - len(filtered),
            location,
            len(filtered),
        )
    return filtered

def generate_grid_points(
    center_lat: float,
    center_lng: float,
    search_radius_km: float,
    grid_spacing_km: float
) -> list[tuple[float, float]]:
    """
    Generate grid points within a circular search area.
    
    Args:
        center_lat, center_lng: Center coordinates
        search_radius_km: Search radius in kilometers
        grid_spacing_km: Grid spacing in kilometers
    
    Returns:
        List of (lat, lng) tuples
    """
    points = []
    
    # Approximate degrees per km (varies by latitude, using approximation for equator/tropical)
    lat_delta_per_km = 1 / 111.32  # ~111.32 km per degree latitude
    lng_delta_per_km = 1 / (111.32 * math.cos(math.radians(center_lat)))
    
    grid_spacing_lat = grid_spacing_km * lat_delta_per_km
    grid_spacing_lng = grid_spacing_km * lng_delta_per_km
    
    # Calculate bounds
    lat_steps = int(search_radius_km / grid_spacing_km) + 1
    lng_steps = int(search_radius_km / grid_spacing_km) + 1
    
    start_lat = center_lat - (lat_steps * grid_spacing_lat / 2)
    start_lng = center_lng - (lng_steps * grid_spacing_lng / 2)
    
    # Generate grid points within circular area
    for i in range(lat_steps * 2 + 1):
        for j in range(lng_steps * 2 + 1):
            point_lat = start_lat + (i * grid_spacing_lat)
            point_lng = start_lng + (j * grid_spacing_lng)
            
            # Check if point is within radius
            distance = haversine_distance(center_lat, center_lng, point_lat, point_lng)
            if distance <= search_radius_km:
                points.append((point_lat, point_lng))
    
    return points

# Prefer town/locality over province/admin centroids. Google often returns
# "Lumbini Province" first for "Lumbini" (~70km from the hotel town).
_GEOCODE_TYPE_RANK = {
    "locality": 0,
    "postal_town": 0,
    "neighborhood": 1,
    "sublocality": 1,
    "sublocality_level_1": 1,
    "establishment": 2,
    "premise": 2,
    "point_of_interest": 2,
    "tourist_attraction": 2,
    "natural_feature": 3,
    "administrative_area_level_3": 4,
    "administrative_area_level_2": 7,
    "administrative_area_level_1": 8,
    "country": 9,
    "continent": 10,
    "colloquial_area": 10,
}


def _geocode_bounds(result: dict) -> dict | None:
    geometry = result.get("geometry") or {}
    return geometry.get("bounds") or geometry.get("viewport")


def _geocode_bounds_radius_km(result: dict) -> float:
    bounds = _geocode_bounds(result)
    if not bounds:
        return 5.0
    ne, sw = bounds.get("northeast") or {}, bounds.get("southwest") or {}
    if not ne or not sw:
        return 5.0
    return haversine_distance(sw["lat"], sw["lng"], ne["lat"], ne["lng"]) / 2


def _geocode_type_rank(result: dict) -> int:
    types = result.get("types") or []
    ranks = [_GEOCODE_TYPE_RANK[t] for t in types if t in _GEOCODE_TYPE_RANK]
    return min(ranks) if ranks else 5


def _is_broad_admin_geocode(result: dict | None) -> bool:
    """True for province/country-scale results that are a bad search center."""
    if not result:
        return True
    types = set(result.get("types") or [])
    if types & {"country", "continent", "colloquial_area"}:
        return True
    if "administrative_area_level_1" in types and _geocode_bounds_radius_km(result) > 25:
        return True
    if "administrative_area_level_2" in types and _geocode_bounds_radius_km(result) > 40:
        return True
    return False


def pick_best_geocode_result(results: list[dict] | None) -> dict | None:
    """Pick the best search-center candidate from a Google Geocode response.

    Prefers locality/town (and smaller viewports) over province/admin centroids.
    """
    if not results:
        return None
    return min(
        results,
        key=lambda r: (_geocode_type_rank(r), _geocode_bounds_radius_km(r)),
    )


def _coords_from_geocode_result(result: dict) -> tuple[float, float, float] | None:
    latlng = (result.get("geometry") or {}).get("location") or {}
    lat, lng = latlng.get("lat"), latlng.get("lng")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng), float(_geocode_bounds_radius_km(result))


def _geocode_country_name(result: dict) -> str | None:
    for component in result.get("address_components") or []:
        if "country" in (component.get("types") or []):
            name = (component.get("long_name") or "").strip()
            if name:
                return name
    return None


def _geocode_query_variants(location: str, countries: list[str] | None = None) -> list[str]:
    """Address strings to try when Google's first hit is a broad admin region."""
    base = " ".join((location or "").strip().split())
    if not base:
        return []
    place = base.split(",")[0].strip() or base
    variants = [base]
    # Bare place names ("Lumbini") often resolve to a province; nudge toward the town.
    if "," not in base:
        variants.extend([f"{place} city", f"{place} town", f"{place} municipality"])
    for country in countries or []:
        c = " ".join(country.split())
        if not c:
            continue
        variants.extend([
            f"{place}, {c}",
            f"{place} city, {c}",
            f"{place} municipality, {c}",
        ])
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for q in variants:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out


async def _fetch_geocode_results(
    client: httpx.AsyncClient, address: str,
) -> list[dict]:
    if not GOOGLE_MAPS_API_KEY or not (address or "").strip():
        return []
    started = time.perf_counter()
    try:
        geo_resp = await client.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": GOOGLE_MAPS_API_KEY},
            timeout=10.0,
        )
        payload = geo_resp.json() or {}
        await record_places_usage(
            api_name="geocode",
            google_status=payload.get("status"),
            http_status=geo_resp.status_code,
            latency_ms=int((time.perf_counter() - started) * 1000),
            feature="lead_search",
            meta=(address or "")[:256] or None,
        )
        return list(payload.get("results") or [])
    except Exception as e:
        logger.error("Geocoding fetch error for %r: %s", address, e)
        await record_places_usage(
            api_name="geocode",
            google_status="ERROR",
            http_status=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            feature="lead_search",
            meta=(address or "")[:256] or None,
        )
        return []


async def _places_textsearch_center(
    client: httpx.AsyncClient, location: str,
) -> tuple[float, float, float] | None:
    """Resolve a town/POI center via Places Text Search when Geocode only returns a province.

    Staging bug: Geocode("Lumbini") → Lumbini Province (~27.92, 82.73). Text Search
    usually returns the pilgrimage town / Maya Devi area (~27.48, 83.28) instead.
    """
    if not GOOGLE_MAPS_API_KEY or not (location or "").strip():
        return None
    started = time.perf_counter()
    try:
        resp = await client.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params={"query": location.strip(), "key": GOOGLE_MAPS_API_KEY},
            timeout=10.0,
        )
        payload = resp.json() or {}
        await record_places_usage(
            api_name="text_search",
            google_status=payload.get("status"),
            http_status=resp.status_code,
            latency_ms=int((time.perf_counter() - started) * 1000),
            feature="lead_search",
            meta=location.strip()[:256],
        )
        results = list(payload.get("results") or [])
    except Exception as e:
        logger.warning("[GEOCODE] Places Text Search failed for %r: %s", location, e)
        await record_places_usage(
            api_name="text_search",
            google_status="ERROR",
            http_status=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            feature="lead_search",
            meta=location.strip()[:256],
        )
        return None

    def _usable(result: dict) -> bool:
        types = set(result.get("types") or [])
        if "administrative_area_level_1" in types or "country" in types:
            return False
        if _geocode_bounds_radius_km(result) > 40:
            return False
        loc = (result.get("geometry") or {}).get("location") or {}
        return loc.get("lat") is not None and loc.get("lng") is not None

    pick = next((r for r in results if _usable(r)), None)
    if pick is None:
        return None
    loc = pick["geometry"]["location"]
    radius = min(_geocode_bounds_radius_km(pick), 12.0)
    logger.info(
        "[GEOCODE] Places Text Search center for %r → %.5f,%.5f (%s)",
        location, loc["lat"], loc["lng"], pick.get("name"),
    )
    return float(loc["lat"]), float(loc["lng"]), float(radius or 5.0)


async def geocode_location_candidates(
    client: httpx.AsyncClient,
    location: str,
    *,
    max_candidates: int = 4,
) -> list[tuple[float, float, float]]:
    """Ranked (lat, lng, city_radius_km) candidates for a place name.

    Prefers town/locality over province centroids. When Geocode only returns a
    broad admin region (e.g. Lumbini Province), falls back to Places Text Search
    for a usable town/POI center.
    """
    # (coords, type_rank, is_broad)
    scored: list[tuple[tuple[float, float, float], int, bool]] = []
    seen: set[tuple[float, float]] = set()
    countries: list[str] = []
    found_local = False

    async def _ingest(query: str) -> None:
        nonlocal found_local
        ranked = sorted(
            await _fetch_geocode_results(client, query),
            key=lambda r: (_geocode_type_rank(r), _geocode_bounds_radius_km(r)),
        )
        for result in ranked:
            country = _geocode_country_name(result)
            if country and country not in countries:
                countries.append(country)
            coords = _coords_from_geocode_result(result)
            if not coords:
                continue
            key = (round(coords[0], 3), round(coords[1], 3))
            if key in seen:
                continue
            seen.add(key)
            broad = _is_broad_admin_geocode(result)
            scored.append((coords, _geocode_type_rank(result), broad))
            if not broad:
                found_local = True

    # Pass 1: base name + city/town suffixes.
    for query in _geocode_query_variants(location):
        await _ingest(query)
        if found_local:
            break

    # Pass 2: reuse country from the province hit ("Lumbini" → Nepal → "Lumbini, Nepal").
    if not found_local and countries:
        for query in _geocode_query_variants(location, countries=countries):
            await _ingest(query)
            if found_local:
                break

    # Pass 3: Places Text Search — Geocode often has ONLY the province for names
    # like Lumbini; Text Search returns the town/attraction center instead.
    if not found_local:
        places_center = await _places_textsearch_center(client, location)
        if places_center:
            key = (round(places_center[0], 3), round(places_center[1], 3))
            if key not in seen:
                scored.append((places_center, 0, False))
                found_local = True

    # Locality/town first; drop broad admin when we have a tighter center.
    scored.sort(key=lambda item: (1 if item[2] else 0, item[1], item[0][2]))
    local = [coords for coords, _, broad in scored if not broad]
    if local:
        return local[:max_candidates]
    if scored:
        logger.warning(
            "[GEOCODE] Only broad admin center(s) for %r — lead search may miss the town",
            location,
        )
    return [coords for coords, _, _ in scored[:max_candidates]]


async def geocode_location(client: httpx.AsyncClient, location: str) -> tuple[float, float, float] | None:
    """
    Geocode a location and return (lat, lng, city_radius_km).
    city_radius_km is derived from the bounds Google returns so that
    get_leads() can cap the grid to the actual city size.
    Results are cached in Redis for 7 days.

    Prefers locality/town results over province/admin centroids (see
    ``geocode_location_candidates``). Broad province centroids are not cached.
    """
    cached = await arun(get_cached_geocode, location)
    if cached:
        return cached

    try:
        candidates = await geocode_location_candidates(client, location)
        if not candidates:
            return None
        lat, lng, city_radius_km = candidates[0]
        # Only cache tight centers. Caching a province centroid (Lumbini Province)
        # made every later search miss the hotel town until the 7-day TTL expired.
        if city_radius_km <= 25:
            await arun(set_cached_geocode, location, lat, lng, city_radius_km)
        if len(candidates) > 1:
            logger.info(
                "[GEOCODE] %r → %.5f,%.5f (r=%.1fkm); %s alternate candidate(s)",
                location, lat, lng, city_radius_km, len(candidates) - 1,
            )
        else:
            logger.info(
                "[GEOCODE] %r → %.5f,%.5f (r=%.1fkm)",
                location, lat, lng, city_radius_km,
            )
        return lat, lng, city_radius_km
    except Exception as e:
        logger.error(f"Geocoding error: {e}")

    return None


async def geocode_location_shape(client: httpx.AsyncClient, location: str) -> dict | None:
    """Return Google geocode result shape used for boundary filtering."""
    try:
        results = await _fetch_geocode_results(client, location)
        result = pick_best_geocode_result(results)
        if not result:
            return None

        bounds = _geocode_bounds(result)
        return {
            "types": result.get("types", []),
            "bounds": bounds,
            "formatted_address": result.get("formatted_address"),
            "address_components": result.get("address_components", []),
            "country_short_name": _country_short_name(result.get("address_components", [])),
        }
    except Exception as e:
        logger.warning("Geocode shape lookup error for %s: %s", location, e)
        return None


async def geocode_strict_country_shape(client: httpx.AsyncClient, location: str) -> dict | None:
    """
    Return a city-sized country shape for strict boundary filtering.

    Short inputs like "vatican" can geocode to an ambiguous local area. A second
    lookup with "country" nudges Google toward the sovereign place without
    hardcoding specific country names.
    """
    seen_queries = set()
    for query in (location, f"{location} country"):
        normalized_query = query.strip().lower()
        if not normalized_query or normalized_query in seen_queries:
            continue
        seen_queries.add(normalized_query)

        shape = await geocode_location_shape(client, query)
        if _is_city_sized_country_shape(shape):
            if normalized_query != location.strip().lower():
                logger.info(
                    "[LEAD FILTER] Resolved ambiguous location %r using geocode query %r",
                    location,
                    query,
                )
            return shape
    return None

async def fetch_details(
    client: httpx.AsyncClient,
    place: dict,
    industry: str,
    semaphores,
    details_url: str = "https://maps.googleapis.com/maps/api/place/details/json"
) -> dict | None:
    """Fetch detailed information for a single place"""
    pid = place.get("place_id")
    if not pid:
        return None

    params = {
        "place_id": pid,
        "fields": "name,formatted_phone_number,website,vicinity,formatted_address,address_components",
        "key": GOOGLE_MAPS_API_KEY,
    }

    async with semaphores.google_maps:
        started = time.perf_counter()
        try:
            resp = await client.get(
                details_url,
                params=params,
                timeout=6.0,
            )
            payload = resp.json() or {}
            await record_places_usage(
                api_name="place_details",
                google_status=payload.get("status"),
                http_status=resp.status_code,
                latency_ms=int((time.perf_counter() - started) * 1000),
                feature="lead_search",
                meta=str(pid)[:256],
            )
            result = payload.get("result", {})

            nearby_location_names = _nearby_location_names(result.get("address_components", []))
            nearby_location_names.extend(
                name for name in _nearby_text_location_names(result.get("name"), result.get("formatted_address"), result.get("vicinity"))
                if name not in nearby_location_names
            )

            return {
                "business_name": result.get("name", place.get("name")),
                "industry": industry,
                "address": result.get("formatted_address") or result.get("vicinity", place.get("vicinity")),
                "website": result.get("website", "N/A"),
                "contact_number": result.get("formatted_phone_number", "N/A"),
                "_country_short_name": _country_short_name(result.get("address_components", [])),
                "_nearby_location_names": nearby_location_names,
            }
        except Exception as e:
            logger.error(f"Details fetch error: {e}")
            await record_places_usage(
                api_name="place_details",
                google_status="ERROR",
                http_status=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                feature="lead_search",
                meta=str(pid)[:256],
            )
            return None


async def get_leads_overture(
    industry: str,
    location: str,
    search_radius_km: float = 5.0,
    limit: int | None = 100,
    search_terms: list[str] | None = None,
    db: AsyncSession | None = None,
    load_if_cold: bool = True,
    city_for_tier: str | None = None,
    user_id=None,
    topup: bool = False,
) -> tuple[list[dict], dict]:
    """
    Fetch nearby businesses from Overture, returning the same lead-dict shape as Google.

    Cached path (db provided):
      - load_if_cold=True  → cold-load the area synchronously if not cached, then query.
      - load_if_cold=False → if the area is NOT warm, return [] with
        error_info["overture_cold"]=True so the caller can background the load
        (never blocks the request). Warm areas query PostGIS as usual.

    Direct path (db is None): pull straight from Overture S3 with DuckDB. Used by
    the standalone smoke test; ~20-25s per call, no caching.
    """
    error_info = {
        "geocoding_failed": False,
        "no_results": False,
        "suggested_location": None,
        "grid_search_used": False,
        "total_grid_points": 0,
        "overture_cached_path": db is not None,
        "overture_cold": False,
        "exhausted": False,        # warm area has matches but user has pulled them all (GEO-4)
        "overture_topup": False,   # exhausted here, but Overture has more to pull (§6.11)
        "total_available": 0,
        "nearby": [],
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Ranked candidates (town before province). Cache hit still wins for the
            # common case; on a cold-load that finds 0 places we retry the next
            # candidate so "Lumbini" → province centroid does not dead-end.
            cached = await arun(get_cached_geocode, location)
            if cached:
                geo_candidates = [cached]
            else:
                geo_candidates = await geocode_location_candidates(client, location)
                if geo_candidates:
                    lat, lng, city_radius_km = geo_candidates[0]
                    # Never pin a province-scale centroid in Redis (see geocode_location).
                    if city_radius_km <= 25:
                        await arun(set_cached_geocode, location, lat, lng, city_radius_km)

        if not geo_candidates:
            error_info["geocoding_failed"] = True
            return [], error_info

        center_lat, center_lng, _city_radius_km = geo_candidates[0]
        effective_limit = limit or 100

        if db is not None:
            # Dynamic, DB-backed category resolution. Only the background cold-load
            # path (load_if_cold=True) runs the LLM + learns aliases; the request
            # warm-check (load_if_cold=False) is alias-lookup only — fast, no LLM.
            from app.services.overture_category_service import resolve_overture_categories
            resolved_filter = await resolve_overture_categories(
                db, industry, search_terms, learn=load_if_cold, user_id=user_id
            )
            if topup:
                # §6.11: user drained this area but Overture has more — pull the next
                # nearest batch into the shared cache before querying, so this same
                # search returns the fresh leads.
                await topup_overture_area(
                    db, center_lat, center_lng, search_radius_km, resolved_filter, industry
                )
            elif load_if_cold:
                # Cold-load this category for the area if needed, then query PostGIS.
                await ensure_overture_area_loaded(
                    db, center_lat, center_lng, search_radius_km, resolved_filter, industry
                )
            elif not await overture_area_is_warm(
                db, center_lat, center_lng, search_radius_km, resolved_filter, industry
            ):
                # Cold area, must not block → signal the caller to background the load.
                error_info["overture_cold"] = True
                return [], error_info
            leads = await _query_overture_warm(
                db, center_lat, center_lng, search_radius_km, resolved_filter, effective_limit,
                city_for_tier=city_for_tier,
                user_id=user_id,
                industry=industry,
            )
            # Wrong geocode centroid (e.g. Lumbini Province vs town): first center
            # loads/queries empty. Retry ranked alternate centers.
            if not leads and not topup:
                if len(geo_candidates) <= 1:
                    async with httpx.AsyncClient(timeout=20.0) as client:
                        geo_candidates = await geocode_location_candidates(client, location)
                for alt_lat, alt_lng, alt_radius in geo_candidates:
                    if haversine_distance(center_lat, center_lng, alt_lat, alt_lng) < 15:
                        continue
                    logger.info(
                        "[OVERTURE] Empty at %.4f,%.4f — retrying geocode candidate %.4f,%.4f for %r",
                        center_lat, center_lng, alt_lat, alt_lng, location,
                    )
                    if load_if_cold:
                        await ensure_overture_area_loaded(
                            db, alt_lat, alt_lng, search_radius_km, resolved_filter, industry
                        )
                        alt_leads = await _query_overture_warm(
                            db, alt_lat, alt_lng, search_radius_km, resolved_filter,
                            effective_limit,
                            city_for_tier=city_for_tier,
                            user_id=user_id,
                            industry=industry,
                        )
                        if alt_leads:
                            leads = alt_leads
                            center_lat, center_lng, _city_radius_km = alt_lat, alt_lng, alt_radius
                            await arun(set_cached_geocode, location, alt_lat, alt_lng, alt_radius)
                            break
                    else:
                        # Request path: if an alternate center is still cold, pin
                        # it in cache and background-load (Celery re-geocodes from
                        # the updated cache).
                        if not await overture_area_is_warm(
                            db, alt_lat, alt_lng, search_radius_km, resolved_filter, industry
                        ):
                            await arun(set_cached_geocode, location, alt_lat, alt_lng, alt_radius)
                            error_info["overture_cold"] = True
                            return [], error_info
            # GEO-4: a warm search that returns nothing for THIS user is either
            # "exhausted" (matches exist but they've pulled them all) or genuinely
            # empty. Detect by counting without the exclude-seen filter.
            if not leads and user_id is not None:
                total = await _count_overture_matches(
                    db, center_lat, center_lng, search_radius_km, resolved_filter
                )
                if total > 0:
                    error_info["exhausted"] = True
                    error_info["total_available"] = total
                    # §6.11: if Overture still has more for this area, signal a top-up
                    # (the caller backgrounds it) instead of a dead-end. Suppressed on a
                    # topup pass that already ran — a still-empty result means upstream
                    # is now exhausted, so has_more is False and we fall through to the
                    # normal exhaustion message.
                    error_info["overture_topup"] = await _area_has_more(
                        db, center_lat, center_lng, search_radius_km, resolved_filter, industry
                    )
                    error_info["nearby"] = await _nearby_cities_with_counts(
                        db, center_lat, center_lng, search_radius_km,
                        resolved_filter, city_for_tier,
                        user_id=user_id, industry=industry,
                    )
        else:
            # Direct path (no DB): static map resolution + pull from S3 each call.
            resolved_filter = resolve_overture_filter(industry, search_terms)
            leads = []
            for cand_lat, cand_lng, _ in geo_candidates:
                bbox = bbox_around(
                    cand_lat,
                    cand_lng,
                    search_radius_km + _overture_setting("OVERTURE_AREA_BUFFER_KM", 3.0),
                )
                leads = await duckdb_pull_overture(
                    bbox=bbox,
                    center_lat=cand_lat,
                    center_lng=cand_lng,
                    radius_km=search_radius_km,
                    resolved_filter=resolved_filter,
                    limit=effective_limit,
                )
                if leads:
                    center_lat, center_lng = cand_lat, cand_lng
                    break

        for lead in leads:
            lead["industry"] = industry

        if not leads:
            error_info["no_results"] = True

        return prioritize_location_matches(leads, location), error_info

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Lead search failed. Please try again.",
        )

async def get_leads(
    industry: str,
    location: str,
    use_grid_search: bool = False,
    grid_config_type: str = "dense_urban",
    search_radius_km: float = 5.0,
    limit: int | None = 100,
    semaphores=None,
    search_terms: list[str] | None = None,
):
    """
    Fetch nearby businesses using Google Maps Places API.
    Results are cached in Redis for 24 h to minimise API costs.

    Args:
        industry: Business category to search for
        location: Location name or address
        use_grid_search: Enable grid search for better coverage
        grid_config_type: Type of grid configuration ("dense_urban", "medium_urban", "suburban")
        search_radius_km: Plan's max radius cap in km. Actual radius used is
                          min(search_radius_km, city_radius_from_google_bounds)
                          so large cities like Sydney are capped at search_radius_km
                          and small cities like Kathmandu use their real boundary.
        limit: Maximum number of leads to return
        semaphores: Semaphore object for rate limiting
        search_terms: Google Places keyword terms resolved from the user's intent.
                      Leads are still labeled with the canonical industry.

    Returns:
        Tuple of (leads list, error info dict)
    """

    if not GOOGLE_MAPS_API_KEY:
        raise HTTPException(status_code=500, detail="Lead search is temporarily unavailable. Please try again.")

    places_search_terms = _normalize_places_search_terms(industry, search_terms)

    error_info = {
        "geocoding_failed": False,
        "no_results": False,
        "suggested_location": None,
        "grid_search_used": use_grid_search,
        "total_grid_points": 0,
    }

    # ── Redis cache check ────────────────────────────────────────────────────
    cached_leads = await arun(get_cached_leads, industry, location)
    if cached_leads is not None:
        # Respect the per-request limit even for cached results
        sorted_cached_leads = prioritize_location_matches(cached_leads, location)
        result = sorted_cached_leads[:limit] if limit else sorted_cached_leads
        if not result:
            error_info["no_results"] = True
        return result, error_info
    # ────────────────────────────────────────────────────────────────────────

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:

            # -------------------------------------------------
            # Step 1: Geocode location
            # -------------------------------------------------
            coords = await geocode_location(client, location)

            if not coords:
                error_info["geocoding_failed"] = True
                return [], error_info

            center_lat, center_lng, city_radius_km = coords
            strict_country_shape = await geocode_strict_country_shape(client, location)
            strict_bounds = None
            if strict_country_shape:
                strict_bounds = strict_country_shape.get("bounds")
                logger.info("[LEAD FILTER] Enforcing strict bounds for city-sized country: %s", location)
            tiny_strict_location = bool(
                strict_country_shape
                and city_radius_km <= TINY_STRICT_LOCATION_RADIUS_KM
            )
            target_limit = limit
            if tiny_strict_location:
                target_limit = min(limit or TINY_STRICT_LOCATION_MAX_LEADS, TINY_STRICT_LOCATION_MAX_LEADS)
                logger.info(
                    "[LEAD FETCH] Tiny strict location detected for %s; target capped to %s leads",
                    location,
                    target_limit,
                )

            # Cap plan's max radius to the actual city size from Google bounds.
            # Small city (Kathmandu ~5km) → use 5km even if plan allows 7km.
            # Large city (Sydney ~30km)   → use plan cap (7km) as ceiling.
            effective_radius_km = min(
                search_radius_km,
                max(city_radius_km, MIN_LOCAL_SEARCH_RADIUS_KM),
            )
            logger.info(
                f"[GRID] city_radius={city_radius_km:.1f}km "
                f"plan_max={search_radius_km}km "
                f"effective={effective_radius_km:.1f}km | {location}"
            )

            # -------------------------------------------------
            # Step 2: Grid Search or Single Point Search
            # -------------------------------------------------

            if use_grid_search:
                config = GRID_CONFIG.get(grid_config_type, GRID_CONFIG["dense_urban"])
                grid_spacing_km = config["grid_spacing"]
                search_radius = config["radius"]

                # Generate grid points using the effective (capped) radius
                grid_points = generate_grid_points(
                    center_lat=center_lat,
                    center_lng=center_lng,
                    search_radius_km=effective_radius_km,
                    grid_spacing_km=grid_spacing_km
                )
                if tiny_strict_location:
                    grid_points = [(center_lat, center_lng)]
                
                error_info["total_grid_points"] = len(grid_points)
                logger.info(f"Generated {len(grid_points)} grid points for {location}")
                
                # Fetch from each grid point and each resolved search term.
                all_places = []
                seen_place_ids = set()  # Deduplicate results

                stop_search = False
                for search_term in places_search_terms:
                    logger.info("[GOOGLE PLACES] Searching keyword=%r for canonical industry=%r", search_term, industry)
                    for idx, (lat, lng) in enumerate(grid_points):
                        logger.info(f"Searching grid point {idx + 1}/{len(grid_points)}")

                        base_params = {
                            "location": f"{lat},{lng}",
                            "radius": search_radius,
                            "keyword": search_term,
                            "key": GOOGLE_MAPS_API_KEY,
                        }

                        try:
                            places = await fetch_all_nearby_pages(
                                client=client,
                                base_params=base_params,
                                limit=None,  # Get all from this point
                                semaphores=semaphores,
                            )
                        except httpx.RequestError:
                            if all_places:
                                logger.warning(
                                    "[GOOGLE PLACES] Request failed after %s in-bound candidates; returning partial results",
                                    len(all_places),
                                )
                                stop_search = True
                                break
                            raise
                        places = _filter_places_by_bounds(places, strict_bounds, location)

                        # Deduplicate by place_id
                        for place in places:
                            place_id = place.get("place_id")
                            if place_id and place_id not in seen_place_ids:
                                all_places.append(place)
                                seen_place_ids.add(place_id)

                        # Stop if we've reached or exceeded limit
                        if target_limit and len(all_places) >= target_limit:
                            all_places = all_places[:target_limit]
                            break

                        # Add delay between grid point requests to avoid rate limiting
                        if idx < len(grid_points) - 1:
                            await asyncio.sleep(0.5)
                    if stop_search:
                        break
                    if target_limit and len(all_places) >= target_limit:
                        break
                
            else:
                all_places = []
                seen_place_ids = set()
                stop_search = False
                for search_term in places_search_terms:
                    logger.info("[GOOGLE PLACES] Searching keyword=%r for canonical industry=%r", search_term, industry)
                    base_params = {
                        "location": f"{center_lat},{center_lng}",
                        "radius": 5000,
                        "keyword": search_term,
                        "key": GOOGLE_MAPS_API_KEY,
                    }

                    try:
                        places = await fetch_all_nearby_pages(
                            client=client,
                            base_params=base_params,
                            limit=None if strict_bounds else target_limit,
                            semaphores=semaphores,
                        )
                    except httpx.RequestError:
                        if all_places:
                            logger.warning(
                                "[GOOGLE PLACES] Request failed after %s in-bound candidates; returning partial results",
                                len(all_places),
                            )
                            stop_search = True
                            break
                        raise
                    places = _filter_places_by_bounds(places, strict_bounds, location)
                    for place in places:
                        place_id = place.get("place_id")
                        if place_id and place_id not in seen_place_ids:
                            all_places.append(place)
                            seen_place_ids.add(place_id)
                    if target_limit and len(all_places) >= target_limit:
                        all_places = all_places[:target_limit]
                        break
                    if stop_search:
                        break

            if not all_places:
                error_info["no_results"] = True
                return [], error_info
            
            # -------------------------------------------------
            # Step 3: Fetch details concurrently
            # -------------------------------------------------
            leads = await asyncio.gather(
                *[fetch_details(client, p, industry, semaphores) for p in all_places]
            )

            valid_leads = [l for l in leads if l]
            if strict_country_shape:
                strict_country_code = strict_country_shape.get("country_short_name")
                before_country_filter = len(valid_leads)
                rejected_leads = [
                    lead for lead in valid_leads
                    if lead.get("_country_short_name") != strict_country_code
                ]
                valid_leads = [
                    lead for lead in valid_leads
                    if lead.get("_country_short_name") == strict_country_code
                ]
                nearby_suggestions = _complete_nearby_suggestions(
                    strict_country_code,
                    _rank_nearby_suggestions(rejected_leads),
                )
                if nearby_suggestions:
                    error_info["nearby_suggestions"] = nearby_suggestions
                logger.info(
                    "[LEAD FILTER] Removed %s detailed leads outside country=%s; kept %s; nearby=%s",
                    before_country_filter - len(valid_leads),
                    strict_country_code,
                    len(valid_leads),
                    nearby_suggestions,
                )

            for lead in valid_leads:
                lead.pop("_country_short_name", None)
                lead.pop("_nearby_location_names", None)

            valid_leads = prioritize_location_matches(valid_leads, location)

            if not valid_leads:
                error_info["no_results"] = True
            else:
                # Store in Redis so subsequent requests skip the API entirely
                await arun(set_cached_leads, industry, location, valid_leads)

            return valid_leads, error_info

    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail="Lead search is temporarily unavailable. Please try again.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Lead search failed. Please try again.",
        )

async def _resolve_email_from_texts(lead: dict, domain: str, texts: list[str], semaphores) -> None:
    """Find a contact email from already-fetched page texts, falling back to Hunter.io."""
    from app.utils.email_scraper import (
        emails_from_texts,
        pick_best_result,
        hunter_fallback_company,
        HunterRateLimited,
    )
    from app.utils.chat_helper import has_mx_record

    mx_ok = await has_mx_record(domain)
    best_list = pick_best_result(emails_from_texts(texts, domain, mx_ok))
    if not best_list:
        try:
            best_list = await hunter_fallback_company(domain, semaphores)
        except HunterRateLimited:
            lead["email"] = None
            lead["hunter_data"] = None
            lead["email_source"] = "hunter_rate_limited"
            return

    if best_list:
        best = best_list[0]
        lead["email"] = best.get("email")
        lead["hunter_data"] = best.get("hunter_data")
        lead["email_source"] = best.get("source")
    else:
        lead["email"] = None
        lead["hunter_data"] = None
        lead["email_source"] = None


async def enrich_lead(lead: dict, semaphores, user_id=None):
    """
    Per-lead enrichment with a SINGLE site fetch shared by email-finding and context
    extraction (no double scrape). Steps:
      1. fetch the union of contact + about/services pages once
      2. find a contact email from that text (skipped if the lead already has one)
      3. extract context (services, website_summary, business_description) from that text
    Every step degrades to None on failure; context never invents data.
    """
    website = lead.get("website")
    has_email = bool(lead.get("email"))  # e.g. Overture-provided
    domain = clean_domain(website) if website and website != "N/A" else None

    # No fetchable site: keep any existing email, leave everything else None.
    if not domain:
        if has_email:
            lead.setdefault("email_source", "overture")
        else:
            lead["email"] = None
            lead["hunter_data"] = None
            lead["email_source"] = None
        lead["services"] = None
        lead["website_summary"] = None
        lead["business_description"] = None
        return lead

    # ── ONE fetch, reused by both email-finding and context extraction ──
    try:
        from app.utils.email_scraper import fetch_pages_raw, ENRICH_FETCH_PATHS
        texts = await fetch_pages_raw(domain, ENRICH_FETCH_PATHS, semaphores)
    except Exception:
        texts = []

    # EMAIL — only when the lead doesn't already have one.
    if has_email:
        lead.setdefault("email_source", "overture")
    else:
        try:
            await _resolve_email_from_texts(lead, domain, texts, semaphores)
        except Exception:
            lead["email"] = None
            lead["hunter_data"] = None
            lead["email_source"] = None

    # CONTEXT — always; bound the LLM call with the context semaphore.
    try:
        from app.services.company_scraper_service import build_context_text, extract_lead_context
        context_text = build_context_text(texts)
        async with semaphores.context:
            ctx = await extract_lead_context(domain, context_text, user_id=user_id)
        lead["services"] = ctx.get("services")
        lead["website_summary"] = ctx.get("website_summary")
        lead["business_description"] = ctx.get("business_description")
    except Exception:
        lead["services"] = None
        lead["website_summary"] = None
        lead["business_description"] = None

    return lead

def batch_score_leads(leads: list[dict]) -> list[dict]:
    for lead in leads:
        score = 0

        # Primary signals
        if lead.get("email"):
            score += 40

        if lead.get("website") and lead["website"] != "N/A":
            score += 30

        # Secondary signals
        if lead.get("contact_number") and lead["contact_number"] != "N/A":
            score += 15

        if lead.get("address"):
            score += 10

        # Quality bonus
        if lead.get("industry"):
            score += 5

        lead["lead_score"] = min(score, 100)

    return leads


# ── Master-catalog enrichment helpers (Phase 3, doc §5.2/§6.3) ─────────────────
# Enrichment is per-BUSINESS: the master (overture_places) is checked/claimed by
# overture_id so each business is scraped at most once, ever. Results are written
# onto the master; lead_log_leads is still written too (thinned in Phase 4).


async def _fetch_master_enrichment(db, overture_ids: list[str]) -> dict[str, dict]:
    """Enrichment state of the master rows for these overture_ids, keyed by id."""
    if not overture_ids:
        return {}
    rows = (
        await db.execute(
            select(
                OverturePlace.overture_id,
                OverturePlace.enrichment_status,
                OverturePlace.email,
                OverturePlace.scraped_email,
                OverturePlace.email_source,
                OverturePlace.lead_score,
                OverturePlace.hunter_data,
                OverturePlace.services,
                OverturePlace.website_summary,
                OverturePlace.business_description,
            ).where(OverturePlace.overture_id.in_(overture_ids))
        )
    ).mappings().all()
    return {r["overture_id"]: dict(r) for r in rows}


async def _claim_master_for_enrichment(db, overture_ids: list[str]) -> set[str]:
    """Atomically claim eligible master rows (NULL/pending/failed → 'processing').

    Returns the ids actually claimed. Ids already 'done' or claimed by a concurrent
    worker come back empty — Postgres row locking makes the race impossible. The
    claim is committed immediately so other workers see 'processing'.
    """
    if not overture_ids:
        return set()
    rows = (
        await db.execute(
            update(OverturePlace)
            .where(
                OverturePlace.overture_id.in_(overture_ids),
                (OverturePlace.enrichment_status.is_(None))
                | (OverturePlace.enrichment_status.in_(["pending", "failed"])),
            )
            .values(enrichment_status="processing")
            .returning(OverturePlace.overture_id)
        )
    ).fetchall()
    await db.commit()
    return {r[0] for r in rows}


def _item_from_master(lead: dict, master: dict) -> dict:
    """Shape a master row's enrichment into an enrich_lead-style item for the log row.

    Served email = COALESCE(scraped_email, email) — enrichment wins over raw
    Overture (doc §4.6).
    """
    if master.get("scraped_email"):
        email, email_source = master["scraped_email"], master.get("email_source")
    elif master.get("email"):
        email, email_source = master["email"], master.get("email_source") or "overture"
    else:
        email, email_source = None, None
    return {
        **lead,
        "email": email,
        "email_source": email_source,
        "hunter_data": master.get("hunter_data"),
        "services": master.get("services"),
        "website_summary": master.get("website_summary"),
        "business_description": master.get("business_description"),
    }


async def _persist_enriched_lead(db, lead_log_id: UUID, item: dict) -> None:
    """
    Write one lead's enrichment results to its search-stage row and any promoted Lead row.

    - lead_log_leads: authoritative result row — always written (incl. None context).
    - leads (promoted): email/score synced only while email is still None (don't clobber a
      user-set email); context fields sync regardless of email, but never overwrite existing
      context with None.
    - overture_places (master): written ONLY for leads whose master row this job
      claimed (item["_master_claimed"]) — see the write-back block at the end.
    """
    now = datetime.now(timezone.utc)

    await db.execute(
        update(LeadLogLead)
        .where(LeadLogLead.id == item["id"])
        .values(
            email=item.get("email"),
            lead_score=item.get("lead_score", 0),
            enrichment_status="done",
            hunter_data=item.get("hunter_data"),
            services=item.get("services"),
            website_summary=item.get("website_summary"),
            business_description=item.get("business_description"),
            updated_at=now,
        )
    )

    # Sync email/score to the promoted Lead record (if any). Email only when still None.
    await db.execute(
        update(Lead)
        .where(
            Lead.lead_log_id == lead_log_id,
            Lead.business_name == item.get("business_name"),
            Lead.email.is_(None),
        )
        .values(
            email=item.get("email"),
            lead_score=item.get("lead_score", 0),
            updated_at=now,
        )
    )

    # Context fields are not contact data — sync them regardless of email state, but only
    # the ones we actually extracted (skip None so we never wipe existing context).
    context_values = {
        k: v
        for k, v in {
            "services": item.get("services"),
            "website_summary": item.get("website_summary"),
            "business_description": item.get("business_description"),
        }.items()
        if v is not None
    }
    if context_values:
        context_values["updated_at"] = now
        await db.execute(
            update(Lead)
            .where(
                Lead.lead_log_id == lead_log_id,
                Lead.business_name == item.get("business_name"),
            )
            .values(**context_values)
        )

    # ── Master write-back (Phase 3) — only for rows THIS job claimed ────────────
    # scraped_email gets the email only when it came from the scraper/Hunter; an
    # Overture-provided email already lives in master.email and must NOT be
    # duplicated into scraped_email (column split, doc §4.6). email_source keeps
    # the existing label if enrichment produced none. Safe to overwrite the rest:
    # the claim guarantees no other worker's enrichment is in this row.
    if item.get("_master_claimed") and item.get("overture_id"):
        source = item.get("email_source")
        if source == "hunter_rate_limited":
            await db.execute(
                update(OverturePlace)
                .where(OverturePlace.overture_id == item["overture_id"])
                .values(
                    services=item.get("services"),
                    website_summary=item.get("website_summary"),
                    business_description=item.get("business_description"),
                    enrichment_status="failed",
                )
            )
        else:
            scraped_email = (
                item.get("email") if (item.get("email") and source and source != "overture") else None
            )
            await db.execute(
                update(OverturePlace)
                .where(OverturePlace.overture_id == item["overture_id"])
                .values(
                    scraped_email=(str(scraped_email)[:320] if scraped_email else None),
                    email_source=func.coalesce(source, OverturePlace.email_source),
                    lead_score=item.get("lead_score", 0),
                    hunter_data=item.get("hunter_data"),
                    services=item.get("services"),
                    website_summary=item.get("website_summary"),
                    business_description=item.get("business_description"),
                    enriched_at=now,
                    enrichment_status="done",
                )
            )


async def enrich_leads_background(lead_log_id: UUID, session_factory):
    """
    Background task:
    - Fetch leads by lead_log_id
    - Enrich emails
    - Score leads
    - Update DB
    """
    from app.utils.enrichment_semaphores import get_enrichment_semaphores
    import time

    semaphores = get_enrichment_semaphores()

    job_start = time.perf_counter()
    logger.info(f"[ENRICH] Job started | lead_log_id={lead_log_id}")

    # Master rows THIS job claimed ('processing'); reset to 'failed' on a crash so
    # a dead worker never leaves businesses permanently stuck un-enrichable.
    claimed: set[str] = set()

    async with session_factory() as db:
        try:
            # Fetch user_id from LeadLog for credit deduction later
            from app.models.lead_log import LeadLog
            lead_log = await db.get(LeadLog, lead_log_id)
            enrich_user_id = lead_log.user_id if lead_log else None

            # Fetch leads from DB
            result = await db.execute(
                select(LeadLogLead).where(
                    LeadLogLead.lead_log_id == lead_log_id,
                    LeadLogLead.enrichment_status == "processing",
                )
            )
            leads = result.scalars().all()

            lead_dicts = [
                {
                    "id": lead.id,
                    "business_name": lead.business_name,
                    "website": lead.website,
                    "address": lead.address,
                    "contact_number": lead.contact_number,
                    "industry": lead.industry,
                    "email": lead.email,  # carry existing (Overture) email so we don't re-scrape
                    "overture_id": lead.overture_id,  # master link; None = legacy/Google
                }
                for lead in leads
            ]

            if not lead_dicts:
                logger.info(f"[ENRICH] No leads to process — skipping (lead_log_id={lead_log_id})")
                return

            total_leads = len(lead_dicts)

            # ── Master-catalog gate (Phase 3, doc §5.2) ──────────────────────────
            # Each BUSINESS is scraped at most once, ever:
            #   master done                → copy enrichment from master, no scrape
            #   master NULL/pending/failed → atomically claim, scrape, write back
            #   master processing (other)  → defer; recheck once after the batch
            #   no overture_id             → legacy path (Google/manual), unchanged
            master_ids = [l["overture_id"] for l in lead_dicts if l.get("overture_id")]
            master_map = await _fetch_master_enrichment(db, master_ids)

            reuse_items: list[dict] = []
            deferred: list[dict] = []
            to_scrape: list[dict] = []
            eligible_ids: list[str] = []
            for l in lead_dicts:
                master = master_map.get(l.get("overture_id"))
                if master is None:
                    to_scrape.append(l)  # legacy / master row missing
                elif master["enrichment_status"] == "done":
                    reuse_items.append(_item_from_master(l, master))
                elif master["enrichment_status"] == "processing":
                    deferred.append(l)  # another worker owns the scrape
                else:  # NULL / pending / failed → try to claim
                    eligible_ids.append(l["overture_id"])
                    to_scrape.append(l)

            claimed = await _claim_master_for_enrichment(db, eligible_ids)
            eligible_set = set(eligible_ids)
            still_scrape: list[dict] = []
            for l in to_scrape:
                oid = l.get("overture_id")
                if oid and oid in eligible_set:
                    if oid in claimed:
                        l["_master_claimed"] = True
                        still_scrape.append(l)
                    else:
                        deferred.append(l)  # lost the race between fetch and claim
                else:
                    still_scrape.append(l)
            to_scrape = still_scrape

            logger.info(
                f"[ENRICH] Processing {total_leads} leads | "
                f"scrape={len(to_scrape)} (claimed={len(claimed)}) | "
                f"reused_from_master={len(reuse_items)} | deferred={len(deferred)}"
            )

            # Reused businesses: already enriched on the master — persist the copy
            # immediately, no site fetch, no Hunter call, no re-charge.
            if reuse_items:
                for item in reuse_items:
                    item = batch_score_leads([item])[0]
                    await _persist_enriched_lead(db, lead_log_id, item)
                await db.commit()

            tasks = [
                enrich_lead(lead, semaphores, user_id=enrich_user_id)
                for lead in to_scrape
            ]

            pending_batch = []
            completed = 0
            emails_found = 0
            hunter_emails = 0
            scraper_emails = 0

            # Run enrichment concurrently AND commit live
            for coro in asyncio.as_completed(tasks):
                lead_start = time.perf_counter()
                e = await coro
                e = batch_score_leads([e])[0]
                lead_elapsed = time.perf_counter() - lead_start

                completed += 1
                if e.get("email"):
                    emails_found += 1
                    source = e.get("email_source", "")
                    if source in ("hunter", "hunter_company_enrichment"):
                        hunter_emails += 1
                    else:
                        scraper_emails += 1

                logger.info(
                    f"[ENRICH] [{completed}/{len(to_scrape)}] "
                    f"email={'found' if e.get('email') else 'not found'} | "
                    f"score={e.get('lead_score', 0)} | "
                    f"took={lead_elapsed:.2f}s"
                )

                pending_batch.append(e)

                # Commit as soon as batch is full
                if len(pending_batch) >= ENRICH_COMMIT_BATCH_SIZE:
                    batch_start = time.perf_counter()
                    try:
                        for item in pending_batch:
                            await _persist_enriched_lead(db, lead_log_id, item)

                        await db.commit()
                        logger.info(f"[ENRICH] Committed batch of {len(pending_batch)} leads in {time.perf_counter() - batch_start:.2f}s")
                    except Exception as err:
                        await db.rollback()
                        logger.error(f"[ENRICH] Batch commit failed: {err}")

                    pending_batch.clear()

            # Commit remaining leads (last partial batch)
            if pending_batch:
                batch_start = time.perf_counter()
                try:
                    for item in pending_batch:
                        await _persist_enriched_lead(db, lead_log_id, item)

                    await db.commit()
                    logger.info(f"[ENRICH] Committed final batch of {len(pending_batch)} leads in {time.perf_counter() - batch_start:.2f}s")
                except Exception as err:
                    await db.rollback()
                    logger.error(f"[ENRICH] Final batch commit failed: {err}")

            # ── Deferred leads: business claimed by ANOTHER worker (doc §6.3) ────
            # Recheck the master once now that our batch is done; if the owner
            # finished, copy its enrichment. If it's still running (rare — a slow
            # site), degrade gracefully: keep what the row already has (incl. any
            # Overture email), context stays NULL, and mark the row done so the
            # frontend poll completes. The master itself stays owned by the other
            # worker and finishes independently.
            if deferred:
                recheck = await _fetch_master_enrichment(
                    db, [l["overture_id"] for l in deferred]
                )
                copied = 0
                for l in deferred:
                    master = recheck.get(l["overture_id"])
                    if master and master["enrichment_status"] == "done":
                        item = _item_from_master(l, master)
                        copied += 1
                    else:
                        item = {
                            **l,
                            "hunter_data": None,
                            "services": None,
                            "website_summary": None,
                            "business_description": None,
                        }
                    item = batch_score_leads([item])[0]
                    await _persist_enriched_lead(db, lead_log_id, item)
                await db.commit()
                logger.info(
                    f"[ENRICH] Deferred resolved: {copied}/{len(deferred)} copied from "
                    f"master, {len(deferred) - copied} degraded (owner still running)"
                )

            total_elapsed = time.perf_counter() - job_start
            logger.info(
                f"[ENRICH] Job complete | "
                f"total={total_leads} leads (scraped={len(to_scrape)}, "
                f"reused={len(reuse_items)}, deferred={len(deferred)}) | "
                f"emails_found={emails_found} (hunter={hunter_emails}, scraper={scraper_emails}) | "
                f"total_time={total_elapsed:.2f}s | "
                f"avg_per_lead={total_elapsed / total_leads:.2f}s"
            )

            # Enrichment credit hooks (costs are 0 in CREDIT_COSTS — only lead_found is billed)
            if enrich_user_id and emails_found > 0:
                try:
                    from app.services.credit_service import spend_credits
                    if hunter_emails > 0:
                        await spend_credits(
                            db, enrich_user_id, "email_enriched",
                            quantity=hunter_emails,
                            description=f"Hunter.io: {hunter_emails} emails found",
                        )
                    if scraper_emails > 0:
                        await spend_credits(
                            db, enrich_user_id, "email_scraped",
                            quantity=scraper_emails,
                            description=f"Scraper: {scraper_emails} emails found",
                        )
                    logger.info(
                        f"[CREDITS] Enrichment spend skipped (cost 0): hunter={hunter_emails}, scraper={scraper_emails}"
                    )
                except Exception as credit_err:
                    logger.warning(f"[CREDITS] Warning: enrichment credit deduction failed: {credit_err}")

        except Exception as e:
            await db.rollback()

            # Mark all still-processing leads as failed
            await db.execute(
                update(LeadLogLead)
                .where(LeadLogLead.lead_log_id == lead_log_id)
                .where(LeadLogLead.enrichment_status == "processing")
                .values(
                    enrichment_status="failed",
                    updated_at=datetime.now(timezone.utc),
                )
            )

            # Crash safety (doc §6.3): release OUR claimed-but-unfinished master
            # rows back to 'failed' (retry-eligible). Rows already written 'done'
            # are untouched; other workers' claims are untouched.
            if claimed:
                await db.execute(
                    update(OverturePlace)
                    .where(
                        OverturePlace.overture_id.in_(claimed),
                        OverturePlace.enrichment_status == "processing",
                    )
                    .values(enrichment_status="failed")
                )
            await db.commit()

            total_elapsed = time.perf_counter() - job_start
            logger.error(f"[ENRICH] Job failed after {total_elapsed:.2f}s: {e}")
