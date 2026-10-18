from app.utils.ai_email_generator import (
    _is_unclear_description,
    _user_intent_section,
    _plain_text_snippet,
    get_fallback_template,
)


def test_partnership_brief_is_not_unclear():
    assert _is_unclear_description("write a mail for partnership") is False


def test_greeting_only_is_unclear():
    assert _is_unclear_description("hello") is True


def test_ads_placement_brief_is_not_unclear():
    assert _is_unclear_description("Write an email saying for ads placement or anything") is False


def test_user_intent_section_mentions_partnership_priority():
    section = _user_intent_section("write a mail for partnership")
    assert "partnership" in section.lower()
    assert "highest priority" in section.lower()
    assert "brief fidelity" in section.lower()
    assert "never discard" in section.lower() or "do not invent" in section.lower()


def test_user_intent_section_tells_model_not_to_abandon_unclear_brief():
    section = _user_intent_section("something about local events maybe")
    assert "rephrase" in section.lower() or "expand" in section.lower()
    assert "generic" in section.lower()


def test_plain_text_snippet_strips_html():
    snippet = _plain_text_snippet("<p>Hello</p><p>About <b>ads</b> placement</p>", max_chars=100)
    assert "Hello" in snippet
    assert "ads" in snippet
    assert "<p>" not in snippet


def test_fallback_embeds_user_brief():
    subject, body = get_fallback_template(
        description="Ask them about advertising placement on their website homepage",
        user_profile={"full_name": "Ada Lovelace"},
    )
    assert "advertising placement" in body.lower() or "advertising" in body.lower()
    assert "Ada Lovelace" in body
    assert "{{ business_name }}" in body


def test_campaign_email_llm_retry_loop_can_retry():
    """max_retries=1 made `attempt < max_retries - 1` always false."""
    import inspect
    from app.utils import ai_email_generator as mod

    source = inspect.getsource(mod.generate_campaign_ai_draft)
    assert "max_retries = 1" not in source
    assert "max_retries = 2" in source or "max_retries = 3" in source
