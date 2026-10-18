"""Unit prices for Hunter.io and Google Places/Maps (USD snapshot at write time)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from app.utils.money import as_decimal, quantize_cost, quantize_rate

# Google Maps Platform list prices used at Evecta (Essentials / Places Pro SKUs).
# Geocoding: $5.00 / 1,000 after 10,000 free monthly → $0.005 / request.
# Nearby / Text Search (legacy Places): ~$32 / 1,000 → $0.032 / request.
# Place Details (Basic/Contact fields): ~$17 / 1,000 → $0.017 / request.
GOOGLE_PLACES_UNIT_USD: dict[str, float] = {
    "geocode": 0.005,
    "nearby_search": 0.032,
    "place_details": 0.017,
    "text_search": 0.032,
}

# Catalog shown in admin AI Usage / Maps pricing panels.
GOOGLE_MAPS_API_CATALOG: list[dict[str, Any]] = [
    {
        "api_name": "geocode",
        "label": "Geocoding",
        "endpoint": "/maps/api/geocode/json",
        "unit_cost_usd": GOOGLE_PLACES_UNIT_USD["geocode"],
        "unit_label": "per request",
        "free_monthly": 10_000,
        "notes": (
            "City / address → lat/lng. First 10,000 requests/month free on Google "
            "Essentials; Evecta estimates $0.005 after that. Redis-cached 7 days."
        ),
    },
    {
        "api_name": "nearby_search",
        "label": "Nearby Search",
        "endpoint": "/maps/api/place/nearbysearch/json",
        "unit_cost_usd": GOOGLE_PLACES_UNIT_USD["nearby_search"],
        "unit_label": "per request",
        "free_monthly": None,
        "notes": "Lead discovery around a point. Up to 20 results per page (max 3 pages).",
    },
    {
        "api_name": "place_details",
        "label": "Place Details",
        "endpoint": "/maps/api/place/details/json",
        "unit_cost_usd": GOOGLE_PLACES_UNIT_USD["place_details"],
        "unit_label": "per request",
        "free_monthly": None,
        "notes": "Enrichment per business (name, phone, website, address fields).",
    },
    {
        "api_name": "text_search",
        "label": "Text Search",
        "endpoint": "/maps/api/place/textsearch/json",
        "unit_cost_usd": GOOGLE_PLACES_UNIT_USD["text_search"],
        "unit_label": "per request",
        "free_monthly": None,
        "notes": "Text query place lookup when geocode/nearby need a Places fallback.",
    },
]


def google_maps_pricing_catalog() -> list[dict[str, Any]]:
    """Return the Google Maps / Places APIs Evecta bills against."""
    return [dict(row) for row in GOOGLE_MAPS_API_CATALOG]

# Hunter.io: 1 credit per successful domain-search / companies/find call.
# Default ≈ Growth plan effective cost ($104 / 2,500 searches).
DEFAULT_HUNTER_CREDIT_USD = 0.042

HUNTER_APIS = frozenset({"domain_search", "company_find"})
GOOGLE_PLACES_APIS = frozenset(GOOGLE_PLACES_UNIT_USD.keys())


def hunter_credit_cost_usd() -> float:
    try:
        from app.core.config import settings

        val = getattr(settings, "HUNTER_CREDIT_COST_USD", None)
        if val is not None and float(val) >= 0:
            return float(val)
    except Exception:
        pass
    return DEFAULT_HUNTER_CREDIT_USD


def unit_cost_usd(provider: str, api_name: str) -> Optional[Decimal]:
    if provider == "hunter" and api_name in HUNTER_APIS:
        return as_decimal(hunter_credit_cost_usd())
    if provider == "google_places":
        unit = GOOGLE_PLACES_UNIT_USD.get(api_name)
        return as_decimal(unit) if unit is not None else None
    return None


def estimate_cost_usd(provider: str, api_name: str, units: int) -> tuple[Decimal, Optional[Decimal]]:
    """Return (estimated_cost_usd, unit_cost_usd)."""
    unit = unit_cost_usd(provider, api_name)
    if unit is None or units <= 0:
        return Decimal("0"), quantize_rate(unit) if unit is not None else None
    return quantize_cost(unit * units), quantize_rate(unit)


def places_is_billable(status: Optional[str]) -> bool:
    """Google bills OK and ZERO_RESULTS; quota/denied/invalid usually do not."""
    return (status or "").upper() in {"OK", "ZERO_RESULTS"}
