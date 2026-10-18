"""SES/SNS webhook: signature alerts, topic allowlist, replay idempotency."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.webhook_ses import (
    claim_processed_webhook_event,
    handle_ses_webhook,
    verify_sns_signature,
)
from app.utils.security_alert import (
    SNS_SIGNATURE_FAILURE_MARKER,
    record_sns_signature_failure_sync,
)

_ALLOWED = "arn:aws:sns:us-east-1:123456789012:evecta-ses"
_VALID_CERT = (
    "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-"
    "bb750dd426ca79cb9e65ce6a4ba83a3c.pem"
)


def _notification(topic=_ALLOWED, message_id="sns-msg-1", ses_id="ses-1"):
    return {
        "Type": "Notification",
        "MessageId": message_id,
        "TopicArn": topic,
        "SigningCertURL": _VALID_CERT,
        "Signature": "c2ln",
        "Message": json.dumps(
            {"eventType": "Delivery", "mail": {"messageId": ses_id, "headers": []}}
        ),
    }


def test_missing_signature_fields_alert_and_403():
    alerts = []

    async def fake_alert(**kwargs):
        alerts.append(kwargs)

    async def run():
        with patch("app.api.v1.webhook_ses.record_sns_signature_failure", fake_alert):
            with pytest.raises(HTTPException) as exc:
                await verify_sns_signature({"Type": "Notification"})
        assert exc.value.status_code == 403
        assert exc.value.detail == "Missing SNS signature fields"

    asyncio.run(run())
    assert alerts == [{"reason": "missing_fields"}]


def test_untrusted_cert_url_alerts_and_does_not_fetch():
    alerts = []

    async def fake_alert(**kwargs):
        alerts.append(kwargs)

    async def run():
        with (
            patch("app.api.v1.webhook_ses.record_sns_signature_failure", fake_alert),
            patch("httpx.AsyncClient") as client_cls,
        ):
            with pytest.raises(HTTPException) as exc:
                await verify_sns_signature(
                    {
                        "SigningCertURL": "https://evil.s3.amazonaws.com/cert.pem",
                        "Signature": "c2ln",
                    }
                )
        assert exc.value.status_code == 403
        assert exc.value.detail == "Untrusted SNS certificate source"
        client_cls.assert_not_called()

    asyncio.run(run())
    assert alerts[0]["reason"] == "untrusted_cert_url"
    assert "evil.s3.amazonaws.com" in alerts[0]["detail"]


def test_signature_crypto_failure_alerts():
    alerts = []

    async def fake_alert(**kwargs):
        alerts.append(kwargs)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=SimpleNamespace(content=b"not-a-cert"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    async def run():
        with (
            patch("app.api.v1.webhook_ses.record_sns_signature_failure", fake_alert),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            with pytest.raises(HTTPException) as exc:
                await verify_sns_signature(
                    {"SigningCertURL": _VALID_CERT, "Signature": "c2ln"}
                )
        assert exc.value.status_code == 403
        assert exc.value.detail == "SNS signature verification failed"

    asyncio.run(run())
    assert alerts == [{"reason": "verify_failed"}]


def test_signature_failure_logs_critical_marker(caplog):
    import logging

    with caplog.at_level(logging.CRITICAL, logger="app.utils.security_alert"):
        with patch("app.utils.redis_context.REDIS_AVAILABLE", False):
            record_sns_signature_failure_sync(reason="untrusted_cert_url", detail="x")
    assert SNS_SIGNATURE_FAILURE_MARKER in caplog.text
    assert "untrusted_cert_url" in caplog.text


def test_empty_topic_allowlist_rejects_webhook():
    request = MagicMock()
    request.body = AsyncMock(return_value=json.dumps(_notification()).encode())

    async def run():
        with (
            patch("app.api.v1.webhook_ses.verify_sns_signature", AsyncMock()),
            patch(
                "app.core.config.get_settings",
                return_value=SimpleNamespace(SNS_ALLOWED_TOPIC_ARNS=""),
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await handle_ses_webhook(request, db=AsyncMock())
        assert exc.value.status_code == 403
        assert exc.value.detail == "SNS webhook not configured"

    asyncio.run(run())


def test_unknown_topic_arn_rejected():
    request = MagicMock()
    request.body = AsyncMock(
        return_value=json.dumps(
            _notification(topic="arn:aws:sns:us-east-1:999:attacker")
        ).encode()
    )

    async def run():
        with (
            patch("app.api.v1.webhook_ses.verify_sns_signature", AsyncMock()),
            patch(
                "app.core.config.get_settings",
                return_value=SimpleNamespace(SNS_ALLOWED_TOPIC_ARNS=_ALLOWED),
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await handle_ses_webhook(request, db=AsyncMock())
        assert exc.value.status_code == 403
        assert exc.value.detail == "Untrusted SNS topic"

    asyncio.run(run())


def test_claim_webhook_event_treats_rowcount_zero_as_replay():
    db = AsyncMock()
    first = MagicMock(rowcount=1)
    replay = MagicMock(rowcount=0)
    db.execute = AsyncMock(side_effect=[first, replay])
    db.commit = AsyncMock()

    async def run():
        assert await claim_processed_webhook_event(db, "sns-msg-1", "ses:Delivery") is True
        assert await claim_processed_webhook_event(db, "sns-msg-1", "ses:Delivery") is False

    asyncio.run(run())
    assert db.execute.call_count == 2
    assert db.commit.call_count == 2


def test_replayed_sns_notification_returns_duplicate():
    request = MagicMock()
    request.body = AsyncMock(return_value=json.dumps(_notification()).encode())
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    db.commit = AsyncMock()

    async def run():
        with (
            patch("app.api.v1.webhook_ses.verify_sns_signature", AsyncMock()),
            patch(
                "app.core.config.get_settings",
                return_value=SimpleNamespace(SNS_ALLOWED_TOPIC_ARNS=_ALLOWED),
            ),
        ):
            result = await handle_ses_webhook(request, db=db)
        assert result == {"status": "duplicate_sns_event"}

    asyncio.run(run())
    db.execute.assert_called()
