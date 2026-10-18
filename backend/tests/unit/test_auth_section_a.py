"""Section A: Google email_verified, OTP HMAC, lockout keys, password max length."""
from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.auth import LoginRequest, ResetPasswordRequest
from app.schemas.user import PasswordChange, UserCreate
from app.services.auth_service import _login_attempts_key, _login_lockout_key
from app.services.google_auth_service import google_verified_email
from app.services.otp_service import hash_otp_code, otp_code_matches


def test_google_email_requires_verified_true():
    with pytest.raises(HTTPException) as exc:
        google_verified_email({"email": "user@example.com", "email_verified": False})
    assert exc.value.status_code == 400


def test_google_email_normalizes_case():
    assert (
        google_verified_email({"email": "  User@Example.COM ", "email_verified": True})
        == "user@example.com"
    )


def test_google_email_missing_raises():
    with pytest.raises(HTTPException):
        google_verified_email({"email_verified": True})


def test_otp_hmac_is_not_bare_sha256():
    code = "123456"
    hashed = hash_otp_code(code)
    assert hashed != hashlib.sha256(code.encode()).hexdigest()
    assert otp_code_matches(hashed, code)
    assert not otp_code_matches(hashed, "000000")


def test_otp_rejects_legacy_unsalted_sha256():
    code = "654321"
    legacy = hashlib.sha256(code.encode()).hexdigest()
    assert not otp_code_matches(legacy, code)


def test_login_lockout_is_per_email_and_ip():
    key_a = _login_lockout_key("a@x.com", "1.1.1.1")
    key_b = _login_lockout_key("a@x.com", "2.2.2.2")
    assert key_a != key_b
    assert "1.1.1.1" in key_a
    assert _login_attempts_key("a@x.com", "1.1.1.1") != _login_attempts_key("a@x.com", "2.2.2.2")


def test_password_fields_reject_over_128_chars():
    long_pw = "a" * 129
    with pytest.raises(ValidationError):
        UserCreate(email="a@b.com", username="u", password=long_pw)
    with pytest.raises(ValidationError):
        PasswordChange(current_password="oldpass1", new_password=long_pw)
    with pytest.raises(ValidationError):
        ResetPasswordRequest(email="a@b.com", otp_code="123456", new_password=long_pw)
    with pytest.raises(ValidationError):
        LoginRequest(email="a@b.com", password=long_pw)
