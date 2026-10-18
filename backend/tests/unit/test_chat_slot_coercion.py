"""Unit tests for chat industry/location slot coercion (no LLM)."""

from app.services.chat_service import (
    backfill_industry_from_history,
    coerce_search_understanding,
    merge_basic_slots,
    message_looks_like_lead_search,
    sanitize_industry_label,
    _industry_phrase_from_search_message,
    _looks_like_bare_greeting,
)
from app.services.understanding import Understanding


def test_message_looks_like_lead_search():
    assert message_looks_like_lead_search("then search Proton Emas5 shops")
    assert message_looks_like_lead_search("find Apple stores")
    assert message_looks_like_lead_search("looking for car dealerships")
    assert not message_looks_like_lead_search("How is proton emas 5?")
    assert not message_looks_like_lead_search("Malaysia")


def test_industry_phrase_from_search_message():
    phrase = _industry_phrase_from_search_message("then search Proton Emas5 shops")
    assert phrase is not None
    assert "proton" in phrase.lower()
    assert "emas5" in phrase.lower().replace(" ", "")


def test_industry_phrase_strips_want_to_find_filler():
    assert _industry_phrase_from_search_message("i want to find hotels") == "hotels"
    assert _industry_phrase_from_search_message("can you help me find hotels") == "hotels"
    assert sanitize_industry_label("i want to hotels", "hotels") == "hotels"
    assert sanitize_industry_label("hotels") == "hotels"


def test_bare_greeting_detection():
    assert _looks_like_bare_greeting("hi")
    assert _looks_like_bare_greeting("hellooo")
    assert _looks_like_bare_greeting("Hey!")
    assert not _looks_like_bare_greeting("hi find hotels")
    assert not _looks_like_bare_greeting("hotels")

def test_coerce_brand_search_general_question_to_lead_search():
    u = Understanding(
        intent="general_question",
        industry=None,
    )
    out = coerce_search_understanding(u, "then search Proton Emas5 shops", {})
    assert out.intent == "lead_search"
    assert out.industry
    assert "proton" in out.industry.lower()


def test_coerce_preserves_known_location_on_brand_search():
    u = Understanding(intent="general_question", industry=None)
    ctx = {"country": "Malaysia"}
    out = coerce_search_understanding(u, "search Proton Emas5 shops", ctx)
    assert out.intent == "lead_search"
    assert out.country == "Malaysia"


def test_coerce_bare_industry_when_place_known():
    u = Understanding(intent="general_question", industry=None)
    ctx = {"country": "Malaysia"}
    out = coerce_search_understanding(u, "Proton Emas 5", ctx)
    assert out.intent == "lead_search"
    assert out.industry == "Proton Emas 5"
    assert out.country == "Malaysia"


def test_coerce_leaves_pure_info_question_alone():
    u = Understanding(intent="general_question", industry=None)
    out = coerce_search_understanding(u, "tell me about Proton", {})
    assert out.intent == "general_question"


def test_merge_basic_slots_does_not_wipe_known_industry():
    ctx = {"industry": "Proton Emas5 shops", "location": None}
    u = Understanding(intent="lead_search", industry=None, country="Malaysia")
    merge_basic_slots(ctx, u)
    assert ctx["industry"] == "Proton Emas5 shops"
    assert ctx["country"] == "Malaysia"


def test_merge_basic_slots_does_not_wipe_known_country():
    ctx = {"industry": None, "country": "Malaysia"}
    u = Understanding(intent="lead_search", industry="Proton Emas 5", country=None)
    merge_basic_slots(ctx, u)
    assert ctx["industry"] == "Proton Emas 5"
    assert ctx["country"] == "Malaysia"


def test_backfill_industry_from_history():
    ctx: dict = {}
    history = [
        {"role": "user", "message": "How is proton emas 5?"},
        {"role": "assistant", "message": "Outside my lane…"},
        {"role": "user", "message": "then search Proton Emas5 shops"},
        {"role": "assistant", "message": "Which city or country?"},
        {"role": "user", "message": "Malaysia"},
    ]
    backfill_industry_from_history(ctx, history)
    assert ctx.get("industry")
    assert "proton" in ctx["industry"].lower()


def test_backfill_skips_when_industry_already_set():
    ctx = {"industry": "restaurants"}
    history = [{"role": "user", "message": "search Proton Emas5 shops"}]
    backfill_industry_from_history(ctx, history)
    assert ctx["industry"] == "restaurants"


def test_shops_without_search_verb_is_lead_search():
    from app.services.chat_service import coerce_search_understanding
    from app.services.understanding import Understanding

    u = Understanding(intent="general_question", industry=None)
    out = coerce_search_understanding(u, "Proton Emas5 shops", {})
    assert out.intent == "lead_search"
    assert "proton" in (out.industry or "").lower()


def test_coerce_bare_place_when_industry_known():
    from app.services.understanding import Understanding

    u = Understanding(intent="general_question", industry=None)
    ctx = {"industry": "Proton Emas5 dealerships"}
    out = coerce_search_understanding(u, "Malaysia", ctx)
    assert out.intent == "lead_search"
    assert out.country == "Malaysia"
    assert "proton" in (out.industry or "").lower()


def test_recover_slots_from_confusing_history():
    from app.services.chat_service import recover_slots_from_history

    ctx: dict = {}
    history = [
        {"role": "user", "message": "How is proton emas 5?"},
        {"role": "assistant", "message": "That's outside my lane."},
        {"role": "user", "message": "then search Proton Emas5 shops"},
        {
            "role": "assistant",
            "message": "I can search for Proton Emas5 shops. Which city or country?",
        },
        {"role": "user", "message": "Malaysia"},
        {
            "role": "assistant",
            "message": "What industry are you interested in finding leads for in Malaysia?",
        },
    ]
    recover_slots_from_history(ctx, history)
    assert ctx.get("industry")
    assert "proton" in ctx["industry"].lower()
    assert ctx.get("country") == "Malaysia"


def test_info_question_not_coerced():
    from app.services.understanding import Understanding

    u = Understanding(intent="general_question")
    out = coerce_search_understanding(u, "How is proton emas 5?", {})
    assert out.intent == "general_question"

