from app.services.chat_service import _display_title, build_chat_title
from app.utils.chat_helper import (
    fallback_ack_narrow_ask_location,
    fallback_ask_city_or_country,
    fallback_greeting,
)


def test_display_title_keeps_possessive_s_lowercase():
    assert _display_title("john's bakery") == "John's Bakery"


def test_display_title_keeps_nonpossessive_apostrophe_capitalization():
    assert _display_title("o'reilly media") == "O'Reilly Media"


def test_chat_title_formats_apostrophes_across_industry_and_location():
    assert (
        build_chat_title("john's restaurants", "st. john's", None)
        == "John's Restaurants in St. John's"
    )


def test_location_ask_after_narrow_acknowledges_constraint():
    first = fallback_ask_city_or_country("hotels")
    after_only = fallback_ack_narrow_ask_location("hotels")
    assert "city" in first.lower() or "country" in first.lower()
    assert "hotels" in first.lower()
    assert after_only != first
    assert "only" in after_only.lower()
    assert "hotels" in after_only.lower()


def test_location_ask_never_interpolates_chat_sentence():
    ask = fallback_ask_city_or_country("i want to hotels")
    assert "i want" not in ask.lower()
    assert "those businesses" in ask.lower()


def test_fallback_greeting_is_a_real_greeting():
    text = fallback_greeting().lower()
    assert text.startswith("hi")
    assert "industry" in text
    assert "help" in text


def test_about_assistant_fallback_introduces_evecta():
    from app.utils.chat_helper import fallback_about_assistant, _looks_like_about_assistant, _pick_response_mode

    text = fallback_about_assistant()
    assert "Evecta" in text
    assert "industry" in text.lower()
    assert "selling" in text.lower()
    assert _looks_like_about_assistant("can you tell me about yourself")
    assert _looks_like_about_assistant("who are you?")
    assert not _looks_like_about_assistant("find hotels in sydney")
    assert _pick_response_mode(message="tell me about yourself", context={}, leads=[]) == "general_answer"
