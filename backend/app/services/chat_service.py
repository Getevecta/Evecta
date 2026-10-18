import httpx
import logging
import re
import time
from datetime import datetime, timezone
from fastapi import HTTPException, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from app.core.config import get_settings
import asyncio
logger = logging.getLogger(__name__)
from app.services.external_api_usage import record_places_usage
from app.models.user import User
from app.models.lead_log import LeadLog
from app.models.lead_log_lead import LeadLogLead
from sqlalchemy import insert, text
from app.utils.chat_helper import (
    CHAT_PERSONA,
    _verified_city_suggestions,
    fallback_ack_narrow_ask_location,
    fallback_about_assistant,
    fallback_ask_city_or_country,
    fallback_ask_industry,
    fallback_ask_location,
    fallback_greeting,
    generate_human_response,
    generate_human_response_stream,
    generate_suggestions,
    generate_suggestions_with_verification,
    _looks_like_about_assistant,
)
from app.utils.chat_knowledge import (
    build_undocumented_reply,
    generate_grounded_answer_stream,
)
from app.utils.chat_stream_sink import emit_chat_token
from app.knowledge.retriever import retrieve
from app.services.chat_knowledge_log import log_retrieval
from app.services.ai.tracked_llm import tracked_astream, llm_model_name
from app.utils.llm_errors import LLMUnavailableError, llm_error_result, is_llm_unavailable
from app.services.understanding import understand
from app.services import chat_memory_service as chat_memory
from app.services.lead_generation_service import (
    get_leads,
    get_leads_overture,
    prioritize_location_matches,
    OVERTURE_STRICT_INTENT_MARKERS,
)
from app.utils.chat_history import format_chat_history_for_prompt as _history_str
from app.utils.redis_context import (
    arun,
    acquire_search_lock,
    release_search_lock,
    get_cached_leads,
    check_user_search_rate,
    increment_user_search_rate,
    set_cached_geocode,
    get_cached_country_check,
    set_cached_country_check,
    set_cached_region_check,
    get_cached_place_kind,
    set_cached_place_kind,
)

# CONFIG
settings = get_settings()
GOOGLE_MAPS_API_KEY = settings.GOOGLE_MAPS_API_KEY


FAST_PATHS = ["/", "/contact", "/contact-us"]
ALLOWED_PREFIXES = ["info", "contact", "hello", "support",
    "sales", "admin", "office", "team",
    "enquiries", "marketing"]
EMAIL_REGEX = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
HTTP_TIMEOUT = 6.0
MAX_CONCURRENT = 5
ENRICH_COMMIT_BATCH_SIZE = 30
_DEFAULT_LEADS_LIMIT = 100  # fallback; overridden per-user by plan at runtime

# Search verbs that mean the user wants leads — even when the LLM mislabels a
# brand/product query as general_question (e.g. "search Proton Emas5 shops").
_SEARCH_VERB_RE = re.compile(
    r"\b(search(?:\s+for)?|find(?:\s+me)?|looking\s+for|leads?\s+for|show\s+me|get\s+me|pull)\b",
    re.IGNORECASE,
)
_SEARCH_FILLER_RE = re.compile(
    r"\b("
    r"then|please|can\s+you|could\s+you|would\s+you|"
    r"for\s+me|help\s+me|with|"
    r"i(?:'m|\s+am)?\s+(?:looking\s+for|searching\s+for)|"
    r"i\s+(?:want|need|d\s+like|would\s+like)(?:\s+to)?|"
    r"want\s+to|need\s+to|like\s+to|looking\s+to|"
    r"me|some|any|a|an|the"
    r")\b",
    re.IGNORECASE,
)
_CHATTY_INDUSTRY_RE = re.compile(
    r"\b(i|me|my|you|we|want|need|like|help|please|find|search|looking|"
    r"can|could|would|should)\b",
    re.IGNORECASE,
)
_BARE_GREETING_RE = re.compile(
    r"^\s*(hi+|hello+|hey+|howdy|greetings|yo+"
    r"|good\s+(morning|afternoon|evening)"
    r"|thanks|thank\s+you|thx|ty"
    r"|bye+|goodbye|see\s+ya|cya)[\s!.]*$",
    re.IGNORECASE,
)
# Category / shop-type hints — brand queries often omit an explicit "search".
_BUSINESS_HINT_RE = re.compile(
    r"\b(shops?|stores?|dealers?|dealerships?|restaurants?|cafes?|hotels?|"
    r"clinics?|dentists?|pharmac(?:y|ies)|agenc(?:y|ies)|companies|"
    r"business(?:es)?|suppliers?|factories|manufacturers?|offices|"
    r"showrooms?|outlets?|franchises?|workshops?|garages?|salons?)\b",
    re.IGNORECASE,
)
# Assistant prompts we use to reconstruct which slot the user already answered.
_ASKED_INDUSTRY_RE = re.compile(
    r"\b(what industry|which industry|business type|what kind of business|"
    r"what (?:are|should) we search|who are you after)\b",
    re.IGNORECASE,
)
_ASKED_PLACE_RE = re.compile(
    r"\b(which (?:city|country|location)|what (?:city|country|location)|"
    r"where (?:should|do|would)|in which (?:city|country)|city or country)\b",
    re.IGNORECASE,
)
_INFO_QUESTION_RE = re.compile(
    r"^\s*(what|who|how|why|when|where|tell|explain|is|are|can|do|does)\b",
    re.IGNORECASE,
)
_INDUSTRY_SWITCH_CUE_RE = re.compile(
    r"\b(actually|instead|rather|switch|change|new|different|search|find|looking\s+for)\b",
    re.IGNORECASE,
)


def message_looks_like_lead_search(message: str) -> bool:
    msg = message or ""
    return bool(_SEARCH_VERB_RE.search(msg) or _BUSINESS_HINT_RE.search(msg))


def _looks_like_bare_greeting(message: str | None) -> bool:
    """True for hi/hellooo/thanks/bye with no search content."""
    return bool(_BARE_GREETING_RE.match((message or "").strip()))


def _looks_like_chatty_industry(phrase: str | None) -> bool:
    """True when a supposed industry still looks like chat / intent filler."""
    text = " ".join((phrase or "").strip().split())
    if not text:
        return True
    words = text.split()
    if len(words) > 4:
        return True
    # Remaining filler words mean cleaning failed (e.g. "i want to hotels").
    return bool(_CHATTY_INDUSTRY_RE.search(text))


def _industry_phrase_from_search_message(message: str) -> str | None:
    """Strip search verbs/filler from a search message to recover the category/brand."""
    cleaned = _SEARCH_VERB_RE.sub(" ", message or "")
    # Repeat filler stripping — nested phrases like "can you help me" need multiple passes.
    for _ in range(3):
        nxt = _SEARCH_FILLER_RE.sub(" ", cleaned)
        nxt = " ".join(nxt.split())
        if nxt == cleaned:
            break
        cleaned = nxt
    cleaned = cleaned.strip(" .,?!")
    return cleaned or None


def sanitize_industry_label(raw: str | None, fallback: str | None = None) -> str | None:
    """Return a clean business category, never a chat sentence fragment."""
    candidates = [
        (raw or "").strip() or None,
        _industry_phrase_from_search_message(raw) if raw else None,
        (fallback or "").strip() or None,
        _industry_phrase_from_search_message(fallback) if fallback else None,
    ]
    for candidate in candidates:
        if candidate and not _looks_like_chatty_industry(candidate):
            return candidate
    return None


def _looks_like_info_question(message: str) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    if _looks_like_bare_greeting(msg):
        return False
    if "?" in msg:
        return True
    return bool(_INFO_QUESTION_RE.match(msg))


def _looks_like_industry_switch(message: str) -> bool:
    """Detect corrections like 'actually, search physiotherapists instead'."""
    msg = (message or "").strip()
    if not msg or _looks_like_info_question(msg):
        return False
    if message_looks_like_lead_search(msg):
        return True
    lower = msg.lower()
    if _INDUSTRY_SWITCH_CUE_RE.search(lower):
        return True
    # Short category-like corrections ("physiotherapists instead")
    if len(msg.split()) <= 6 and any(s in lower for s in (" instead", " rather", " therapists", " clinics", " dentists")):
        return True
    return False


def merge_basic_slots(context: dict, u) -> None:
    """Merge non-null understanding slots into context without wiping known values."""
    from app.utils.conversation_health import looks_like_valid_place

    cleaned = sanitize_industry_label(u.industry, context.get("industry"))
    if cleaned:
        context["industry"] = cleaned
    if u.location and looks_like_valid_place(u.location):
        context["location"] = u.location
    elif u.location is None:
        pass  # keep existing
    if u.country and looks_like_valid_place(u.country):
        context["country"] = u.country


def backfill_industry_from_history(context: dict, history: list | None) -> None:
    """If industry was never stored (brand search misclassified), recover from history."""
    if context.get("industry"):
        return
    for entry in reversed(history or []):
        if entry.get("role") != "user":
            continue
        msg = (entry.get("message") or "").strip()
        if not msg or _looks_like_info_question(msg):
            continue
        # Prefer explicit search / shop-type messages.
        if message_looks_like_lead_search(msg):
            phrase = _industry_phrase_from_search_message(msg)
            if phrase and len(phrase) > 1:
                context["industry"] = phrase
                return
    # Reconstruct from Q/A: if assistant asked for city/country, the prior user
    # message was almost certainly the industry (even without "search" / "shops").
    hist = list(history or [])
    for i in range(len(hist) - 1, -1, -1):
        entry = hist[i]
        if entry.get("role") != "assistant":
            continue
        assistant_msg = entry.get("message") or ""
        if not _ASKED_PLACE_RE.search(assistant_msg):
            continue
        # Walk backward to the nearest earlier user message.
        for j in range(i - 1, -1, -1):
            prev = hist[j]
            if prev.get("role") != "user":
                continue
            msg = (prev.get("message") or "").strip()
            if not msg or _looks_like_info_question(msg):
                continue
            # Skip pure place answers that came AFTER the ask (handled elsewhere).
            phrase = _industry_phrase_from_search_message(msg) or msg
            if phrase and len(phrase) > 1:
                context["industry"] = phrase
                return
            break


def backfill_place_from_history(context: dict, history: list | None) -> None:
    """If place was never stored but user already answered a location ask, recover it."""
    if context.get("location") or context.get("country"):
        return
    hist = list(history or [])
    for i in range(len(hist) - 1, -1, -1):
        entry = hist[i]
        if entry.get("role") != "assistant":
            continue
        if not _ASKED_PLACE_RE.search(entry.get("message") or ""):
            continue
        # Next user message after that ask is the place answer.
        for j in range(i + 1, len(hist)):
            nxt = hist[j]
            if nxt.get("role") != "user":
                continue
            msg = (nxt.get("message") or "").strip()
            if not msg or _looks_like_info_question(msg):
                break
            if message_looks_like_lead_search(msg) and _BUSINESS_HINT_RE.search(msg):
                # Likely restated industry, not a place.
                break
            from app.utils.conversation_health import looks_like_valid_place

            # Short answers after a place ask → treat as country/location.
            if looks_like_valid_place(msg):
                context["country"] = msg
                return
            break


def recover_slots_from_history(context: dict, history: list | None) -> None:
    """Belt-and-suspenders recovery so confusing chat cannot wipe both slots."""
    backfill_industry_from_history(context, history)
    backfill_place_from_history(context, history)


def _return_stuck_recovery(context: dict, history: list) -> dict:
    from app.utils.chat_recovery import build_stuck_recovery

    payload = build_stuck_recovery(context)
    history.append({"role": "assistant", "message": payload["message"]})
    return payload


def _pending_ask(
    context: dict,
    history: list,
    reply: str,
    ask_kind: str,
    *,
    allow_stuck: bool = True,
    **extra,
) -> dict:
    """Record a pending clarifying ask; if the conversation is stuck, break the loop.

    Set ``allow_stuck=False`` after Change city / incomplete "X in" so we actually
    ask for the city instead of bouncing back into the stuck recovery card.
    """
    from app.utils.conversation_health import is_conversation_stuck, note_pending_ask

    note_pending_ask(context, ask_kind)
    if allow_stuck and is_conversation_stuck(context):
        return _return_stuck_recovery(context, history)
    history.append({"role": "assistant", "message": reply})
    payload = {"status": "pending", "message": reply, "context": context}
    payload.update(extra)
    return payload


def _maybe_clear_for_start_over(context: dict, message: str | None) -> bool:
    """If the user chose Start over, wipe search slots and health so a fresh goal can begin."""
    from app.utils.conversation_health import note_progress, normalize_user_message

    if normalize_user_message(message) not in {"start over", "restart", "reset", "start again"}:
        return False
    for key in (
        "industry",
        "location",
        "country",
        "search_terms",
        "quality",
        "radius_km",
        "anchor",
        "ambiguous",
        "candidate_meanings",
        "awaiting_clarification",
        "awaiting_scope",
        "awaiting_confirmation",
        "scope_family",
        "scope_siblings",
        "scope_terms",
        "confirmed_goal",
        "strict_intent",
        "_force_ask_location",
    ):
        context.pop(key, None)
    note_progress(context)
    return True


def _apply_change_city_command(context: dict, message: str | None) -> bool:
    """Handle recovery action 'Change city' — clear place, keep industry, ask for a city."""
    from app.utils.conversation_health import note_progress, normalize_user_message

    norm = normalize_user_message(message)
    if norm not in {"change city", "change location", "new city", "different city"}:
        return False
    for key in (
        "location",
        "country",
        "anchor",
        "radius_km",
        "confirmed_goal",
        "awaiting_confirmation",
        "awaiting_scope",
    ):
        context.pop(key, None)
    context["_force_ask_location"] = True
    note_progress(context)
    return True


