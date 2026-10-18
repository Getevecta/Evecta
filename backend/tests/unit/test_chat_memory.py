"""Unit tests for long-term chat memory helpers (no DB required)."""

from app.services.chat_memory_service import (
    MemoryBundle,
    format_memory_for_prompt,
    greeting_reply_hint,
    personalized_greeting_fallback,
    soft_location_hint,
    wants_company_location,
)
from app.utils.chat_helper import fallback_greeting


def test_greeting_uses_usual_market_not_memory_dump():
    bundle = MemoryBundle(
        preferred_name="Sadhan",
        preferred_cities=["Kathmandu"],
        default_country="Nepal",
        frequent_industries=["hotels", "restaurants"],
        response_style="concise",
        company_name="Evecta",
        recent_searches=[],
    )
    text = personalized_greeting_fallback(bundle, {})
    assert "Sadhan" in text
    assert "Kathmandu" in text or "Nepal" in text
    # Must not dump every preference on hello.
    assert "concise" not in text.lower()
    assert "Evecta" not in text or "welcome" in text.lower()
    prompt = format_memory_for_prompt(bundle, for_greeting=True)
    assert "preferred_name" in prompt
    assert "usual_market" in prompt
    assert "response_style" not in prompt


def test_greeting_mentions_last_search_when_present():
    bundle = MemoryBundle(
        preferred_name="Sadhan",
        recent_searches=[{"industry": "hotels", "location": "Kathmandu"}],
    )
    text = personalized_greeting_fallback(bundle, {})
    assert "hotels" in text.lower()
    assert "Kathmandu" in text


def test_current_message_location_not_overridden_by_memory_hint():
    bundle = MemoryBundle(preferred_cities=["Kathmandu"])
    context = {"industry": "hotels", "location": "London"}
    assert soft_location_hint(bundle, context) is None


def test_soft_location_offer_when_place_missing():
    bundle = MemoryBundle(preferred_cities=["Kathmandu"])
    context = {"industry": "hotels"}
    hint = soft_location_hint(bundle, context)
    assert hint is not None
    assert "Kathmandu" in hint
    assert "silently" in hint.lower() or "NOT silently" in hint


def test_memory_priority_london_wins_conceptually():
    """Documented contract: saved Kathmandu + London message → London in ChatState."""
    bundle = MemoryBundle(preferred_cities=["Kathmandu"])
    context = {"industry": "hotels", "location": "London"}
    # Soft hint must not fire when ChatState already has a place.
    assert soft_location_hint(bundle, context) is None
    # Greeting hint with active goal should not restate old defaults as search slots.
    hint = greeting_reply_hint(bundle, context)
    assert "active search" in hint.lower() or "continue" in hint.lower()


def test_company_location_phrase_detected():
    assert wants_company_location("Use my company location")
    assert wants_company_location("search my company location please")
    assert not wants_company_location("find hotels in Sydney")


def test_fallback_greeting_accepts_name():
    assert "Sadhan" in fallback_greeting("Sadhan")
    assert fallback_greeting().startswith("Hi!")
