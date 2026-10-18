import asyncio
import dns.resolver
import httpx
import json
import logging
import re
import time
from typing import Literal, Optional, Union
from uuid import UUID

logger = logging.getLogger(__name__)
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from fastapi import HTTPException
from app.core.config import get_settings
from app.services.ai.tracked_llm import tracked_agenerate, tracked_astream, llm_model_name
from app.services.external_api_usage import record_places_usage
from app.utils.redis_context import (
    arun,
    get_cached_quick_check,
    set_cached_quick_check,
    get_cached_geocode,
    set_cached_geocode,
)
from app.utils.chat_history import format_chat_history_for_prompt

settings = get_settings()
GOOGLE_MAPS_API_KEY = settings.GOOGLE_MAPS_API_KEY

CHAT_PERSONA = """You are Evecta's lead-finding assistant — a warm, professional colleague who helps users discover businesses by industry and city, then pull contact-ready leads.

RULE HIERARCHY (higher always wins when anything conflicts):
1. Backend safety, auth, credits
2. Explicit changes in the current user message
3. Validated CURRENT CONTEXT / ChatState for this chat
4. Explicit saved long-term preferences (confirmed)
5. Company / account profile
6. Recent search summaries
7. Inferred preferences (ask before applying)
8. Conversation history (tone and references only)
9. Style and wording preferences

- Treat CURRENT CONTEXT as the source of truth for this chat's industry, city, and country. Long-term memory never overrides a current instruction (saved Kathmandu + "London" → London).
- Use conversation history only for tone and unresolved references. Never restore an older value that conflicts with CURRENT CONTEXT.
- Use LONG-TERM MEMORY sparingly and only when relevant. On greetings: name once + at most one usual market or last search. Do not dump every known fact.
- Never re-ask for industry, location, or anything else already present in CURRENT CONTEXT.
- Sound like a helpful human colleague: acknowledge what the user said in a natural way, then ask the next useful question.
- Keep replies natural and concise — usually 1–3 sentences. Style prefs must not hide errors or required disclosures.
- Lean toward lead generation when it fits naturally. Do not force a lead-generation transition into every reply.
- When the user asks who you are / about yourself / how you work, actually answer that first. Then offer a soft next step (industry or what they're selling) — do not skip straight to a dry industry ask.
- Warm acknowledgments are welcome ("Got it", "Sure", "Happy to help"). Avoid over-the-top cheerleading and hard-sell framing like "I specialize in…"."""


# Deterministic fallbacks used when the LLM is unavailable. Keep these aligned with
# CHAT_PERSONA tone — warm/professional/natural, no cheerleading or hard-sell.
def fallback_greeting(preferred_name: str | None = None) -> str:
    hi = f"Hi {preferred_name}" if (preferred_name or "").strip() else "Hi"
    return f"{hi}! Happy to help you find business leads. What industry are you looking for?"


def fallback_about_assistant() -> str:
    return (
        "I'm Evecta's lead-finding assistant — I help you discover businesses by industry "
        "and city, then pull contact-ready leads. Want to start with an industry, or tell "
        "me what you're selling first?"
    )


def fallback_ask_industry() -> str:
    return (
        "Sure — what kind of businesses should I search for? "
        "For example: restaurants, coffee shops, or dentists."
    )


def _fallback_industry_label(industry: str | None) -> str:
    """Never interpolate a chat sentence into a location ask."""
    label = " ".join((industry or "").strip().split())
    if not label:
        return "those businesses"
    # Defense in depth if a chatty fragment slipped into context.
    lowered = label.lower()
    if any(w in lowered.split() for w in ("i", "want", "need", "help", "please", "find", "search", "looking", "can", "you")):
        return "those businesses"
    if len(label.split()) > 4:
        return "those businesses"
    return label


def fallback_ask_location(industry: str | None = None) -> str:
    label = _fallback_industry_label(industry)
    return (
        f"Got it — {label}. Which city should I search in? "
        "For example: Melbourne, Kathmandu, or London."
    )


def fallback_ask_city_or_country(industry: str | None = None) -> str:
    label = _fallback_industry_label(industry)
    return f"Got it — I'll look for {label}. Which city or country should I search in?"