def _apply_incomplete_in_query(context: dict, message: str | None) -> bool:
    """Handle 'chocolate in' — set industry, clear place, force a city ask."""
    from app.utils.conversation_health import note_progress, parse_industry_missing_city

    industry = parse_industry_missing_city(message)
    if not industry:
        return False
    context["industry"] = industry
    for key in (
        "location",
        "country",
        "anchor",
        "confirmed_goal",
        "awaiting_confirmation",
        "awaiting_scope",
    ):
        context.pop(key, None)
    context["_force_ask_location"] = True
    note_progress(context)
    return True


def coerce_search_understanding(u, message: str, context: dict):
    """Force brand+search (and missing-slot answers) onto lead_search so slots merge.

    Without this, "search Proton Emas5 shops" often lands as general_question, skips
    the merge block, and the bot loops asking for industry ↔ location forever.
    """
    if u.intent not in ("general_question",):
        return u

    msg = (message or "").strip()
    if not msg:
        return u

    if message_looks_like_lead_search(msg) and not _looks_like_info_question(msg):
        industry = u.industry or _industry_phrase_from_search_message(msg) or msg
        from app.utils.conversation_health import looks_like_valid_place

        loc = u.location or context.get("location")
        ctry = u.country or context.get("country")
        return u.model_copy(
            update={
                "intent": "lead_search",
                "industry": industry,
                "location": loc if looks_like_valid_place(loc) else None,
                "country": ctry if looks_like_valid_place(ctry) else None,
            }
        )

    # Answering "what industry?" while a place is already known — bare brand/category.
    from app.utils.conversation_health import looks_like_valid_place

    loc = context.get("location")
    ctry = context.get("country")
    has_place = bool(
        (loc and looks_like_valid_place(str(loc)))
        or (ctry and looks_like_valid_place(str(ctry)))
    )
    has_industry = bool(context.get("industry"))
    if (
        has_place
        and not has_industry
        and len(msg.split()) <= 8
        and not _looks_like_info_question(msg)
        and not msg.lower().startswith(("hi", "hello", "hey", "thanks", "thank", "bye"))
    ):
        return u.model_copy(
            update={
                "intent": "lead_search",
                "industry": u.industry or msg,
                "location": loc if looks_like_valid_place(str(loc or "")) else None,
                "country": ctry if looks_like_valid_place(str(ctry or "")) else None,
            }
        )

    # Answering "which city/country?" while industry is known — bare place name.
    # Only trust the model's own location/country slots here. Do NOT promote the raw
    # user message into country (that turned "please" into a geocode attempt).
    if (
        has_industry
        and not has_place
        and (looks_like_valid_place(u.location) or looks_like_valid_place(u.country))
        and not _looks_like_info_question(msg)
        and not message_looks_like_lead_search(msg)
    ):
        return u.model_copy(
            update={
                "intent": "lead_search",
                "industry": u.industry or context.get("industry"),
                "country": u.country if looks_like_valid_place(u.country) else None,
                "location": u.location if looks_like_valid_place(u.location) else None,
            }
        )

    return u


def normalize_search_terms(industry: str | None, raw_terms) -> list[str]:
    """Return up to 3 unique Places search keywords, falling back to industry."""
    terms: list[str] = []

    if isinstance(raw_terms, list):
        candidates = raw_terms
    elif isinstance(raw_terms, str):
        candidates = [raw_terms]
    else:
        candidates = []

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


def rank_leads(leads, industry, search_terms, location, quality=None):
    """Order leads by relevance + contactability, preserving location priority.

    Signals available at this point in the flow: contact completeness (email/site/
    phone) and whether the resolved industry/search-terms appear in the business
    name. The place's category isn't carried in the lead dict, so this is a
    completeness + name-match reorder *within* the existing location tiers (kept
    first so behavior doesn't regress). A quality refinement such as "premium"
    is a silent ranking hint; it should not block the search or trigger a
    ratings disclaimer.
    """
    kws = {
        w
        for t in [industry, *(search_terms or [])]
        for w in (t or "").lower().split()
        if len(w) > 2
    }
    city = (location or "").split(",")[0].strip().lower()

    def _present(v):
        return str(v or "").strip().lower() not in ("", "n/a", "none")

    def _score(lead):
        name = (lead.get("business_name") or "").lower()
        name_match = sum(1 for k in kws if k in name)
        completeness = (
            (2 if _present(lead.get("email")) else 0)
            + (1 if _present(lead.get("website")) else 0)
            + (1 if _present(lead.get("contact_number")) else 0)
        )
        lead_score = int(lead.get("lead_score") or 0)
        quality_boost = 0
        if quality in ("premium", "top_rated"):
            # Without ratings/reviews in the lead shape, contact completeness and
            # enrichment score are the best available quality signals.
            quality_boost = completeness * 2 + min(lead_score, 100) // 20
        elif quality == "budget":
            # Budget is kept as a soft hint only; we do not have pricing fields.
            quality_boost = completeness
        return name_match * 3 + completeness + quality_boost

    def _key(lead):
        name = (lead.get("business_name") or "").lower()
        addr = (lead.get("address") or "").lower()
        loc_first = 0 if (city and (city in addr or city in name)) else 1
        return (loc_first, -_score(lead), name)

    return sorted(leads, key=_key)


# LOCATION VALIDATION
_CITY_SIZED_REGION_MAX_DEGREES = 3.0

# Closed set of continent-scale names. Google often returns these as
# ``continent`` / ``natural_feature`` / ``political`` — not ``country`` — so the
# old classifier wrongly treated them as cities and skipped city suggestions.
_CONTINENT_NAMES = frozenset({
    "africa",
    "antarctica",
    "asia",
    "europe",
    "north america",
    "south america",
    "oceania",
    "australia and oceania",
    "eurasia",
    "americas",
    "the americas",
})

_BROAD_PLACE_TYPES = frozenset({
    "continent",
    "natural_feature",
})


def _is_city_sized_geocode_result(result: dict) -> bool:
    """Return True when Google bounds are small enough for direct local search."""
    viewport = result.get("geometry", {}).get("viewport", {})
    ne = viewport.get("northeast", {})
    sw = viewport.get("southwest", {})
    if not ne or not sw:
        return False

    lat_span = abs(ne.get("lat", 0) - sw.get("lat", 0))
    lng_span = abs(ne.get("lng", 0) - sw.get("lng", 0))
    return (
        lat_span < _CITY_SIZED_REGION_MAX_DEGREES
        and lng_span < _CITY_SIZED_REGION_MAX_DEGREES
    )


def _normalize_place_label(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _is_continent_name(place: str | None) -> bool:
    return _normalize_place_label(place) in _CONTINENT_NAMES


def _classify_geocode_result(place: str, result: dict) -> str:
    """Map a Google Geocode result to city vs broad_region (needs a city pick)."""
    types = set(result.get("types") or [])
    if _is_continent_name(place) or types & _BROAD_PLACE_TYPES:
        return "broad_region"
    if "country" in types or "administrative_area_level_1" in types:
        return "city" if _is_city_sized_geocode_result(result) else "broad_region"
    # Locality / neighborhood / establishment — only treat as city when bounds are small.
    if _is_city_sized_geocode_result(result):
        return "city"
    return "broad_region"


async def classify_place_on_map(location: str) -> str:
    """Classify a place via Google Geocoding (cached in Redis).

    Returns one of:
      - ``city`` — searchable locality / city-sized area
      - ``broad_region`` — country, continent, or large admin region (need a city)
      - ``unresolved`` — Google returned no results (not a real place)
      - ``unavailable`` — no API key or request error (fail open later)
    """
    place = (location or "").strip()
    if not place:
        return "unresolved"

    from app.utils.conversation_health import looks_like_valid_place

    if not looks_like_valid_place(place):
        return "unresolved"

    # Continents are always too broad to search as a single city — suggest cities
    # even if a stale Redis cache previously marked them as "city".
    if _is_continent_name(place):
        await arun(set_cached_place_kind, place, "broad_region")
        await arun(set_cached_region_check, place, True)
        return "broad_region"

    cached_kind = await arun(get_cached_place_kind, place)
    if cached_kind:
        return cached_kind

    if not GOOGLE_MAPS_API_KEY:
        return "unavailable"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            geo_url = "https://maps.googleapis.com/maps/api/geocode/json"
            geo_started = time.perf_counter()
            geo_resp = await client.get(geo_url, params={"address": place, "key": GOOGLE_MAPS_API_KEY})
            geo_data = geo_resp.json()
            await record_places_usage(
                api_name="geocode",
                google_status=geo_data.get("status"),
                http_status=geo_resp.status_code,
                latency_ms=int((time.perf_counter() - geo_started) * 1000),
                feature="place_classify",
                meta=(place or "")[:256] or None,
            )

            if not geo_data.get("results"):
                await arun(set_cached_place_kind, place, "unresolved")
                await arun(set_cached_region_check, place, False)
                return "unresolved"

            # Prefer locality/town over province/admin centroids (same ranking as
            # lead search) so "Lumbini" caches the town, not Lumbini Province.
            from app.services.lead_generation_service import (
                haversine_distance,
                pick_best_geocode_result,
            )
            result = pick_best_geocode_result(geo_data["results"]) or geo_data["results"][0]

            latlng = result.get("geometry", {}).get("location", {})
            if latlng.get("lat") and latlng.get("lng"):
                bounds = result.get("geometry", {}).get("bounds") or result.get("geometry", {}).get("viewport")
                if bounds:
                    ne, sw = bounds["northeast"], bounds["southwest"]
                    _city_radius = haversine_distance(sw["lat"], sw["lng"], ne["lat"], ne["lng"]) / 2
                else:
                    _city_radius = 5.0
                await arun(set_cached_geocode, place, latlng["lat"], latlng["lng"], _city_radius)

            kind = _classify_geocode_result(place, result)
            await arun(set_cached_place_kind, place, kind)
            await arun(set_cached_region_check, place, kind == "broad_region")
            return kind
    except Exception as e:
        logger.warning("Error classifying place on map (%s): %s", place, e)
        return "unavailable"


async def is_country_name(location: str) -> bool:
    """Check if the provided location is a country name. Result cached 7 days."""
    if not GOOGLE_MAPS_API_KEY:
        return False

    cached = await arun(get_cached_country_check, location)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            geo_url = "https://maps.googleapis.com/maps/api/geocode/json"
            geo_started = time.perf_counter()
            geo_resp = await client.get(geo_url, params={"address": location, "key": GOOGLE_MAPS_API_KEY})
            geo_data = geo_resp.json()
            await record_places_usage(
                api_name="geocode",
                google_status=geo_data.get("status"),
                http_status=geo_resp.status_code,
                latency_ms=int((time.perf_counter() - geo_started) * 1000),
                feature="country_check",
                meta=(location or "")[:256] or None,
            )

            if not geo_data.get("results"):
                await arun(set_cached_country_check, location, False)
                return False

            result = geo_data["results"][0]
            address_components = result.get("address_components", [])
            types = result.get("types", [])

            # Cache geocode coords while we have them — avoids a second Geocoding call later
            latlng = result.get("geometry", {}).get("location", {})
            if latlng.get("lat") and latlng.get("lng"):
                bounds = result.get("geometry", {}).get("bounds") or result.get("geometry", {}).get("viewport")
                if bounds:
                    from app.services.lead_generation_service import haversine_distance
                    ne, sw = bounds["northeast"], bounds["southwest"]
                    _city_radius = haversine_distance(sw["lat"], sw["lng"], ne["lat"], ne["lng"]) / 2
                else:
                    _city_radius = 5.0
                await arun(set_cached_geocode, location, latlng["lat"], latlng["lng"], _city_radius)

            if "country" in types:
                has_locality = any("locality" in comp.get("types", []) for comp in address_components)
                has_admin_area = any("administrative_area_level_1" in comp.get("types", []) for comp in address_components)
                if not has_locality and not has_admin_area:
                    await arun(set_cached_country_check, location, True)
                    return True

            await arun(set_cached_country_check, location, False)
            return False
    except Exception as e:
        logger.warning("Error checking if location is country: %s", e)
        return False


async def is_country_or_region(location: str) -> bool:
    """
    Returns True if the location is too broad to search directly —
    i.e. a country OR an administrative region like a US state, province, etc.
    These require the user to specify a city before we can search.
    """
    return (await classify_place_on_map(location)) == "broad_region"


def _return_place_unresolved(
    context: dict,
    history: list,
    bad_place: str,
    *,
    clear_location: bool = True,
    clear_country: bool = False,
) -> dict:
    """Clear the bad place slot and ask the user for a real map-resolved city."""
    from app.utils.chat_recovery import build_place_unresolved_recovery
    from app.utils.conversation_health import note_progress

    if clear_location:
        context.pop("location", None)
        context.pop("anchor", None)
    if clear_country:
        context.pop("country", None)
    context.pop("confirmed_goal", None)
    context.pop("awaiting_confirmation", None)
    note_progress(context)
    payload = build_place_unresolved_recovery(context, bad_place)
    history.append({"role": "assistant", "message": payload["message"]})
    return payload


def _display_title(value: str) -> str:
    """Title-case UI copy without turning possessive apostrophes into ``'S``."""
    return re.sub(r"(?<=[A-Za-z])'S\b", "'s", value.title())


def build_chat_title(
    industry: str | None,
    location: str | None,
    country: str | None,
    anchor: str | None = None,
) -> str:
    """
    Build a clean, complete, human-readable chat title.
    This function NEVER returns incomplete titles.
    """

    industry = industry.strip() if industry else None
    location = location.strip() if location else None
    country = country.strip() if country else None
    anchor = anchor.strip() if anchor else None

    # Anchor search → "Restaurants near Lakeside, Pokhara" (mirror what the user asked).
    if industry and anchor:
        where = (
            f"{_display_title(anchor)}, {_display_title(location)}"
            if location
            else _display_title(anchor)
        )
        return f"{_display_title(industry)} near {where}"

    if industry and location and country:
        return (
            f"{_display_title(industry)} in {_display_title(location)}, "
            f"{_display_title(country)}"
        )

    if industry and location:
        return f"{_display_title(industry)} in {_display_title(location)}"

    if industry and country:
        return f"{_display_title(industry)} in {_display_title(country)}"

    if industry:
        return f"{_display_title(industry)} Leads"

    if location:
        return f"Businesses in {_display_title(location)}"

    return "Business Leads"

def _format_choice_list(labels: list[str]) -> str:
    """Format candidate labels as a natural human-readable choice list."""
    labels = [label.strip() for label in labels if label and label.strip()]
    if not labels:
        return "the right business type"
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]}, or {labels[1]}"
    return f"{', '.join(labels[:-1])}, or {labels[-1]}"


