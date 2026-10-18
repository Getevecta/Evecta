"""Unit tests for DSN bounce detection (user-connected mailboxes)."""

from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.utils.bounce_detector import (
    extract_bounce_ids,
    extract_final_recipient,
    is_bounce_headers,
    is_bounce_message,
)


def test_is_bounce_mailer_daemon():
    msg = EmailMessage()
    msg["From"] = "Mail Delivery Subsystem <mailer-daemon@googlemail.com>"
    msg["Content-Type"] = "text/plain"
    assert is_bounce_message(msg) is True


def test_is_bounce_multipart_report():
    msg = EmailMessage()
    msg["From"] = "someone@example.com"
    msg["Content-Type"] = 'multipart/report; report-type=delivery-status; boundary="b"'
    assert is_bounce_message(msg) is True
    assert is_bounce_headers(msg["From"], msg["Content-Type"]) is True


def test_not_bounce_normal_reply():
    msg = EmailMessage()
    msg["From"] = "lead@example.com"
    msg["Content-Type"] = "text/plain"
    assert is_bounce_message(msg) is False


def test_extract_bounce_ids_from_rfc822_headers():
    campaign = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    lead = "11111111-2222-3333-4444-555555555555"
    mid = f"<EV-99999999-9999-9999-9999-999999999999-{campaign}-{lead}@evecta>"

    msg = MIMEMultipart("report", report_type="delivery-status")
    msg["From"] = "Mailer-Daemon <mailer-daemon@mx.example.com>"
    msg["Subject"] = "Undelivered Mail Returned to Sender"

    headers_part = MIMEText(
        f"Return-Path: <>\nMessage-ID: {mid}\nTo: bounce@example.com\n",
        "rfc822-headers",
    )
    headers_part.set_type("text/rfc822-headers")
    msg.attach(headers_part)

    ds = MIMEText(
        "Final-Recipient: rfc822; bounce@example.com\nAction: failed\nStatus: 5.1.1\n",
        "plain",
    )
    ds.set_type("message/delivery-status")
    msg.attach(ds)

    assert is_bounce_message(msg) is True
    ids = extract_bounce_ids(msg)
    assert ids == (campaign, lead)
    assert extract_final_recipient(msg) == "bounce@example.com"