def fallback_ack_narrow_ask_location(industry: str | None = None) -> str:
    """Acknowledge an explicit 'only/just' refinement, then ask for the missing place."""
    label = _fallback_industry_label(industry)
    return f"Yes — {label} only, no related types. Which city or country should I search?"


def fallback_ask_city_in_country(industry: str | None = None, country: str | None = None) -> str:
    label = _fallback_industry_label(industry)
    place = (country or "").strip() or "that country"
    return f"Sure — which city in {place} should I search for {label} in?"


def fallback_ask_industry_and_location() -> str:
    return "Happy to help. Which industry and city should I search?"

# EMAIL HELPER FUNCTIONS
MX_CACHE: dict[str, bool] = {}

def clean_domain(domain: str) -> str:
    domain = domain.lower().strip()
    domain = domain.replace("http://", "").replace("https://", "").replace("www.", "")
    return domain.split("/")[0]

async def has_mx_record(domain: str) -> bool:
    if domain in MX_CACHE:
        return MX_CACHE[domain]
    try:
        answers = await asyncio.to_thread(
            dns.resolver.resolve, domain, "MX", lifetime=2.0
        )
        MX_CACHE[domain] = len(answers) > 0
    except:
        MX_CACHE[domain] = False
    return MX_CACHE[domain]

def compute_score(mx_ok: bool, prefix_ok: bool) -> int:
    score = 50
    if mx_ok:
        score += 20
    if prefix_ok:
        score += 10
    return min(score, 100)


def _normalize_quick_check_terms(industry: str, search_terms: list[str] | None = None) -> list[str]:
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


async def _quick_check_single_term(industry: str, location: str, radius: int = 3000) -> tuple[bool, dict]:
    """Quickly check if there are any results without fetching full details.
    Returns: (has_results: bool, error_info: dict)
    This is fast because it only does geocoding + nearby search, no detail fetching.
    Results are cached in Redis to avoid redundant API calls.
    """
    if not GOOGLE_MAPS_API_KEY:
        return False, {"geocoding_failed": False, "no_results": False}

    # Redis cache check — skip Google API entirely if we already know the answer
    cached = await arun(get_cached_quick_check, industry, location)
    if cached is not None:
        logger.info(f"[QCHECK] Cache HIT: industry={industry}, location={location}, has_results={cached}")
        error_info = {"geocoding_failed": False, "no_results": not cached}
        return cached, error_info

    error_info = {"geocoding_failed": False, "no_results": False}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: Geocode location (check Redis first)
            coords = await arun(get_cached_geocode, location)
            if coords:
                lat, lng = coords
            else:
                geo_url = "https://maps.googleapis.com/maps/api/geocode/json"
                geo_started = time.perf_counter()
                geo_resp = await client.get(geo_url, params={"address": location, "key": GOOGLE_MAPS_API_KEY}, timeout=5.0)
                geo_data = geo_resp.json()
                await record_places_usage(
                    api_name="geocode",
                    google_status=geo_data.get("status"),
                    http_status=geo_resp.status_code,
                    latency_ms=int((time.perf_counter() - geo_started) * 1000),
                    feature="quick_check",
                    meta=(location or "")[:256] or None,
                )
                if not geo_data.get("results"):
                    error_info["geocoding_failed"] = True
                    await arun(set_cached_quick_check, industry, location, False, ttl=3600)
                    return False, error_info
                geo_result = geo_data["results"][0]
                latlng = geo_result["geometry"]["location"]
                lat, lng = latlng["lat"], latlng["lng"]
                bounds = geo_result["geometry"].get("bounds") or geo_result["geometry"].get("viewport")
                if bounds:
                    from app.services.lead_generation_service import haversine_distance
                    ne, sw = bounds["northeast"], bounds["southwest"]
                    city_radius_km = haversine_distance(sw["lat"], sw["lng"], ne["lat"], ne["lng"]) / 2
                else:
                    city_radius_km = 5.0
                await arun(set_cached_geocode, location, lat, lng, city_radius_km)

            # Step 2: Quick nearby search (just check if any results exist)
            nearby_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
            nearby_started = time.perf_counter()
            nearby_resp = await client.get(
                nearby_url,
                params={"location": f"{lat},{lng}", "radius": radius, "keyword": industry, "key": GOOGLE_MAPS_API_KEY},
                timeout=5.0,
            )
            nearby_data = nearby_resp.json()
            await record_places_usage(
                api_name="nearby_search",
                google_status=nearby_data.get("status"),
                http_status=nearby_resp.status_code,
                latency_ms=int((time.perf_counter() - nearby_started) * 1000),
                feature="quick_check",
                meta=(industry or "")[:256] or None,
            )
            places = nearby_data.get("results", [])

            if not places:
                error_info["no_results"] = True
                await arun(set_cached_quick_check, industry, location, False, ttl=3600)
                return False, error_info

            await arun(set_cached_quick_check, industry, location, True, ttl=7200)
            return True, error_info
    except httpx.RequestError:
        return False, error_info
    except Exception:
        return False, error_info

