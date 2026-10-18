"""
Email tone registry — single source of truth for UI tiers, plan unlocks, and LLM guidance.

Each tone maps to:
  - a short instruction (injected at the top of the generator prompt)
  - a markdown rules file under email_engine/rules/tones/*.md (detailed Do/Don't guidance)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.plans import DEFAULT_PLAN, PLANS

DEFAULT_TONE = "friendly"

PLAN_RANK: dict[str, int] = {
    "free": 0,
    "starter": 1,
    "growth": 2,
    "scale": 3,
}

TONE_ALIASES: dict[str, str] = {
    "partnership": "partnership-focused",
    "partnershipfocused": "partnership-focused",
    "soft": "soft-introduction",
    "softintro": "soft-introduction",
    "softintroduction": "soft-introduction",
    "concise": "casual",
}


@dataclass(frozen=True)
class ToneCard:
    id: str
    label: str
    description: str
    engine_key: str
    instruction: str


@dataclass(frozen=True)
class ToneTier:
    tier_plan: str
    tier_label: str
    min_plan: str
    tones: tuple[ToneCard, ...]


# ---------------------------------------------------------------------------
# Tone writing instructions + engine keys (markdown file stems)
# ---------------------------------------------------------------------------
_TONE_META: dict[str, dict[str, str]] = {
    "professional": {
        "instruction": (
            "Keep a formal, polished tone suitable for B2B communication. "
            "Focus on clarity and respect."
        ),
        "engine_key": "professional",
    },
    "friendly": {
        "instruction": (
            "Use a conversational, warm, and approachable tone — write like a person "
            "excited to collaborate."
        ),
        "engine_key": "friendly",
    },
    "casual": {
        "instruction": (
            "Be light, simple, and direct — avoid corporate jargon. "
            "Favor brevity and plain language."
        ),
        "engine_key": "casual",
    },
    "persuasive": {
        "instruction": (
            "Be confident, action-oriented, and motivating — inspire the reader to take "
            "interest or respond."
        ),
        "engine_key": "persuasive",
    },
    "partnership-focused": {
        "instruction": (
            "Emphasize mutual value and collaboration. Frame the outreach as exploring "
            "a partnership, not a hard sell."
        ),
        "engine_key": "partnership",
    },
    "soft-introduction": {
        "instruction": (
            "Use a gentle, low-pressure introduction grounded in research and context. "
            "Be brief, respectful of their time, and avoid aggressive calls to action."
        ),
        "engine_key": "soft_intro",
    },
    "enthusiastic": {
        "instruction": (
            "Lead with the recipient's likely pain point or challenge, then connect your "
            "offer as a relevant solution. Stay energetic but credible — not hypey."
        ),
        "engine_key": "enthusiastic",
    },
}

TONE_LABELS: dict[str, str] = {
    "professional": "Professional",
    "friendly": "Friendly",
    "casual": "Concise",
    "persuasive": "Persuasive",
    "partnership-focused": "Consultative",
    "soft-introduction": "Research-Based",
    "enthusiastic": "Problem-Focused",
}

# Tiered UI structure — plan unlocks and display labels are owned here.
EMAIL_TONE_TIERS: tuple[ToneTier, ...] = (
    ToneTier(
        tier_plan="starter",
        tier_label="Starter",
        min_plan="free",
        tones=(
            ToneCard(
                id="professional",
                label="Professional",
                description="Polished & business-ready",
                engine_key="professional",
                instruction=_TONE_META["professional"]["instruction"],
            ),
            ToneCard(
                id="friendly",
                label="Friendly",
                description="Warm & conversational",
                engine_key="friendly",
                instruction=_TONE_META["friendly"]["instruction"],
            ),
        ),
    ),
    ToneTier(
        tier_plan="growth",
        tier_label="Growth",
        min_plan="growth",
        tones=(
            ToneCard(
                id="casual",
                label="Concise",
                description="Short & direct",
                engine_key="casual",
                instruction=_TONE_META["casual"]["instruction"],
            ),
            ToneCard(
                id="persuasive",
                label="Persuasive",
                description="Compelling & action-oriented",
                engine_key="persuasive",
                instruction=_TONE_META["persuasive"]["instruction"],
            ),
            ToneCard(
                id="partnership-focused",
                label="Consultative",
                description="Advisory & collaborative",
                engine_key="partnership",
                instruction=_TONE_META["partnership-focused"]["instruction"],
            ),
        ),
    ),
    ToneTier(
        tier_plan="scale",
        tier_label="Scale",
        min_plan="scale",
        tones=(
            ToneCard(
                id="soft-introduction",
                label="Research-Based",
                description="Context-rich & informed",
                engine_key="soft_intro",
                instruction=_TONE_META["soft-introduction"]["instruction"],
            ),
            ToneCard(
                id="enthusiastic",
                label="Problem-Focused",
                description="Pain-point led outreach",
                engine_key="enthusiastic",
                instruction=_TONE_META["enthusiastic"]["instruction"],
            ),
            ToneCard(
                id="partnership-focused",
                label="Strategic",
                description="High-level partnership angle",
                engine_key="partnership",
                instruction=_TONE_META["partnership-focused"]["instruction"],
            ),
        ),
    ),
)


def normalize_plan(plan: str | None) -> str:
    key = (plan or DEFAULT_PLAN).strip().lower()
    return key if key in PLANS else DEFAULT_PLAN


def plan_rank(plan: str | None) -> int:
    return PLAN_RANK.get(normalize_plan(plan), 0)


def normalize_tone(tone: str | None) -> str:
    if not tone:
        return DEFAULT_TONE
    key = tone.strip().lower().replace("_", "-").replace(" ", "-")
    key = TONE_ALIASES.get(key, key)
    return key if key in _TONE_META else DEFAULT_TONE


def tone_instruction(tone: str | None) -> str:
    key = normalize_tone(tone)
    return _TONE_META[key]["instruction"]


def tone_to_engine_key(tone: str | None) -> str:
    key = normalize_tone(tone)
    return _TONE_META[key]["engine_key"]


def tone_label(tone: str | None) -> str:
    key = normalize_tone(tone)
    return TONE_LABELS.get(key, key.replace("-", " ").title())


def is_tier_unlocked(plan: str | None, tier: ToneTier) -> bool:
    return plan_rank(plan) >= PLAN_RANK.get(tier.min_plan, 0)


def is_tone_unlocked_for_plan(plan: str | None, tone_id: str) -> bool:
    """True when the user's plan can use this tone in at least one tier."""
    normalized = normalize_tone(tone_id)
    for tier in EMAIL_TONE_TIERS:
        if not is_tier_unlocked(plan, tier):
            continue
        if any(t.id == normalized for t in tier.tones):
            return True
    return False


