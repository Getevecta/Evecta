"""Fail-closed environment detection for production-like vs explicit local/dev."""
from __future__ import annotations

import pytest

from app.core.config import (
    LOCAL_PUBLIC_BASE_URL,
    PRODUCTION_PUBLIC_BASE_URL,
    STAGING_PUBLIC_BASE_URL,
    environment_allows_dev_only_routes,
    environment_cookie_secure,
    environment_is_live_production,
    environment_is_production,
    environment_is_staging,
    environment_public_base_url,
    normalize_environment,
    resolve_environment_name,
)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("production", True),
        ("Production", True),
        ("PRODUCTION", True),
        ("prod", True),
        ("staging", True),
        ("stage", True),
        ("development", False),
        ("local", False),
        ("dev", False),
        ("test", False),
        ("", False),
        (None, False),
    ],
)
def test_environment_is_production(name, expected):
    assert environment_is_production(name) is expected


@pytest.mark.parametrize(
    "name, expected",
    [
        ("development", True),
        ("local", True),
        ("dev", True),
        ("test", True),
        ("Development", True),
        ("", False),
        (None, False),
        ("production", False),
        ("Production", False),
        ("prod", False),
        ("staging", False),
        ("stage", False),
    ],
)
def test_environment_allows_dev_only_routes_fail_closed(name, expected):
    assert environment_allows_dev_only_routes(name) is expected


def test_normalize_environment_strips_and_lowercases():
    assert normalize_environment("  Prod  ") == "prod"
    assert normalize_environment(None) == ""


def test_resolve_environment_name_prefers_configured_over_process_env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("NODE_ENV", "production")
    assert resolve_environment_name("development") == "development"


def test_resolve_environment_name_falls_back_to_process_env(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("NODE_ENV", "Production")
    assert resolve_environment_name(None) == "production"
    monkeypatch.delenv("NODE_ENV", raising=False)
    assert resolve_environment_name(None) == ""
    assert not environment_allows_dev_only_routes(resolve_environment_name(None))
    assert not environment_is_production(resolve_environment_name(None))


@pytest.mark.parametrize(
    "name, expected",
    [
        ("production", True),
        ("prod", True),
        ("Production", True),
        ("staging", False),
        ("stage", False),
        ("development", False),
        ("", False),
        (None, False),
    ],
)
def test_environment_is_live_production(name, expected):
    assert environment_is_live_production(name) is expected


@pytest.mark.parametrize(
    "name, expected",
    [
        ("staging", True),
        ("stage", True),
        ("Staging", True),
        ("production", False),
        ("prod", False),
        ("development", False),
        ("", False),
        (None, False),
    ],
)
def test_environment_is_staging(name, expected):
    assert environment_is_staging(name) is expected


@pytest.mark.parametrize(
    "name, https, expected",
    [
        ("production", False, True),
        ("prod", False, True),
        ("staging", False, True),
        ("stage", False, True),
        ("", False, True),
        (None, False, True),
        ("producton", False, True),
        ("development", False, False),
        ("local", False, False),
        ("dev", True, True),
        ("test", False, False),
        ("Development", False, False),
    ],
)
def test_environment_cookie_secure_fail_closed(name, https, expected):
    assert environment_cookie_secure(name, https) is expected


@pytest.mark.parametrize(
    "name, hostname, expected",
    [
        ("production", "", PRODUCTION_PUBLIC_BASE_URL),
        ("prod", "", PRODUCTION_PUBLIC_BASE_URL),
        ("staging", "", STAGING_PUBLIC_BASE_URL),
        ("stage", "", STAGING_PUBLIC_BASE_URL),
        ("development", "", LOCAL_PUBLIC_BASE_URL),
        ("local", "", LOCAL_PUBLIC_BASE_URL),
        ("", "", PRODUCTION_PUBLIC_BASE_URL),
        (None, "", PRODUCTION_PUBLIC_BASE_URL),
        ("", "api.evecta.io", PRODUCTION_PUBLIC_BASE_URL),
        ("", "staging.evecta.io", STAGING_PUBLIC_BASE_URL),
        ("development", "api.evecta.io", LOCAL_PUBLIC_BASE_URL),
    ],
)
def test_environment_public_base_url(name, hostname, expected):
    assert environment_public_base_url(name, hostname=hostname) == expected