# QUICK CHECK FOR RESULTS (FAST)
async def quick_check_results(
    industry: str,
    location: str,
    radius: int = 3000,
    search_terms: list[str] | None = None,
) -> tuple[bool, dict]:
    """Check if any canonical or resolved search term has Places results."""
    terms = _normalize_quick_check_terms(industry, search_terms)
    final_error_info = {"geocoding_failed": False, "no_results": False}
    for term in terms:
        has_results, error_info = await _quick_check_single_term(term, location, radius)
        final_error_info = error_info
        if has_results:
            logger.info(
                "[QCHECK] Verified results | industry=%s | location=%s | matched_term=%s | terms=%s",
                industry,
                location,
                term,
                terms,
            )
            return True, error_info
    final_error_info["no_results"] = True
    logger.info(
        "[QCHECK] No verified results | industry=%s | location=%s | terms=%s",
        industry,
        location,
        terms,
    )
    return False, final_error_info

async def _verified_city_suggestions(
    industry: str,
    country: str | None,
    context: dict,
    history: list,
    llm: ChatGoogleGenerativeAI,
    search_terms: list[str] | None = None,
    limit: int = 2,
    user_id: Optional[Union[str, UUID]] = None,
) -> list[str]:
    """Ask the LLM for candidate alternate cities (deduped; no external verification)."""
    history_str = format_chat_history_for_prompt(history)

    location = context.get("location")
    country_line = f'Region/country: "{country}"' if country else "Region/country: null"
    prompt = f"""You are helping suggest alternate cities for business lead generation.

The user searched for industry "{industry}" and needs city options in a broader region.
{country_line}
Current location: "{location}"
Search terms used: {_normalize_quick_check_terms(industry, search_terms)}

CONVERSATION HISTORY:
{history_str}

Return ONLY a JSON array of 4-6 candidate city names likely to have real businesses for this industry.
If a country, continent, or region is provided, only return real cities inside that area (e.g. for Africa: Lagos, Nairobi, Cape Town, Cairo — not the continent name itself).
Do not return the current location.
Do not return continent or country names as if they were cities.
IMPORTANT — avoid repeats: read the CONVERSATION HISTORY above. The user may have already
searched or fully exhausted ("reached the end") several cities for industry "{industry}".
Do NOT suggest any city already searched or exhausted for THIS industry. Only suggest NEW
cities the user has not tried yet. (A city exhausted for a different industry is still fine.)

Example: ["Kathmandu", "Lalitpur", "Bhaktapur", "Pokhara"]
Return JSON array:"""

    human_message = HumanMessage(content=prompt)
    response = await tracked_agenerate(
        llm=llm,
        messages=[[human_message]],
        provider="gemini",
        model=llm_model_name(llm, fallback=settings.GEMINI_MODEL),
        feature="nearby_city_suggestion",
        user_id=user_id,
    )
    cities_text = response.generations[0][0].text.strip()
    for p in ("```json", "```", "[", "]"):
        cities_text = cities_text.replace(p, "").strip()

    raw_cities = [c.strip().strip('"').strip("'") for c in cities_text.split(",") if c.strip()]
    # No external verification: leads come from Overture (loaded on demand), so
    # alternative cities are "cold" and can't be cheaply verified — and the old
    # check used Google Places (we keep Google for geocoding only). Trust the LLM's
    # suggestions; if a chosen city is empty, the normal no-results path handles it.
    suggestions = []
    seen_city_names = set()
    current_location_key = (location or "").strip().lower()
    country_key = (country or "").strip().lower()

    for city in raw_cities[:6]:
        city_name = city.strip()
        city_key = city_name.lower()
        if not city_name or city_key in seen_city_names:
            continue
        if city_key == current_location_key or city_key == country_key:
            continue
        seen_city_names.add(city_key)
        suggestions.append(city_name)
        if len(suggestions) >= limit:
            break

    logger.info(
        "[SUGGEST] industry=%r | country=%r | raw=%r | suggested=%r",
        industry, country, raw_cities, suggestions,
    )
    return suggestions