def build_ambiguous_clarification(industry: str, location: str, candidates: list[dict]) -> str:
    """Build a consistent warm clarification for any ambiguous business keyword."""
    labels = [
        str(candidate.get("label") or "").strip()
        for candidate in candidates
        if str(candidate.get("label") or "").strip()
    ]
    choices = _format_choice_list(labels)
    if not industry or industry.strip().lower() == "this":
        industry = (labels[0].split("/")[0].split()[0] if labels else "this").strip().lower()
    target = f"{industry}-related business leads"
    if location:
        target = f"{target} in {location}"
    location_phrase = f" for {location} leads" if location else ""
    first_label = labels[0] if labels else "one business type"
    second_label = labels[1] if len(labels) > 1 else "another business type"
    location_context = f" in {location}" if location else ""

    variants = [
        (
            f"I can help with {target}. "
            f"Here, {industry} could send the search toward {first_label} or toward {second_label}, and those would produce very different lead lists. "
            "A quick clarification keeps the results focused.\n\n"
            "Which one do you want me to focus on?\n\n"
            f"Do you mean {choices}? Once you choose one, I'll search in that direction."
        ),
        (
            f"Before I pull leads{location_context}, I need to separate the meaning of {industry}. "
            f"{first_label} and {second_label} are not the same market, so confirming this first will save you from noisy results.\n\n"
            "Which market should I use?\n\n"
            f"Should I focus on {choices}? Pick the closest match and I'll continue from there."
        ),
        (
            f"For {target}, the word {industry} is doing more than one job. "
            f"It might mean {first_label}, but it could also mean {second_label}. "
            "I want the lead list to match your actual intent, not just the keyword.\n\n"
            "Which one fits your search best?\n\n"
            f"Choose from {choices}, and I'll move ahead with that exact lead search."
        ),
        (
            f"{_display_title(industry)} is ambiguous in this search{location_phrase}. "
            f"The options I see are {choices}, and mixing them would make the results less useful. "
            "Let me narrow it before searching.\n\n"
            "Which one should I search for?\n\n"
            f"Tell me which option fits, and I'll continue with the right business category."
        ),
        (
            f"Your {industry} search can go in a couple of directions{location_context}. "
            f"One path is {first_label}; another is {second_label}. "
            "I can handle either, but I need the category before I fetch leads.\n\n"
            "Which direction should I take?\n\n"
            f"Should the search target {choices}? Once you answer, I'll keep the results aligned with that choice."
        ),
        (
            f"I can search for {target}, but the keyword needs one more detail first. "
            f"If I treat {industry} as {first_label}, the results will be completely different from {second_label}. "
            "That choice changes the businesses and contacts I should return.\n\n"
            "Which meaning should I use?\n\n"
            f"Do you want {choices}? After you choose, I'll start with the right lead pool."
        ),
        (
            f"That search is possible, but {industry} is not specific enough by itself. "
            f"The lead source could match {first_label}, {second_label}, or another close variation. "
            "Confirming the category first keeps the output useful.\n\n"
            "Which category is closest?\n\n"
            f"Are you after {choices}? I'll use your choice for the search."
        ),
    ]
    variant_key = f"{industry}|{location}|{choices}".lower()
    variant_index = sum(ord(ch) for ch in variant_key) % len(variants)
    return variants[variant_index]


def build_scope_question(industry: str, location: str, scope_family: str | None, siblings: list[str]) -> str:
    """Build a warm deterministic scope question for broad family searches."""
    industry = (industry or "these businesses").strip()
    location = (location or "").strip()
    family = (scope_family or "related business").strip()
    siblings = [s.strip() for s in siblings if s and s.strip()]
    sibling_text = _format_choice_list(siblings)

    target = industry
    if location:
        target = f"{target} in {location}"

    return (
        f"I can search for {target}. The {industry} search can stay narrow, or I can broaden it within the "
        f"{family} family to include related types like {sibling_text}. Broader searches usually find more "
        "businesses, while the narrow option keeps the list closer to your exact request.\n\n"
        "Which version do you want?\n\n"
        f"Should I include those related {family} types too, or search only for {industry}?"
    )


def build_confirm_message(industry: str, location: str, radius_km=None, anchor: str | None = None) -> str:
    """Friendly one-time confirm/refine prompt shown before a fresh search.

    Wording is picked at random from several variants so repeated confirmations don't
    read identically. When the user gave a radius (and/or an anchor), the message
    reflects them and — if no anchor was given — teaches that they can center it on a
    specific area.
    """
    import random

    industry = (industry or "those businesses").strip()
    location = (location or "").strip()
    anchor = (anchor or "").strip()

    if radius_km:
        r = min(max(float(radius_km), 1.0), 15.0)
        capped = " (max)" if float(radius_km) > 15.0 else ""
        if anchor:
            where = f"{anchor}, {location}" if location else anchor
            tails = [
                "Want to refine it — best ones first, or change the industry, city, "
                "area, or radius — or just say go and I'll start searching.",
                "You can tweak it first — best ones, a different area or radius — "
                "or say go and I'll get started.",
                "Happy to adjust anything — industry, area, radius, best-first — "
                "or just say go to kick off the search.",
            ]
        elif location:
            tails = [
                "Want to refine it — center it on a specific area (a neighbourhood or "
                "landmark), get the best ones first, or change the industry, city, or "
                "radius — or just say go and I'll start searching.",
                "You can center it on a neighbourhood or landmark, ask for the best "
                "ones first, or tweak the industry, city, or radius — or say go and "
                "I'll start searching.",
                "If you like, point me at a specific area, ask for best-first, or "
                "change anything — otherwise just say go.",
            ]
            where = f"central {location}"
        else:
            where = "the area"
            tails = [
                "Want to refine it — change the industry, city, or radius — or just say go and I'll start searching.",
                "Tweak the industry, city, or radius if you like — or say go and I'll get searching.",
            ]
        target = f"{industry} within {round(r, 1):g} km{capped} of {where}"
        openers = ["Nice —", "Got it —", "Alright —", "Perfect —"]
        return f"{random.choice(openers)} {target}. {random.choice(tails)}"

    # No radius → several phrasings of the tuned confirm/refine message. Reflect the
    # anchor when one was given ("near Lakeside, Pokhara") so the reply mirrors the user.
    if anchor:
        where = f"{anchor}, {location}" if location else anchor
        target = f"{industry} near {where}"
    else:
        target = f"{industry} in {location}" if location else industry
    variants = [
        f"Nice — {target} it is. Want to refine it first — best ones first · "
        f"change industry/city — or just say go and I'll start searching.",
        f"Got it — {target}. Refine it if you like (best ones first, a different "
        f"industry or city) or say go and I'll start searching.",
        f"Alright — {target}. You can tweak it — best-rated first, another city or "
        f"industry — or just say go to start the search.",
        f"Perfect — {target}. Anything to adjust first (best ones, industry, city)? "
        f"If not, say go and I'll find them.",
        f"{target[:1].upper() + target[1:]} — sounds good. Say go to start searching, or "
        f"refine it first (best ones · different industry or city).",
        f"On it — {target}. Want the best ones first, or a different industry or "
        f"city? Or just say go and I'll start looking.",
    ]
    return random.choice(variants)


async def generate_ambiguous_clarification_stream(
    industry: str, location: str, candidates: list[dict], history: list,
    llm: ChatGoogleGenerativeAI, user_id=None,
):
    """Stream a warm clarification asking which meaning of an ambiguous term the user
    intends. Falls back to build_ambiguous_clarification's deterministic wording if the
    LLM is unavailable."""
    labels = [str(c.get("label") or "").strip() for c in candidates if str(c.get("label") or "").strip()]
    choices = _format_choice_list(labels)
    prompt = f"""{CHAT_PERSONA}

CONVERSATION HISTORY:
{_history_str(history)}

The user's search term "{industry}"{f' (in {location})' if location else ''} is ambiguous — it could mean more than one kind of business. You must ask them to clarify BEFORE searching.

The ONLY valid options are exactly these — do not invent, add, drop, or reword any of them: {choices}

Write a warm, professional message that:
1. Explains that the term could mean different things
2. Lists ALL of these exact options: {choices}
3. Asks which one they mean
4. Does NOT search yet and does NOT invent options beyond the ones listed

Write the message now:"""
    try:
        async for chunk in tracked_astream(
            llm=llm,
            messages=[HumanMessage(content=prompt)],
            provider="gemini",
            model=llm_model_name(llm, fallback=settings.GEMINI_MODEL),
            feature="chat_response",
            user_id=user_id,
            config={"tags": ["human_response"]},
        ):
            if chunk.content:
                from app.utils.chat_stream_sink import content_to_text
                text = content_to_text(chunk.content)
                if text:
                    yield text
    except Exception as e:
        if is_llm_unavailable(e):
            raise LLMUnavailableError() from e
        logger.warning("Error generating ambiguous clarification: %s", e)
        from app.utils.chat_stream_sink import emit_chat_token
        fallback = build_ambiguous_clarification(industry, location, candidates)
        await emit_chat_token(fallback)
        yield fallback


async def generate_ambiguous_clarification(
    industry: str, location: str, candidates: list[dict], history: list,
    llm: ChatGoogleGenerativeAI, user_id=None,
) -> str:
    chunks = [
        piece async for piece in
        generate_ambiguous_clarification_stream(industry, location, candidates, history, llm, user_id=user_id)
    ]
    return "".join(chunks).strip()


async def generate_scope_question_stream(
    industry: str, location: str, scope_family: str | None, siblings: list[str], history: list,
    llm: ChatGoogleGenerativeAI, user_id=None,
):
    """Stream a warm question asking whether to keep a broad-family search narrow or
    widen it to sibling types. Falls back to build_scope_question's deterministic
    wording if the LLM is unavailable."""
    family = (scope_family or "related business").strip()
    siblings_clean = [s.strip() for s in siblings if s and s.strip()]
    sibling_text = _format_choice_list(siblings_clean)
    prompt = f"""{CHAT_PERSONA}

CONVERSATION HISTORY:
{_history_str(history)}

The user is searching for "{industry}"{f' in {location}' if location else ''}. This is a broad "{family}" family that also includes these related types: {sibling_text}.

Write a warm, professional message that:
1. Explains the search can stay narrow (just "{industry}") or broaden to include the related {family} types: {sibling_text}
2. Notes broader searches usually find more businesses
3. Asks which version they want

Write the message now:"""
    try:
        async for chunk in tracked_astream(
            llm=llm,
            messages=[HumanMessage(content=prompt)],
            provider="gemini",
            model=llm_model_name(llm, fallback=settings.GEMINI_MODEL),
            feature="chat_response",
            user_id=user_id,
            config={"tags": ["human_response"]},
        ):
            if chunk.content:
                from app.utils.chat_stream_sink import content_to_text
                text = content_to_text(chunk.content)
                if text:
                    yield text
    except Exception as e:
        if is_llm_unavailable(e):
            raise LLMUnavailableError() from e
        logger.warning("Error generating scope question: %s", e)
        from app.utils.chat_stream_sink import emit_chat_token
        fallback = build_scope_question(industry, location, scope_family, siblings)
        await emit_chat_token(fallback)
        yield fallback


async def generate_scope_question(
    industry: str, location: str, scope_family: str | None, siblings: list[str], history: list,
    llm: ChatGoogleGenerativeAI, user_id=None,
) -> str:
    chunks = [
        piece async for piece in
        generate_scope_question_stream(industry, location, scope_family, siblings, history, llm, user_id=user_id)
    ]
    return "".join(chunks).strip()


async def generate_confirm_message_stream(
    industry: str, location: str, history: list, llm: ChatGoogleGenerativeAI,
    radius_km=None, anchor: str | None = None, user_id=None,
):
    """Stream a one-time confirm/refine prompt before a fresh search. Falls back to
    build_confirm_message's deterministic wording if the LLM is unavailable."""
    industry_clean = (industry or "those businesses").strip()
    location_clean = (location or "").strip()
    anchor_clean = (anchor or "").strip()
    if radius_km:
        r = min(max(float(radius_km), 1.0), 15.0)
        where = f"{anchor_clean}, {location_clean}" if anchor_clean and location_clean else (anchor_clean or location_clean or "the area")
        target_desc = f"{industry_clean} within {round(r, 1):g} km of {where}"
    elif anchor_clean:
        where = f"{anchor_clean}, {location_clean}" if location_clean else anchor_clean
        target_desc = f"{industry_clean} near {where}"
    else:
        target_desc = f"{industry_clean} in {location_clean}" if location_clean else industry_clean
    prompt = f"""{CHAT_PERSONA}

CONVERSATION HISTORY:
{_history_str(history)}

About to search for: {target_desc}.

Write a warm, professional message that:
1. Confirms what will be searched: {target_desc}
2. Mentions they can refine it first (best-rated first, or a different industry, city, or radius)
3. MUST explicitly tell them to say "go" to start the search as-is

Write the message now:"""
    try:
        async for chunk in tracked_astream(
            llm=llm,
            messages=[HumanMessage(content=prompt)],
            provider="gemini",
            model=llm_model_name(llm, fallback=settings.GEMINI_MODEL),
            feature="chat_response",
            user_id=user_id,
            config={"tags": ["human_response"]},
        ):
            if chunk.content:
                from app.utils.chat_stream_sink import content_to_text
                text = content_to_text(chunk.content)
                if text:
                    yield text
    except Exception as e:
        if is_llm_unavailable(e):
            raise LLMUnavailableError() from e
        logger.warning("Error generating confirm message: %s", e)
        from app.utils.chat_stream_sink import emit_chat_token
        fallback = build_confirm_message(industry, location, radius_km, anchor)
        await emit_chat_token(fallback)
        yield fallback


