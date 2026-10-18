"""Overture category matching: primary-only, token-boundary.

Guards the two bugs found on 2026-07-23 in a live "restaurants in Kathmandu" search:
  1. alternate categories were matched as strongly as the primary one, so bus stops
     and police departments came back as restaurants;
  2. codes were matched as substrings, so "bar" reached "barber" and "public_toilet".
"""
import re

from app.services.lead_generation_service import (
    _duckdb_binder,
    _overture_match_sql,
    _pg_binder,
    resolve_overture_filter,
)

PG_COLS = {
    "primary_col": "category_primary",
    "taxonomy_col": "taxonomy_primary",
    "hierarchy_col": "taxonomy_hierarchy",
    "name_col": "name",
}


def build(resolved_filter: dict) -> tuple[str, dict]:
    params: dict = {}
    clause = _overture_match_sql(resolved_filter, bind=_pg_binder(params), **PG_COLS)
    return clause, params


def like(value: str, pattern: str) -> bool:
    """SQL LIKE, including "_" as a single-character wildcard (the trap in bug 2)."""
    regex = "".join(
        ".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern
    )
    return re.match(f"^{regex}$", value, re.DOTALL) is not None


def haystack_for(category: str | None) -> str:
    """What _overture_token_haystack builds for a row: primary + taxonomy ancestry."""
    norm = (category or "").lower().replace("_", "|")
    return f"|{norm}|{norm}||"


def matches(clause: str, params: dict, *, category: str | None, name: str = "") -> bool:
    """Evaluate the generated clause the way Postgres would, one OR-branch at a time."""
    body = clause[1:-1] if clause.startswith("(") and clause.endswith(")") else clause
    for condition in body.split(" OR "):
        placeholder = re.search(r":(p\d+)", condition)
        if not placeholder:
            continue
        pattern = params[placeholder.group(1)]
        if "lower(coalesce(name" in condition:
            gated = "IS NULL AND" in condition
            if gated and category is not None:
                continue
            if like(name.lower(), pattern):
                return True
        elif like(haystack_for(category), pattern):
            return True
    return False


class TestTokenBoundary:
    """Bug 2 — "%bar%" must not reach "barber"."""

    def test_bar_does_not_match_barber_or_public_school(self):
        clause, params = build(resolve_overture_filter("bars"))
        assert matches(clause, params, category="bar")
        assert matches(clause, params, category="cocktail_bar")
        for wrong in ("barber", "bartender", "barbecue_restaurant", "public_school",
                      "public_toilet", "notary_public", "public_transportation"):
            assert not matches(clause, params, category=wrong), wrong

    def test_multi_token_codes_stay_contiguous(self):
        clause, params = build({"category_codes": ["coffee_shop"], "keyword_patterns": []})
        assert matches(clause, params, category="coffee_shop")
        assert not matches(clause, params, category="frozen_yoghurt_shop")

    def test_multi_token_codes_are_anchored_at_both_ends(self):
        """pet_store must not reach carpet_store even though suffixes are allowed."""
        clause, params = build({"category_codes": ["pet_store"], "keyword_patterns": []})
        assert matches(clause, params, category="pet_store")
        assert not matches(clause, params, category="carpet_store")


class TestSuffixAndPlural:
    """Overture writes `bookstore`, `gastropub`, `architecture_schools`, `spas`.
    Anchoring single-token codes at both ends dropped 31 legitimate codes."""

    def test_single_token_codes_match_as_suffix(self):
        for code, real in [("store", "bookstore"), ("store", "drugstore"),
                           ("store", "superstore"), ("pub", "gastropub"),
                           ("school", "preschool")]:
            clause, params = build({"category_codes": [code], "keyword_patterns": []})
            assert matches(clause, params, category=real), f"{code} -> {real}"

    def test_single_token_codes_match_plurals(self):
        for code, real in [("spa", "spas"), ("school", "architecture_schools"),
                           ("lawyer", "civil_rights_lawyers"),
                           ("contractor", "flooring_contractors"),
                           ("store", "dairy_stores")]:
            clause, params = build({"category_codes": [code], "keyword_patterns": []})
            assert matches(clause, params, category=real), f"{code} -> {real}"

    def test_suffix_allowance_does_not_reopen_the_substring_bug(self):
        """The trailing delimiter still has to line up."""
        clause, params = build({"category_codes": ["bar", "pub"], "keyword_patterns": []})
        assert matches(clause, params, category="cocktail_bar")
        for wrong in ("barber", "bartender", "cabaret", "barbecue_restaurant",
                      "public_toilet", "public_school", "notary_public", "topic_publisher"):
            assert not matches(clause, params, category=wrong), wrong

    def test_spa_does_not_reach_space_or_spanish(self):
        clause, params = build({"category_codes": ["spa"], "keyword_patterns": []})
        assert matches(clause, params, category="day_spa")
        for wrong in ("art_space_rental", "coworking_space", "makerspace", "spanish_restaurant"):
            assert not matches(clause, params, category=wrong), wrong

    def test_other_known_regressions(self):
        cases = [("pet stores", "carpet_store"), ("gyms", "gymnastics_center"),
                 ("dentists", "dentistry_schools"), ("cafes", "cafeteria")]
        for term, wrong in cases:
            clause, params = build(resolve_overture_filter(term))
            assert not matches(clause, params, category=wrong), f"{term} -> {wrong}"

    def test_underscore_is_not_used_as_a_delimiter(self):
        """"_" is a single-char wildcard in LIKE; using it as a boundary matches all."""
        _, params = build(resolve_overture_filter("bars"))
        assert not any("_" in pattern for pattern in params.values())


