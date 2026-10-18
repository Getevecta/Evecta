"""Long-term chat memory: store small user-approved facts, retrieve only what helps this turn.

Priority (highest wins):
  current user message >
  current ChatState >
  explicit saved preferences >
  company / account profile >
  recent search summaries >
  inferred preferences >
  style preferences

Never silently apply a remembered location/filter that would change search results
without stating the assumption. Never send secrets or full lead tables to Gemini.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.user import User
from app.models.user_chat_memory import UserMemoryItem
from app.services.company_service import get_company_by_user_id

logger = logging.getLogger(__name__)

SOURCE_ACCOUNT = "account_profile"
SOURCE_COMPANY = "company_profile"
SOURCE_EXPLICIT = "explicit_user_statement"
SOURCE_REPEATED = "repeated_behavior"
SOURCE_SYSTEM = "system_derived"

MAX_RECENT_SEARCHES = 5
LOCATION_HIT_OFFER_THRESHOLD = 3

# Keys that must never be written into conversational memory.
_FORBIDDEN_KEY_FRAGMENTS = (
    "password",
    "token",
    "api_key",
    "secret",
    "card",
    "cvv",
    "bank",
    "ssn",
)


@dataclass
class MemoryBundle:
    """Compact, prompt-ready snapshot for one turn."""

    preferred_name: Optional[str] = None
    preferred_language: Optional[str] = None
    timezone: Optional[str] = None
    company_name: Optional[str] = None
    company_location: Optional[str] = None
    company_industry: Optional[str] = None
    user_role: Optional[str] = None
    default_country: Optional[str] = None
    preferred_cities: list[str] = field(default_factory=list)
    frequent_industries: list[str] = field(default_factory=list)
    default_radius_km: Optional[float] = None
    requires_email: Optional[bool] = None
    preferred_quality: Optional[str] = None
    exclude: list[str] = field(default_factory=list)
    exact_category_only: Optional[bool] = None
    response_style: Optional[str] = None
    explanation_depth: Optional[str] = None
    use_examples: Optional[bool] = None
    distance_unit: Optional[str] = None
    preferred_tone: Optional[str] = None
    experience_level: Optional[str] = None
    has_completed_first_search: bool = False
    has_used_radius_filter: bool = False
    recent_searches: list[dict] = field(default_factory=list)
    corrections: list[dict] = field(default_factory=list)
    pending_offer: Optional[dict] = None
    raw_items: dict[str, Any] = field(default_factory=dict)

    def usual_location_label(self) -> Optional[str]:
        if self.preferred_cities:
            return self.preferred_cities[0]
        if self.default_country:
            return self.default_country
        if self.company_location:
            return self.company_location
        return None

    def usual_industry_label(self) -> Optional[str]:
        if self.frequent_industries:
            return self.frequent_industries[0]
        return None


def _is_forbidden_key(key: str) -> bool:
    lowered = (key or "").lower()
    return any(frag in lowered for frag in _FORBIDDEN_KEY_FRAGMENTS)


def _first_name(user: User) -> Optional[str]:
    full = (user.full_name or "").strip()
    if full:
        return full.split()[0]
    username = (user.username or "").strip()
    if username and "@" not in username:
        return username
    return None


def _company_location_label(company: Optional[Company]) -> Optional[str]:
    if not company:
        return None
    parts = [p for p in (company.city, company.country) if (p or "").strip()]
    if parts:
        return ", ".join(parts)
    loc = (company.target_location or "").strip()
    return loc or None


async def get_item(db: AsyncSession, user_id: UUID, key: str) -> Optional[UserMemoryItem]:
    result = await db.execute(
        select(UserMemoryItem).where(
            UserMemoryItem.user_id == user_id,
            UserMemoryItem.key == key,
        )
    )
    return result.scalar_one_or_none()


async def upsert_memory(
    db: AsyncSession,
    user_id: UUID,
    *,
    category: str,
    key: str,
    value: Any,
    source: str,
    confidence: float = 1.0,
    confirmed: bool = False,
    commit: bool = True,
) -> Optional[UserMemoryItem]:
    if _is_forbidden_key(key):
        logger.warning("Refused to store forbidden memory key=%s user=%s", key, user_id)
        return None

    item = await get_item(db, user_id, key)
    now = datetime.now(timezone.utc)
    if item is None:
        item = UserMemoryItem(
            user_id=user_id,
            category=category,
            key=key,
            value=value,
            source=source,
            confidence=confidence,
            confirmed=confirmed,
            created_at=now,
            updated_at=now,
        )
        db.add(item)
    else:
        # Explicit statements beat inferred; do not overwrite confirmed explicit with weaker source.
        if item.confirmed and item.source == SOURCE_EXPLICIT and source != SOURCE_EXPLICIT:
            return item
        item.category = category
        item.value = value
        item.source = source
        item.confidence = confidence
        item.confirmed = confirmed
        item.updated_at = now
    if commit:
        await db.commit()
        await db.refresh(item)
    return item


async def list_memory_items(db: AsyncSession, user_id: UUID) -> list[UserMemoryItem]:
    result = await db.execute(
        select(UserMemoryItem)
        .where(UserMemoryItem.user_id == user_id)
        .order_by(UserMemoryItem.updated_at.desc())
    )
    return list(result.scalars().all())


async def delete_memory_key(db: AsyncSession, user_id: UUID, key: str) -> bool:
    item = await get_item(db, user_id, key)
    if not item:
        return False
    await db.delete(item)
    await db.commit()
    return True


async def confirm_pending(
    db: AsyncSession,
    user_id: UUID,
    key: str,
    *,
    confirm: bool,
) -> Optional[UserMemoryItem]:
    item = await get_item(db, user_id, key)
    if not item:
        return None
    if confirm:
        item.confirmed = True
        item.source = SOURCE_EXPLICIT if item.source == SOURCE_REPEATED else item.source
        item.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(item)
        return item
    await db.delete(item)
    await db.commit()
    return None


async def sync_profile_seeds(db: AsyncSession, user: User) -> None:
    """Seed identity/company facts from authenticated profile (never guessed by the model)."""
    company = await get_company_by_user_id(db, str(user.id))
    name = _first_name(user)
    if name:
        await upsert_memory(
            db,
            user.id,
            category="identity",
            key="preferred_name",
            value=name,
            source=SOURCE_ACCOUNT,
            confidence=1.0,
            confirmed=True,
            commit=False,
        )
    if company:
        if company.company_name:
            await upsert_memory(
                db,
                user.id,
                category="company",
                key="company_name",
                value=company.company_name,
                source=SOURCE_COMPANY,
                confidence=1.0,
                confirmed=True,
                commit=False,
            )
        if company.role:
            await upsert_memory(
                db,
                user.id,
                category="company",
                key="user_role",
                value=company.role,
                source=SOURCE_COMPANY,
                confidence=1.0,
                confirmed=True,
                commit=False,
            )
        if company.industry:
            await upsert_memory(
                db,
                user.id,
                category="company",
                key="company_industry",
                value=company.industry,
                source=SOURCE_COMPANY,
                confidence=1.0,
                confirmed=True,
                commit=False,
            )
        loc = _company_location_label(company)
        if loc:
            await upsert_memory(
                db,
                user.id,
                category="company",
                key="company_location",
                value=loc,
                source=SOURCE_COMPANY,
                confidence=1.0,
                confirmed=True,
                commit=False,
            )
        # Soft ICP seeds — confirmed but lower priority than explicit search prefs.
        if company.target_location:
            existing_default = await get_item(db, user.id, "default_country")
            existing_city = await get_item(db, user.id, "preferred_cities")
            if not existing_default and not existing_city:
                await upsert_memory(
                    db,
                    user.id,
                    category="search_pref",
                    key="profile_target_location",
                    value=company.target_location,
                    source=SOURCE_COMPANY,
                    confidence=0.8,
                    confirmed=True,
                    commit=False,
                )
        if company.target_industry:
            existing_ind = await get_item(db, user.id, "frequent_industries")
            if not existing_ind:
                await upsert_memory(
                    db,
                    user.id,
                    category="search_pref",
                    key="profile_target_industry",
                    value=company.target_industry,
                    source=SOURCE_COMPANY,
                    confidence=0.8,
                    confirmed=True,
                    commit=False,
                )
    await db.commit()


def _val(item: Optional[UserMemoryItem]) -> Any:
    if item is None:
        return None
    return item.value


async def load_memory_bundle(db: AsyncSession, user: User) -> MemoryBundle:
    await sync_profile_seeds(db, user)
    items = await list_memory_items(db, user.id)
    by_key = {i.key: i for i in items}
    bundle = MemoryBundle(raw_items={k: i.value for k, i in by_key.items()})

    def confirmed(key: str) -> Optional[UserMemoryItem]:
        item = by_key.get(key)
        if item and item.confirmed:
            return item
        return None

    name_item = confirmed("preferred_name")
    bundle.preferred_name = _val(name_item) or _first_name(user)
    bundle.preferred_language = _val(confirmed("preferred_language"))
    bundle.timezone = _val(confirmed("timezone"))
    bundle.company_name = _val(confirmed("company_name"))
    bundle.company_location = _val(confirmed("company_location"))
    bundle.company_industry = _val(confirmed("company_industry"))
    bundle.user_role = _val(confirmed("user_role"))
    bundle.default_country = _val(confirmed("default_country"))
    cities = _val(confirmed("preferred_cities"))
    if isinstance(cities, list):
        bundle.preferred_cities = [str(c) for c in cities if c]
    elif isinstance(cities, str) and cities.strip():
        bundle.preferred_cities = [cities.strip()]
    # Fall back to profile target location when no explicit preferred city.
    if not bundle.preferred_cities and not bundle.default_country:
        profile_loc = _val(confirmed("profile_target_location"))
        if isinstance(profile_loc, str) and profile_loc.strip():
            bundle.preferred_cities = [profile_loc.strip()]
    inds = _val(confirmed("frequent_industries"))
    if isinstance(inds, list):
        bundle.frequent_industries = [str(x) for x in inds if x]
    elif isinstance(inds, str) and inds.strip():
        bundle.frequent_industries = [inds.strip()]
    if not bundle.frequent_industries:
        profile_ind = _val(confirmed("profile_target_industry"))
        if isinstance(profile_ind, str) and profile_ind.strip():
            bundle.frequent_industries = [profile_ind.strip()]
    radius = _val(confirmed("default_radius_km"))
    if isinstance(radius, (int, float)):
        bundle.default_radius_km = float(radius)
    req_email = _val(confirmed("requires_email"))
    if isinstance(req_email, bool):
        bundle.requires_email = req_email
    bundle.preferred_quality = _val(confirmed("preferred_quality"))
    excl = _val(confirmed("exclude"))
    if isinstance(excl, list):
        bundle.exclude = [str(x) for x in excl if x]
    exact = _val(confirmed("exact_category_only"))
    if isinstance(exact, bool):
        bundle.exact_category_only = exact
    bundle.response_style = _val(confirmed("response_style"))
    bundle.explanation_depth = _val(confirmed("explanation_depth"))
    use_ex = _val(confirmed("use_examples"))
    if isinstance(use_ex, bool):
        bundle.use_examples = use_ex
    bundle.distance_unit = _val(confirmed("distance_unit"))
    bundle.preferred_tone = _val(confirmed("preferred_tone"))
    bundle.experience_level = _val(confirmed("experience_level"))
    bundle.has_completed_first_search = bool(_val(confirmed("has_completed_first_search")))
    bundle.has_used_radius_filter = bool(_val(confirmed("has_used_radius_filter")))
    recent = _val(confirmed("recent_searches"))
    if isinstance(recent, list):
        bundle.recent_searches = [r for r in recent if isinstance(r, dict)][:MAX_RECENT_SEARCHES]
    corrections = []
    for item in items:
        if item.category == "correction" and item.confirmed:
            corrections.append({"key": item.key, "preference": item.value, "source": item.source})
    bundle.corrections = corrections

    pending = by_key.get("_pending_offer")
    if pending and not pending.confirmed:
        if isinstance(pending.value, dict):
            bundle.pending_offer = pending.value
    return bundle


def format_memory_for_prompt(bundle: MemoryBundle, *, for_greeting: bool = False) -> str:
    """Only inject a small relevant subset — never dump everything on hello."""
    lines: list[str] = []
    if bundle.preferred_name:
        lines.append(f"preferred_name: {bundle.preferred_name}")
    if for_greeting:
        usual = bundle.usual_location_label()
        industry = bundle.usual_industry_label()
        if usual:
            lines.append(f"usual_market: {usual}")
        if industry:
            lines.append(f"usual_industry: {industry}")
        if bundle.recent_searches:
            last = bundle.recent_searches[0]
            bits = [last.get("industry"), last.get("location")]
            label = " in ".join(str(b) for b in bits if b)
            if label:
                lines.append(f"last_search: {label}")
        if bundle.experience_level:
            lines.append(f"experience_level: {bundle.experience_level}")
        if bundle.pending_offer:
            lines.append(f"pending_memory_offer: {bundle.pending_offer}")
        return "\n".join(lines) if lines else "None"

    # Full turn (search / missing slots) — include actionable prefs only.
    if bundle.default_country:
        lines.append(f"default_country: {bundle.default_country}")
    if bundle.preferred_cities:
        lines.append(f"preferred_cities: {', '.join(bundle.preferred_cities[:3])}")
    if bundle.frequent_industries:
        lines.append(f"frequent_industries: {', '.join(bundle.frequent_industries[:3])}")
    if bundle.default_radius_km is not None:
        lines.append(f"default_radius_km: {bundle.default_radius_km}")
    if bundle.requires_email is not None:
        lines.append(f"requires_email: {bundle.requires_email}")
    if bundle.preferred_quality:
        lines.append(f"preferred_quality: {bundle.preferred_quality}")
    if bundle.exclude:
        lines.append(f"exclude: {', '.join(bundle.exclude)}")
    if bundle.exact_category_only is not None:
        lines.append(f"exact_category_only: {bundle.exact_category_only}")
    if bundle.distance_unit:
        lines.append(f"distance_unit: {bundle.distance_unit}")
    if bundle.response_style:
        lines.append(f"response_style: {bundle.response_style}")
    if bundle.explanation_depth:
        lines.append(f"explanation_depth: {bundle.explanation_depth}")
    if bundle.use_examples is not None:
        lines.append(f"use_examples: {bundle.use_examples}")
    if bundle.preferred_tone:
        lines.append(f"preferred_tone: {bundle.preferred_tone}")
    if bundle.experience_level:
        lines.append(f"experience_level: {bundle.experience_level}")
    for c in bundle.corrections[:3]:
        lines.append(f"correction: {c.get('preference')}")
    if bundle.company_location:
        lines.append(f"company_location: {bundle.company_location}")
    if bundle.recent_searches:
        last = bundle.recent_searches[0]
        lines.append(
            "last_search: "
            + ", ".join(
                f"{k}={last[k]}"
                for k in ("industry", "location", "filters")
                if last.get(k) is not None
            )
        )
    return "\n".join(lines) if lines else "None"


def greeting_reply_hint(bundle: MemoryBundle, context: dict) -> str:
    """Hint for greeting responses — small and relevant, not a memory dump."""
    name = bundle.preferred_name
    has_active = bool(context.get("industry") or context.get("location") or context.get("country"))
    if has_active:
        return (
            "Greet briefly"
            + (f" using the name {name} once" if name else "")
            + ". The user already has an active search goal — do not restate old defaults; "
            "offer to continue or change."
        )

    if bundle.pending_offer:
        offer = bundle.pending_offer
        return (
            f"Greet briefly"
            + (f" as {name}" if name else "")
            + f". Ask once whether to save '{offer.get('value')}' as their "
            f"{offer.get('key', 'default')} preference (yes/no). Do not apply it yet."
        )

    usual = bundle.usual_location_label()
    last = bundle.recent_searches[0] if bundle.recent_searches else None
    parts = ["Greet warmly once"]
    if name:
        parts.append(f"using the name {name} once only")
    if last and last.get("industry") and last.get("location"):
        parts.append(
            f". Mention their last search ({last['industry']} in {last['location']}) "
            "and ask if they want to start another lead search — do not list other memories."
        )
    elif usual:
        parts.append(
            f". Offer their usual market ({usual}) or a different location — "
            "do not mention every preference you know."
        )
    else:
        parts.append(". Ask what industry they want to find leads for.")
    if bundle.experience_level == "experienced" or bundle.has_completed_first_search:
        parts.append(" Keep it short — they already know the product.")
    else:
        parts.append(" One short example is fine if helpful.")
    return "".join(parts)


def personalized_greeting_fallback(bundle: MemoryBundle, context: dict | None = None) -> str:
    context = context or {}
    name = bundle.preferred_name
    hi = f"Hi {name}" if name else "Hi"
    if context.get("industry") and not (context.get("location") or context.get("country")):
        return f"{hi}! Which city should I search for {context.get('industry')}?"
    if bundle.pending_offer:
        offer = bundle.pending_offer
        return (
            f"{hi}. You often search in {offer.get('value')}. "
            f"Want me to use that as your default location?"
        )
    last = bundle.recent_searches[0] if bundle.recent_searches else None
    if last and last.get("industry") and last.get("location"):
        return (
            f"{hi}. Last time you searched for {last['industry']} in {last['location']}. "
            "Would you like to start another lead search?"
        )
    usual = bundle.usual_location_label()
    if usual:
        return (
            f"{hi}, welcome back. Want to find leads using your usual {usual} market, "
            "or start with a different location?"
        )
    return f"{hi}! Happy to help you find business leads. What industry are you looking for?"


def soft_location_hint(bundle: MemoryBundle, context: dict) -> Optional[str]:
    """When industry is known but place is missing, offer usual market — do not silently fill."""
    if context.get("location") or context.get("country"):
        return None
    if not context.get("industry"):
        return None
    usual = bundle.usual_location_label()
    if not usual:
        return None
    industry = context.get("industry")
    return (
        f"Acknowledge the industry ({industry}). Offer to use their usual location "
        f"({usual}) or let them name another city. Do NOT silently assume {usual} "
        "without stating it. Do not dump other memories."
    )


# ---------------------------------------------------------------------------
# Explicit memory statements (safe to save immediately)
# ---------------------------------------------------------------------------
_RE_CALL_ME = re.compile(
    r"\b(?:call me|my name is|i'?m)\s+([A-Z][a-zA-Z'-]{1,30})\b",
    re.I,
)
_RE_DEFAULT_LOC = re.compile(
    r"\b(?:remember(?:\s+that)?\s+)?(?:my\s+)?default\s+(?:location|city|country)\s+is\s+([A-Za-z][A-Za-z\s,'.-]{1,60})",
    re.I,
)
_RE_REMEMBER_LOC = re.compile(
    r"\bremember(?:\s+that)?\s+(?:i\s+(?:usually|always)\s+(?:search|work)\s+(?:in|from)\s+)"
    r"([A-Za-z][A-Za-z\s,'.-]{1,60})",
    re.I,
)
_RE_EXACT_CAT = re.compile(
    r"\b(?:always\s+)?(?:search\s+)?exact\s+categor(?:y|ies)\b"
    r"|\bwhen i say\s+(\w+)\s*,?\s*i mean only\b"
    r"|\bonly\s+(\w+)\s*[—\-–]\s*not\b",
    re.I,
)
_RE_KM = re.compile(r"\buse\s+kilomet(?:er|re)s?\b|\bin\s+km\b", re.I)
_RE_MILES = re.compile(r"\buse\s+miles?\b|\bin\s+miles\b", re.I)
_RE_CONCISE = re.compile(r"\b(?:be\s+)?(?:more\s+)?concise\b|\bkeep\s+(?:it\s+)?short\b", re.I)
_RE_COMPANY_LOC = re.compile(
    r"\b(?:use|search)\s+(?:my\s+)?company\s+location\b",
    re.I,
)


async def apply_explicit_memory_statements(
    db: AsyncSession,
    user_id: UUID,
    message: str,
) -> list[str]:
    """Detect reusable explicit prefs; return human keys that were saved."""
    msg = (message or "").strip()
    if not msg:
        return []
    saved: list[str] = []

    m = _RE_CALL_ME.search(msg)
    if m:
        name = m.group(1).strip()
        # Avoid capturing "looking" from "I'm looking for hotels"
        if name.lower() not in {
            "looking", "searching", "trying", "here", "just", "not", "the", "a",
        }:
            await upsert_memory(
                db,
                user_id,
                category="identity",
                key="preferred_name",
                value=name,
                source=SOURCE_EXPLICIT,
                confirmed=True,
            )
            saved.append("preferred_name")

    m = _RE_DEFAULT_LOC.search(msg) or _RE_REMEMBER_LOC.search(msg)
    if m:
        place = m.group(1).strip().rstrip(".")
        await upsert_memory(
            db,
            user_id,
            category="search_pref",
            key="default_country",
            value=place,
            source=SOURCE_EXPLICIT,
            confirmed=True,
        )
        await upsert_memory(
            db,
            user_id,
            category="search_pref",
            key="preferred_cities",
            value=[place],
            source=SOURCE_EXPLICIT,
            confirmed=True,
        )
        saved.append("default_location")

    if _RE_EXACT_CAT.search(msg):
        await upsert_memory(
            db,
            user_id,
            category="correction",
            key="exact_category_only",
            value=True,
            source=SOURCE_EXPLICIT,
            confirmed=True,
        )
        await upsert_memory(
            db,
            user_id,
            category="search_pref",
            key="exact_category_only",
            value=True,
            source=SOURCE_EXPLICIT,
            confirmed=True,
        )
        saved.append("exact_category_only")

    if _RE_KM.search(msg):
        await upsert_memory(
            db,
            user_id,
            category="conversational",
            key="distance_unit",
            value="kilometers",
            source=SOURCE_EXPLICIT,
            confirmed=True,
        )
        saved.append("distance_unit")
    elif _RE_MILES.search(msg):
        await upsert_memory(
            db,
            user_id,
            category="conversational",
            key="distance_unit",
            value="miles",
            source=SOURCE_EXPLICIT,
            confirmed=True,
        )
        saved.append("distance_unit")

    if _RE_CONCISE.search(msg):
        await upsert_memory(
            db,
            user_id,
            category="conversational",
            key="response_style",
            value="concise",
            source=SOURCE_EXPLICIT,
            confirmed=True,
        )
        saved.append("response_style")

    return saved


def wants_company_location(message: str) -> bool:
    return bool(_RE_COMPANY_LOC.search(message or ""))


# ---------------------------------------------------------------------------
# Episodic: recent searches + inferred location offers
# ---------------------------------------------------------------------------
async def record_completed_search(
    db: AsyncSession,
    user_id: UUID,
    *,
    industry: Optional[str],
    location: Optional[str],
    country: Optional[str],
    filters: Optional[list[str]] = None,
    radius_km: Optional[float] = None,
    exact_category: bool = False,
) -> None:
    place = (location or country or "").strip() or None
    summary = {
        "industry": (industry or "").strip() or None,
        "location": place,
        "filters": filters or [],
        "completed_at": datetime.now(timezone.utc).date().isoformat(),
    }
    existing = await get_item(db, user_id, "recent_searches")
    recent: list[dict] = []
    if existing and isinstance(existing.value, list):
        recent = [r for r in existing.value if isinstance(r, dict)]
    recent = [summary] + [
        r
        for r in recent
        if not (
            r.get("industry") == summary["industry"]
            and r.get("location") == summary["location"]
        )
    ]
    recent = recent[:MAX_RECENT_SEARCHES]
    await upsert_memory(
        db,
        user_id,
        category="recent_search",
        key="recent_searches",
        value=recent,
        source=SOURCE_SYSTEM,
        confidence=1.0,
        confirmed=True,
        commit=False,
    )
    await upsert_memory(
        db,
        user_id,
        category="familiarity",
        key="has_completed_first_search",
        value=True,
        source=SOURCE_SYSTEM,
        confidence=1.0,
        confirmed=True,
        commit=False,
    )
    await upsert_memory(
        db,
        user_id,
        category="familiarity",
        key="experience_level",
        value="experienced",
        source=SOURCE_SYSTEM,
        confidence=0.9,
        confirmed=True,
        commit=False,
    )
    if radius_km is not None:
        await upsert_memory(
            db,
            user_id,
            category="familiarity",
            key="has_used_radius_filter",
            value=True,
            source=SOURCE_SYSTEM,
            confidence=1.0,
            confirmed=True,
            commit=False,
        )
    if exact_category:
        # Do not auto-confirm permanent exact-category from one search.
        pass

    # Track location hits for optional "make this your default?" offer.
    if place:
        hits_item = await get_item(db, user_id, "_location_hits")
        hits: dict = {}
        if hits_item and isinstance(hits_item.value, dict):
            hits = dict(hits_item.value)
        key = place.strip().lower()
        hits[key] = int(hits.get(key, 0)) + 1
        await upsert_memory(
            db,
            user_id,
            category="familiarity",
            key="_location_hits",
            value=hits,
            source=SOURCE_REPEATED,
            confidence=0.5,
            confirmed=False,
            commit=False,
        )
        default = await get_item(db, user_id, "default_country")
        preferred = await get_item(db, user_id, "preferred_cities")
        has_explicit_default = bool(
            (default and default.confirmed and default.source == SOURCE_EXPLICIT)
            or (preferred and preferred.confirmed and preferred.source == SOURCE_EXPLICIT)
        )
        if hits[key] >= LOCATION_HIT_OFFER_THRESHOLD and not has_explicit_default:
            await upsert_memory(
                db,
                user_id,
                category="search_pref",
                key="_pending_offer",
                value={
                    "key": "preferred_cities",
                    "value": place,
                    "reason": "repeated_searches",
                    "hits": hits[key],
                },
                source=SOURCE_REPEATED,
                confidence=0.6,
                confirmed=False,
                commit=False,
            )
        # Soft-update frequent industries (confirmed system list, not silent default apply).
        if industry:
            freq_item = await get_item(db, user_id, "frequent_industries")
            freq: list[str] = []
            if freq_item and isinstance(freq_item.value, list):
                freq = [str(x) for x in freq_item.value]
            ind = industry.strip()
            freq = [ind] + [x for x in freq if x.lower() != ind.lower()]
            await upsert_memory(
                db,
                user_id,
                category="search_pref",
                key="frequent_industries",
                value=freq[:5],
                source=SOURCE_SYSTEM,
                confidence=0.7,
                confirmed=True,
                commit=False,
            )
    await db.commit()


async def resolve_memory_offer_reply(
    db: AsyncSession,
    user_id: UUID,
    message: str,
    bundle: MemoryBundle,
) -> Optional[str]:
    """If a pending default-location offer exists, handle yes/no."""
    offer = bundle.pending_offer
    if not offer:
        return None
    msg = (message or "").strip().lower()
    affirm = bool(re.fullmatch(r"(yes|yep|yeah|yup|sure|ok|okay|please|do it|sounds good)[!.,\s]*", msg))
    negate = bool(re.fullmatch(r"(no|nope|nah|not now|don'?t|never)[!.,\s]*", msg))
    if not affirm and not negate:
        return None
    key = offer.get("key") or "preferred_cities"
    value = offer.get("value")
    # Clear pending offer either way.
    pending = await get_item(db, user_id, "_pending_offer")
    if pending:
        await db.delete(pending)
    if affirm and value:
        if key == "preferred_cities":
            await upsert_memory(
                db,
                user_id,
                category="search_pref",
                key="preferred_cities",
                value=[value],
                source=SOURCE_EXPLICIT,
                confirmed=True,
                commit=False,
            )
            await upsert_memory(
                db,
                user_id,
                category="search_pref",
                key="default_country",
                value=value,
                source=SOURCE_EXPLICIT,
                confirmed=True,
                commit=False,
            )
        else:
            await upsert_memory(
                db,
                user_id,
                category="search_pref",
                key=key,
                value=value,
                source=SOURCE_EXPLICIT,
                confirmed=True,
                commit=False,
            )
        await db.commit()
        return f"Got it — I'll remember {value} as your usual location."
    await db.commit()
    if negate:
        return "No problem — I won't set a default location."
    return None


def apply_exact_category_from_memory(context: dict, bundle: MemoryBundle) -> None:
    """If user has a confirmed exact-category preference and scope isn't set, hint context."""
    if bundle.exact_category_only and context.get("industry") and not context.get("scope_choice"):
        context.setdefault("_memory_exact_category", True)


def memory_priority_block() -> str:
    return (
        "LONG-TERM MEMORY PRIORITY (when values conflict):\n"
        "1. Current user message\n"
        "2. CURRENT CONTEXT / ChatState for this chat\n"
        "3. Explicit saved preferences (confirmed)\n"
        "4. Company / account profile\n"
        "5. Recent search summaries\n"
        "6. Inferred preferences (unconfirmed — ask before applying)\n"
        "7. Style preferences\n"
        "A current instruction always overrides long-term memory "
        "(e.g. saved Kathmandu + 'find hotels in London' → London).\n"
        "Use memory sparingly: greetings may use name + one usual market or last search. "
        "Do not list everything you know. Do not invent profile facts."
    )
