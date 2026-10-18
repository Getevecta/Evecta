"""Unit tests for the Personalization Level Engine."""
import pytest

from app.core.personalization import (
    effective_depth,
    normalize_tone,
    plan_capabilities,
    cap_depth,
)
from app.services.personalization_service import (
    score_lead_context,
    resolve_personalization,
)


class TestContextScoring:
    def test_none_when_no_context_fields(self):
        assert score_lead_context({}) == "none"
        assert score_lead_context({"business_name": "Acme"}) == "none"

    def test_partial_with_one_or_two_fields(self):
        assert score_lead_context({"website_summary": "A bakery."}) == "partial"
        assert (
            score_lead_context(
                {"website_summary": "A bakery.", "services": "Bread, cakes"}
            )
            == "partial"
        )

    def test_full_with_all_three_fields(self):
        data = {
            "website_summary": "A bakery.",
            "services": "Bread, cakes",
            "business_description": "Family-owned since 1990.",
        }
        assert score_lead_context(data) == "full"


class TestEffectiveDepth:
    def test_free_plan_caps_at_basic(self):
        assert effective_depth("free", "full") == "basic"

    def test_starter_with_full_context(self):
        assert effective_depth("starter", "full") == "standard"

    def test_growth_with_partial_context(self):
        assert effective_depth("growth", "partial") == "standard"

    def test_scale_with_no_context_degrades(self):
        assert effective_depth("scale", "none") == "basic"

    def test_cap_depth_picks_shallowest(self):
        assert cap_depth("deep", "basic", "standard") == "basic"


class TestToneNormalization:
    def test_defaults_to_friendly(self):
        assert normalize_tone(None) == "friendly"
        assert normalize_tone("") == "friendly"

    def test_normalizes_aliases(self):
        assert normalize_tone("Partnership Focused") == "partnership-focused"
        assert normalize_tone("Soft Introduction") == "soft-introduction"


class TestResolvePersonalization:
    def test_thin_context_uses_sender_fallback(self):
        profile = resolve_personalization(
            plan="growth",
            tone="professional",
            lead_data={"business_name": "Acme", "industry": "Retail"},
        )
        assert profile["context_score"] == "none"
        assert profile["effective_depth"] == "basic"
        assert profile["fallback"] == "sender_profile"
        assert profile["thin_context"] is True

    def test_deep_plan_with_full_context(self):
        profile = resolve_personalization(
            plan="growth",
            tone="friendly",
            lead_data={
                "business_name": "Acme",
                "website_summary": "Cloud software vendor.",
                "services": "SaaS, consulting",
                "business_description": "B2B platform for ops teams.",
            },
        )
        assert profile["context_score"] == "full"
        assert profile["effective_depth"] == "deep"
        assert "website_summary" in profile["context"]
        assert profile["fallback"] is None


class TestPlanCapabilities:
    def test_free_plan_capabilities(self):
        caps = plan_capabilities("free")
        assert caps["plan"] == "free"
        assert caps["max_depth"] == "basic"
        assert len(caps["tone_options"]) == 2
        assert len(caps["tone_tiers"]) == 3
