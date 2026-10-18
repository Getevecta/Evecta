"""State-aware chat failure recovery: preserve the goal and offer concrete next steps.

Recovery payloads include:
  - recovery_kind: machine-readable failure class
  - message: user-facing copy that names what succeeded / where it failed
  - actions: clickable next steps [{id, label, message}]
"""

from __future__ import annotations

from typing import Any, Literal, Optional

RecoveryKind = Literal[
    "understanding_failed",
    "location_unresolved",
    "zero_results",
    "search_exhausted",
    "search_timeout",
    "enrichment_timeout",
    "conversation_memory_lost",
    "conversation_stuck",
    "rate_limited",
    "llm_unavailable",
    "llm_rate_limited",
    "insufficient_credits",
]


def goal_label(
    industry: str | None = None,
    location: str | None = None,
    *,
    country: str | None = None,
    anchor: str | None = None,
) -> str:
    """Human phrase for the user's search goal, e.g. independent dentists in Melbourne."""
    ind = (industry or "").strip()
    loc = (location or "").strip()
    ctry = (country or "").strip()
    anc = (anchor or "").strip()

    place = loc
    if loc and ctry and ctry.lower() not in loc.lower():
        place = f"{loc}, {ctry}"
    elif not loc and ctry:
        place = ctry

    if ind and anc and place:
        return f"{ind} near {anc} in {place}"
    if ind and place:
        return f"{ind} in {place}"
    if ind:
        return ind
    if place:
        return f"leads in {place}"
    return "your search"


def search_prompt(
    industry: str | None,
    location: str | None,
    *,
    country: str | None = None,
    anchor: str | None = None,
    radius_km: float | int | None = None,
) -> str:
    """Chat message that re-runs (or adjusts) the same goal."""
    ind = (industry or "").strip() or "businesses"
    loc = (location or "").strip()
    ctry = (country or "").strip()
    anc = (anchor or "").strip()

    place = loc
    if loc and ctry and ctry.lower() not in loc.lower():
        place = f"{loc}, {ctry}"
    elif not loc and ctry:
        place = ctry

    if anc and place:
        base = f"{ind} near {anc} in {place}"
    elif place:
        base = f"{ind} in {place}"
    else:
        base = ind

    if radius_km:
        return f"{base} within {int(radius_km)} km"
    return base


def _action(action_id: str, label: str, message: str) -> dict[str, str]:
    return {"id": action_id, "label": label, "message": message}


def _from_context(context: dict | None) -> tuple[str | None, str | None, str | None, str | None, float | None]:
    ctx = context or {}
    radius = ctx.get("radius_km")
    try:
        radius_f = float(radius) if radius is not None else None
    except (TypeError, ValueError):
        radius_f = None
    return (
        (ctx.get("industry") or None),
        (ctx.get("location") or None),
        (ctx.get("country") or None),
        (ctx.get("anchor") or None),
        radius_f,
    )


