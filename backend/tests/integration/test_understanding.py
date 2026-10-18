"""
Golden-set for the single structured-output understanding call (Step 1).

These hit the real Gemini API, so they are integration tests: skipped unless
GEMINI_API_KEY is set. Assertions are intentionally lenient (case-insensitive,
substring) because the model's exact wording varies — we check the *structured
decisions* (intent, resolved slots, ambiguity/scope/quality), not phrasing.

Run:  pytest backend/tests/integration/test_understanding.py -v
"""

import asyncio
import os

import pytest

from app.services.understanding import understand, Understanding

pytestmark = pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set — skips the live understanding golden-set",
)


def _run(message, context=None, history=None) -> Understanding:
    return asyncio.run(understand(message, context or {}, history or []))


def test_ambiguous_apple_triggers_disambiguation():
    u = _run("apple leads in sydney")
    assert u.intent == "lead_search"
    assert u.ambiguous is True
    assert len(u.candidate_meanings) >= 2
    # location should resolve to Sydney
    assert (u.location or "").lower().startswith("sydney")


def test_hotel_is_specific_category_not_ambiguous():
    u = _run("hotels in sydney")
    assert u.intent in ("lead_search", "refinement")
    assert u.ambiguous is False
    assert not u.scope_family and not u.scope_siblings  # specific category → search as-is
    assert (u.location or "").lower().startswith("sydney")


def test_plain_term_is_not_ambiguous():
    u = _run("restaurants in melbourne")
    assert u.intent == "lead_search"
    assert u.ambiguous is False
    assert "restaurant" in (u.industry or "").lower()
    assert (u.location or "").lower().startswith("melbourne")


def test_spelling_is_normalized_inline():
    u = _run("resturants in katmandu")
    assert "restaurant" in (u.industry or "").lower()
    assert "kathmandu" in (u.location or "").lower()


def test_quality_qualifier_is_captured():
    u = _run("best restaurants in kathmandu")
    assert u.quality == "top_rated"
    assert "restaurant" in (u.industry or "").lower()


def test_general_question_is_classified_without_generating_reply():
    u = _run("what's the capital of france?")
    assert u.intent == "general_question"
    # no slots invented for a general question
    assert not u.industry


def test_named_company_is_classified_without_generating_reply():
    u = _run("tell me about plutonictech")
    assert u.intent == "general_question"


def test_brand_search_is_lead_search_not_general_question():
    """'search <brand> shops' must be lead_search so industry is stored (fixes industry↔location loop)."""
    u = _run("then search Proton Emas5 shops")
    assert u.intent == "lead_search"
    assert u.industry
    blob = (u.industry or "").lower()
    assert "proton" in blob or "emas" in blob


def test_carry_forward_preserves_industry_when_only_country_given():
    u = _run("Malaysia", context={"industry": "Proton Emas5 dealerships"})
    assert "proton" in (u.industry or "").lower() or "emas" in (u.industry or "").lower()
    place = ((u.country or "") + " " + (u.location or "")).lower()
    assert "malaysia" in place


def test_carry_forward_preserves_country_when_only_industry_given():
    u = _run("Proton Emas 5", context={"country": "Malaysia"})
    assert u.industry
    assert "malaysia" in ((u.country or "") + " " + (u.location or "")).lower()


def test_greeting_intent():
    assert _run("hi").intent == "greeting"


def test_negation_intent():
    assert _run("no").intent == "negate"


def test_carry_forward_preserves_industry_when_only_city_given():
    u = _run("delhi", context={"industry": "restaurants"})
    assert "restaurant" in (u.industry or "").lower()   # carried forward
    assert (u.location or "").lower().startswith("delhi")


def test_new_city_without_country_clears_stale_country():
    u = _run("mumbai", context={"industry": "restaurants", "country": "Nepal"})
    assert (u.location or "").lower().startswith("mumbai")
    assert not u.country     # stale "Nepal" must be dropped


def test_clarification_choice_resolves_to_chosen_meaning():
    ctx = {
        "industry": "apple", "location": "Sydney",
        "ambiguous": True, "awaiting_clarification": True,
        "candidate_meanings": [
            {"label": "Apple product / Mac stores",
             "search_terms": ["apple store", "electronics store"], "why": ""},
            {"label": "Apple fruit suppliers",
             "search_terms": ["fruit wholesaler", "produce supplier"], "why": ""},
        ],
    }
    history = [
        {"role": "user", "message": "apple leads in sydney"},
        {"role": "assistant", "message": '"apple" can mean different businesses in Sydney:\n'
                                         "1. Apple product / Mac stores\n2. Apple fruit suppliers\n\nWhich did you mean?"},
    ]
    u = _run("the stores", context=ctx, history=history)
    assert u.ambiguous is False                              # resolved, not re-flagged
    blob = ((u.industry or "") + " " + " ".join(u.search_terms or [])).lower()
    assert any(w in blob for w in ("store", "mac", "electronics"))   # chose the products meaning
    assert (u.location or "").lower().startswith("sydney")   # location carried forward


def test_specific_category_hotels_has_no_scope():
    u = _run("hotels in sydney")
    assert not u.scope_family and not u.scope_siblings


def test_specific_category_yoga_studios_has_no_scope():
    u = _run("yoga studios in melbourne")
    assert not u.scope_family and not u.scope_siblings


def test_broad_family_accommodation_triggers_scope():
    u = _run("accommodation in sydney")
    assert u.scope_family
    assert len(u.scope_siblings) >= 2


def test_broad_family_fitness_triggers_scope():
    u = _run("fitness businesses in melbourne")
    assert u.scope_family
    assert len(u.scope_siblings) >= 2


def test_plain_term_is_not_a_family():
    u = _run("dentists in delhi")
    assert not u.scope_family and not u.scope_siblings   # plain term → no scope question


def test_scope_answer_resolves():
    ctx = {"industry": "accommodation", "location": "Sydney", "scope_family": "accommodation",
           "awaiting_scope": True, "scope_siblings": ["hotel", "motel", "resort", "hostel"]}
    hist = [
        {"role": "user", "message": "accommodation in sydney"},
        {"role": "assistant", "message": "Should I search hotels, resorts, motels, hostels, or all accommodation?"},
    ]
    assert _run("just hotels", context=ctx, history=hist).scope_choice == "narrow"
    assert _run("include all of them", context=ctx, history=hist).scope_choice == "all"


def test_unsolicited_only_hotels_sets_narrow_scope():
    """'Only hotels' while waiting for a city must narrow exactly — no family expand."""
    ctx = {"industry": "hotels", "location": None, "country": None}
    hist = [
        {"role": "user", "message": "I am looking for hotels."},
        {"role": "assistant", "message": "Which city or country should I search for hotels in?"},
    ]
    u = _run("Can you find only hotels?", context=ctx, history=hist)
    assert u.scope_choice == "narrow"
    assert not u.scope_family and not u.scope_siblings
    assert "hotel" in (u.industry or "").lower()
    assert not u.location  # still missing — do not invent a city
