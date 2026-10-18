"""Geocode ranking: prefer town/locality over province centroids (Lumbini bug)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.services.lead_generation_service import (
    _geocode_query_variants,
    _is_broad_admin_geocode,
    geocode_location_candidates,
    pick_best_geocode_result,
)


def _result(types, lat, lng, *, lat_span=0.05, lng_span=0.05, country=None):
    components = []
    if country:
        components.append({
            "long_name": country,
            "short_name": country[:2].upper(),
            "types": ["country", "political"],
        })
    return {
        "types": types,
        "formatted_address": ",".join(types),
        "address_components": components,
        "geometry": {
            "location": {"lat": lat, "lng": lng},
            "viewport": {
                "northeast": {"lat": lat + lat_span / 2, "lng": lng + lng_span / 2},
                "southwest": {"lat": lat - lat_span / 2, "lng": lng - lng_span / 2},
            },
        },
    }


def test_pick_best_prefers_locality_over_province():
    """Staging bug: Google put Lumbini Province first; town must win."""
    province = _result(
        ["administrative_area_level_1", "political"],
        27.9207402,
        82.7347142,
        lat_span=2.0,
        lng_span=2.0,
    )
    town = _result(
        ["locality", "political"],
        27.4833,
        83.2767,
        lat_span=0.08,
        lng_span=0.08,
    )
    # Province listed first — same order Google returned on staging.
    best = pick_best_geocode_result([province, town])
    assert best is town
    assert best["geometry"]["location"]["lat"] == 27.4833


def test_pick_best_single_locality():
    town = _result(["locality", "political"], -37.8, 144.9)
    assert pick_best_geocode_result([town]) is town


def test_pick_best_empty():
    assert pick_best_geocode_result([]) is None
    assert pick_best_geocode_result(None) is None


def test_broad_admin_detects_large_province():
    province = _result(
        ["administrative_area_level_1", "political"],
        27.92,
        82.73,
        lat_span=2.5,
        lng_span=2.5,
    )
    assert _is_broad_admin_geocode(province)


def test_broad_admin_allows_small_locality():
    town = _result(["locality", "political"], 27.48, 83.28)
    assert not _is_broad_admin_geocode(town)


def test_query_variants_add_city_town_for_bare_name():
    variants = _geocode_query_variants("Lumbini")
    assert variants[0] == "Lumbini"
    assert "Lumbini city" in variants
    assert "Lumbini town" in variants
    assert "Lumbini municipality" in variants


def test_query_variants_with_country_from_province():
    variants = _geocode_query_variants("Lumbini", countries=["Nepal"])
    assert "Lumbini, Nepal" in variants
    assert "Lumbini city, Nepal" in variants


def test_query_variants_comma_name_keeps_base():
    variants = _geocode_query_variants("Lumbini, Nepal")
    assert variants[0] == "Lumbini, Nepal"


def test_warm_coverage_sql_ignores_empty_place_count():
    """Empty cold-loads must not freeze an area as warm (Lumbini Province poison)."""
    import inspect
    from app.services import lead_generation_service as lgs

    warm_src = inspect.getsource(lgs.overture_area_is_warm)
    ensure_src = inspect.getsource(lgs.ensure_overture_area_loaded)
    assert "place_count > 0" in warm_src
    assert "place_count > 0" in ensure_src
    assert "Empty cold-load NOT registered as warm" in ensure_src


def test_candidates_use_places_when_geocode_only_returns_province():
    """Staging: Geocode(Lumbini)=province only → Places Text Search supplies the town."""
    province = _result(
        ["administrative_area_level_1", "political"],
        27.9207402,
        82.7347142,
        lat_span=2.0,
        lng_span=2.0,
        country="Nepal",
    )

    async def fake_geocode(_client, address):
        # Every geocode variant returns only the province (real staging behavior).
        return [province]

    places_resp = MagicMock()
    places_resp.json.return_value = {
        "results": [
            {
                "name": "Lumbini",
                "types": ["locality", "political"],
                "geometry": {
                    "location": {"lat": 27.4833, "lng": 83.2767},
                    "viewport": {
                        "northeast": {"lat": 27.52, "lng": 83.32},
                        "southwest": {"lat": 27.45, "lng": 83.23},
                    },
                },
            }
        ]
    }
    client = AsyncMock()
    client.get.return_value = places_resp

    from app.services import lead_generation_service as lgs

    original = lgs._fetch_geocode_results
    original_key = lgs.GOOGLE_MAPS_API_KEY
    lgs._fetch_geocode_results = fake_geocode
    lgs.GOOGLE_MAPS_API_KEY = "test-key"
    try:
        candidates = asyncio.run(geocode_location_candidates(client, "Lumbini"))
    finally:
        lgs._fetch_geocode_results = original
        lgs.GOOGLE_MAPS_API_KEY = original_key

    assert candidates
    lat, lng, _radius = candidates[0]
    assert abs(lat - 27.4833) < 0.01
    assert abs(lng - 83.2767) < 0.01
    # Must not keep the province centroid as the primary center.
    assert abs(lat - 27.9207402) > 0.1
