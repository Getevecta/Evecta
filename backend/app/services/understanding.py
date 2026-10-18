"""
Single structured-output "understanding" call.

Replaces the previous chain of narrow LLM calls (is_general_question +
run_extraction + extract_industry_from_history + suggest_correction x3) and the
~170-line hand-written merge block in chat_service.chat_logged_in.

ONE Gemini call now returns the user's intent, the fully-resolved (carry-forward)
search slots, spelling-normalized values, and — captured but NOT yet acted on in
Step 1 — ambiguity / scope / quality signals for later steps.
"""

import json
import logging
from typing import Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import get_settings
from app.services.ai.tracked_llm import tracked_ainvoke, llm_model_name

from app.utils.chat_helper import CHAT_PERSONA
from app.utils.chat_history import format_chat_history_for_prompt
from app.utils.llm_errors import LLMUnavailableError, is_llm_unavailable

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------------
class Meaning(BaseModel):
    """One possible business interpretation of an ambiguous keyword (e.g. apple)."""
    label: str = Field(description="Short human label, e.g. 'Apple product / Mac stores'")
    search_terms: list[str] = Field(default_factory=list, description="<=3 Places/Overture keywords for this meaning")
    why: str = Field(default="", description="One-line reason this meaning is plausible")


class Understanding(BaseModel):
    """The full result of reading one user message in context."""

    intent: Literal[
        "lead_search", "refinement", "general_question", "greeting", "affirm", "negate"
    ] = Field(description="What the user is trying to do with THIS message")

    goal: str | None = Field(default=None, description="One-line plain-English resolved goal, if a search")

    # Only read on the general_question branch, to decide whether the question can be
    # answered from Evecta's own documentation or gets the existing redirect.
    about_evecta: bool = Field(
        default=False,
        description="true when the user is asking about THIS product — how Evecta works, what a feature does, billing, credits, plans, limits — rather than a general-knowledge or third-party question",
    )

    # A narrower case inside about_evecta: the user is asking who or what the
    # assistant is, rather than about a product feature. Read only when retrieval
    # finds nothing, to answer "who are u" with a self-description instead of "not
    # documented". This is a model field rather than a regex because the phrasings
    # are short and typo-prone ("what di u do", "who r u") and a pattern list is
    # always one typo behind; the model already reads the message.
    about_assistant: bool = Field(
        default=False,
        description="true when the user is asking who or what YOU (the assistant) are, or what you can do for them, rather than asking about a specific Evecta feature",
    )

    # Resolved slots — the model carries unchanged slots forward and applies
    # spelling correction inline. `country` is null when it should be cleared.
    industry: str | None = Field(
        default=None,
        description=(
            "business type/category ONLY (e.g. hotels, restaurants) — never a chat sentence. "
            "For lead_search/refinement fill when the message names a type. "
            "Null means no change this turn (backend keeps the active goal), not 'clear industry'."
        ),
    )
    location: str | None = None          # city; null = no change this turn unless clearing invalid place
    country: str | None = None           # COUNTRY only; null = no change, or clear after a new city
    search_terms: list[str] = Field(default_factory=list)   # <=3 keywords
    radius_km: float | None = Field(
        default=None,
        description="requested search radius in KILOMETERS: 'within 10 km' -> 10; convert miles to km (N miles -> N*1.609). null if the user gave no radius.",
    )
    anchor: str | None = Field(
        default=None,
        description="a specific center point WITHIN the city to search around — a neighborhood/area/landmark the user names, e.g. 'near Thapathali' -> 'Thapathali'. Keep the CITY in `location`. null if no specific area is named.",
    )

    # Captured but NOT acted on in Step 1 (Step 3 / silent-now features):
    quality: Literal["any", "top_rated", "premium", "budget"] | None = None
    ambiguous: bool = False
    candidate_meanings: list[Meaning] = Field(default_factory=list)
    scope_family: str | None = Field(
        default=None,
        description="short family label ONLY when the user explicitly requested a broad umbrella family (e.g. accommodation, education providers, fitness businesses); null for a specific category like hotels or yoga studios",
    )
    scope_siblings: list[str] = Field(
        default_factory=list,
        description="for an explicit broad-family request, related member search terms to optionally include; empty when scope_family is null",
    )
    scope_choice: Literal["all", "narrow"] | None = Field(
        default=None,
        description=(
            "set to 'narrow' when the user explicitly restricts to the exact category "
            "('only hotels', 'just hotels', 'hotels only') — even without a pending scope "
            "question; set to 'all' only when answering AWAITING SCOPE by including the family; "
            "null otherwise"
        ),
    )
    reasoning: str | None = Field(default=None, description="Short rationale, logged only")