class TestPrimaryOnly:
    """Bug 1 — a place must earn its spot on its own primary category."""

    def test_leaf_and_ancestry_match(self):
        clause, params = build(resolve_overture_filter("restaurants"))
        for right in ("restaurant", "pizza_restaurant", "himalayan_nepalese_restaurant"):
            assert matches(clause, params, category=right), right

    def test_alternate_only_places_are_excluded(self):
        """The real rows that polluted the search: primary is not food."""
        clause, params = build(resolve_overture_filter("restaurants"))
        for wrong in ("bus_station", "police_department", "clothing_store", "hotel",
                      "beauty_salon", "language_school", "park", "automotive_dealer"):
            assert not matches(clause, params, category=wrong), wrong

    def test_clause_never_reads_the_alternates_array(self):
        clause, _ = build(resolve_overture_filter("restaurants"))
        assert "categories" not in clause


class TestNameFallback:
    def test_uncategorised_places_are_rescued_by_name(self):
        """Keeps real listings like "waah restaurant & cafe" that Overture never typed."""
        clause, params = build(resolve_overture_filter("restaurant"))
        assert matches(clause, params, category=None, name="waah restaurant & cafe")

    def test_known_gap_plural_terms_miss_the_name_rescue(self):
        """Pre-existing: keyword patterns are the raw term, so a plural search builds
        "%restaurants%", which no singular business name contains. Category matching is
        unaffected (aliases cover plurals); only uncategorised rows lose the rescue."""
        clause, params = build(resolve_overture_filter("restaurants"))
        assert not matches(clause, params, category=None, name="waah restaurant & cafe")
        assert matches(clause, params, category="pizza_restaurant")

    def test_categorised_places_cannot_win_on_name_alone(self):
        clause, params = build(resolve_overture_filter("restaurants"))
        assert not matches(clause, params, category="hotel", name="Hotel Everest Restaurant")

    def test_long_tail_industries_still_match_on_name(self):
        """No category resolved -> name is the only signal, so it stays unrestricted."""
        resolved = resolve_overture_filter("solar panel installers")
        assert not resolved["has_category"]
        clause, params = build(resolved)
        assert f"({PG_COLS['primary_col']} IS NULL AND" not in clause
        assert matches(clause, params, category=None, name="himalaya solar panel installers")


class TestBinders:
    def test_duckdb_binder_is_positional_and_ordered(self):
        values: list = []
        clause = _overture_match_sql(
            {"category_codes": ["restaurant", "cafe"], "keyword_patterns": ["%pizza%"]},
            primary_col="categories.primary",
            taxonomy_col="taxonomy.primary",
            hierarchy_col="taxonomy.hierarchy",
            name_col="names.primary",
            bind=_duckdb_binder(values),
        )
        # 3 patterns per single-token code (exact/suffix + 2 plurals) + 1 keyword
        assert clause.count("?") == len(values) == 7
        assert values[0] == "%restaurant|%" and values[3] == "%cafe|%"
        assert values[-1] == "%pizza%"

    def test_empty_filter_matches_everything(self):
        clause, params = build({"category_codes": [], "keyword_patterns": []})
        assert clause == "TRUE"
        assert params == {}

    def test_legacy_pattern_only_filters_still_work(self):
        """overture_refresh_service and older callers pass "%code%" without codes."""
        clause, params = build({"category_patterns": ["%restaurant%"], "keyword_patterns": []})
        assert list(params.values()) == ["%restaurant|%", "%restaurants|%", "%restaurantes|%"]
        assert matches(clause, params, category="pizza_restaurant")
        assert not matches(clause, params, category="hotel")

    def test_known_gap_restaurant_supply_store(self):
        """Documents a known limitation: "restaurant" is a real token here, so a shop
        selling restaurant equipment still matches. Needs a denylist, not a match fix."""
        clause, params = build(resolve_overture_filter("restaurants"))
        assert matches(clause, params, category="restaurant_supply_store")
