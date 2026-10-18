"""Section D: scraper SSRF, MIME CR/LF, Hunter 429 distinction."""
from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from app.models.mailbox import MailboxType
from app.schemas.campaign_draft import CampaignDraftBase, DraftType, SpamCheckRequest
from app.utils.email_mime_builder import build_campaign_mime_bytes
from app.utils.safe_http import parse_safe_http_url, safe_http_get_text


def test_http_url_rejects_schemes_ports_and_userinfo():
    assert parse_safe_http_url("file:///etc/passwd") is None
    assert parse_safe_http_url("https://example.com:8080/") is None
    assert parse_safe_http_url("https://user:pass@example.com/") is None
    assert parse_safe_http_url("https://example.com/path") is not None
    assert parse_safe_http_url("http://example.com/contact") is not None


def test_loopback_http_is_not_fetched():
    assert safe_http_get_text("http://127.0.0.1/") is None
    assert safe_http_get_text("http://169.254.169.254/latest/meta-data") is None
    assert safe_http_get_text("http://localhost/") is None


def test_redirect_to_private_host_is_not_followed(monkeypatch):
    monkeypatch.setattr(
        "app.utils.safe_http.try_resolve_public_ip",
        lambda host: (host, "93.184.216.34") if host == "example.com" else None,
    )
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})

    text = safe_http_get_text(
        "https://example.com/",
        transport=httpx.MockTransport(handler),
    )
    assert text is None
    assert requested
    assert all("127.0.0.1" not in url for url in requested)
    assert requested[0].startswith("https://93.184.216.34")


def test_pinned_request_keeps_original_host_header(monkeypatch):
    monkeypatch.setattr(
        "app.utils.safe_http.try_resolve_public_ip",
        lambda host: (host, "93.184.216.34"),
    )
    seen_host = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_host["host"] = request.headers.get("host")
        seen_host["url_host"] = request.url.host
        return httpx.Response(200, text="<html>ok</html>")

    text = safe_http_get_text(
        "https://example.com/about",
        transport=httpx.MockTransport(handler),
    )
    assert text == "<html>ok</html>"
    assert seen_host["host"] == "example.com"
    assert seen_host["url_host"] == "93.184.216.34"


def test_mime_builder_rejects_crlf_in_headers():
    with pytest.raises(ValueError):
        build_campaign_mime_bytes(
            html_content="<p>hi</p>",
            subject="Hello\r\nBcc: attacker@evil.com",
            from_addr="from@example.com",
            to_email="to@example.com",
            message_id="<id@evecta>",
            unsubscribe_url=None,
            campaign_id="c1",
            lead_id="l1",
            mailbox_type=MailboxType.USER,
        )
    with pytest.raises(ValueError):
        build_campaign_mime_bytes(
            html_content="<p>hi</p>",
            subject="Hello",
            from_addr="from@example.com",
            to_email="to@example.com\r\nBcc: attacker@evil.com",
            message_id="<id@evecta>",
            unsubscribe_url=None,
            campaign_id="c1",
            lead_id="l1",
            mailbox_type=MailboxType.USER,
        )


def test_mime_builder_emits_list_unsubscribe_before_content_type():
    raw = build_campaign_mime_bytes(
        html_content="<p>hi</p>",
        subject="Hello",
        from_addr="from@example.com",
        to_email="to@example.com",
        message_id="<EV-1@evecta>",
        unsubscribe_url="https://evecta.io/unsub",
        campaign_id="c1",
        lead_id="l1",
        mailbox_type=MailboxType.USER,
    )
    text = raw.decode()
    assert text.index("List-Unsubscribe:") < text.index("Content-Type:")
    assert "\r\nBcc:" not in text


def test_draft_and_spam_schemas_reject_header_injection():
    with pytest.raises(ValidationError):
        CampaignDraftBase(
            draft_type=DraftType.MANUAL,
            email_subject="Hi\r\nBcc: x@y.com",
        )
    with pytest.raises(ValidationError):
        SpamCheckRequest(subject="Hi\nBcc: x@y.com", body="hello")