def recovery_payload(
    *,
    kind: RecoveryKind,
    message: str,
    context: dict | None = None,
    actions: list[dict[str, str]] | None = None,
    status: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Standard soft-failure chat turn shape (returned inside BaseResponse.data / SSE done)."""
    payload: dict[str, Any] = {
        "status": status or _default_status(kind),
        "message": message,
        "context": context or {},
        "recovery_kind": kind,
        "actions": actions or [],
    }
    if extra:
        payload.update(extra)
    return payload


def _default_status(kind: RecoveryKind) -> str:
    return {
        "understanding_failed": "error",
        "location_unresolved": "empty",
        "zero_results": "empty",
        "search_exhausted": "exhausted",
        "search_timeout": "error",
        "enrichment_timeout": "error",
        "conversation_memory_lost": "pending",
        "conversation_stuck": "pending",
        "rate_limited": "rate_limited",
        "llm_unavailable": "error",
        "llm_rate_limited": "error",
        "insufficient_credits": "insufficient_credits",
    }.get(kind, "error")


def build_zero_results_recovery(
    context: dict | None,
    *,
    nearby_cities: list[str] | None = None,
    geocoding_failed: bool = False,
) -> dict[str, Any]:
    industry, location, country, anchor, _radius = _from_context(context)
    goal = goal_label(industry, location, country=country, anchor=anchor)
    cities = [c.strip() for c in (nearby_cities or []) if c and str(c).strip()][:3]

    actions: list[dict[str, str]] = []
    if geocoding_failed:
        kind: RecoveryKind = "location_unresolved"
        message = (
            f'I understood “{goal},” but I could not resolve that location. '
            "Try a clearer city name, or pick one of these options."
        )
        if location or country:
            actions.append(
                _action(
                    "retry_location",
                    f"Retry {location or country}",
                    search_prompt(industry, location, country=country, anchor=anchor),
                )
            )
    else:
        kind = "zero_results"
        message = (
            f'I understood “{goal},” but the search returned zero results. '
            "I can retry here, try a nearby city, or widen the radius."
        )
        actions.append(
            _action(
                "retry_same",
                f"Retry {location or country or 'search'}",
                search_prompt(industry, location, country=country, anchor=anchor),
            )
        )
        actions.append(
            _action(
                "widen_radius",
                "Use 15 km radius",
                search_prompt(industry, location, country=country, anchor=anchor, radius_km=15),
            )
        )

    for city in cities:
        actions.append(
            _action(
                f"nearby_{city.lower().replace(' ', '_')}",
                f"Search {city}",
                search_prompt(industry, city, country=country),
            )
        )

    if industry:
        actions.append(
            _action(
                "broader_industry",
                "Try a broader industry",
                f"broader industry than {industry}"
                + (f" in {location or country}" if (location or country) else ""),
            )
        )

    # De-dupe by message while preserving order
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for a in actions:
        key = a["message"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(a)

    return recovery_payload(kind=kind, message=message, context=context, actions=unique[:5])


def build_exhaustion_recovery(
    context: dict | None,
    *,
    industry_display: str,
    city_display: str,
    nearby: list[dict[str, Any]] | None = None,
    log_id: str | None = None,
) -> dict[str, Any]:
    industry, _loc, country, anchor, _r = _from_context(context)
    ind = industry_display or industry or "leads"
    city = city_display or _loc or "this area"
    goal = goal_label(ind, city, country=country, anchor=anchor)

    nearby_rows = nearby or []
    city_names = [n.get("city") for n in nearby_rows if n.get("city")]
    where = f" ({', '.join(city_names)})" if city_names else ""

    message = (
        f'I found every “{goal}” match we have — you\'ve reached the end in {city}. '
        f"Try a different location{where} or industry to keep finding leads."
    )

    actions: list[dict[str, str]] = []
    for n in nearby_rows[:3]:
        c = n.get("city")
        if not c:
            continue
        label = f"Search {c}"
        deliverable = n.get("deliverable")
        if deliverable:
            label = f"Search {c} (~{deliverable})"
        actions.append(_action(f"nearby_{c.lower().replace(' ', '_')}", label, search_prompt(ind, c, country=country)))

    actions.append(
        _action(
            "widen_radius",
            "Use 15 km radius",
            search_prompt(ind, city, country=country, anchor=anchor, radius_km=15),
        )
    )
    actions.append(
        _action(
            "broader_industry",
            "Try a broader industry",
            f"broader industry than {ind} in {city}",
        )
    )

    extra: dict[str, Any] = {
        "exhausted": {
            "industry": ind,
            "city": city,
            "log_id": log_id,
            "nearby": nearby_rows,
        }
    }
    return recovery_payload(
        kind="search_exhausted",
        message=message,
        context=context,
        actions=actions[:5],
        status="exhausted",
        extra=extra,
    )


def build_rate_limited_recovery(context: dict | None) -> dict[str, Any]:
    industry, location, country, anchor, _r = _from_context(context)
    goal = goal_label(industry, location, country=country, anchor=anchor)
    message = (
        f'I understood “{goal},” but you\'ve reached this hour\'s search limit. '
        "Wait a bit and retry, or refine with a nearby city or wider radius."
    )
    actions = [
        _action(
            "retry_same",
            "Retry same search",
            search_prompt(industry, location, country=country, anchor=anchor),
        ),
        _action(
            "widen_radius",
            "Use 15 km radius",
            search_prompt(industry, location, country=country, anchor=anchor, radius_km=15),
        ),
    ]
    if location or country:
        actions.append(
            _action(
                "broader_industry",
                "Try a broader industry",
                f"broader industry than {industry or 'this'} in {location or country}",
            )
        )
    return recovery_payload(kind="rate_limited", message=message, context=context, actions=actions)


def build_llm_unavailable_recovery(
    context: dict | None,
    *,
    rate_limited: bool = False,
) -> dict[str, Any]:
    industry, location, country, anchor, _r = _from_context(context)
    has_goal = bool(industry or location or country)
    goal = goal_label(industry, location, country=country, anchor=anchor) if has_goal else None

    if rate_limited:
        kind: RecoveryKind = "llm_rate_limited"
        if goal:
            message = (
                f'I understood “{goal},” but the AI assistant hit a rate limit. '
                "Please wait a moment, then retry."
            )
        else:
            message = (
                "The AI assistant hit a rate limit. Please wait a moment, then try again."
            )
    else:
        kind = "llm_unavailable"
        if goal:
            message = (
                f'I understood “{goal},” but the AI assistant is temporarily unavailable. '
                "You can retry in a moment."
            )
        else:
            message = (
                "Something went wrong. Our AI assistant is temporarily unavailable. "
                "Please try again in a moment."
            )

    actions = [
        _action(
            "retry_same",
            "Try again",
            search_prompt(industry, location, country=country, anchor=anchor)
            if has_goal
            else "try again",
        ),
    ]
    return recovery_payload(kind=kind, message=message, context=context, actions=actions)


def build_search_timeout_recovery(
    context: dict | None = None,
    *,
    user_message: str | None = None,
) -> dict[str, Any]:
    industry, location, country, anchor, _r = _from_context(context)
    if industry or location or country:
        goal = goal_label(industry, location, country=country, anchor=anchor)
        retry_msg = search_prompt(industry, location, country=country, anchor=anchor)
        widen = search_prompt(industry, location, country=country, anchor=anchor, radius_km=15)
    else:
        goal = (user_message or "").strip() or "your search"
        retry_msg = (user_message or "").strip() or "try again"
        widen = f"{retry_msg} within 15 km" if retry_msg != "try again" else "search within 15 km"

    message = (
        f'I understood “{goal},” but the location search timed out. '
        "I can retry, widen the radius, or you can try a nearby suburb."
    )
    actions = [
        _action("retry_same", "Retry search", retry_msg),
        _action("widen_radius", "Use 15 km radius", widen),
    ]
    return recovery_payload(
        kind="search_timeout",
        message=message,
        context=context,
        actions=actions,
        status="error",
    )


def build_enrichment_timeout_recovery(context: dict | None = None) -> dict[str, Any]:
    industry, location, country, anchor, _r = _from_context(context)
    goal = goal_label(industry, location, country=country, anchor=anchor)
    message = (
        f'I understood “{goal},” and the search succeeded, but enrichment timed out '
        "before emails finished loading. You can keep waiting from Lead results, or retry."
    )
    actions = [
        _action(
            "retry_same",
            "Retry search",
            search_prompt(industry, location, country=country, anchor=anchor),
        ),
    ]
    if location or country:
        actions.append(
            _action(
                "widen_radius",
                "Retry with 15 km radius",
                search_prompt(industry, location, country=country, anchor=anchor, radius_km=15),
            )
        )
    return recovery_payload(
        kind="enrichment_timeout",
        message=message,
        context=context,
        actions=actions,
        status="error",
    )


# Matches campaign enrichment wait budget; FE also cuts over to N/A around 3 minutes.
ENRICHMENT_TIMEOUT_SECONDS = 180


def build_chat_timeout_recovery(
    context: dict | None = None,
    *,
    user_message: str | None = None,
    saved_log_id: str | None = None,
) -> dict[str, Any]:
    """Choose search vs enrichment recovery after the chat graph times out.

    A LeadLog persisted during this turn means the catalog search finished and
    background email enrichment may still be running — surface that, with log_id
    so the client can open Lead results. Otherwise the location search itself stalled.
    """
    if saved_log_id:
        payload = build_enrichment_timeout_recovery(context)
        payload["log_id"] = str(saved_log_id)
        return payload
    return build_search_timeout_recovery(context, user_message=user_message)


def build_memory_lost_recovery(context: dict | None = None) -> dict[str, Any]:
    message = (
        "I lost track of this conversation's search goal. "
        "Tell me the industry and city again — for example: dentists in Melbourne."
    )
    actions = [
        _action("example_dentists", "Dentists in Melbourne", "dentists in Melbourne"),
        _action("example_restaurants", "Restaurants in Austin", "restaurants in Austin"),
        _action("example_agencies", "Marketing agencies in London", "marketing agencies in London"),
    ]
    return recovery_payload(
        kind="conversation_memory_lost",
        message=message,
        context=context or {},
        actions=actions,
        status="pending",
    )


def build_place_unresolved_recovery(
    context: dict | None,
    bad_place: str,
) -> dict[str, Any]:
    """Early map check failed — ask for a real city without re-submitting the bad place."""
    ctx = context or {}
    place = (bad_place or "").strip() or "that location"
    industry, _loc, _country, _anchor, _r = _from_context(ctx)
    message = (
        f'I couldn’t find “{place}” on the map. '
        "Please give a real city name — for example: Melbourne, Kathmandu, or London."
    )
    actions: list[dict[str, str]] = []
    if industry:
        actions.append(_action("change_location", "Change city", "change city"))
        example_industry = str(industry).strip()
        actions.append(
            _action(
                "example_search",
                f"{example_industry.title()} in Kathmandu",
                f"{example_industry} in Kathmandu",
            )
        )
    else:
        actions.append(
            _action("example_dentists", "Dentists in Kathmandu", "dentists in Kathmandu")
        )
    actions.append(_action("start_over", "Start over", "start over"))
    return recovery_payload(
        kind="location_unresolved",
        message=message,
        context=ctx,
        actions=actions,
        status="pending",
    )


def build_stuck_recovery(context: dict | None = None) -> dict[str, Any]:
    """Break a stuck loop by restating known slots and asking what to correct."""
    from app.utils.conversation_health import known_slots_summary, looks_like_valid_place, scrub_invalid_place_slots

    ctx = context or {}
    scrub_invalid_place_slots(ctx)
    slots = known_slots_summary(ctx)
    if slots:
        parts = [f'“{value}” as the {label}' for label, value in slots.items()]
        if len(parts) == 1:
            known = parts[0]
        elif len(parts) == 2:
            known = f"{parts[0]} and {parts[1]}"
        else:
            known = ", ".join(parts[:-1]) + f", and {parts[-1]}"
        message = (
            f"I may have misunderstood you. I currently have {known}. "
            "What should I correct?"
        )
    else:
        message = (
            "I may have misunderstood you, and we seem stuck. "
            "Tell me the business type and city you want — for example: dentists in Kathmandu."
        )

    industry, location, country, anchor, _r = _from_context(ctx)
    # Never offer actions that re-submit a garbage location.
    if location and not looks_like_valid_place(location):
        location = None
    if country and not looks_like_valid_place(country):
        country = None

    actions: list[dict[str, str]] = []
    if industry and (location or country):
        actions.append(
            _action(
                "confirm_current",
                "Keep current search",
                search_prompt(industry, location, country=country, anchor=anchor),
            )
        )
    if industry:
        # Explicit command — backend clears place slots and asks for a real city.
        actions.append(
            _action(
                "change_location",
                "Change city",
                "change city",
            )
        )
    actions.append(_action("start_over", "Start over", "start over"))
    if not industry:
        actions.insert(
            0,
            _action("example_dentists", "Dentists in Kathmandu", "dentists in Kathmandu"),
        )

    ctx["health_stuck_offered"] = True
    # Soft-reset ask streak so we don't immediately re-trigger on the next pending ask
    # unless the user stays stuck (same message / more corrections / more no-results).
    ctx["health_pending_ask_count"] = 0
    ctx["health_ask_kind"] = None

    return recovery_payload(
        kind="conversation_stuck",
        message=message,
        context=ctx,
        actions=actions,
        status="pending",
    )


def build_insufficient_credits_recovery(context: dict | None = None) -> dict[str, Any]:
    industry, location, country, anchor, _r = _from_context(context)
    goal = goal_label(industry, location, country=country, anchor=anchor)
    has_goal = bool(industry or location or country)
    if has_goal:
        message = (
            f'I understood “{goal},” but you\'re out of lead credits. '
            "Add credits in Billing to continue."
        )
    else:
        message = (
            "You're out of lead credits. Add credits in Billing to continue chatting "
            "and generating leads."
        )
    # Billing is a navigation action — FE maps id "open_billing"
    actions = [
        {"id": "open_billing", "label": "Go to Billing", "message": ""},
    ]
    return recovery_payload(
        kind="insufficient_credits",
        message=message,
        context=context,
        actions=actions,
        status="insufficient_credits",
    )