async def generate_confirm_message(
    industry: str, location: str, history: list, llm: ChatGoogleGenerativeAI,
    radius_km=None, anchor: str | None = None, user_id=None,
) -> str:
    chunks = [
        piece async for piece in
        generate_confirm_message_stream(industry, location, history, llm, radius_km=radius_km, anchor=anchor, user_id=user_id)
    ]
    return "".join(chunks).strip()


def build_refine_prompt(industry: str, location: str, context: dict) -> str:
    """Acknowledge a refinement and keep the refine loop open until the user says 'go'."""
    target = f"{industry} in {location}" if location else (industry or "your search")
    quality = context.get("quality")
    note = ""
    if quality in ("top_rated", "premium"):
        note = ", best first"
    elif quality == "budget":
        note = ", budget-friendly"
    return (
        f"Got it — {target}{note}. Refine more — best ones · change industry/city — "
        f"or say go to search."
    )


def infer_ambiguous_industry(message: str, candidates: list[dict], fallback: str | None = None) -> str:
    """Infer the ambiguous keyword when the LLM gives meanings but no industry slot.
    e AI didn't tell us plainly which word was the confusing one. It gave us the meanings, but not the word itself. We need to know the word is "apple" (to remember it, and to say "hey, the word apple is unclear…")."""
    fallback = (fallback or "").strip()
    if fallback and fallback.lower() != "this":
        return fallback

    stopwords = {
        "find", "search", "lead", "leads", "business", "businesses", "in",
        "at", "near", "for", "me", "can", "you", "then", "ok", "okay",
        "the", "a", "an", "and", "or", "related",
    }
    message_words = {
        "".join(ch for ch in word.lower() if ch.isalnum())
        for word in (message or "").split()
    }
    message_words = {word for word in message_words if len(word) > 2 and word not in stopwords}

    label_words: list[str] = []
    for candidate in candidates:
        label = str(candidate.get("label") or "")
        for raw in label.replace("/", " ").replace("-", " ").split():
            word = "".join(ch for ch in raw.lower() if ch.isalnum())
            if len(word) > 2 and word not in stopwords:
                label_words.append(word)

    for word in message_words:
        if word in label_words:
            return word

    return fallback or (next(iter(message_words), "this"))


def is_repeated_ambiguous_query(message: str, industry: str | None, candidates: list[dict]) -> bool:
    """Return True when the user repeats the ambiguous keyword instead of choosing an option."""
    msg = (message or "").strip().lower()
    ind = (industry or "").strip().lower()
    if not msg or not ind or ind not in msg:
        return False

    candidate_text = " ".join(
        str(candidate.get("label") or "").lower()
        for candidate in candidates
    )
    return not any(word in msg for word in candidate_text.split() if len(word) > 4 and word != ind)

def chunked(iterable, size: int):
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]


