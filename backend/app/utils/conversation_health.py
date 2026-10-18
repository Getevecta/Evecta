"""Conversation health / stuck-loop detection for lead-gen chat.

Tracks light-weight counters on the LangGraph ``context`` dict so the assistant
can stop repeating the same ask when the conversation is clearly not progressing.
"""

from __future__ import annotations

import re
from typing import Any

# Thresholds — keep conservative so we don't interrupt healthy multi-turn slot fill.
PENDING_ASK_STUCK = 3
SAME_USER_MSG_STUCK = 2
NO_RESULT_STUCK = 2
CORRECTION_STUCK = 2

# Explicit "you got it wrong" corrections — NOT industry refinements like
# "no no i want chocolate" (those update the search goal, they aren't stuck).
_CORRECTION_RE = re.compile(
    r"\b("
    r"no[,!]?\s+i\s+(meant|said)|"
    r"i\s+meant|"
    r"i\s+said|"
    r"that'?s\s+wrong|"
    r"wrong\s+(city|location|industry|type|place)|"
    r"correct\s+(that|it|the)|"
    r"change\s+(the\s+)?(industry|location|city|country|type)"
    r")\b",
    re.IGNORECASE,
)

# Phrases / shapes that are clearly not city/country answers (structural, not a word list).
_NON_PLACE_RE = re.compile(
    r"\b("
    r"i\s+want|i\s+need|looking\s+for|search\s+for|find\s+leads|"
    r"tell\s+me|about\s+yourself|how\s+you|who\s+are\s+you|"
    r"no\s+no|keep\s+(it\s+)?narrow|broaden|start\s+over"
    r")\b",
    re.IGNORECASE,
)

# Discourse particles — universal replies, never geography. Kept tiny on purpose;
# everything else is decided by the understanding model + map confirmation.
_DISCOURSE_ONLY = frozenset({
    "yes", "y", "no", "n", "ok", "okay", "sure", "yep", "yeah", "nah", "nope",
    "go", "go ahead", "continue", "again", "retry",
})


def normalize_user_message(message: str | None) -> str:
    text = (message or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def looks_like_valid_place(message: str | None) -> bool:
    """Loose structural gate: reject obvious non-places.

    This is NOT a dictionary of cities vs chat words. Real place-vs-chat decisions
    come from ``understand()`` (LLM) and map geocoding confirmation.
    """
    msg = (message or "").strip().strip(".,!;:")
    if not msg or len(msg) > 60:
        return False
    words = msg.split()
    if not words or len(words) > 4:
        return False
    # Incomplete "chocolate in" / trailing "in" — city never provided.
    if words[-1].lower() == "in" or normalize_user_message(msg).endswith(" in"):
        return False
    if _NON_PLACE_RE.search(msg):
        return False
    if "?" in msg:
        return False
    norm = normalize_user_message(msg)
    if norm in _DISCOURSE_ONLY:
        return False
    # Reject clear sentence fragments (pronouns / intent verbs), not every English word.
    if re.search(r"\b(i|me|my|you|we|want|need|find|search|tell|about)\b", msg, re.I):
        return False
    return True


def scrub_invalid_place_slots(context: dict[str, Any]) -> bool:
    """Drop location/country values that were clearly mis-captured from chat.

    Returns True if anything was removed.
    """
    removed = False
    for key in ("location", "country"):
        val = context.get(key)
        if val is None:
            continue
        if not looks_like_valid_place(str(val)):
            context.pop(key, None)
            removed = True
    if removed:
        # Stale confirm/scope keyed off the bad place must not survive.
        context.pop("confirmed_goal", None)
        context.pop("awaiting_confirmation", None)
        context.pop("anchor", None)
    return removed


def parse_industry_missing_city(message: str | None) -> str | None:
    """If message is 'chocolate in' / 'dentists in ', return the industry stem."""
    msg = (message or "").strip()
    if not msg:
        return None
    match = re.match(r"^(.+?)\s+in\s*$", msg, flags=re.IGNORECASE)
    if not match:
        return None
    industry = match.group(1).strip(" .,!")
    if not industry or len(industry.split()) > 6:
        return None
    if _NON_PLACE_RE.search(industry):
        return None
    return industry


def note_user_turn(context: dict[str, Any], message: str | None) -> None:
    """Update per-turn health counters after appending the user message."""
    ctx = context
    ctx["health_turn_count"] = int(ctx.get("health_turn_count") or 0) + 1

    norm = normalize_user_message(message)
    last = ctx.get("health_last_user_norm")
    if norm and last and norm == last:
        ctx["health_same_user_msg_count"] = int(ctx.get("health_same_user_msg_count") or 1) + 1
    else:
        ctx["health_same_user_msg_count"] = 1 if norm else 0
    ctx["health_last_user_norm"] = norm or None

    if norm and _CORRECTION_RE.search(norm):
        ctx["health_correction_count"] = int(ctx.get("health_correction_count") or 0) + 1


def note_pending_ask(context: dict[str, Any], ask_kind: str) -> None:
    """Record that this turn ended by asking the same class of clarifying question."""
    kind = (ask_kind or "").strip().lower() or "unknown"
    prev = (context.get("health_ask_kind") or "").strip().lower()
    if prev == kind:
        context["health_pending_ask_count"] = int(context.get("health_pending_ask_count") or 0) + 1
    else:
        context["health_ask_kind"] = kind
        context["health_pending_ask_count"] = 1


def note_no_results(context: dict[str, Any]) -> None:
    context["health_no_result_count"] = int(context.get("health_no_result_count") or 0) + 1


def note_progress(context: dict[str, Any]) -> None:
    """Reset stuck counters after genuine progress (slot filled, search succeeded, etc.)."""
    context["health_pending_ask_count"] = 0
    context["health_ask_kind"] = None
    context["health_same_user_msg_count"] = 0
    context["health_no_result_count"] = 0
    context["health_correction_count"] = 0
    context["health_stuck_offered"] = False


def is_conversation_stuck(context: dict[str, Any] | None) -> bool:
    ctx = context or {}
    return (
        int(ctx.get("health_pending_ask_count") or 0) >= PENDING_ASK_STUCK
        or int(ctx.get("health_same_user_msg_count") or 0) >= SAME_USER_MSG_STUCK
        or int(ctx.get("health_no_result_count") or 0) >= NO_RESULT_STUCK
        or int(ctx.get("health_correction_count") or 0) >= CORRECTION_STUCK
    )


def known_slots_summary(context: dict[str, Any] | None) -> dict[str, str]:
    """Human-facing known slots for stuck recovery copy."""
    ctx = context or {}
    out: dict[str, str] = {}
    if ctx.get("industry"):
        out["business type"] = str(ctx["industry"]).strip()
    if ctx.get("location") and looks_like_valid_place(str(ctx["location"])):
        out["location"] = str(ctx["location"]).strip()
    country = ctx.get("country")
    if country and looks_like_valid_place(str(country)):
        if not out.get("location"):
            out["country"] = str(country).strip()
        else:
            loc = out["location"].lower()
            ctry = str(country).strip()
            if ctry.lower() not in loc:
                out["country"] = ctry
    return out