# GENERATE SUGGESTIONS FOR NO RESULTS
def _suggestion_history_str(history: list) -> str:
    return format_chat_history_for_prompt(history)


async def _stream_grounded_suggestion(facts: str, fallback: str, history: list, llm: ChatGoogleGenerativeAI, user_id=None):
    """Shared plumbing for the two suggestion functions below: stream a short reply that
    conveys exactly `facts` (which already encodes any real city names — verified by
    _verified_city_suggestions, never invented by this prompt) and falls back to the
    deterministic `fallback` text if the LLM is unavailable."""
    prompt = f"""{CHAT_PERSONA}

CONVERSATION HISTORY:
{_suggestion_history_str(history)}

{facts}

Convey exactly those facts. Do not add any information, city names, or options beyond what is stated above.

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
                yield chunk.content
    except Exception as e:
        from app.utils.llm_errors import LLMUnavailableError, is_llm_unavailable

        if is_llm_unavailable(e):
            raise LLMUnavailableError() from e
        logger.error(f"Error generating suggestion: {e}")
        yield fallback


async def generate_suggestions_stream(
    industry: str,
    location: str,
    context: dict,
    history: list,
    llm: ChatGoogleGenerativeAI,
    nearby_suggestions: list[str] | None = None,
    search_terms: list[str] | None = None,
    user_id: Optional[Union[str, UUID]] = None,
):
    """Stream professional, human-like suggestions when no results are found. City names
    are always grounded in nearby_suggestions or _verified_city_suggestions — never
    invented by the phrasing LLM call."""
    if nearby_suggestions:
        suggestions = [name for name in nearby_suggestions if name]
        if suggestions:
            suggestion_text = " or ".join(suggestions[:2])
            facts = (
                f'Tell the user you could not find any leads for "{industry}" in "{location}", '
                f'and ask if they would like to search in exactly these alternative cities instead: {suggestion_text}. '
                "Do NOT mention or invent any other city."
            )
            fallback = f"I couldn't find any leads for {industry} in {location}. Would you like me to search in {suggestion_text}?"
            async for piece in _stream_grounded_suggestion(facts, fallback, history, llm, user_id=user_id):
                yield piece
            return

    has_country = context.get("country")
    has_city = location and location.strip() and context.get("location") and location.lower() != context.get("country", "").lower()
    country_name = context.get("country") if has_country else None
    verified_cities = await _verified_city_suggestions(
        industry,
        country_name,
        context,
        history,
        llm,
        search_terms=search_terms,
        user_id=user_id,
    )
    if verified_cities:
        city_list = " or ".join(verified_cities[:2])
        if has_country and not has_city:
            facts = (
                f'Tell the user you see they are looking in "{country_name}", and ask if they would like to '
                f"search in these cities: {city_list}. Do NOT mention or invent any other city."
            )
            fallback = f"I see you're looking in {country_name}. Would you like me to search in {city_list}?"
        else:
            facts = (
                f'Tell the user you could not find "{industry}" in "{location}", and ask if they would like to '
                f"search in these cities instead: {city_list}. Do NOT mention or invent any other city."
            )
            fallback = f"I couldn't find {industry} in {location}. Would you like me to search in {city_list}?"
    elif has_country and not has_city:
        facts = (
            f'Tell the user you could not verify any cities in "{country_name}" with matching "{industry}" leads yet, '
            "and ask if they would like to try a broader industry term or another country. "
            "Do NOT suggest any specific city name since none has been verified."
        )
        fallback = (
            f"I couldn't verify any cities in {country_name} with matching {industry} leads yet. "
            "Would you like to try a broader industry term or another country?"
        )
    else:
        facts = (
            f'Tell the user you could not verify another city with matching "{industry}" leads yet, '
            "and ask if they would like to try a broader industry term or another location. "
            "Do NOT suggest any specific city name since none has been verified."
        )
        fallback = (
            f"I couldn't verify another city with matching {industry} leads yet. "
            "Would you like to try a broader industry term or another location?"
        )
    async for piece in _stream_grounded_suggestion(facts, fallback, history, llm, user_id=user_id):
        yield piece


async def generate_suggestions(
    industry: str,
    location: str,
    context: dict,
    history: list,
    llm: ChatGoogleGenerativeAI,
    nearby_suggestions: list[str] | None = None,
    search_terms: list[str] | None = None,
    user_id: Optional[Union[str, UUID]] = None,
) -> str:
    chunks = [
        piece async for piece in
        generate_suggestions_stream(
            industry, location, context, history, llm,
            nearby_suggestions=nearby_suggestions, search_terms=search_terms, user_id=user_id,
        )
    ]
    return "".join(chunks).strip()


async def generate_suggestions_with_verification_stream(
    industry: str,
    country: str,
    context: dict,
    history: list,
    llm: ChatGoogleGenerativeAI,
    search_terms: list[str] | None = None,
    user_id: Optional[Union[str, UUID]] = None,
):
    """Stream city suggestions for a country, grounded only in cities the industry is
    actually verified to exist in — never invented by the phrasing LLM call."""
    verified_cities = await _verified_city_suggestions(
        industry,
        country,
        context,
        history,
        llm,
        search_terms=search_terms,
        user_id=user_id,
    )
    if verified_cities:
        city_list = " or ".join(verified_cities[:2])
        facts = (
            f'Tell the user that "{country}" is too broad to search as one place for "{industry}" leads, '
            f"and suggest these cities instead: {city_list}. Ask which city they want to search. "
            "Do NOT mention or invent any other city."
        )
        fallback = (
            f"{country} is too broad to search as one place. "
            f"Would you like me to search for {industry} in {city_list}?"
        )
    else:
        facts = (
            f'Tell the user you could not verify any cities in "{country}" with matching "{industry}" leads yet, '
            "and ask if they would like to try a broader industry term or another country. "
            "Do NOT suggest any specific city name since none has been verified."
        )
        fallback = (
            f"I couldn't verify any cities in {country} with matching {industry} leads yet. "
            "Would you like to try a broader industry term or another country?"
        )
    async for piece in _stream_grounded_suggestion(facts, fallback, history, llm, user_id=user_id):
        yield piece


async def generate_suggestions_with_verification(
    industry: str,
    country: str,
    context: dict,
    history: list,
    llm: ChatGoogleGenerativeAI,
    search_terms: list[str] | None = None,
    user_id: Optional[Union[str, UUID]] = None,
) -> str:
    chunks = [
        piece async for piece in
        generate_suggestions_with_verification_stream(
            industry, country, context, history, llm, search_terms=search_terms, user_id=user_id,
        )
    ]
    return "".join(chunks).strip()


# RESPONSE MODE
ResponseMode = Literal[
    "greeting",
    "missing_information",
    "clarification",
    "search_acknowledgement",
    "search_summary",
    "general_answer",
    "no_results",
    "error_recovery",
    "refinement_summary",
]


def _looks_like_about_assistant(message: str | None) -> bool:
    """True for who-are-you / how-do-you-work questions about the assistant itself."""
    msg = " ".join((message or "").strip().lower().split())
    if not msg:
        return False
    # "u" for "you" is matched deliberately: these are the shortest messages users
    # send, and a terse one carries too little signal for the corpus to answer it
    # (retrieval scores "who are u" at 0.66, well under the floor), so failing to
    # recognise it here is what sends the most basic question in the product to the
    # "I don't have that documented" reply.
    _you = r"(you|u)"
    _are = r"(are|r)"
    patterns = (
        rf"\b(tell|talk)\s+me\s+about\s+(yourself|you|u)\b",
        rf"\bwho\s+{_are}\s+{_you}\b",
        rf"\bwhat\s+{_are}\s+{_you}\b",
        rf"\bwhat\s+can\s+{_you}\s+do\b",
        rf"\bwhat\s+do\s+{_you}\s+do\b",
        rf"\bhow\s+do\s+{_you}\s+work\b",
        r"\bhow\s+does\s+this\s+work\b",
        r"\bwhat\s+is\s+(this|evecta)\b",
        r"\babout\s+(yourself|you|evecta)\b",
        r"\bintroduce\s+yourself\b",
    )
    return any(re.search(p, msg) for p in patterns)


def _pick_response_mode(
    *,
    message: str,
    context: dict,
    leads: list,
) -> ResponseMode:
    msg = (message or "").strip().lower()
    has_industry = bool(context.get("industry"))
    has_place = bool(context.get("location") or context.get("country"))
    has_leads = bool(leads)
    # Greetings first — otherwise missing slots force a dry industry ask on "hi"/"hellooo".
    if re.fullmatch(
        r"(hi+|hello+|hey+|howdy|greetings|yo+"
        r"|good\s+(morning|afternoon|evening)"
        r"|thanks|thank\s+you|thx|ty"
        r"|bye+|goodbye|see\s+ya|cya)[!.,\s]*",
        msg,
    ):
        return "greeting"
    # About-the-assistant questions must be answered even when industry/city are missing.
    if _looks_like_about_assistant(message):
        return "general_answer"
    if has_leads:
        return "search_summary"
    if context.get("awaiting_clarification") or context.get("awaiting_scope") or context.get("awaiting_confirmation"):
        return "clarification"
    if not has_industry or not has_place:
        return "missing_information"
    if any(k in msg for k in ("refine", "instead", "narrow", "broader", "only", "within", "radius")):
        return "refinement_summary"
    if "?" in msg or msg.startswith(("what ", "how ", "why ", "tell ", "explain ", "can ", "do ")):
        return "general_answer"
    return "search_acknowledgement"


# HUMAN-STYLE RESPONSE
async def generate_human_response_stream(
    message: str,
    context: dict,
    leads: list,
    llm: ChatGoogleGenerativeAI,
    history: list = None,
    user_id: Optional[Union[str, UUID]] = None,
    memory_block: str | None = None,
):
    """Stream short, human-friendly AI response chunks. See ``generate_human_response``
    for the non-streaming callers that just want the full text."""
    has_industry = "industry" in context and context.get("industry")
    has_country = "country" in context and context.get("country")
    has_location = "location" in context and context.get("location")

    known_info = []
    if has_industry:
        known_info.append(f"Industry: {context.get('industry')}")
    if has_country:
        known_info.append(f"Country: {context.get('country')}")
    if has_location:
        known_info.append(f"City: {context.get('location')}")
    if context.get("quality"):
        known_info.append(f"Quality preference: {context.get('quality')}")
    
    known_info_str = ", ".join(known_info) if known_info else "None"
    
    history_str = format_chat_history_for_prompt(history)
    
    conversation_state = ""
    if not has_industry:
        conversation_state = "We need to know what industry you're looking for."
    elif has_industry and not has_location and not has_country:
        conversation_state = f"We know you want {context.get('industry')} businesses, but we need to know which city or country."
    elif has_country and not has_location:
        conversation_state = f"We know you want {context.get('industry')} businesses in {context.get('country')}, but we need to know which city."

    reply_hint = (context.get("_human_reply_hint") or "").strip()
    if reply_hint:
        conversation_state = f"{conversation_state} {reply_hint}".strip()
    
    response_mode = _pick_response_mode(message=message, context=context, leads=leads)
    memory_section = (memory_block or context.get("_memory_prompt") or "").strip() or "None"

    prompt = f"""{CHAT_PERSONA}