# ----------------------------------------------------------------------------
# LLM (lazy) — structured extraction wants determinism, not creative wording.
# Conversational replies use a separate LLM (chat.py / generate_human_response)
# at higher temperature.
# ----------------------------------------------------------------------------
_understand_llm = None
 

def _get_understand_llm():
    global _understand_llm
    if _understand_llm is None:
        settings = get_settings()
        base = ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            # Intent/slot extraction must be stable turn-to-turn (industry, city,
            # scope). Chat phrasing is handled elsewhere at higher temperature.
            temperature=0,
            # LangChain defaults to 6 retries with exponential backoff (~67s). A 429
            # for depleted credits never recovers, so fail fast and let the chat
            # fallback answer instead of hanging the user's request.
            max_retries=1,
        )
        # json_mode (native JSON response) instead of the default function-calling:
        # langchain-google-genai 2.1.12 can't parse Gemini 3.x function-call responses
        # (returns None -> every understand() call fell back to a slotless lead_search).
        # include_raw=True keeps the AIMessage (and usage_metadata) for token tracking.
        _understand_llm = base.with_structured_output(
            Understanding, method="json_mode", include_raw=True
        )
    return _understand_llm


# ----------------------------------------------------------------------------
# Prompt
# ----------------------------------------------------------------------------
def _format_history(history: list | None) -> str:
    """Prior turns only (current message is passed separately), capped like other chat prompts."""
    prior = history[:-1] if history else None
    return format_chat_history_for_prompt(prior)


