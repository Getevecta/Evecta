"""Unit tests for Template + Variation Engine (stage #3)."""
import pytest

from app.core.personalization import resolve_engine_level, tone_to_engine_key
from app.email_engine import loader, variation
from app.email_engine.loader import clear_cache
from app.email_engine.prompt_builder import format_writing_spec_prompt
from app.email_engine.repetition import is_too_similar, jaccard_similarity
from app.email_engine.spec_builder import build_spec
from app.services.personalization_service import resolve_personalization
from app.services.writing_spec_service import build_writing_spec, writing_spec_summary


@pytest.fixture(autouse=True)
def _fresh_loader_cache():
    clear_cache()
    yield
    clear_cache()


class TestToneBridge:
    def test_ui_tone_maps_to_engine_key(self):
        assert tone_to_engine_key("partnership-focused") == "partnership"
        assert tone_to_engine_key("soft-introduction") == "soft_intro"
        assert tone_to_engine_key("persuasive") == "persuasive"
        assert tone_to_engine_key("enthusiastic") == "enthusiastic"


class TestEngineLevel:
    def test_thin_context_caps_to_minimal(self):
        assert resolve_engine_level("scale", "basic") == "minimal"

    def test_scale_deep_becomes_research(self):
        assert resolve_engine_level("scale", "deep") == "research"

    def test_growth_deep_stays_deep(self):
        assert resolve_engine_level("growth", "deep") == "deep"


class TestLoader:
    def test_structures_loaded(self):
        structures = loader.get_structures()
        assert len(structures) >= 2
        assert "short_intro" in structures

    def test_tone_files_load(self):
        assert "formal" in loader.get_tone("professional").lower() or loader.get_tone("professional")

    def test_prohibited_phrases_nonempty(self):
        assert len(loader.get_prohibited_phrases()) > 0


class TestVariation:
    def test_deterministic_selection(self):
        a = variation.select_variants(campaign_seed="camp-1", index=0, tone="friendly", personalization_level="standard")
        b = variation.select_variants(campaign_seed="camp-1", index=0, tone="friendly", personalization_level="standard")
        assert a.structure_id == b.structure_id
        assert a.greeting == b.greeting

    def test_index_changes_recipe(self):
        a = variation.select_variants(campaign_seed="camp-1", index=0, tone="friendly", personalization_level="standard")
        b = variation.select_variants(campaign_seed="camp-1", index=1, tone="friendly", personalization_level="standard")
        # At least one axis should differ across leads in a real pool
        assert (
            a.structure_id != b.structure_id
            or a.greeting != b.greeting
            or a.cta != b.cta
            or a.closing != b.closing
        )

    def test_minimal_level_limits_structures(self):
        sel = variation.select_variants(
            campaign_seed="x", index=0, tone="professional", personalization_level="minimal"
        )
        assert sel.structure_id in {"short_intro", "problem_solution"}


class TestSpecBuilder:
    def test_build_spec_has_merge_fields(self):
        spec = build_spec(
            lead={"business_name": "Acme", "industry": "Retail", "address": "NY"},
            campaign_seed="c1",
            index=0,
            tone="professional",
            personalization_level="standard",
        )
        assert spec.structure_id
        assert spec.greeting
        assert "{{ business_name }}" in " ".join(loader.get_required_merge_fields()) or spec.required_merge_fields

    def test_minimal_hides_deep_context(self):
        spec = build_spec(
            lead={
                "business_name": "Acme",
                "industry": "Retail",
                "website_summary": "Hidden",
            },
            campaign_seed="c1",
            index=0,
            tone="friendly",
            personalization_level="minimal",
        )
        assert "website_summary" not in spec.lead_context


class TestPromptBuilder:
    def test_format_includes_structure(self):
        spec = build_spec(
            lead={"business_name": "Acme", "industry": "Tech"},
            campaign_seed="c1",
            index=0,
            tone="friendly",
            personalization_level="standard",
        )
        text = format_writing_spec_prompt(spec)
        assert "WRITING SPEC" in text
        assert spec.structure_label in text or spec.structure_id in text


class TestWritingSpecService:
    def test_end_to_end_from_personalization(self):
        lead = {
            "business_name": "Acme",
            "industry": "SaaS",
            "address": "Austin",
            "services": "Analytics",
            "website_summary": "B2B platform",
            "business_description": "Ops tooling",
        }
        spec = build_writing_spec(
            lead_data=lead,
            plan="growth",
            tone="partnership-focused",
            campaign_seed="campaign-abc",
            index=2,
        )
        summary = writing_spec_summary(spec)
        assert summary["tone"] == "partnership"
        assert summary["structure_id"]


class TestRepetition:
    def test_identical_text_is_similar(self):
        a = "<p>Hello there we help teams grow faster every day</p>"
        assert is_too_similar(a, [a])

    def test_different_text_not_similar(self):
        a = "<p>Hello {{ business_name }} we offer cloud security tools</p>"
        b = "<p>Hi {{ business_name }} curious if you explore automation partners</p>"
        assert jaccard_similarity(a, b) < 0.6