CONVERSATION HISTORY:
{history_str}

Current user message: {message}
CURRENT CONTEXT (ALREADY KNOWN): {known_info_str}
LONG-TERM MEMORY (use sparingly; current message and CURRENT CONTEXT win):
{memory_section}
Conversation state: {conversation_state}
Leads (top 3): {json.dumps(leads[:3]) if leads else 'No leads yet'}
Selected response mode: {response_mode}

Response modes (must follow Selected response mode above):
- greeting: greet the user warmly first (use preferred_name at most once if present). If a usual market or last search is in memory and CURRENT CONTEXT has no place/industry yet, offer that briefly — do not list every memory. If industry is still unknown, ask for it only after the greeting — never skip the hello.
- missing_information: acknowledge any change in THIS user message (e.g. "hotels only"), then ask ONE focused question for the single missing slot. If Conversation state includes a reply hint, follow that hint. Do not repeat an identical previous ask when the user just refined the goal. If offering a remembered usual location, state the assumption — never silently apply it.
- clarification: short explanation, explicit choices, and one question.
- search_acknowledgement: restate interpreted goal and briefly mention progress.
- search_summary: briefly state what was searched and what was found, and that results are opening. Do NOT offer chat refinements, follow-up actions, or "ask me to…" next steps — the chat ends when results open.
- general_answer: answer the user's actual question first. For who-you-are / about-yourself / how-you-work questions, introduce yourself as Evecta's lead-finding assistant (discover businesses by industry and city, then pull contact-ready leads), then offer a soft choice: start with an industry, or tell you what they're selling. Do NOT skip the answer and jump straight to "what industry?".
- no_results: explain what was attempted and offer recovery options.
- error_recovery: explain what failed and the next best step.
- refinement_summary: explain what changed and what stayed the same.

