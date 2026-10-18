"""Tests for backend-managed email tone registry."""
import pytest

from app.core.email_tones import (
    default_tone_for_plan,
    is_tone_unlocked_for_plan,
    normalize_tone,
    tone_to_engine_key,
    tone_tiers_for_api,
    unlocked_tone_options,
    validate_tone_for_plan,
)
from app.core.personalization import plan_capabilities
from app.email_engine import loader
from app.email_engine.loader import clear_cache


@pytest.fixture(autouse=True)
def _fresh_loader_cache():
    clear_cache()
    yield
    clear_cache()


class TestToneRegistry:
    def test_each_ui_tone_has_dedicated_engine_rules(self):
        for tone_id in (
            "professional",
            "friendly",
            "casual",
            "persuasive",
            "partnership-focused",
            "soft-introduction",
            "enthusiastic",
        ):
            engine_key = tone_to_engine_key(tone_id)
            body = loader.get_tone(engine_key)
            assert body.strip(), f"missing rules for {tone_id} -> {engine_key}"

    def test_persuasive_and_enthusiastic_no_longer_alias_other_tones(self):
        assert tone_to_engine_key("persuasive") == "persuasive"
        assert tone_to_engine_key("enthusiastic") == "enthusiastic"

    def test_free_plan_unlocks_starter_tones_only(self):
        assert is_tone_unlocked_for_plan("free", "friendly")
        assert is_tone_unlocked_for_plan("free", "professional")
        assert not is_tone_unlocked_for_plan("free", "casual")
        assert not is_tone_unlocked_for_plan("free", "soft-introduction")

    def test_growth_plan_unlocks_growth_tier(self):
        assert is_tone_unlocked_for_plan("growth", "persuasive")
        assert not is_tone_unlocked_for_plan("growth", "enthusiastic")

    def test_validate_rejects_locked_tone(self):
        with pytest.raises(ValueError, match="not available"):
            validate_tone_for_plan("free", "persuasive")

    def test_validate_accepts_unlocked_tone(self):
        assert validate_tone_for_plan("starter", "friendly") == "friendly"

    def test_default_tone_for_plan(self):
        assert default_tone_for_plan("free") == "professional"
        assert default_tone_for_plan("growth") in {"casual", "professional", "friendly"}


class TestToneApiPayload:
    def test_plan_capabilities_includes_tone_tiers(self):
        caps = plan_capabilities("starter")
        assert "tone_tiers" in caps
        assert len(caps["tone_tiers"]) == 3
        assert caps["default_tone"]
        starter = caps["tone_tiers"][0]
        assert starter["tier_plan"] == "starter"
        assert starter["badge"] == "YOUR PLAN"

    def test_unlocked_tone_options_respects_plan(self):
        free_options = unlocked_tone_options("free")
        assert {t["id"] for t in free_options} == {"professional", "friendly"}

        growth_options = unlocked_tone_options("growth")
        ids = {t["id"] for t in growth_options}
        assert "persuasive" in ids
        assert "enthusiastic" not in ids

    def test_tone_tiers_include_backend_badge(self):
        tiers = tone_tiers_for_api("free")
        growth = next(t for t in tiers if t["tier_plan"] == "growth")
        assert growth["badge"] == "UPGRADE TO UNLOCK"
        assert growth["unlocked"] is False

    def test_normalize_aliases(self):
        assert normalize_tone("Concise") == "casual"
        assert normalize_tone("Partnership Focused") == "partnership-focused"
