from datetime import datetime, timezone

from pydantic import ValidationError
import pytest

from app.schemas.campaign_draft import CampaignDraftBase, DraftType
from app.schemas.email_template import EmailTemplateCreate
from app.services.email_send_idempotency import duplicate_send_skip_reason
from app.utils.header_safety import (
    CONTENT_MAX_LENGTH,
    NAME_MAX_LENGTH,
    require_safe_header,
    require_safe_text,
)
from app.utils.log_redaction import redact_url_credentials


def test_require_safe_header_rejects_crlf():
    with pytest.raises(ValueError, match="invalid characters"):
        require_safe_header("Hello\r\nBcc: evil@x.com", name="subject", max_length=255)


def test_require_safe_text_rejects_nul_and_controls():
    with pytest.raises(ValueError, match="invalid characters"):
        require_safe_text("hi\x00there", name="content", max_length=CONTENT_MAX_LENGTH)
    with pytest.raises(ValueError, match="invalid characters"):
        require_safe_text("bad\x07name", name="name", max_length=NAME_MAX_LENGTH, allow_newlines=False)


def test_require_safe_text_allows_newlines_in_content():
    body = "Hello,\n\nThis is a paragraph."
    assert require_safe_text(body, name="content", max_length=CONTENT_MAX_LENGTH) == body


def test_template_create_validates_name_and_content():
    with pytest.raises(ValidationError):
        EmailTemplateCreate(
            name="Nice\nName",
            subject="Hello",
            content="Body",
        )
    with pytest.raises(ValidationError):
        EmailTemplateCreate(
            name="ok",
            subject="Hello\nWorld",
            content="Body",
        )
    EmailTemplateCreate(name="Outreach", subject="Hello", content="Hi {{ business_name }}")


def test_campaign_draft_rejects_control_chars_in_prompt_and_content():
    with pytest.raises(ValidationError):
        CampaignDraftBase(
            draft_type=DraftType.AI,
            ai_email_prompt="hello\x00world",
        )
    CampaignDraftBase(
        draft_type=DraftType.MANUAL,
        email_subject="Hello",
        email_content="Line one\nLine two",
    )


def test_redact_redis_password():
    assert (
        redact_url_credentials("redis://:s3cret@localhost:6379/0")
        == "redis://localhost:6379/0"
    )
    assert (
        redact_url_credentials("redis://user:pass@cache.internal:6379/1")
        == "redis://cache.internal:6379/1"
    )
    assert redact_url_credentials("redis://localhost:6379/0") == "redis://localhost:6379/0"
    assert redact_url_credentials(None) == ""


def test_duplicate_send_skip_reasons():
    now = datetime.now(timezone.utc)
    assert duplicate_send_skip_reason(smtp_started_at=None, has_successful_activity=False) is None
    assert (
        duplicate_send_skip_reason(smtp_started_at=None, has_successful_activity=True)
        == "already_sent_activity"
    )
    assert (
        duplicate_send_skip_reason(smtp_started_at=now, has_successful_activity=False)
        == "smtp_already_started"
    )