Task-specific constraints:
- CURRENT CONTEXT is authoritative. History is for tone/references only — never echo a stale city/industry that conflicts with CURRENT CONTEXT.
- Ask only for a genuinely missing slot from CURRENT CONTEXT / Conversation state.
- Industry plus city is enough to proceed; country is optional.
- When naming the industry in your reply, use ONLY the clean category from CURRENT CONTEXT (e.g. "hotels") — never paste the user's full sentence ("i want to find hotels").
- If industry and location are already known, do not ask what either means. Proceed or suggest grounded alternatives.
- Answer the user's actual question with useful information. Never invent facts about a named company, person, place, or lead.
- Do not invent or echo an invalid city/country from chat history. If place is missing, ask for it cleanly.
- Treat premium/top-rated/best/luxury as a quality preference. Do not claim that ratings, reviews, or pricing are unavailable.
- If leads are present: one short findings line, then that results are opening. No chat next-actions.
- Use complete sentences and avoid excessive exclamation marks.
- When style conflicts with correctness (e.g. varied wording vs a verified city list), correctness always wins.
"""
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
            text = chunk.content if isinstance(chunk.content, str) else None
            if text is None and chunk.content:
                from app.utils.chat_stream_sink import content_to_text
                text = content_to_text(chunk.content)
            if text:
                yield text
    except Exception as e:
        from app.utils.llm_errors import LLMUnavailableError, is_llm_unavailable
        from app.utils.chat_stream_sink import emit_chat_token

        if is_llm_unavailable(e):
            raise LLMUnavailableError() from e
        if not has_industry:
            fallback = fallback_ask_industry()
        elif has_industry and not has_location and not has_country:
            fallback = fallback_ask_city_or_country(context.get("industry"))
        elif has_country and not has_location:
            fallback = fallback_ask_city_in_country(context.get("industry"), context.get("country"))
        else:
            fallback = fallback_ask_industry_and_location()
        await emit_chat_token(fallback)
        yield fallback


async def generate_human_response(
    message: str,
    context: dict,
    leads: list,
    llm: ChatGoogleGenerativeAI,
    history: list = None,
    user_id: Optional[Union[str, UUID]] = None,
    memory_block: str | None = None,
):
    """Non-streaming callers: drain generate_human_response_stream and return the full text."""
    chunks = [
        piece
        async for piece in generate_human_response_stream(
            message, context, leads, llm, history, user_id=user_id, memory_block=memory_block
        )
    ]
    return "".join(chunks).strip()
