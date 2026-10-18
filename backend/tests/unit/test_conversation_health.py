"""Unit tests for conversation health / stuck-loop detection."""

from app.utils.chat_recovery import build_stuck_recovery
from app.utils.conversation_health import (
    PENDING_ASK_STUCK,
    SAME_USER_MSG_STUCK,
    is_conversation_stuck,
    known_slots_summary,
    note_no_results,
    note_pending_ask,
    note_progress,
    note_user_turn,
    parse_industry_missing_city,
)
from app.services.chat_service import coerce_search_understanding
from app.services.understanding import Understanding


def test_same_user_message_triggers_stuck():
    ctx: dict = {}
    note_user_turn(ctx, "dentists in kathmandu")
    assert not is_conversation_stuck(ctx)
    note_user_turn(ctx, "dentists in kathmandu")
    assert ctx["health_same_user_msg_count"] >= SAME_USER_MSG_STUCK
    assert is_conversation_stuck(ctx)


def test_pending_ask_streak_triggers_stuck():
    ctx: dict = {}
    for _ in range(PENDING_ASK_STUCK):
        note_pending_ask(ctx, "location")
    assert is_conversation_stuck(ctx)


def test_pending_ask_resets_when_kind_changes():
    ctx: dict = {}
    note_pending_ask(ctx, "industry")
    note_pending_ask(ctx, "industry")
    note_pending_ask(ctx, "location")
    assert ctx["health_pending_ask_count"] == 1
    assert ctx["health_ask_kind"] == "location"
    assert not is_conversation_stuck(ctx)


def test_corrections_trigger_stuck():
    ctx: dict = {}
    note_user_turn(ctx, "no I meant dentists")
    note_user_turn(ctx, "I said restaurants not that")
    # Second turn also matches "i said" — count should reach threshold
    note_user_turn(ctx, "that's wrong city")
    assert is_conversation_stuck(ctx)


def test_industry_refinement_is_not_a_stuck_correction():
    """'no no i want chocolate' is refining industry — must not trip correction stuck."""
    ctx: dict = {}
    note_user_turn(ctx, "no no i want chocolate")
    note_user_turn(ctx, "no no i want chocolate shops")
    assert int(ctx.get("health_correction_count") or 0) == 0


def test_looks_like_valid_place():
    from app.utils.conversation_health import looks_like_valid_place, scrub_invalid_place_slots

    assert looks_like_valid_place("Kathmandu")
    assert looks_like_valid_place("New York")
    assert not looks_like_valid_place("no no i want chocolate")
    assert not looks_like_valid_place("ho no i want chocolate!")
    assert not looks_like_valid_place("can you tell me about yourself")
    assert not looks_like_valid_place("chocolate in")
    assert not looks_like_valid_place("i want chocolate")
    assert not looks_like_valid_place("change city")
    assert not looks_like_valid_place("yes")
    assert not looks_like_valid_place("ok")
    # Structural gate alone may allow short tokens like "please"; place-vs-chat
    # decisions are made by understand() + map confirmation, not a word list.
    ctx = {"industry": "chocolate", "location": "no no i want chocolate", "confirmed_goal": "x"}
    assert scrub_invalid_place_slots(ctx) is True
    assert "location" not in ctx
    assert "confirmed_goal" not in ctx
    assert ctx["industry"] == "chocolate"


def test_coerce_does_not_promote_raw_chat_into_country():
    """'please' must not become a country just because we asked for a city."""
    u = Understanding(intent="general_question", industry=None, location=None, country=None)
    out = coerce_search_understanding(u, "please", {"industry": "hotels"})
    assert out.intent == "general_question"
    assert not out.location
    assert not out.country


def test_parse_industry_missing_city():
    assert parse_industry_missing_city("chocolate in") == "chocolate"
    assert parse_industry_missing_city("dentists in ") == "dentists"
    assert parse_industry_missing_city("dentists in Kathmandu") is None
    assert parse_industry_missing_city("hello") is None


def test_stuck_recovery_change_city_message():
    ctx = {"industry": "chocolate", "location": "no no i want chocolate"}
    payload = build_stuck_recovery(ctx)
    assert "no no i want chocolate" not in payload["message"]
    assert "chocolate" in payload["message"]
    by_id = {a["id"]: a for a in payload["actions"]}
    assert "confirm_current" not in by_id  # no Keep with garbage location
    assert by_id["change_location"]["message"] == "change city"
    assert by_id["start_over"]["message"] == "start over"


def test_change_city_command_clears_place():
    from app.services.chat_service import _apply_change_city_command, _apply_incomplete_in_query

    ctx = {"industry": "chocolate", "location": "no no i want chocolate", "country": "Nepal"}
    assert _apply_change_city_command(ctx, "change city")
    assert "location" not in ctx
    assert "country" not in ctx
    assert ctx["industry"] == "chocolate"
    assert ctx.get("_force_ask_location") is True

    ctx2: dict = {"location": "garbage city phrase that is long enough to be invalid maybe"}
    assert _apply_incomplete_in_query(ctx2, "chocolate in")
    assert ctx2["industry"] == "chocolate"
    assert "location" not in ctx2
    assert ctx2.get("_force_ask_location") is True


def test_no_results_trigger_stuck():
    ctx: dict = {}
    note_no_results(ctx)
    assert not is_conversation_stuck(ctx)
    note_no_results(ctx)
    assert is_conversation_stuck(ctx)


def test_note_progress_clears_stuck():
    ctx: dict = {"industry": "dentists", "location": "Kathmandu"}
    note_pending_ask(ctx, "location")
    note_pending_ask(ctx, "location")
    note_pending_ask(ctx, "location")
    assert is_conversation_stuck(ctx)
    note_progress(ctx)
    assert not is_conversation_stuck(ctx)


def test_stuck_recovery_names_known_slots():
    ctx = {"industry": "dentists", "location": "Kathmandu"}
    payload = build_stuck_recovery(ctx)
    assert payload["recovery_kind"] == "conversation_stuck"
    assert "dentists" in payload["message"]
    assert "Kathmandu" in payload["message"]
    assert "What should I correct?" in payload["message"]
    assert payload["actions"]
    by_id = {a["id"]: a for a in payload["actions"]}
    assert by_id["change_location"]["message"] == "change city"
    assert "Kathmandu" in by_id["confirm_current"]["message"] or "dentists" in by_id["confirm_current"]["message"]


def test_known_slots_summary():
    assert known_slots_summary({"industry": "dentists", "location": "Kathmandu"}) == {
        "business type": "dentists",
        "location": "Kathmandu",
    }
    assert "location" not in known_slots_summary(
        {"industry": "chocolate", "location": "no no i want chocolate"}
    )