def tier_badge(user_plan: str | None, tier: ToneTier) -> str:
    plan = normalize_plan(user_plan)
    if plan == tier.tier_plan:
        return "YOUR PLAN"
    if is_tier_unlocked(plan, tier):
        return "INCLUDED"
    return "UPGRADE TO UNLOCK"


def tone_tiers_for_api(plan: str | None) -> list[dict[str, Any]]:
    """Serialize tier structure for the campaign UI."""
    user_plan = normalize_plan(plan)
    out: list[dict[str, Any]] = []
    for tier in EMAIL_TONE_TIERS:
        out.append(
            {
                "tier_plan": tier.tier_plan,
                "tier_label": tier.tier_label,
                "min_plan": tier.min_plan,
                "min_plan_rank": PLAN_RANK.get(tier.min_plan, 0),
                "unlocked": is_tier_unlocked(user_plan, tier),
                "badge": tier_badge(user_plan, tier),
                "tones": [
                    {
                        "id": t.id,
                        "label": t.label,
                        "description": t.description,
                    }
                    for t in tier.tones
                ],
            }
        )
    return out


def unlocked_tone_options(plan: str | None) -> list[dict[str, str]]:
    """Flat list of tones the plan may select (first tier label wins for duplicates)."""
    user_plan = normalize_plan(plan)
    seen: set[str] = set()
    options: list[dict[str, str]] = []
    for tier in EMAIL_TONE_TIERS:
        if not is_tier_unlocked(user_plan, tier):
            continue
        for tone in tier.tones:
            if tone.id in seen:
                continue
            seen.add(tone.id)
            options.append({"id": tone.id, "label": tone.label})
    return options


def default_tone_for_plan(plan: str | None) -> str:
    options = unlocked_tone_options(plan)
    if options:
        return options[0]["id"]
    return DEFAULT_TONE


def validate_tone_for_plan(plan: str | None, tone: str | None) -> str:
    """
    Return normalized tone id or raise ValueError if the plan cannot use it.
    """
    normalized = normalize_tone(tone)
    if not is_tone_unlocked_for_plan(plan, normalized):
        label = tone_label(normalized)
        raise ValueError(
            f"Tone '{label}' is not available on your current plan. "
            "Upgrade to unlock additional email tones."
        )
    return normalized


# Backward-compatible flat list used by older callers/tests.
CAMPAIGN_TONE_OPTIONS: tuple[str, ...] = tuple(_TONE_META.keys())

TONE_STYLES: dict[str, str] = {
    tone_id: meta["instruction"] for tone_id, meta in _TONE_META.items()
}