def build_understanding_prompt(
    message: str,
    context: dict,
    history: list | None,
    memory_block: str | None = None,
) -> str:
    known = []
    if context.get("industry"):
        known.append(f"industry={context.get('industry')}")
    if context.get("location"):
        known.append(f"location={context.get('location')}")
    if context.get("country"):
        known.append(f"country={context.get('country')}")
    if context.get("search_terms"):
        known.append(f"search_terms={context.get('search_terms')}")
    known_str = ", ".join(known) if known else "none"

    pending = ""
    if context.get("awaiting_clarification") and context.get("candidate_meanings"):
        opts = "; ".join(
            f"{i + 1}. {m.get('label')} (terms: {m.get('search_terms')})"
            for i, m in enumerate(context["candidate_meanings"])
        )
        pending = (
            "\nAWAITING CLARIFICATION — the assistant just asked the user to choose among these "
            f"meanings: {opts}. If THIS message picks one (by number, label, or keyword), resolve "
            "to that meaning: set industry + search_terms accordingly and ambiguous=false. If instead "
            "the user names a DIFFERENT business type or keyword (e.g. switches from 'apple' to "
            "'amazon'), treat it as a NEW lead_search for that keyword and re-run ambiguity detection "
            "on it — do NOT treat a new business keyword as general_question/off-topic.\n"
        )

    pending_scope = ""
    if context.get("awaiting_scope"):
        ind = context.get("industry") or "the businesses"
        pending_scope = (
            f"\nAWAITING SCOPE — the assistant asked whether to include the broader "
            f"{context.get('scope_family')} family or just {ind}. If THIS message answers, set "
            f"scope_choice='all' (include them / yes / everything / sure) or 'narrow' (just/only "
            f"{ind}). Otherwise leave scope_choice null.\n"
        )

    pending_confirm = ""
    if context.get("awaiting_confirmation"):
        pending_confirm = (
            "\nAWAITING CONFIRMATION — the assistant asked once before searching. Classify THIS message:\n"
            "  - READY TO SEARCH (go / yes / search / show me / sounds good / do it) -> intent='affirm'.\n"
            "  - REFINING the search (best/premium, different city or industry, radius, anchor) -> "
            "intent='refinement' or 'lead_search' and update the slots. Do NOT ask them to say go again.\n"
            "  - Unrelated chit-chat -> intent='general_question' or 'greeting'.\n"
        )

    return f"""{CHAT_PERSONA}

Your task is to read one message from a user of a B2B lead-generation tool and return a single structured result. Do not write a conversational reply; only classify intent and extract the structured fields.

PRECEDENCE: THIS user message > CURRENT RESOLVED GOAL > explicit long-term memory > profile > recent searches > history. History and memory are for tone/defaults only — never re-apply an older industry/city that conflicts with the current goal or this message.

CURRENT RESOLVED GOAL (carry these forward unless the user changes them): {known_str}
LONG-TERM MEMORY (defaults only; do not invent slots from memory when the user named something else):
{(memory_block or context.get("_memory_prompt") or "None").strip() or "None"}
{pending}{pending_scope}{pending_confirm}
CONVERSATION HISTORY:
{_format_history(history)}

CURRENT USER MESSAGE: "{message}"

Fill EVERY field. Rules:

INTENT (pick exactly one):
- "lead_search"      = user is giving an industry/business type and/or a location to search.
- "refinement"       = user is narrowing/adjusting an in-progress search ("only premium", "just hotels", a new city for the same industry).
- "general_question" = a question or chit-chat NOT providing search slots ("what is mining?", "how does this work?", "what's the capital of france?", "tell me about <company>").
- "greeting"         = a bare greeting/thanks/bye, including elongated forms ("hi", "hello", "hellooo", "hey", "thanks").
- "affirm"           = a bare yes/ok/sure agreeing to proceed.
- "negate"           = a bare no/nope/nah declining a suggestion.

SLOTS (industry, location, country, search_terms, radius_km, anchor) — DELTA SEMANTICS:
- These fields are updates relative to CURRENT RESOLVED GOAL. The backend merges them; it keeps any active-goal field you do not change.
- Null / omitted on greeting, negate, affirm, or general_question means "no change this turn" — NOT "erase the active search." The backend retains existing industry/location.
- industry must be the BUSINESS CATEGORY only (e.g. "hotels", "restaurants") — NEVER a chat sentence or intent phrase like "i want to find hotels", "can you help me find hotels", or "i want to hotels". Strip filler and keep the category noun.
- For lead_search / refinement: CARRY FORWARD every slot from the CURRENT RESOLVED GOAL that the user did NOT change. If the user only gives a city, keep the existing industry; if they only give an industry, keep the existing city.
- If the user RESTATES the same category while a location is still missing ("i want to find hotels" after already saying hotels), keep industry as that clean category and leave location null — do not replace industry with the full sentence.
- NEVER wipe a known slot unless the user clearly replaces it (or you are clearing a stale country after a new city — see below). A message that only supplies a location/country (or a bare yes/ok/go) MUST keep the existing industry.
- CONFUSING / PARTIAL CHAT: users often give industry and location across messy turns ("Proton Emas5", then "Malaysia", then "Proton Emas 5" again). ALWAYS keep whichever slots are already in CURRENT RESOLVED GOAL and fill only what is still missing.
- Only change a field the user actually changed.
- When the user gives a NEW city WITHOUT naming a country, set "country" to null (so a stale country is dropped — "Mumbai" must not become "Mumbai, Nepal"). This is an explicit clear of country only.
- "country" holds a COUNTRY name only (e.g. "Australia"); a state/region/city goes in "location".
- location/country MUST be real geographic place names only (city, town, region, or country). Decide from meaning, not a word list: if the user is chatting, being polite, affirming, or asking for help ("please", "thanks", "make my mood better", "sure"), leave location and country null (no change / not a place). NEVER set location/country to chat phrases, refusals, industry talk, or incomplete stubs — e.g. reject "no no i want chocolate", "i want chocolate", "tell me about yourself", "chocolate in", "change city", "start over". If the user has not clearly named a place, leave location and country null.
- When the assistant just asked for a city/country and the user replies with a real place ("Melbourne", "Sydney", "Nepal"), set location or country accordingly. When they reply with anything that is not a place, leave those slots null and keep the known industry.
- Continents and large regions (Africa, Asia, Europe, North America, South America, etc.) are NOT searchable cities. Put them in country (or location) so the app can suggest cities — never treat a continent as a finished search target.
- If the user asks you to SUGGEST / RECOMMEND cities in a country or continent, still fill industry + that region in the slots; do not invent a specific city yourself in the structured output.
- If CURRENT RESOLVED GOAL already has a nonsensical location/country (chat text, not a place), IGNORE it and set that slot to null until the user names a real city.
- Apply SPELLING CORRECTION inline and ALWAYS fix an obviously misspelled city/location to the correct real place name — a wrong spelling breaks geocoding and must never pass through. e.g. "katmandu"->"Kathmandu", "banglore"->"Bangalore", "resturant"->"restaurant"; a correctly-spelled name like "bangkok" stays.
- "search_terms" = up to 3 broad Places/Overture keywords that resolve the user's intent (not just the literal words). e.g. "ethanol factories" -> ["chemical manufacturer","distillery","industrial alcohol supplier"].
- For a lead_search or refinement, ALWAYS fill industry when the message names a business type ("restaurants in berlin" -> industry="restaurants"). Never return a null industry for a clear business search.
- RADIUS: if the user gives a search distance ("within 10 km", "10km radius", "5 miles"), set radius_km (convert miles->km: N miles = N*1.609). null if no distance is given.
- ANCHOR: if the user names a specific AREA / NEIGHBOURHOOD / LANDMARK to search around within the city ("near Thapathali", "around Bondi", "close to the airport"), set anchor to that place and keep the CITY in location. null if they only give the city.
- For greeting / negate / general_question (non-search): leave slots null to mean no slot updates this turn (backend keeps the active goal). Do not invent slots. Exception: BRAND/ENTITY lead searches — see below.

ABOUT_EVECTA (only matters when intent="general_question"; leave false otherwise):
- true when the question is about THIS product — how Evecta works, what a feature does, how to do something in it, credits, billing, plans, limits, mailboxes, campaigns, data sources ("how does this work?", "do searches use my credits?", "how do I connect my mailbox?", "what's in the growth plan?").
- false for general world knowledge, other companies, and chit-chat ("what's the capital of france?", "what is mining?", "tell me about Proton").
- false when the user is asking about THIS CONVERSATION rather than the product — what they asked earlier, what was said, a summary or conclusion of the chat so far, or "more detail" on one of their own earlier messages ("from the second message, can u give me more detail?", "what have we asked so far?", "from the earlier messages what is the conclusion", "can u give me more detail on that"). These need the conversation itself to answer, which the documentation path does not have, so routing them there produces a refusal. Judge this on what the user is pointing AT — an earlier message rather than a feature — not on what the surrounding turns happened to be about: a run of product questions does not make a question about those questions a product question.
- The word "prompt" alone does not make a question conversational. A lead-generation prompt, a search prompt, or a lead prompt is an Evecta FEATURE — the text a user writes to describe the businesses they want — so "what should I include in a lead-generation prompt?" and "how do I write a good prompt?" are about_evecta=true. Only treat "prompt" as conversational when it clearly points at a message the user already sent ("the second prompt I asked").

ABOUT_ASSISTANT (a narrower case inside about_evecta; leave false otherwise):
- true when the user is asking who or what YOU are, or what you can do for them — "who are you", "who r u", "what di u do", "what can u do for us", "introduce yourself", "what services do you provide". Judge the intent, not the spelling: these arrive misspelled and abbreviated more than any other question.
- false when the question names a specific feature or topic, even if phrased at you — "how do you generate emails?", "what plans do you offer?", "how much does it cost?" are about_evecta but NOT about_assistant.

QUALITY: if the user uses a quality word, set quality ("best"/"top rated"->"top_rated", "premium"/"luxury"->"premium", "cheap"/"budget"->"budget"); else null.

AMBIGUITY: if the keyword has 2+ genuinely DIFFERENT business meanings (e.g. apple=Apple Inc. stores vs apple=fruit; amazon, shell, jaguar), set ambiguous=true and list candidate_meanings (label + search_terms + why). A plain-but-broad term like "hotel" or "restaurant" is NOT ambiguous. If an AWAITING CLARIFICATION block is present and the user is answering it, do NOT re-flag ambiguity — resolve to the chosen meaning with ambiguous=false. This rule applies to EVERY ambiguous keyword, not just the examples.
- Provide candidate_meanings with clear labels and search_terms (these are the pickable options).
- Good labels are specific business meanings, e.g. "Shell Oil/gas stations" and "seafood/shellfish businesses"; "computer mouse/computer peripherals" and "pest control for mice".

SCOPE: only ask about family breadth when the user EXPLICITLY requested a broad business FAMILY — not a specific category. If they named a specific member, leave scope_family null and search that category exactly.
- IMPORTANT: Do NOT set scope_family just because a specific category has siblings a buyer might also want. The user already chose the category — search it as-is.
- Do NOT set scope_family for specific requested categories, even if they belong to a larger family. Examples that must stay scope_family=null:
  * hotels, resorts, motels, hostels, guesthouses, B&Bs
  * yoga studios, gyms, pilates studios, personal training studios
  * schools, preschools, colleges, tutoring centers
  * clinics, medical centers, urgent care centers
  * travel agencies, tour operators, visa consultants
  * dentists, pharmacies, accountants, restaurants, coffee shops, plumbers, electricians
- Set scope_family AND scope_siblings ONLY when the user used an explicitly broad/umbrella family term. This must be dynamic common-sense taxonomy, not a fixed list. Examples:
  * "accommodation" / "lodging" / "places to stay" -> scope_family="accommodation"; siblings e.g. hotels, resorts, motels, hostels, guesthouses, B&Bs
  * "education providers" / "education businesses" -> scope_family="education"; siblings e.g. schools, preschools, colleges, tutoring centers
  * "healthcare facilities" / "medical facilities" -> scope_family="healthcare facilities"; siblings e.g. clinics, medical centers, urgent care
  * "fitness businesses" / "fitness facilities" / "wellness businesses" -> scope_family="fitness"; siblings e.g. gyms, yoga studios, personal trainers, pilates studios
  * "travel services" -> scope_family="travel services"; siblings e.g. travel agencies, tour operators, visa consultants
- scope_siblings should contain 3-6 practical member search terms (lowercase) covering the family.
- EXPLICIT NARROW (even when NOT awaiting scope): if the user says "only X", "just X", "X only", "exactly X", or "find only X" (e.g. "Can you find only hotels?"), set scope_choice='narrow', scope_family=null, scope_siblings=[], industry=X, and search_terms=[X] (exact category only). Do not treat this as a brand-new search that forgets the missing location — carry forward known slots and leave location null if still unknown.

BRAND/ENTITY:
- Pure info ask about a company/brand ("tell me about Proton", "what is PlutonicTech?") → general_question and redirect; do NOT fabricate company details; leave slots null.
- Search/find ask naming a brand, product, or shop type ("search Proton Emas5 shops", "find Apple stores", "Proton dealerships", "looking for Emas5 car dealers") → intent=lead_search (NOT general_question). Set industry to that brand/shop type (e.g. "Proton Emas5 dealerships"), fill search_terms, and CARRY FORWARD any known location/country. Do not invent company facts — just treat the name as the lead category to search.
"""


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
async def understand(
    message: str,
    context: dict,
    history: list | None = None,
    user_id: Optional[Union[str, UUID]] = None,
) -> Understanding:
    """Run the single structured-output understanding call.

    Raises ``LLMUnavailableError`` when Gemini quota/billing/429 blocks the call.
    Other failures fall back to a plain ``lead_search`` understanding.
    """
    settings = get_settings()
    try:
        prompt = build_understanding_prompt(message, context or {}, history)
        llm = _get_understand_llm()
        result = await tracked_ainvoke(
            llm=llm,
            prompt=prompt,
            provider="gemini",
            model=llm_model_name(llm, fallback=settings.GEMINI_MODEL),
            feature="chat_understanding",
            user_id=user_id,
        )
        # include_raw=True → {"raw": AIMessage, "parsed": Understanding|None, "parsing_error": ...}
        if isinstance(result, dict) and ("parsed" in result or "raw" in result):
            parsed = result.get("parsed")
            if isinstance(parsed, Understanding):
                return parsed
            if isinstance(parsed, dict):
                return Understanding(**parsed)
            if result.get("parsing_error"):
                logger.warning(
                    "[UNDERSTAND] structured parse error: %s", result.get("parsing_error")
                )
            # Fall through to coerce from raw content if possible
            raw = result.get("raw")
            content = getattr(raw, "content", None) if raw is not None else None
            if isinstance(content, str) and content.strip():
                return Understanding(**json.loads(content))
            raise ValueError("structured output returned no parsed Understanding")
        if isinstance(result, Understanding):
            return result
        if isinstance(result, dict):
            return Understanding(**result)
        return Understanding(**json.loads(result))  # last resort
    except LLMUnavailableError:
        raise
    except Exception as e:
        if is_llm_unavailable(e):
            logger.warning("[UNDERSTAND] LLM unavailable: %s", e)
            raise LLMUnavailableError() from e
        logger.warning("[UNDERSTAND] failed, falling back to lead_search: %s", e)
        # Safe default: behave like a plain lead-search turn with no new slots,
        # so the existing carry-forward guards preserve context unchanged.
        return Understanding(intent="lead_search")
