"""SNS host, certificate URL, and TopicArn allowlist checks."""
from app.utils.sns_trust import (
    _is_trusted_sns_cert_url,
    _is_trusted_sns_host,
    parse_allowed_sns_topic_arns,
    sns_topic_is_permitted,
)

_VALID_CERT = (
    "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-"
    "bb750dd426ca79cb9e65ce6a4ba83a3c.pem"
)
_VALID_SUBSCRIBE = (
    "https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription&Token=abc"
)
_ALLOWED = "arn:aws:sns:us-east-1:123456789012:evecta-ses"


def test_trusted_sns_host_accepts_regional_sns():
    assert _is_trusted_sns_host(_VALID_SUBSCRIBE)
    assert _is_trusted_sns_host("https://sns.eu-west-1.amazonaws.com/confirm")
    assert _is_trusted_sns_host("https://sns.cn-north-1.amazonaws.com.cn/confirm")
    assert _is_trusted_sns_host("https://SNS.US-EAST-1.amazonaws.com/confirm")


def test_trusted_sns_host_rejects_s3_suffix_and_http():
    assert not _is_trusted_sns_host("https://evil.s3.amazonaws.com/cert.pem")
    assert not _is_trusted_sns_host("https://s3.amazonaws.com/bucket/cert.pem")
    assert not _is_trusted_sns_host("https://sns.us-east-1.amazonaws.com.attacker.com/x")
    assert not _is_trusted_sns_host("http://sns.us-east-1.amazonaws.com/x")
    assert not _is_trusted_sns_host("https://aws.amazon.com/sns")
    assert not _is_trusted_sns_host("")
    assert not _is_trusted_sns_host("https://not-sns.us-east-1.amazonaws.com/x")
    assert not _is_trusted_sns_host("https://sns.us-east-1.amazonaws.com.evil/x")


def test_trusted_sns_cert_url_requires_pem_filename():
    assert _is_trusted_sns_cert_url(_VALID_CERT)
    assert _is_trusted_sns_cert_url(_VALID_CERT + "?unused=1")
    assert not _is_trusted_sns_cert_url(_VALID_SUBSCRIBE)
    assert not _is_trusted_sns_cert_url(
        "https://sns.us-east-1.amazonaws.com/not-the-sns-cert.pem"
    )
    assert not _is_trusted_sns_cert_url(
        "https://evil.s3.amazonaws.com/SimpleNotificationService-"
        "bb750dd426ca79cb9e65ce6a4ba83a3c.pem"
    )
    assert not _is_trusted_sns_cert_url(
        "https://sns.us-east-1.amazonaws.com/foo/SimpleNotificationService-"
        "bb750dd426ca79cb9e65ce6a4ba83a3c.pem"
    )
    assert not _is_trusted_sns_cert_url(
        "http://sns.us-east-1.amazonaws.com/SimpleNotificationService-"
        "bb750dd426ca79cb9e65ce6a4ba83a3c.pem"
    )
    assert not _is_trusted_sns_cert_url(
        "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-"
        "short.pem"
    )


def test_topic_allowlist_fail_closed_when_empty():
    assert parse_allowed_sns_topic_arns("") == []
    assert parse_allowed_sns_topic_arns("  ,  ") == []
    assert parse_allowed_sns_topic_arns(None) == []
    assert sns_topic_is_permitted(_ALLOWED, "") is False
    assert sns_topic_is_permitted(_ALLOWED, None) is False


def test_topic_allowlist_requires_exact_arn():
    raw = f" {_ALLOWED} , arn:aws:sns:us-east-1:123456789012:other "
    assert sns_topic_is_permitted(_ALLOWED, raw) is True
    assert sns_topic_is_permitted("arn:aws:sns:us-east-1:123456789012:other", raw) is True
    assert sns_topic_is_permitted("arn:aws:sns:us-east-1:999:attacker", raw) is False
    assert sns_topic_is_permitted(_ALLOWED + "-suffix", raw) is False
    assert sns_topic_is_permitted("", raw) is False
    assert sns_topic_is_permitted(None, raw) is False
