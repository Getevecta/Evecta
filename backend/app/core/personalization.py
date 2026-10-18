"""
Personalization Level Engine — plan-tier rules, tone styles, and depth resolution.

Depth scales with subscription plan (cost control) and available lead context
(graceful degradation). Higher plans unlock richer context fields; thin leads
never get fabricated detail.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from app.core.plans import DEFAULT_PLAN, PLANS

# Ordered shallow → deep; used when capping effective depth.
DEPTH_ORDER: tuple[str, ...] = ("basic", "standard", "deep")


class PersonalizationDepth(str, Enum):
    BASIC = "basic"
    STANDARD = "standard"
    DEEP = "deep"


class ContextScore(str, Enum):
    NONE = "none"
    PARTIAL = "partial"
    FULL = "full"


# Fields available at each depth (merge + prompt context).
DEPTH_FIELDS: dict[str, tuple[str, ...]] = {
    "basic": ("business_name", "industry", "address"),
    "standard": ("business_name", "industry", "address", "website_summary"),
    "deep": (
        "business_name",
        "industry",
        "address",
        "website_summary",
        "services",
        "business_description",
    ),
}

# Max personalization depth each plan may use (when lead context allows).
PLAN_MAX_DEPTH: dict[str, str] = {
    "free": "basic",
    "starter": "standard",
    "growth": "deep",
    "scale": "deep",
}

# Context richness caps how deep we go even on high plans.
CONTEXT_MAX_DEPTH: dict[str, str] = {
    "none": "basic",
    "partial": "standard",
    "full": "deep",
}

# Whether external research (Perplexity) is allowed — Scale only, future Step 1 improvement.
PLAN_EXTERNAL_RESEARCH: dict[str, bool] = {
    "free": False,
    "starter": False,
    "growth": False,
    "scale": True,
}

from app.core.email_tones import (
    CAMPAIGN_TONE_OPTIONS,
    DEFAULT_TONE,
    TONE_LABELS,
    TONE_STYLES,
    default_tone_for_plan,
    normalize_tone,
    tone_instruction,
    tone_tiers_for_api,
    tone_to_engine_key,
    unlocked_tone_options,
)

PLAN_PERSONALIZATION_SUMMARY: dict[str, dict[str, Any]] = {
    "free": {
        "max_depth": "basic",
        "label": "Basic",
        "description": "Mail-merge personalization using business name, industry, and location.",
        "external_research": False,
    },
    "starter": {
        "max_depth": "standard",
        "label": "Standard",
        "description": "Adds website-summary hooks for more relevant opening lines.",
        "external_research": False,
    },
    "growth": {
        "max_depth": "deep",
        "label": "Deep",
        "description": "References services and business description when available.",
        "external_research": False,
    },
    "scale": {
        "max_depth": "deep",
        "label": "Deep + research",
        "description": "Deepest personalization; external research when lead context is thin.",
        "external_research": True,
    },
}


def _depth_index(depth: str) -> int:
    try:
        return DEPTH_ORDER.index(depth)
    except ValueError:
        return 0


def normalize_plan(plan: str | None) -> str:
    key = (plan or DEFAULT_PLAN).strip().lower()
    return key if key in PLANS else DEFAULT_PLAN


def cap_depth(*depths: str) -> str:
    """Return the shallowest depth among the given depth labels."""
    if not depths:
        return "basic"
    return min(depths, key=_depth_index)


def effective_depth(plan: str | None, context_score: str) -> str:
    """Combine plan allowance and lead context richness."""
    plan_key = normalize_plan(plan)
    ctx_key = context_score if context_score in CONTEXT_MAX_DEPTH else "none"
    return cap_depth(
        PLAN_MAX_DEPTH.get(plan_key, "basic"),
        CONTEXT_MAX_DEPTH[ctx_key],
    )


ENGINE_LEVEL_ORDER: tuple[str, ...] = ("minimal", "standard", "deep", "research")

# Stage #3 (email_engine) personalization levels — mapped from plan + effective depth.
PLAN_TO_ENGINE_LEVEL: dict[str, str] = {
    "free": "minimal",
    "starter": "standard",
    "growth": "deep",
    "scale": "research",
}

# UI tone keys → rules/tones/*.md filenames (stage #3). Defined in email_tones.py.

def resolve_engine_level(plan: str | None, effective_depth: str) -> str:
    """
    Map Step-2 effective_depth + plan to stage-#3 personalization_level.

    Context caps richness: thin leads never get deep/research even on Scale.
    Scale + full context upgrades deep → research.
    """
    depth = effective_depth if effective_depth in DEPTH_ORDER else "basic"
    if depth == "basic":
        return "minimal"
    if depth == "standard":
        return "standard"
    # deep — upgrade Scale to research tier
    if normalize_plan(plan) == "scale":
        return "research"
    return "deep"


def fields_for_depth(depth: str) -> tuple[str, ...]:
    return DEPTH_FIELDS.get(depth, DEPTH_FIELDS["basic"])


def plan_capabilities(plan: str | None) -> dict[str, Any]:
    plan_key = normalize_plan(plan)
    summary = PLAN_PERSONALIZATION_SUMMARY.get(
        plan_key, PLAN_PERSONALIZATION_SUMMARY["free"]
    )
    return {
        "plan": plan_key,
        "max_depth": summary["max_depth"],
        "label": summary["label"],
        "description": summary["description"],
        "external_research": summary["external_research"],
        "available_fields": list(fields_for_depth(summary["max_depth"])),
        "tone_options": unlocked_tone_options(plan_key),
        "tone_tiers": tone_tiers_for_api(plan_key),
        "default_tone": default_tone_for_plan(plan_key),
    }