def _norm_email(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip().lower()
    return v or None


def _norm_name(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip().lower()
    return v or None


async def _split_chargeable_leads(
    db: AsyncSession,
    user_id,
    industry: str,
    leads: list[dict],
) -> tuple[list[dict], int]:
    """Return (chargeable_leads, repeat_count) for this user/industry.

    A lead is considered already delivered if any previous lead_log_leads row for the
    same user+industry matches by:
    - overture_id (preferred), or
    - (email + business_name), or
    - business_name when email is missing.
    """
    if not leads:
        return [], 0

    rows = (
        await db.execute(
            text(
                """
                SELECT ll.overture_id, ll.email, ll.business_name
                FROM lead_log_leads ll
                JOIN lead_logs lg ON lg.id = ll.lead_log_id
                WHERE lg.user_id = CAST(:uid AS uuid)
                  AND lower(coalesce(ll.industry, '')) = lower(:industry)
                """
            ),
            {"uid": str(user_id), "industry": industry or ""},
        )
    ).all()

    seen_overture: set[str] = set()
    seen_email_name: set[tuple[str, str]] = set()
    seen_name_only: set[str] = set()
    for row in rows:
        oid = (str(row.overture_id).strip() if row.overture_id else None)
        email = _norm_email(row.email)
        name = _norm_name(row.business_name)
        if oid:
            seen_overture.add(oid)
        if email and name:
            seen_email_name.add((email, name))
        elif name:
            seen_name_only.add(name)

    chargeable: list[dict] = []
    repeat_count = 0
    for lead in leads:
        oid = (str(lead.get("overture_id")).strip() if lead.get("overture_id") else None)
        email = _norm_email(lead.get("email"))
        name = _norm_name(lead.get("business_name"))
        is_repeat = False
        if oid and oid in seen_overture:
            is_repeat = True
        elif email and name and (email, name) in seen_email_name:
            is_repeat = True
        elif (not email) and name and name in seen_name_only:
            is_repeat = True

        if is_repeat:
            repeat_count += 1
        else:
            chargeable.append(lead)
            if oid:
                seen_overture.add(oid)
            if email and name:
                seen_email_name.add((email, name))
            elif name:
                seen_name_only.add(name)

    return chargeable, repeat_count


async def _knowledge_reply_stream(
    message: str,
    llm: ChatGoogleGenerativeAI,
    user_id=None,
    about_assistant: bool = False,
):
    """Stream an answer about Evecta built only from the product knowledge corpus.

    Always yields a reply. When the corpus does not cover the question — or the index
    is unavailable — that reply is the fixed "not documented" answer, never a
    fall-through to the ungrounded conversational generator: answering a product
    question out of general model knowledge is the exact behaviour this replaces.

    The one exception is a question about the assistant itself. "who are u" retrieves
    nothing (0.66, under the floor) because a three-word query carries too little
    signal, and telling a user who asked who you are that it is not documented is the
    worst answer available. Those fall back to the fixed self-description instead —
    still deterministic, still not the ungrounded generator, which invents details
    (it named itself "Aman" on staging). Questions the corpus *does* answer are
    unaffected: "what is evecta" matches this check too but scores 0.80, so it
    retrieves and stays grounded with its source.
    """
    # Union rather than either alone: the model catches phrasings no pattern list
    # anticipates ("what di u do"), the patterns catch turns where the model left
    # the flag false. A false positive costs only a self-description in place of
    # the non-answer, so the permissive side is the cheap one to be wrong on.
    is_about_assistant = about_assistant or _looks_like_about_assistant(message)
    result = await retrieve(message, about_assistant=is_about_assistant)
    fallback_fired = not result.has_matches
    pieces: list[str] = []
    try:
        if fallback_fired:
            reply = (
                fallback_about_assistant()
                if is_about_assistant
                else build_undocumented_reply()
            )
            # The grounded path reaches the stream sink through tracked_astream; push
            # the fixed reply into the same sink so a fallback turn also arrives live.
            await emit_chat_token(reply)
            pieces.append(reply)
            yield reply
        else:
            async for piece in generate_grounded_answer_stream(
                message, result.chunks, llm, user_id=user_id
            ):
                pieces.append(piece)
                yield piece
            if not "".join(pieces).strip():
                reply = (
                    fallback_about_assistant()
                    if is_about_assistant
                    else build_undocumented_reply()
                )
                await emit_chat_token(reply)
                fallback_fired = True
                yield reply
    finally:
        await log_retrieval(message, result, fallback_fired=fallback_fired, user_id=user_id)


async def _knowledge_reply(
    message: str,
    llm: ChatGoogleGenerativeAI,
    user_id=None,
    about_assistant: bool = False,
) -> str:
    """Non-streaming callers: drain the knowledge stream and return the full text."""
    pieces = [
        piece
        async for piece in _knowledge_reply_stream(
            message, llm, user_id=user_id, about_assistant=about_assistant
        )
    ]
    return "".join(pieces).strip()


# CHAT — LOGGED IN USER
async def _understand_phase(message: str, db: AsyncSession, llm: ChatGoogleGenerativeAI, user: User, context: dict, history: list):
    """Phase 1 of the chat graph — perception + merge.

    Appends the user message, runs the single ``understand()`` call, handles the
    conversational / ambiguity early-exits, and merges resolved slots into ``context``.
    Returns a terminal result dict (greeting / clarify / insufficient-credits) OR
    ``{"_continue": True}`` to advance to the interact phase. Conversation state
    (``context`` + ``history``) is injected by the graph node and mutated in place — the
    checkpointer is the single source of truth (no Redis read for state).
    """
    user_key = str(user.id)

    logger.info(f"[CHAT_LOGGED_IN] User {user.id}: message='{message[:50]}...' | context={context} | history_len={len(history)}")

    from app.services.credit_service import get_pool_balance, repair_missing_subscription_credits

    await db.refresh(user)
    await repair_missing_subscription_credits(db, user)
    balance = await get_pool_balance(db, user.id, "lead")
    if balance <= 0:
        from app.utils.chat_recovery import build_insufficient_credits_recovery

        history.append({"role": "user", "message": message})
        payload = build_insufficient_credits_recovery(context)
        history.append({"role": "assistant", "message": payload["message"]})
        return payload

    try:
        # Add current user message to history
        history.append({"role": "user", "message": message})
        from app.utils.conversation_health import note_user_turn

        note_user_turn(context, message)
        force_location = False
        if _maybe_clear_for_start_over(context, message):
            # Fall through — understand() will see cleared slots and ask fresh.
            pass
        elif _apply_change_city_command(context, message):
            force_location = True
        elif _apply_incomplete_in_query(context, message):
            force_location = True
        from app.utils.conversation_health import scrub_invalid_place_slots

        scrub_invalid_place_slots(context)

        # Long-term memory: load once per turn; inject a small prompt block; never dump all facts.
        memory_bundle = None
        try:
            memory_bundle = await chat_memory.load_memory_bundle(db, user)
            for_greeting = _looks_like_bare_greeting(message) and not message_looks_like_lead_search(message)
            context["_memory_prompt"] = chat_memory.format_memory_for_prompt(
                memory_bundle, for_greeting=for_greeting
            )
            context["_memory_name"] = memory_bundle.preferred_name
            chat_memory.apply_exact_category_from_memory(context, memory_bundle)
        except Exception as e:
            logger.warning("[CHAT_MEMORY] load failed: %s", e)
            memory_bundle = None

        # Explicit reusable prefs ("call me X", "default location is…") — save immediately.
        try:
            await chat_memory.apply_explicit_memory_statements(db, user.id, message)
        except Exception as e:
            logger.warning("[CHAT_MEMORY] explicit save failed: %s", e)

        # Pending "make Kathmandu your default?" offer — yes/no before understand().
        if memory_bundle and memory_bundle.pending_offer:
            try:
                offer_reply = await chat_memory.resolve_memory_offer_reply(
                    db, user.id, message, memory_bundle
                )
            except Exception as e:
                logger.warning("[CHAT_MEMORY] offer resolve failed: %s", e)
                offer_reply = None
            if offer_reply:
                history.append({"role": "assistant", "message": offer_reply})
                context.pop("_memory_prompt", None)
                return {"status": "conversation", "message": offer_reply, "context": context}

        # "Use my company location" — soft confirm from profile, do not invent.
        if memory_bundle and chat_memory.wants_company_location(message):
            company_loc = memory_bundle.company_location or memory_bundle.usual_location_label()
            if company_loc:
                reply = (
                    f"I have your company location as {company_loc}. "
                    "Should I search there?"
                )
                context["_pending_company_location"] = company_loc
                history.append({"role": "assistant", "message": reply})
                context.pop("_memory_prompt", None)
                return {"status": "conversation", "message": reply, "context": context}

        # If user affirms a pending company-location offer, apply it to ChatState.
        pending_company = context.get("_pending_company_location")
        if pending_company and re.fullmatch(
            r"(yes|yep|yeah|yup|sure|ok|okay|please|do it|sounds good)[!.,\s]*",
            (message or "").strip().lower(),
        ):
            context["location"] = pending_company
            context.pop("_pending_company_location", None)

        # Recovery actions / incomplete "industry in" — ask for a city immediately.
        # Skip understand() so the model cannot re-inject the stale garbage location.
        if force_location and context.get("industry") and not (
            context.get("location") or context.get("country")
        ):
            reply = fallback_ask_location(context["industry"])
            context.pop("_force_ask_location", None)
            # Do not escalate to stuck recovery here — Change city / "X in" must
            # produce a real city ask, not the same recovery card again.
            return _pending_ask(context, history, reply, "location", allow_stuck=False)

        # Single structured-output understanding call — replaces the old chain of
        # is_general_question + run_extraction + extract_industry_from_history +
        # suggest_correction x3 and the hand-written merge below it.
        try:
            u = await understand(message, context, history, user_id=getattr(user, "id", None))
        except LLMUnavailableError as e:
            logger.warning("[UNDERSTAND] Gemini unavailable during chat: %s", e)
            return llm_error_result(context)

        # Recover industry/place lost when earlier turns were misclassified or confusing.
        recover_slots_from_history(context, history)
        scrub_invalid_place_slots(context)
        # Brand/product searches often come back as general_question — coerce so slots merge.
        u = coerce_search_understanding(u, message, context)
        # Bare hi/hellooo must greet — don't let a misclassified intent skip the greeting path.
        if _looks_like_bare_greeting(message) and not message_looks_like_lead_search(message):
            u.intent = "greeting"

        pending_candidates = context.get("candidate_meanings") or []
        if context.get("awaiting_clarification") and len(pending_candidates) >= 2:
            pending_industry = context.get("industry")
            # Re-ask ONLY when the LLM ALSO failed to resolve the pick (still ambiguous).
            # Works for ANY ambiguous keyword (apple, amazon, shell, jaguar, …) — both
            # signals are computed dynamically from the actual industry + candidates, none
            # are hardcoded. If the model confidently resolved the pick, trust it and fall
            # through; the strict keyword guard alone would otherwise nag the user with a
            # needless re-ask on a valid choice.
            if u.ambiguous and is_repeated_ambiguous_query(message, pending_industry, pending_candidates):
                pending_industry = infer_ambiguous_industry(message, pending_candidates, pending_industry)
                try:
                    reply = await generate_ambiguous_clarification(
                        pending_industry,
                        context.get("location") or "",
                        pending_candidates,
                        history,
                        llm,
                        user_id=getattr(user, "id", None),
                    )
                except LLMUnavailableError as e:
                    logger.warning("Gemini unavailable for ambiguous clarification: %s", e)
                    return llm_error_result(context)
                context["industry"] = pending_industry
                return _pending_ask(context, history, reply, "clarify")

        if u.ambiguous and len(u.candidate_meanings) >= 2:
            location = u.location or context.get("location") or ""
            candidates = [m.model_dump() for m in u.candidate_meanings]
            # Infer from the FRESH read only: if the model left industry null, the word
            # matcher recovers the keyword from THIS message. Don't fall back to the stale
            # context industry, or switching ambiguous words ("apple" -> "amazon") would
            # keep the old label while showing the new options.
            industry = infer_ambiguous_industry(message, candidates, u.industry)
            context["industry"] = industry
            context["location"] = u.location or context.get("location")
            context["ambiguous"] = True
            context["candidate_meanings"] = candidates
            context["awaiting_clarification"] = True
            try:
                reply = await generate_ambiguous_clarification(
                    industry, location, candidates, history, llm, user_id=getattr(user, "id", None)
                )
            except LLMUnavailableError as e:
                logger.warning("Gemini unavailable for ambiguous clarification: %s", e)
                return llm_error_result(context)
            return _pending_ask(context, history, reply, "clarify")

        # Conversational intents (greeting / general question / negation): answer while
        # PRESERVING the resolved goal — never run a search. Same reply text and
        # "conversation" status as before; only the detection moved into understand().
        # Affirm with no place yet is also conversational — "please"/"sure" must not
        # be geocoded as a city.
        from app.utils.conversation_health import looks_like_valid_place, scrub_invalid_place_slots

        _conversational = u.intent in ("greeting", "general_question", "negate")
        if u.intent == "affirm" and not (
            (u.location and looks_like_valid_place(u.location))
            or (u.country and looks_like_valid_place(u.country))
            or context.get("location")
            or context.get("country")
        ):
            _conversational = True
        if _conversational:
            # Still merge any slots the model filled (e.g. a fact answer that names a
            # place) so conversational turns cannot wipe or skip useful context.
            merge_basic_slots(context, u)
            scrub_invalid_place_slots(context)
            # Never intercept conversational turns with stuck recovery — answer the
            # question (about you / how leads work / thanks) even mid-search flow.
            # Always go through generate_human_response so every conversational turn
            # streams token-by-token for logged-in users, the same way the guest path
            # already does — a static safety net if it is unavailable.
            if _looks_like_about_assistant(message):
                context["_human_reply_hint"] = (
                    "The user asked who you are / about yourself. Answer as Evecta's "
                    "lead-finding assistant: you discover businesses by industry and city, "
                    "then pull contact-ready leads. Then offer a soft next step — start "
                    "with an industry, or tell you what they're selling. Do not skip the "
                    "introduction and jump straight to a dry industry ask."
                )
            elif _looks_like_bare_greeting(message) and memory_bundle:
                context["_human_reply_hint"] = chat_memory.greeting_reply_hint(memory_bundle, context)
            else:
                soft_loc = (
                    chat_memory.soft_location_hint(memory_bundle, context)
                    if memory_bundle
                    else None
                )
                if soft_loc:
                    context["_human_reply_hint"] = soft_loc
                elif context.get("industry") and not (context.get("location") or context.get("country")):
                    context["_human_reply_hint"] = (
                        f"The user did not name a city. Respond naturally to what they said, "
                        f"then ask which city or country to search for {context.get('industry')}."
                    )
            memory_block = context.get("_memory_prompt")
            try:
                if u.intent == "general_question" and u.about_evecta:
                    # A question about Evecta itself: answer only from the approved
                    # corpus. Everything else on this branch — world facts, chit-chat,
                    # third-party companies — keeps the existing ungrounded reply.
                    reply = await _knowledge_reply(
                        message,
                        llm,
                        user_id=getattr(user, "id", None),
                        about_assistant=u.about_assistant,
                    )
                else:
                    reply = await generate_human_response(
                        message, context, [], llm, history,
                        user_id=getattr(user, "id", None),
                        memory_block=memory_block,
                    )
                if not reply or not reply.strip():
                    if _looks_like_about_assistant(message):
                        reply = fallback_about_assistant()
                    elif context.get("industry") and not (context.get("location") or context.get("country")):
                        reply = fallback_ask_city_or_country(context.get("industry"))
                    elif memory_bundle:
                        reply = chat_memory.personalized_greeting_fallback(memory_bundle, context)
                    else:
                        reply = fallback_greeting(context.get("_memory_name"))
            except LLMUnavailableError as e:
                logger.warning("Gemini unavailable for conversational reply: %s", e)
                return llm_error_result(context)
            except Exception as e:
                logger.warning("Error generating human response: %s", e)
                if _looks_like_about_assistant(message):
                    reply = fallback_about_assistant()
                elif context.get("industry") and not (context.get("location") or context.get("country")):
                    reply = fallback_ask_city_or_country(context.get("industry"))
                elif memory_bundle:
                    reply = chat_memory.personalized_greeting_fallback(memory_bundle, context)
                else:
                    reply = fallback_greeting(context.get("_memory_name"))
            finally:
                context.pop("_human_reply_hint", None)
                context.pop("_memory_prompt", None)
            history.append({"role": "assistant", "message": reply})
            # IMPORTANT: Preserve context - don't clear it for conversational turns
            return {"status": "conversation", "message": reply, "context": context}

        # lead_search / refinement / affirm: merge the resolved slots into context.
        # understand() already carried unchanged slots forward and spelling-normalized
        # the values; the guards below only protect against a missing field, and a new
        # city without a country clears any stale country ("Mumbai" != "Mumbai, Nepal").
        _new_city = bool(u.location) and (u.location or "").strip().lower() != (context.get("location") or "").strip().lower()
        _prev_industry = (context.get("industry") or "").strip().lower()

        context["industry"] = (
            sanitize_industry_label(u.industry, context.get("industry"))
            or context.get("industry")
        )
        # Places come from the understanding model only — never from "any short reply
        # after we asked for a city" heuristics (that geocoded words like "please").
        _llm_place = False
        if u.location and looks_like_valid_place(u.location):
            context["location"] = u.location
            _llm_place = True
        if u.country and looks_like_valid_place(u.country):
            context["country"] = u.country
            _llm_place = True
        elif _new_city and u.location and looks_like_valid_place(u.location):
            context["country"] = None
        scrub_invalid_place_slots(context)
        context["_llm_endorsed_place"] = _llm_place and bool(
            context.get("location") or context.get("country")
        )
        _resolved_industry = (context.get("industry") or "").strip().lower()
        _industry_changed = bool(_resolved_industry) and _resolved_industry != _prev_industry
        # "only / just / exactly" — the user wants the bare industry, no category
        # expansion. Detect from the RAW message: the understand LLM strips the marker
        # (and even ADDS sibling terms like cafe), so it never reaches the resolver.
        _tokens = set((message or "").lower().replace(",", " ").replace(".", " ").split())
        _strict_narrow = bool(_tokens.intersection(OVERTURE_STRICT_INTENT_MARKERS)) or (
            u.scope_choice == "narrow"
        ) or bool(context.get("_memory_exact_category"))
        # Explicit "only/just X" → exact category only. Always win over sibling expansions
        # even when industry/search_terms were already set on a prior turn.
        if _strict_narrow:
            context["strict_intent"] = True
            context["search_terms"] = normalize_search_terms(context.get("industry"), None)
            context["_narrowed_this_turn"] = True
        elif u.search_terms or _industry_changed or not context.get("search_terms"):
            # Recompute search_terms when the user gives new terms, changes industry, or has
            # none yet. Otherwise PRESERVE the resolved terms — so a scope-expanded family
            # (e.g. education → preschool, college) survives the confirm "go" turn instead of
            # collapsing back to the bare industry leaf.
            if context.get("strict_intent") and not _industry_changed:
                # City/follow-up after "only hotels" must not re-expand into siblings.
                context["search_terms"] = normalize_search_terms(context.get("industry"), None)
            else:
                context["search_terms"] = normalize_search_terms(context.get("industry"), u.search_terms)
                context["strict_intent"] = False
        # captured for later steps / silent-now features (not acted on in Step 1)
        context["quality"] = u.quality or context.get("quality")
        context["ambiguous"] = u.ambiguous
        if not u.ambiguous:
            # the user resolved (or there was never) ambiguity → drop the pending flag
            context.pop("awaiting_clarification", None)
        context["candidate_meanings"] = [m.model_dump() for m in u.candidate_meanings]
        # scope_family/scope_siblings: understand() flags these only for an explicitly
        # broad family ("accommodation", "fitness businesses") — not a specific category
        # like hotels. On a follow-up turn that only supplies the city, understand()
        # won't re-flag them, so carry the already-detected scope forward while the
        # industry is unchanged. An explicit "only/just" (the user narrowed) or an
        # industry change clears it.
        if u.scope_family and not _strict_narrow:
            context["scope_family"] = u.scope_family
            context["scope_siblings"] = list(u.scope_siblings or [])
        elif _industry_changed or _strict_narrow or not _resolved_industry:
            context.pop("scope_family", None)
            context.pop("scope_siblings", None)
            if _industry_changed or _strict_narrow:
                # A NEW industry must not inherit the previous one's pending scope question
                # or sibling terms (S5: hotels -> restaurants must not search motels/resorts).
                # Explicit narrow also cancels any pending family-scope ask.
                context.pop("awaiting_scope", None)
                context.pop("scope_terms", None)
        # else: same industry, no new scope this turn → keep the scope already detected.

        # Radius (city-independent) carries forward; anchor is a point WITHIN the city, so
        # a city change clears a stale anchor unless the user names a new one this turn.
        context["radius_km"] = u.radius_km or context.get("radius_km")
        if u.anchor:
            context["anchor"] = u.anchor
        elif _new_city:
            context.pop("anchor", None)

        logger.info(
            "[UNDERSTAND] message=%r | intent=%s | industry=%r | location=%r | country=%r | search_terms=%r | radius_km=%r | anchor=%r | ambiguous=%s",
            message, u.intent, context.get("industry"), context.get("location"),
            context.get("country"), context.get("search_terms"),
            context.get("radius_km"), context.get("anchor"), u.ambiguous,
        )

        # Carry the Understanding fields the interact phase needs (the object itself
        # is non-serializable, so it must not cross the node boundary)
        context["_intent"] = u.intent
        context["_scope_choice"] = "narrow" if _strict_narrow else u.scope_choice
        context["_new_city"] = _new_city     # interact node: re-ask scope on a city change
        return {"_continue": True}
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


async def _interact_phase(message: str, db: AsyncSession, llm: ChatGoogleGenerativeAI, user: User, context: dict, history: list):
    """Phase 2 of the chat graph — slot-fill + clarify / scope / confirm gates.

    Returns a terminal result dict (a pending question) OR ``{"_continue": True}`` to
    advance to the search phase. State is injected by the node and mutated in place.
    """
    user_key = str(user.id)
    try:
        # Last-chance recovery before asking again — stops industry↔location loops when
        # the LLM forgot a slot the user already gave in a confusing chat.
        recover_slots_from_history(context, history)

        from app.utils.conversation_health import (
            is_conversation_stuck,
            looks_like_valid_place,
            note_progress,
            scrub_invalid_place_slots,
        )

        # Drop chat-garbage places before any ask/stuck decision (and after history
        # backfill, which must not reintroduce invalid cities).
        scrubbed_place = scrub_invalid_place_slots(context)
        if scrubbed_place:
            note_progress(context)

        # Conversational flow: Industry → (City OR Country → City)
        has_industry = "industry" in context and context.get("industry")
        has_country = "country" in context and context.get("country")
        has_location = "location" in context and context.get("location")

        last_assistant = ""
        for entry in reversed(history or []):
            if entry.get("role") == "assistant":
                last_assistant = entry.get("message") or ""
                break

        # Only accept the CURRENT message as industry when we just asked for industry
        # (never when this same turn supplied the place — that caused Malaysia→industry).
        if (
            not has_industry
            and (has_country or has_location)
            and message
            and _ASKED_INDUSTRY_RE.search(last_assistant)
            and not _looks_like_info_question(message)
            and len((message or "").split()) <= 8
        ):
            context["industry"] = (message or "").strip()
            has_industry = True
            note_progress(context)

        # User restated / switched category while we were asking for a city.
        # Keep a clean category only — never store chat fragments like "i want to hotels".
        if (
            has_industry
            and not has_country
            and not has_location
            and message
            and _ASKED_PLACE_RE.search(last_assistant)
            and _looks_like_industry_switch(message)
        ):
            phrase = sanitize_industry_label(
                _industry_phrase_from_search_message(message) or message,
                context.get("industry"),
            )
            if phrase:
                context["industry"] = phrase
                has_industry = True
                note_progress(context)

        # Do NOT promote the raw user message into country/location just because we
        # asked for a city. Place slots come from understand() only; otherwise chat
        # words get geocoded ("please" → map error). If we still need a place, Step 2
        # asks again in a human way.

        # After applying this turn's slot answer, break loops that are still stuck.
        # If we only need a city, ask for it instead of repeating the stuck card.
        if is_conversation_stuck(context):
            if has_industry and not has_location and not has_country:
                note_progress(context)
            else:
                return _return_stuck_recovery(context, history)

        # Step 1: Ask for industry if missing
        if not has_industry:
            from app.utils.chat_recovery import build_memory_lost_recovery

            # Short affirm / continuation with no slots → conversation memory was lost.
            _msg_l = (message or "").strip().lower()
            if _msg_l in {
                "yes", "y", "ok", "okay", "sure", "yep", "yeah", "continue", "again",
                "retry", "try again", "go ahead", "do it",
            } or (len(_msg_l.split()) <= 2 and _msg_l.endswith("again")):
                payload = build_memory_lost_recovery(context)
                history.append({"role": "assistant", "message": payload["message"]})
                return payload
            try:
                reply = await generate_human_response(message, context, [], llm, history, user_id=getattr(user, "id", None))
                if not reply or not reply.strip():
                    reply = fallback_ask_industry()
            except LLMUnavailableError as e:
                logger.error("Gemini unavailable while asking for industry: %s", e)
                return llm_error_result(context, exc=e)
            except Exception as e:
                logger.error(f"Error generating human response: {e}")
                reply = fallback_ask_industry()
            return _pending_ask(context, history, reply, "industry")

        # Step 2: Ask for location when industry is known but place is not.
        # Prefer a human LLM reply (acknowledge + ask). Fixed copy is only the
        # safety net — free-form replies must still use the sanitized industry label
        # and must not invent/echo a garbage city from earlier chat.
        if has_industry and not has_location and not has_country:
            industry_label = sanitize_industry_label(context.get("industry")) or "those businesses"
            context["industry"] = industry_label
            narrowed = bool(context.pop("_narrowed_this_turn", False))
            if narrowed:
                context["_human_reply_hint"] = (
                    f"Acknowledge_change: exact category restricted to {industry_label} only "
                    f"(no related types). Ask_field: location (city or country). "
                    f"Do not repeat a prior identical city ask without acknowledging the narrow scope."
                )
                fallback = fallback_ack_narrow_ask_location(industry_label)
            else:
                context["_human_reply_hint"] = (
                    f"Acknowledge that you will search for {industry_label}, then ask "
                    "which city or country to search. Vary the wording — do not repeat "
                    "an identical previous ask if the user just restated the industry."
                )
                fallback = fallback_ask_city_or_country(industry_label)
            try:
                reply = await generate_human_response(
                    message, context, [], llm, history, user_id=getattr(user, "id", None),
                )
                if not reply or not reply.strip():
                    reply = fallback
                else:
                    lower = reply.lower()
                    # Reject replies that re-injected chat filler as the industry label.
                    if "i want" in lower or "want to find" in lower:
                        reply = fallback
                    elif not any(w in lower for w in ("city", "country", "location", "where")):
                        reply = fallback
            except LLMUnavailableError as e:
                logger.error("Gemini unavailable while asking for location: %s", e)
                return llm_error_result(context, exc=e)
            except Exception as e:
                logger.error(f"Error generating human response: {e}")
                reply = fallback
            finally:
                context.pop("_human_reply_hint", None)
            return _pending_ask(context, history, reply, "location")
        context.pop("_narrowed_this_turn", None)

        # Step 3: If only country is provided (no city), validate on the map first.
        if has_industry and has_country and not has_location:
            country_name = context.get("country")
            place_kind = await classify_place_on_map(country_name)
            if place_kind == "unresolved":
                # Only show a map error when understand() thought this was a place.
                # Otherwise clear and re-ask — never turn chat into a geocode failure.
                if context.pop("_llm_endorsed_place", False):
                    return _return_place_unresolved(
                        context,
                        history,
                        str(country_name),
                        clear_location=False,
                        clear_country=True,
                    )
                context.pop("country", None)
                has_country = False
                return _pending_ask(
                    context,
                    history,
                    fallback_ask_city_or_country(context.get("industry")),
                    "location",
                )
            if place_kind == "broad_region":
                suggestion_msg = await generate_suggestions_with_verification(
                    context["industry"],
                    country_name,
                    context,
                    history,
                    llm,
                    search_terms=normalize_search_terms(context["industry"], context.get("search_terms")),
                    user_id=getattr(user, "id", None),
                )
                context.pop("_llm_endorsed_place", None)
                return _pending_ask(context, history, suggestion_msg, "city_suggest")
            # city-sized country (or Maps unavailable) — treat as the search location
            context["location"] = country_name
            context["country"] = None
            has_country = False
            has_location = True
            context.pop("_llm_endorsed_place", None)

        # Validate location on the map, and reject countries/states that need a city.
        if has_location:
            loc = context["location"]
            query = loc
            if context.get("country"):
                query = f"{loc}, {context['country']}"
            place_kind = await classify_place_on_map(query)
            # Combined "city, country" sometimes fails while bare city succeeds.
            if place_kind == "unresolved" and query != loc:
                place_kind = await classify_place_on_map(loc)
            if place_kind == "unresolved":
                if context.pop("_llm_endorsed_place", False):
                    return _return_place_unresolved(
                        context,
                        history,
                        str(loc),
                        clear_location=True,
                        clear_country=False,
                    )
                context.pop("location", None)
                context.pop("country", None)
                return _pending_ask(
                    context,
                    history,
                    fallback_ask_city_or_country(context.get("industry")),
                    "location",
                )
            context.pop("_llm_endorsed_place", None)
            if place_kind == "broad_region":
                # Treat state/country as a region and ask for a specific city
                context["country"] = context["location"]
                context["location"] = None
                suggestion_msg = await generate_suggestions_with_verification(
                    context["industry"],
                    context["country"],
                    context,
                    history,
                    llm,
                    search_terms=normalize_search_terms(context["industry"], context.get("search_terms")),
                    user_id=getattr(user, "id", None),
                )
                return _pending_ask(context, history, suggestion_msg, "city_suggest")

        # Need both industry and a place before searching.
        if not has_location:
            return _pending_ask(
                context,
                history,
                fallback_ask_city_or_country(context.get("industry")),
                "location",
            )

        # Build search location string
        search_location = context["location"]
        original_location = context["location"]
        if context.get("country") and context["location"]:
            search_location = f"{context['location']}, {context['country']}"

        industry_key = context["industry"]
        search_terms = normalize_search_terms(industry_key, context.get("search_terms"))
        context["search_terms"] = search_terms

        # Disambiguation — ONLY for genuinely ambiguous industries (apple/amazon/...).
        # Non-ambiguous queries skip this entirely, so their flow is unchanged.
        # We offer the model's candidate meanings directly (no Places pre-check — leads
        # come from Overture; if the chosen meaning has no results, the existing
        # no-results suggestion path handles it after the search).
        if context.get("ambiguous"):
            candidates = context.get("candidate_meanings") or []
            if len(candidates) >= 2:
                try:
                    reply = await generate_ambiguous_clarification(
                        industry_key, original_location, candidates, history, llm, user_id=getattr(user, "id", None)
                    )
                except LLMUnavailableError as e:
                    logger.warning("Gemini unavailable for ambiguous clarification: %s", e)
                    return llm_error_result(context)
                context["awaiting_clarification"] = True
                return _pending_ask(context, history, reply, "clarify")
            # fewer than 2 meanings → nothing to disambiguate; search normally.
            context["ambiguous"] = False
            context.pop("candidate_meanings", None)

        # ask_scope — explicitly broad family terms only (e.g. accommodation, fitness
        # businesses). Specific categories (hotels, yoga studios) skip this. The family
        # label + siblings come from understand() (no hardcoded list).
        if context.get("scope_family") and context.get("scope_siblings") \
                and not context.get("awaiting_scope") and not context.get("awaiting_clarification"):
            siblings = [s for s in context["scope_siblings"] if s]
            context["awaiting_scope"] = True
            context["scope_terms"] = siblings   # remembered for the resolution turn
            try:
                reply = await generate_scope_question(
                    industry_key, original_location, context.get("scope_family"), siblings,
                    history, llm, user_id=getattr(user, "id", None),
                )
            except LLMUnavailableError as e:
                logger.warning("Gemini unavailable for scope question: %s", e)
                return llm_error_result(context)
            return _pending_ask(context, history, reply, "scope")
        elif context.get("awaiting_scope"):
            _scope_ans = context.get("_scope_choice")
            if context.get("_new_city") and _scope_ans not in ("all", "narrow"):
                # User changed the city without answering the scope question → re-ask it
                # for the NEW city rather than silently defaulting to "all" (S10).
                siblings = [s for s in (context.get("scope_terms") or []) if s]
                try:
                    reply = await generate_scope_question(
                        industry_key, original_location, context.get("scope_family"), siblings,
                        history, llm, user_id=getattr(user, "id", None),
                    )
                except LLMUnavailableError as e:
                    logger.warning("Gemini unavailable for scope question: %s", e)
                    return llm_error_result(context)
                return _pending_ask(context, history, reply, "scope")
            if _scope_ans == "narrow":
                search_terms = normalize_search_terms(industry_key, None)               # just the leaf
            else:  # "all" or unclear → include the family (recall-first default)
                search_terms = normalize_search_terms(
                    industry_key,
                    [industry_key, *(context.get("scope_terms") or [])],
                )
            context["search_terms"] = search_terms
            for _k in ("awaiting_scope", "scope_terms", "scope_family", "scope_siblings"):
                context.pop(_k, None)

        # One confirmation before a fresh search. After the user replies once (go/yes or a
        # refinement like "best ones"), run the search — no second confirm loop.
        goal_key = f"{(industry_key or '').lower()}|{(search_location or '').lower()}"
        _proceed = context.get("_intent") == "affirm" or message.strip().lower().rstrip("!.") in {
            "go", "go ahead", "search", "search now", "search it", "find them",
            "done", "that's all", "thats all", "proceed", "yes", "yep", "ok", "okay", "sure",
        }
        _intent = context.get("_intent")
        if context.get("awaiting_confirmation"):
            if _proceed or _intent in ("refinement", "lead_search"):
                context.pop("awaiting_confirmation", None)
                context["confirmed_goal"] = goal_key
            else:
                # Still waiting for go or a refinement — re-show the one-time confirm.
                try:
                    reply = await generate_confirm_message(
                        industry_key, original_location, history, llm,
                        radius_km=context.get("radius_km"), anchor=context.get("anchor"),
                        user_id=getattr(user, "id", None),
                    )
                except LLMUnavailableError as e:
                    logger.warning("Gemini unavailable for confirm message: %s", e)
                    return llm_error_result(context)
                return _pending_ask(context, history, reply, "confirm")
        elif context.get("confirmed_goal") != goal_key:
            context["awaiting_confirmation"] = True
            try:
                reply = await generate_confirm_message(
                    industry_key, original_location, history, llm,
                    radius_km=context.get("radius_km"), anchor=context.get("anchor"),
                    user_id=getattr(user, "id", None),
                )
            except LLMUnavailableError as e:
                logger.warning("Gemini unavailable for confirm message: %s", e)
                return llm_error_result(context)
            return _pending_ask(context, history, reply, "confirm")
        else:
            context["confirmed_goal"] = goal_key

        note_progress(context)
        return {"_continue": True}
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


async def _recent_matching_log_id(db, user_id, industry: str, city: str) -> str | None:
    """Most recent search (LeadLog) by this user for (industry, city) that actually
    delivered leads — the log the 'See my N' link deep-links to (GEO-4).

    Matches on chat_title, like the old Tier-1 discovery. Returns None if no
    matching *successful* search exists (empty/failed gathering logs do not count),
    so first-time warm fetches of a small market still deliver leads.
    """
    city_first = (city or "").split(",")[0].strip()
    row = (
        await db.execute(
            text(
                """
                SELECT lg.id FROM lead_logs lg
                WHERE lg.user_id = CAST(:uid AS uuid)
                  AND lg.chat_title ILIKE :ind AND lg.chat_title ILIKE :city
                  AND EXISTS (
                      SELECT 1 FROM lead_log_leads ll
                      WHERE ll.lead_log_id = lg.id
                  )
                ORDER BY lg.created_at DESC
                LIMIT 1
                """
            ),
            {"uid": str(user_id), "ind": f"%{industry}%", "city": f"%{city_first}%"},
        )
    ).first()
    return str(row[0]) if row else None


async def _fill_exhaustion_nearby(error_info, industry_key, context, history, llm, search_terms):
    """Populate error_info['nearby'] with up to 3 real neighbouring cities for the
    exhaustion recovery actions. Cache-detected cities (we know they have leads)
    come first, then LLM geographic suggestions top it up to 3."""
    existing = {
        n["city"]: n.get("available", 0)
        for n in (error_info.get("nearby") or []) if n.get("city")
    }
    llm_cities = []
    try:
        llm_cities = await _verified_city_suggestions(
            industry_key, context.get("country"), context, history, llm, search_terms, limit=3
        )
    except Exception:
        logger.warning("[EXHAUST] nearby city suggestion failed", exc_info=True)
    ordered = list(dict.fromkeys(list(existing.keys()) + list(llm_cities)))[:3]
    error_info["nearby"] = [{"city": c, "available": existing.get(c, 0)} for c in ordered]


def _exhaustion_response(error_info, industry_display, city_display, plan_limit, context, log_id=None):
    """GEO-4: build the 'you've pulled them all' response from get_leads_overture's
    exhaustion signal. Nearby counts are plan-capped (deliverable = min(available,
    plan_limit)). log_id deep-links to the user's most recent matching search log so
    they can view the leads they already pulled (may be None if that search was pruned)."""
    from app.utils.chat_recovery import build_exhaustion_recovery

    nearby = []
    for n in (error_info.get("nearby") or []):
        avail = int(n.get("available", 0))
        nearby.append({
            "city": n.get("city"),
            "available": avail,
            "deliverable": min(avail, plan_limit),
        })
    return build_exhaustion_recovery(
        context,
        industry_display=industry_display,
        city_display=city_display,
        nearby=nearby,
        log_id=log_id,
    )


async def _search_phase(message: str, db: AsyncSession, llm: ChatGoogleGenerativeAI, user: User, background_tasks: BackgroundTasks, context: dict, history: list):
    """Phase 3 of the chat graph — the full search + persistence pipeline (DB-first →
    Overture → credits → ranking → persistence → enrichment). Returns the final result
    dict. State is injected by the node and mutated in place."""
    user_key = str(user.id)
    try:
        # Re-derive the per-search locals from context (they were built in the interact
        # phase, which is now a separate node).
        industry_key = context["industry"]
        search_terms = normalize_search_terms(industry_key, context.get("search_terms"))
        # Strict "only restaurants": drop the LLM's category expansion (cafe/eatery) so the
        # resolver matches the industry alone. Captured at understand time because the LLM
        # strips the "only" marker (context['strict_intent']).
        if context.get("strict_intent"):
            search_terms = [industry_key]
        original_location = context["location"]
        search_location = context["location"]
        if context.get("country") and context["location"]:
            search_location = f"{context['location']}, {context['country']}"
        from app.utils.enrichment_semaphores import get_enrichment_semaphores
        semaphores = get_enrichment_semaphores()

        # Radius/anchor (chat-intelligence): center the search on the anchor (a point
        # within the city) when the user named one, else the city center.
        _anchor = (context.get("anchor") or "").strip()
        center_location = f"{_anchor}, {search_location}" if _anchor else search_location

        # Step 2a: DB first — always free, no API cost.
        # Do this BEFORE any Google API call so we know exactly how many leads we
        # still need. Cap by both plan.leads_per_search and credit balance (1 credit
        # per lead) so a mismatched users.plan row cannot trigger a charge larger
        # than balance (e.g. plan=growth, balance=100 → fetch at most 100, not 300).
        from app.core.plans import PLANS, DEFAULT_PLAN
        from app.services.credit_service import (
            get_pool_balance,
            repair_missing_subscription_credits,
        )

        await db.refresh(user)
        await repair_missing_subscription_credits(db, user)

        raw_plan = (getattr(user, "plan", None) or DEFAULT_PLAN).strip().lower()
        user_plan_key = raw_plan if raw_plan in PLANS else DEFAULT_PLAN
        if user_plan_key != raw_plan:
            logger.warning(
                "[LEAD FETCH] Unknown user.plan=%r — using %r for limits",
                getattr(user, "plan", None),
                user_plan_key,
            )

        _PLAN_GRID = {
            "starter": (True,  5.0),
            "growth":  (True,  6.0),
            "scale":   (True,  7.0),
        }
        _use_grid, _plan_max_radius = _PLAN_GRID.get(user_plan_key, (False, 5.0))
        # A user-requested radius wins (clamped to [1, 15] km); else the plan radius.
        _req_radius = context.get("radius_km")
        _search_radius = min(max(float(_req_radius), 1.0), 15.0) if _req_radius else _plan_max_radius

        leads_limit = PLANS[user_plan_key]["leads_per_search"]
        balance = await get_pool_balance(db, user.id, "lead")
        if balance <= 0:
            from app.utils.chat_recovery import build_insufficient_credits_recovery

            payload = build_insufficient_credits_recovery(context)
            history.append({"role": "assistant", "message": payload["message"]})
            return payload

        effective_leads_limit = min(leads_limit, balance)
        if effective_leads_limit < leads_limit:
            logger.info(
                "[LEAD FETCH] Capping batch to %s leads (plan_limit=%s, balance=%s)",
                effective_leads_limit,
                leads_limit,
                balance,
            )

        # Reuse comes from overture_places (the master) via get_leads_overture below —
        # a warm area IS the reuse. lead_log_leads is written for the results page but
        # NEVER read for reuse (Phase 4.1: single source, no Tier-1 lead_log_leads scan).
        error_info = {"no_results": False}
        leads: list = []
        logger.info(
            f"[LEAD FETCH] industry={industry_key}, search_terms={search_terms}, "
            f"location={context['location']} | effective_limit={effective_leads_limit}"
        )

        # We need the full batch from Overture (no DB pre-fill anymore).
        remaining = effective_leads_limit - len(leads)
        api_count = 0
        if remaining > 0:
            # Fetch exactly what we need — no 3x buffer.
            # Place Details is called for every candidate; fetching 3x more
            # than needed wastes Detail calls on places already in the DB.
            # The cache stores the full result set, so future requests are free.
            api_fetch_limit = remaining

            # Single Redis GET — reuse result throughout this block (fixes double-fetch).
            # In Overture mode the Redis lead-cache is bypassed: PostGIS (overture_places)
            # is the cache, and a stale Redis entry (e.g. from a prior Google-mode run)
            # must not shadow Overture and serve wrong leads.
            if settings.LEAD_SOURCE == "overture":
                cached_leads_data = None
            else:
                cached_leads_data = await arun(get_cached_leads, industry_key, search_location)
            cache_hit = cached_leads_data is not None

            if cache_hit:
                # Warm cache: return data directly — no lock, no rate-limit, no qcheck.
                api_leads = cached_leads_data[:api_fetch_limit]
                error_info = {"no_results": False}
                logger.info(f"[LEAD FETCH] Cache hit — {len(api_leads)} leads served, 0 API calls.")
            else:
                # Cold cache: rate-limit → qcheck → lock → Google API.
                allowed, remaining_quota = await arun(check_user_search_rate, str(user.id))
                if not allowed:
                    logger.warning(f"[RATE LIMIT] User {user.id} exceeded hourly search quota.")
                    if leads:
                        logger.info(f"[RATE LIMIT] Serving {len(leads)} DB leads despite quota exhaustion.")
                        api_leads = []
                    else:
                        from app.utils.chat_recovery import build_rate_limited_recovery

                        payload = build_rate_limited_recovery(context)
                        history.append({"role": "assistant", "message": payload["message"]})
                        return payload
                else:
                    logger.info(f"[RATE LIMIT] User {user.id} quota: {remaining_quota} fresh searches remaining this hour.")

                    # Distributed lock: one request fetches, the rest poll the cache.
                    # qcheck is removed — get_leads already does geocode+nearby internally,
                    # so a separate preflight would duplicate the first Nearby Search call.
                    # No-results and geocoding-failed cases are handled after get_leads returns.
                    lock_acquired = await arun(acquire_search_lock, industry_key, search_location, ttl=45)
                    if not lock_acquired:
                        logger.info(f"[LEAD FETCH] Search lock held by another request — polling cache...")
                        api_leads = None
                        for _ in range(60):  # poll up to 30 s (60 × 0.5 s)
                            await asyncio.sleep(0.5)
                            api_leads = await arun(get_cached_leads, industry_key, search_location)
                            if api_leads:
                                break
                        if api_leads:
                            api_leads = api_leads[:api_fetch_limit]
                            error_info = {"no_results": False}
                            logger.info(f"[LEAD FETCH] Got {len(api_leads)} leads from cache after lock wait.")
                        else:
                            api_leads, error_info = [], {"no_results": True}
                    else:
                        try:
                            if settings.LEAD_SOURCE == "overture":
                                # Overture path: PostGIS cache is the source of leads.
                                # load_if_cold=False → warm areas query instantly; cold
                                # areas are loaded in the BACKGROUND (Celery) so the
                                # request never blocks on the ~30s+ S3 pull.
                                api_leads, error_info = await get_leads_overture(
                                    industry_key, center_location,
                                    search_radius_km=_search_radius,
                                    limit=api_fetch_limit,
                                    search_terms=search_terms,
                                    db=db,
                                    load_if_cold=False,
                                    # Mode A (city-dominant + spillover cap) when the user
                                    # named only a city; Mode B (pure distance) when they
                                    # anchored on a specific spot. Exclude leads this user
                                    # already pulled for this industry (fresh on repeat).
                                    city_for_tier=(None if _anchor else search_location),
                                    user_id=user.id,
                                )
                            else:
                                api_leads, error_info = await get_leads(
                                    industry_key, center_location,
                                    search_terms=search_terms,
                                    use_grid_search=_use_grid,
                                    search_radius_km=_search_radius,
                                    limit=api_fetch_limit,
                                    semaphores=semaphores,
                                )
                            await arun(increment_user_search_rate, str(user.id))
                        finally:
                            await arun(release_search_lock, industry_key, search_location)

                    # Overture cold area: create an empty LeadLog NOW and let a
                    # background task load the area + fill it. We return the log_id so
                    # the frontend's existing lead-polling shows the loader and renders
                    # the table automatically when leads land — no re-search, no block.
                    if (
                        settings.LEAD_SOURCE == "overture"
                        and error_info.get("overture_cold")
                        and not leads
                    ):
                        now = datetime.now(timezone.utc)
                        cold_log = LeadLog(
                            chat_title=build_chat_title(
                                industry=context.get("industry"),
                                location=context.get("location"),
                                country=context.get("country"),
                                anchor=context.get("anchor"),
                            ),
                            query=message,
                            user_id=user.id,
                            is_read=False,
                            status="gathering",   # background load in progress; task resolves this
                            created_at=now,
                            updated_at=now,
                        )
                        db.add(cold_log)
                        await db.flush()
                        await db.commit()

                        from app.tasks.overture_tasks import load_and_fill_overture_task
                        try:
                            load_and_fill_overture_task.delay(
                                str(cold_log.id), str(user.id), industry_key, center_location,
                                _search_radius, search_terms, api_fetch_limit,
                                (None if _anchor else search_location),
                            )
                            logger.info(
                                "[OVERTURE] Enqueued load+fill for %s in %s (log_id=%s)",
                                industry_key, search_location, cold_log.id,
                            )
                        except Exception:
                            logger.error("[OVERTURE] Failed to enqueue load+fill task", exc_info=True)

                        gathering_msg = (
                            f"This looks like a new area for me — I'm gathering "
                            f"{context.get('industry') or industry_key} leads in "
                            f"{original_location}. It takes about a minute; they'll "
                            f"appear here automatically when they're ready."
                        )
                        ai_msg = {"role": "assistant", "message": gathering_msg}
                        history.append(ai_msg)
                        return {
                            "status": "gathering",
                            "message": gathering_msg,
                            "context": context,
                            "log_id": str(cold_log.id),
                        }

                    # §6.11: user drained a cached area that still has more upstream.
                    # Same machinery as the cold-load above — a gathering log + a
                    # background task that pulls the NEXT batch into the shared cache
                    # then fills the log. Must precede the exhaustion message below
                    # (both fire on empty leads; the top-up wins when more exists).
                    if (
                        settings.LEAD_SOURCE == "overture"
                        and error_info.get("overture_topup")
                        and not leads
                    ):
                        now = datetime.now(timezone.utc)
                        topup_log = LeadLog(
                            chat_title=build_chat_title(
                                industry=context.get("industry"),
                                location=context.get("location"),
                                country=context.get("country"),
                                anchor=context.get("anchor"),
                            ),
                            query=message,
                            user_id=user.id,
                            is_read=False,
                            status="gathering",
                            created_at=now,
                            updated_at=now,
                        )
                        db.add(topup_log)
                        await db.flush()
                        await db.commit()

                        from app.tasks.overture_tasks import load_and_fill_overture_task
                        try:
                            load_and_fill_overture_task.delay(
                                str(topup_log.id), str(user.id), industry_key, center_location,
                                _search_radius, search_terms, api_fetch_limit,
                                (None if _anchor else search_location),
                                True,   # topup: pull the next batch before filling
                            )
                            logger.info(
                                "[OVERTURE] Enqueued top-up load+fill for %s in %s (log_id=%s)",
                                industry_key, search_location, topup_log.id,
                            )
                        except Exception:
                            logger.error("[OVERTURE] Failed to enqueue top-up task", exc_info=True)

                        topup_msg = (
                            f"You've gone through all the "
                            f"{context.get('industry') or industry_key} in "
                            f"{original_location} for now — let me find you some more. "
                            f"This takes about a minute, and new ones will show up here "
                            f"automatically."
                        )
                        history.append({"role": "assistant", "message": topup_msg})
                        return {
                            "status": "gathering",
                            "message": topup_msg,
                            "context": context,
                            "log_id": str(topup_log.id),
                        }

                    # Handle no results / geocoding failure after get_leads returns.
                    if not api_leads and not leads:
                        # GEO-4: EXHAUSTED (area has matches, user pulled them all) vs
                        # genuinely EMPTY. get_leads_overture set error_info["exhausted"].
                        if error_info.get("exhausted"):
                            _city = context.get("location") or original_location
                            _log_id = await _recent_matching_log_id(db, user.id, industry_key, _city)
                            await _fill_exhaustion_nearby(error_info, industry_key, context, history, llm, search_terms)
                            payload = _exhaustion_response(
                                error_info, context.get("industry") or industry_key,
                                _city, leads_limit, context, log_id=_log_id,
                            )
                            history.append({"role": "assistant", "message": payload["message"]})
                            return payload
                        # No leads. Location spelling is normalized upfront by understand(),
                        # so reaching here means the place is genuinely unfindable (not a
                        # typo) → state-aware recovery with concrete next-step actions.
                        from app.utils.chat_recovery import build_zero_results_recovery

                        nearby = list(error_info.get("nearby_suggestions") or [])
                        if not nearby:
                            try:
                                nearby = await _verified_city_suggestions(
                                    industry_key,
                                    context.get("country"),
                                    context,
                                    history,
                                    llm,
                                    search_terms=search_terms,
                                    limit=3,
                                )
                            except Exception:
                                nearby = []
                        payload = build_zero_results_recovery(
                            context,
                            nearby_cities=nearby,
                            geocoding_failed=bool(error_info.get("geocoding_failed")),
                        )
                        from app.utils.conversation_health import note_no_results

                        note_no_results(context)
                        history.append({"role": "assistant", "message": payload["message"]})
                        return payload

            if api_leads:
                db_names = {l["business_name"].lower().strip() for l in leads}
                logger.info(f"[DEDUP] DB name set ({len(db_names)} entries): {sorted(db_names)}")
                for lead in api_leads:
                    if api_count >= remaining:
                        break
                    name = (lead.get("business_name") or "").lower().strip()
                    if name and name not in db_names:
                        leads.append(lead)
                        db_names.add(name)
                        api_count += 1
                        logger.info(f"[DEDUP] ADDED   : '{name}'")
                    else:
                        logger.info(f"[DEDUP] SKIPPED : '{name}' (already in DB)")
            logger.info(f"[LEAD FETCH] Leads added: {api_count} (needed {remaining}, fetched {len(api_leads) if api_leads else 0} candidates)")
        else:
            logger.info("[LEAD FETCH] Nothing to fetch (batch limit already satisfied).")

        logger.info(f"[LEAD FETCH] TOTAL leads: {len(leads)} (overture={api_count})")

        # Near-exhaustion guard: when a *repeat* search returns a tiny remnant
        # (< 10% of the plan batch), the area is effectively exhausted for this
        # user. Show the exhaustion message instead of charging credits for
        # 1-2 leftover leads on every retry.
        #
        # Important: do NOT apply this on a user's first search for this
        # industry/city. After User A warms a small market (e.g. 2 e-commerce
        # leads in Miami), User B's first sync warm fetch must still deliver
        # those leads — otherwise they incorrectly see "reached the end" with
        # zero results while User A got the same leads via the cold path.
        _city = context.get("location") or original_location
        _prior_log_id = await _recent_matching_log_id(db, user.id, industry_key, _city)
        _min_useful = max(3, int(effective_leads_limit * 0.1))
        if (
            _prior_log_id is not None
            and 0 < len(leads) < _min_useful
            and error_info.get("no_results") is False
        ):
            logger.info(
                "[LEAD FETCH] Near-exhaustion (repeat): only %d leads (threshold %d) — treating as exhausted",
                len(leads), _min_useful,
            )
            error_info["exhausted"] = True
            await _fill_exhaustion_nearby(error_info, industry_key, context, history, llm, search_terms)
            payload = _exhaustion_response(
                error_info, context.get("industry") or industry_key,
                _city, leads_limit, context, log_id=_prior_log_id,
            )
            history.append({"role": "assistant", "message": payload["message"]})
            return payload
        if 0 < len(leads) < _min_useful and _prior_log_id is None:
            logger.info(
                "[LEAD FETCH] Small first-search batch (%d < %d) — delivering leads (not exhausted)",
                len(leads), _min_useful,
            )

        # Deduct credits only for NEW leads not shown before to this user.
        # Repeated leads in later searches are free.
        chargeable_leads, repeated_seen_count = await _split_chargeable_leads(
            db=db,
            user_id=user.id,
            industry=industry_key,
            leads=leads,
        )
        if repeated_seen_count > 0:
            logger.info(
                "[CREDITS] Skipping charge for %d repeated lead(s) previously shown to user %s",
                repeated_seen_count,
                user.id,
            )

        if chargeable_leads:
            try:
                from app.services.credit_service import spend_credits
                await spend_credits(
                    db, user.id, "lead_found",
                    quantity=len(chargeable_leads),
                    description=f"Search: {industry_key} in {context.get('location', '')}",
                )
            except HTTPException as credit_err:
                if credit_err.status_code == status.HTTP_402_PAYMENT_REQUIRED:
                    raise credit_err
                logger.exception("[CREDITS] credit deduction failed (HTTP)")
                raise credit_err
            except Exception as credit_err:
                logger.exception("[CREDITS] credit deduction failed: %s", credit_err)
                raise

        if not leads:
            if error_info.get("exhausted"):
                _city = context.get("location") or original_location
                _log_id = await _recent_matching_log_id(db, user.id, industry_key, _city)
                await _fill_exhaustion_nearby(error_info, industry_key, context, history, llm, search_terms)
                payload = _exhaustion_response(
                    error_info, context.get("industry") or industry_key,
                    _city, leads_limit, context, log_id=_log_id,
                )
                history.append({"role": "assistant", "message": payload["message"]})
                return payload
            from app.utils.chat_recovery import build_zero_results_recovery

            nearby = list(error_info.get("nearby_suggestions") or [])
            if not nearby:
                try:
                    nearby = await _verified_city_suggestions(
                        industry_key,
                        context.get("country"),
                        context,
                        history,
                        llm,
                        search_terms=search_terms,
                        limit=3,
                    )
                except Exception:
                    nearby = []
            payload = build_zero_results_recovery(
                context,
                nearby_cities=nearby,
                geocoding_failed=bool(error_info.get("geocoding_failed")),
            )
            history.append({"role": "assistant", "message": payload["message"]})
            return payload

        # Relevance ordering — contactable + on-name leads first, within location tiers.
        leads = rank_leads(
            leads,
            industry_key,
            context.get("search_terms"),
            context.get("location"),
            context.get("quality"),
        )

        # Step 3: Save to DB
        now = datetime.now(timezone.utc)

        # Create chat title with location and country if available
        final_industry = context.get("industry")
        final_location = context.get("location")
        final_country = context.get("country")

        chat_title = build_chat_title(
            industry=final_industry,
            location=final_location,
            country=final_country,
            anchor=context.get("anchor"),
        )
        log = LeadLog(
            chat_title=chat_title,
            query=message,
            user_id=user.id,
            is_read=False,  # Default value for backward compatibility
            created_at=now,
            updated_at=now,
        )
        db.add(log)
        await db.flush()

        # A lead is already enriched when it came from a reused DB row (_from_db) OR
        # from a warm overture_places row whose master is 'done' (_enriched). Those
        # save straight to 'done' with their scraped email/context; everything else
        # is 'processing' and the enrichment job fills it (reusing the master where it
        # can). §4.1
        lead_rows = [
            {
                "business_name": (l.get("business_name") or "")[:255],
                "industry": (l.get("industry") or "")[:255],
                # Already-enriched leads carry their (scraped/Overture) email; fresh
                # leads that carry an Overture email keep it; the rest start empty and
                # enrichment fills them.
                "email": ((l.get("email") or "") or None)
                if (l.get("_from_db") or l.get("_enriched") or l.get("email"))
                else None,
                "contact_number": (l.get("contact_number") or "")[:255],
                "address": (l.get("address") or "")[:255],
                "website": (l.get("website") or "")[:255],
                "lead_score": l.get("lead_score", 0),
                "enrichment_status": "done"
                if (l.get("_from_db") or l.get("_enriched"))
                else "processing",
                # Context: populated for already-enriched leads served from the master
                # — keeps their 'done' log rows complete for the poll (the enrichment
                # job skips done rows). None for leads that still need enrichment.
                "services": l.get("services"),
                "website_summary": l.get("website_summary"),
                "business_description": l.get("business_description"),
                # Master-catalog link (overture_places.overture_id); NULL for
                # Google/manual leads — they keep the legacy snapshot path.
                "overture_id": (str(l.get("overture_id"))[:64] if l.get("overture_id") else None),
                "lead_log_id": log.id,
                "created_at": now,
                "updated_at": now,
            }
            for l in leads
        ]

        if lead_rows:
            for chunk in chunked(lead_rows, 250):
                stmt = insert(LeadLogLead).values(chunk)
                await db.execute(stmt)

        await db.commit()

        # Fire background email enrichment only when there are leads still needing it
        has_processing_leads = any(r["enrichment_status"] == "processing" for r in lead_rows)
        enrichment_recovery = None
        if has_processing_leads:
            from app.tasks.enrich_leads import enrich_leads_task
            from app.utils.chat_recovery import build_enrichment_timeout_recovery
            try:
                task_result = enrich_leads_task.delay(log.id)
                logger.info(f" Enqueued enrichment task for lead_log_id={log.id}, task_id={task_result.id}, user_id={user.id}")
            except Exception as e:
                logger.error(f" Failed to enqueue enrichment task for lead_log_id={log.id}, user_id={user.id}: {str(e)}", exc_info=True)
                enrichment_recovery = build_enrichment_timeout_recovery(context)
        else:
            logger.info(f" Skipped enrichment task — all leads already enriched from DB (lead_log_id={log.id})")
        # Generate friendly message
        try:
            reply = await generate_human_response(
                message, context, leads, llm, history,
                user_id=getattr(user, "id", None),
                memory_block=context.get("_memory_prompt"),
            )
        except LLMUnavailableError as e:
            logger.warning("Gemini unavailable after search; returning leads with fallback copy: %s", e)
            n = len(lead_rows)
            reply = (
                f"I found {n} lead{'s' if n != 1 else ''} for you. Opening the results now."
                if n
                else "I finished the search. Opening the results now."
            )
        # Add assistant response to history
        history.append({"role": "assistant", "message": reply})

        from app.utils.conversation_health import note_progress

        note_progress(context)

        # Compact episodic memory — never store the lead table in conversational memory.
        try:
            filters = []
            if context.get("_scope_choice") == "narrow" or context.get("_memory_exact_category"):
                filters.append("exact category")
            if context.get("quality"):
                filters.append(str(context.get("quality")))
            if context.get("radius_km") is not None:
                filters.append(f"radius {context.get('radius_km')}km")
            await chat_memory.record_completed_search(
                db,
                user.id,
                industry=context.get("industry"),
                location=context.get("location"),
                country=context.get("country"),
                filters=filters,
                radius_km=context.get("radius_km"),
                exact_category=("exact category" in filters),
            )
        except Exception as e:
            logger.warning("[CHAT_MEMORY] record search failed: %s", e)

        # Build success response (chat remains active until user clicks "New Chat")
        response = {
            "status": "success",
            "message": reply,
            "context": context,
            "log_id": str(log.id),
            "lead_count": len(lead_rows),
            "timestamp": datetime.now(timezone.utc),
        }
        if enrichment_recovery:
            response["recovery_kind"] = enrichment_recovery["recovery_kind"]
            response["actions"] = enrichment_recovery["actions"]
            response["message"] = enrichment_recovery["message"]
            history[-1] = {"role": "assistant", "message": enrichment_recovery["message"]}
        return response
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")

# CHAT — GUEST
async def chat_guest(message: str, llm: ChatGoogleGenerativeAI):
    """Guest chat path — simple single-turn response, no DB or session storage."""
    try:
        u = await understand(message, {}, [{"role": "user", "message": message}])
    except LLMUnavailableError as e:
        logger.warning("Gemini unavailable for guest chat: %s", e)
        return llm_error_result({})
    if u.ambiguous and len(u.candidate_meanings) >= 2:
        candidates = [m.model_dump() for m in u.candidate_meanings]
        try:
            clarification = await generate_ambiguous_clarification(
                infer_ambiguous_industry(message, candidates, u.industry),
                u.location or "",
                candidates,
                [],
                llm,
            )
        except LLMUnavailableError as e:
            logger.warning("Gemini unavailable for guest ambiguous clarification: %s", e)
            return llm_error_result({})
        return {"message": clarification, "leads": []}
    try:
        # Guests get the same grounded answers as signed-in users: the corpus is
        # product knowledge and is not scoped to who is asking.
        if u.intent == "general_question" and u.about_evecta:
            response = await _knowledge_reply(
                message, llm, about_assistant=u.about_assistant
            )
        else:
            response = await generate_human_response(message, {}, [], llm)
    except LLMUnavailableError as e:
        logger.warning("Gemini unavailable for guest reply: %s", e)
        return llm_error_result({})
    return {"message": response, "leads": []}


async def chat_guest_stream(message: str, llm: ChatGoogleGenerativeAI):
    """Streaming counterpart to ``chat_guest``. Yields ``{"type": "token", "content": ...}``
    for each text chunk, followed by one ``{"type": "done", "data": {...}}`` carrying the
    same result shape ``chat_guest`` returns."""
    try:
        u = await understand(message, {}, [{"role": "user", "message": message}])
    except LLMUnavailableError as e:
        logger.warning("Gemini unavailable for guest chat: %s", e)
        yield {"type": "done", "data": llm_error_result({})}
        return

    if u.ambiguous and len(u.candidate_meanings) >= 2:
        candidates = [m.model_dump() for m in u.candidate_meanings]
        pieces = []
        try:
            async for chunk in generate_ambiguous_clarification_stream(
                infer_ambiguous_industry(message, candidates, u.industry),
                u.location or "",
                candidates,
                [],
                llm,
            ):
                pieces.append(chunk)
                yield {"type": "token", "content": chunk}
        except LLMUnavailableError as e:
            logger.warning("Gemini unavailable for guest ambiguous clarification: %s", e)
            yield {"type": "done", "data": llm_error_result({})}
            return
        yield {"type": "done", "data": {"message": "".join(pieces).strip(), "leads": []}}
        return

    if u.intent == "general_question" and u.about_evecta:
        # Grounded answers reach guests too (see chat_guest), and stream the same way
        # the ungrounded guest reply below does.
        pieces = []
        try:
            async for chunk in _knowledge_reply_stream(
                message, llm, about_assistant=u.about_assistant
            ):
                pieces.append(chunk)
                yield {"type": "token", "content": chunk}
        except LLMUnavailableError as e:
            logger.warning("Gemini unavailable for guest knowledge reply: %s", e)
            yield {"type": "done", "data": llm_error_result({})}
            return
        yield {"type": "done", "data": {"message": "".join(pieces).strip(), "leads": []}}
        return

    pieces = []
    try:
        async for chunk in generate_human_response_stream(message, {}, [], llm):
            pieces.append(chunk)
            yield {"type": "token", "content": chunk}
    except LLMUnavailableError as e:
        logger.warning("Gemini unavailable for guest reply: %s", e)
        yield {"type": "done", "data": llm_error_result({})}
        return
    yield {"type": "done", "data": {"message": "".join(pieces).strip(), "leads": []}}
