"""Unit tests for early Google Maps place classification."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.utils.chat_recovery import build_place_unresolved_recovery


def test_classify_place_unresolved_when_google_empty():
    from app.services import chat_service as cs

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": []}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with (
        patch.object(cs, "GOOGLE_MAPS_API_KEY", "test-key"),
        patch.object(cs, "get_cached_place_kind", return_value=None),
        patch.object(cs, "set_cached_place_kind") as set_kind,
        patch.object(cs, "set_cached_region_check"),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        kind = asyncio.run(cs.classify_place_on_map("ZzzNotARealCity999"))
        assert kind == "unresolved"
        set_kind.assert_called_with("ZzzNotARealCity999", "unresolved")


def test_classify_place_city_when_locality():
    from app.services import chat_service as cs

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "results": [
            {
                "types": ["locality", "political"],
                "geometry": {
                    "location": {"lat": -37.8, "lng": 144.9},
                    "viewport": {
                        "northeast": {"lat": -37.7, "lng": 145.0},
                        "southwest": {"lat": -37.9, "lng": 144.8},
                    },
                },
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with (
        patch.object(cs, "GOOGLE_MAPS_API_KEY", "test-key"),
        patch.object(cs, "get_cached_place_kind", return_value=None),
        patch.object(cs, "set_cached_place_kind") as set_kind,
        patch.object(cs, "set_cached_region_check"),
        patch.object(cs, "set_cached_geocode"),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        kind = asyncio.run(cs.classify_place_on_map("Melbourne"))
        assert kind == "city"
        set_kind.assert_called_with("Melbourne", "city")


def test_classify_continent_as_broad_region_without_api():
    """Africa/Asia/etc. must never be treated as a searchable city."""
    from app.services import chat_service as cs

    with (
        patch.object(cs, "GOOGLE_MAPS_API_KEY", "test-key"),
        patch.object(cs, "set_cached_place_kind") as set_kind,
        patch.object(cs, "set_cached_region_check") as set_region,
        patch("httpx.AsyncClient") as client_cls,
    ):
        kind = asyncio.run(cs.classify_place_on_map("Africa"))
        assert kind == "broad_region"
        set_kind.assert_called_with("Africa", "broad_region")
        set_region.assert_called_with("Africa", True)
        client_cls.assert_not_called()


def test_classify_geocode_continent_type_as_broad_region():
    from app.services import chat_service as cs

    result = {
        "types": ["continent", "political"],
        "geometry": {
            "location": {"lat": 0.0, "lng": 20.0},
            "viewport": {
                "northeast": {"lat": 40.0, "lng": 60.0},
                "southwest": {"lat": -40.0, "lng": -20.0},
            },
        },
    }
    assert cs._classify_geocode_result("Somewhere", result) == "broad_region"


def test_classify_large_non_country_bounds_as_broad_region():
    from app.services import chat_service as cs

    result = {
        "types": ["political"],
        "geometry": {
            "location": {"lat": 0.0, "lng": 0.0},
            "viewport": {
                "northeast": {"lat": 20.0, "lng": 20.0},
                "southwest": {"lat": -20.0, "lng": -20.0},
            },
        },
    }
    assert cs._classify_geocode_result("Large Area", result) == "broad_region"

def test_classify_place_rejects_chat_garbage_without_api():
    from app.services import chat_service as cs

    with patch.object(cs, "GOOGLE_MAPS_API_KEY", "test-key"):
        assert asyncio.run(cs.classify_place_on_map("no no i want chocolate")) == "unresolved"


def test_classify_uses_cache():
    from app.services import chat_service as cs

    with (
        patch.object(cs, "GOOGLE_MAPS_API_KEY", "test-key"),
        patch.object(cs, "get_cached_place_kind", return_value="broad_region"),
        patch("httpx.AsyncClient") as client_cls,
    ):
        kind = asyncio.run(cs.classify_place_on_map("Australia"))
        assert kind == "broad_region"
        client_cls.assert_not_called()


def test_place_unresolved_recovery_clears_path_for_change_city():
    payload = build_place_unresolved_recovery(
        {"industry": "chocolate"},
        "ZzzNotARealCity999",
    )
    assert payload["recovery_kind"] == "location_unresolved"
    assert "ZzzNotARealCity999" in payload["message"]
    assert "on the map" in payload["message"]
    by_id = {a["id"]: a for a in payload["actions"]}
    assert by_id["change_location"]["message"] == "change city"
    assert "start_over" in by_id


def test_return_place_unresolved_clears_slots():
    from app.services.chat_service import _return_place_unresolved

    ctx = {"industry": "dentists", "location": "ZzzFake", "confirmed_goal": "x"}
    history: list = []
    payload = _return_place_unresolved(ctx, history, "ZzzFake", clear_location=True)
    assert "location" not in ctx
    assert "confirmed_goal" not in ctx
    assert ctx["industry"] == "dentists"
    assert payload["recovery_kind"] == "location_unresolved"
    assert history and history[-1]["role"] == "assistant"
