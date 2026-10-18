"""Tests for the open/click classifier and the EmailActivity event state machine."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.email_activity import EmailActivity, EmailStatus
from app.services.email_event_service import apply_email_event
from app.utils.open_classifier import OpenClassification, classify_open


NOW = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)
HUMAN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class TestClassifyOpen:
    def test_normal_browser_ua_is_human(self):
        assert classify_open(HUMAN_UA) == OpenClassification.HUMAN

    def test_empty_or_missing_ua_is_bot(self):
        assert classify_open("") == OpenClassification.BOT
        assert classify_open(None) == OpenClassification.BOT
        assert classify_open("   ") == OpenClassification.BOT

    @pytest.mark.parametrize(
        "ua",
        [
            "Barracuda Sentinel (EE)",
            "Mozilla/5.0 (compatible; proofpoint)",
            "Mozilla/5.0 (compatible; Googlebot/2.1)",
            "python-requests/2.31.0",
            "curl/8.4.0",
            "Microsoft Office Existence Discovery scanner",
        ],
    )
    def test_scanner_uas_are_bot(self, ua):
        assert classify_open(ua) == OpenClassification.BOT

    def test_gmail_image_proxy_is_human(self):
        # Gmail always loads pixels via GoogleImageProxy when the message is shown.
        # Timing guard still drops instant prefetch (<15s after delivery).
        ua = (
            "Mozilla/5.0 (Windows NT 5.1; rv:11.0) Gecko Firefox/11.0 "
            "(via ggpht.com GoogleImageProxy)"
        )
        assert classify_open(ua) == OpenClassification.HUMAN
        delivered = NOW
        assert (
            classify_open(
                ua,
                occurred_at=delivered + timedelta(seconds=3),
                delivered_at=delivered,
            )
            == OpenClassification.BOT
        )
        assert (
            classify_open(
                ua,
                occurred_at=delivered + timedelta(minutes=5),
                delivered_at=delivered,
            )
            == OpenClassification.HUMAN
        )

    def test_apple_mpp_proxy_ua(self):
        # Apple MPP fetches with a truncated WebKit UA (no Version/Safari suffix)
        mpp_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"
        assert classify_open(mpp_ua) == OpenClassification.APPLE_MPP
        assert classify_open("Mozilla/5.0") == OpenClassification.APPLE_MPP

    def test_real_safari_ua_is_human(self):
        safari = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
        )
        assert classify_open(safari) == OpenClassification.HUMAN

    def test_open_seconds_after_delivery_is_bot(self):
        delivered = NOW
        opened = NOW + timedelta(seconds=3)
        assert (
            classify_open(HUMAN_UA, occurred_at=opened, delivered_at=delivered)
            == OpenClassification.BOT
        )

    def test_open_minutes_after_delivery_is_human(self):
        delivered = NOW
        opened = NOW + timedelta(minutes=10)
        assert (
            classify_open(HUMAN_UA, occurred_at=opened, delivered_at=delivered)
            == OpenClassification.HUMAN
        )

    def test_timing_rule_skipped_when_timestamps_missing(self):
        assert classify_open(HUMAN_UA, occurred_at=NOW) == OpenClassification.HUMAN
        assert classify_open(HUMAN_UA, delivered_at=NOW) == OpenClassification.HUMAN


def _activity(**overrides) -> EmailActivity:
    activity = EmailActivity(
        email="lead@example.com",
        status=EmailStatus.SENT,
        opened=False,
        clicked=False,
        bounced=False,
        delivered=False,
        open_count=0,
        sent_at=NOW - timedelta(hours=1),
    )
    for key, value in overrides.items():
        setattr(activity, key, value)
    return activity


class TestApplyEmailEvent:
    def test_delivery_sets_flag_and_timestamp_once(self):
        a = _activity()
        apply_email_event(a, "delivery", occurred_at=NOW)
        assert a.delivered is True
        assert a.delivered_at == NOW
        assert a.status == EmailStatus.SENT

        later = NOW + timedelta(hours=2)
        apply_email_event(a, "delivery", occurred_at=later)
        assert a.delivered_at == NOW  # write-once

    def test_open_sets_all_open_fields(self):
        a = _activity()
        apply_email_event(a, "open", occurred_at=NOW)
        assert a.opened is True
        assert a.delivered is True
        assert a.first_opened_at == NOW
        assert a.open_count == 1
        assert a.status == EmailStatus.OPENED

    def test_repeat_opens_increment_count_keep_first_ts(self):
        a = _activity()
        apply_email_event(a, "open", occurred_at=NOW)
        apply_email_event(a, "open", occurred_at=NOW + timedelta(hours=1))
        assert a.open_count == 2
        assert a.first_opened_at == NOW

    def test_click_implies_open_and_outranks_it(self):
        a = _activity()
        apply_email_event(a, "click", occurred_at=NOW)
        assert a.clicked is True
        assert a.opened is True
        assert a.status == EmailStatus.CLICKED

    def test_bounce_is_terminal_for_status(self):
        a = _activity()
        apply_email_event(a, "bounce")
        assert a.status == EmailStatus.BOUNCED
        # A later scanner click must NOT resurrect the row (old bug)
        apply_email_event(a, "click", occurred_at=NOW)
        assert a.clicked is True
        assert a.status == EmailStatus.BOUNCED

    def test_complaint_marks_failed_and_stays_failed(self):
        a = _activity()
        apply_email_event(a, "complaint")
        assert a.status == EmailStatus.FAILED
        apply_email_event(a, "open", occurred_at=NOW)
        assert a.opened is True
        assert a.status == EmailStatus.FAILED  # terminal

    def test_unknown_event_raises(self):
        with pytest.raises(ValueError):
            apply_email_event(_activity(), "close")
