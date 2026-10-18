"""Section C: mailbox SSRF, OAuth state, token encryption, smtp_port mapping."""
from __future__ import annotations

import asyncio
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.mailbox import MailboxProvider
from app.schemas.mailbox import MailboxUpdate
from app.schemas.system_mailbox import SystemMailboxRead
from app.services.google_gmail_token_service import (
    google_access_token_plain,
    store_google_access_token,
)
from app.services.mailbox_oauth_state import (
    consume_mailbox_oauth_state,
    store_mailbox_oauth_state,
)
from app.services.mailbox_service import (
    apply_mailbox_update_fields,
    update_mailbox,
)
from app.utils.crypto import decrypt_secret_compat, encrypt_secret
from app.utils.outbound_host import assert_safe_outbound_port, resolve_public_ip


def test_rejects_loopback_and_private_literal_hosts():
    for host in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254", "localhost"):
        with pytest.raises(HTTPException) as exc:
            resolve_public_ip(host)
        assert exc.value.status_code == 400


def test_rejects_hostname_that_resolves_to_loopback(monkeypatch):
    monkeypatch.setattr(
        "app.utils.outbound_host.socket.getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ],
    )
    with pytest.raises(HTTPException) as exc:
        resolve_public_ip("smtp.example.com")
    assert exc.value.status_code == 400


def test_rejects_cgnat_and_unspecified():
    for host in ("100.64.0.1", "0.0.0.0"):
        with pytest.raises(HTTPException):
            resolve_public_ip(host)


def test_smtp_and_imap_ports_are_restricted():
    assert_safe_outbound_port(587, "smtp")
    assert_safe_outbound_port(993, "imap")
    with pytest.raises(HTTPException):
        assert_safe_outbound_port(8080, "smtp")
    with pytest.raises(HTTPException):
        assert_safe_outbound_port(1433, "imap")


def test_mailbox_update_schema_bounds_ports():
    with pytest.raises(ValidationError):
        MailboxUpdate(smtp_port=0)
    with pytest.raises(ValidationError):
        MailboxUpdate(smtp_port=70000)
    MailboxUpdate(smtp_port=465)


def test_smtp_port_maps_to_orm_port_column():
    mailbox = SimpleNamespace(
        smtp_host="smtp.example.com",
        port=587,
        imap_host="imap.example.com",
        imap_port=993,
        smtp_pass="old",
        is_active=True,
    )
    apply_mailbox_update_fields(mailbox, {"smtp_port": 465})
    assert mailbox.port == 465
    assert not hasattr(mailbox, "smtp_port")


def test_update_revalidates_and_persists_smtp_port(monkeypatch):
    user_id = "user-1"
    mailbox = SimpleNamespace(
        user_id=user_id,
        provider=MailboxProvider.ANY_PROVIDER,
        smtp_host="smtp.example.com",
        port=587,
        smtp_user="user",
        smtp_pass=encrypt_secret("old-pass"),
        imap_host="imap.example.com",
        imap_port=993,
        receive_username=None,
        receive_password=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=mailbox)

    smtp_calls = {}

    async def fake_smtp(**kwargs):
        smtp_calls.update(kwargs)

    async def fake_imap(**kwargs):
        raise AssertionError("IMAP should not be revalidated for SMTP-only updates")

    monkeypatch.setattr("app.services.mailbox_service.validate_smtp_credentials", fake_smtp)
    monkeypatch.setattr("app.services.mailbox_service.validate_imap_credentials", fake_imap)

    async def _run():
        return await update_mailbox("mid", MailboxUpdate(smtp_port=465), user_id, db)

    result = asyncio.run(_run())
    assert result.port == 465
    assert smtp_calls["port"] == 465
    assert smtp_calls["host"] == "smtp.example.com"
    db.commit.assert_awaited()
    db.refresh.assert_awaited()


def test_google_mailbox_update_ignores_host_changes():
    mailbox = SimpleNamespace(
        user_id="u",
        provider=MailboxProvider.GOOGLE,
        smtp_host="google",
        port=0,
        is_active=True,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=mailbox)

    async def _run():
        await update_mailbox("mid", MailboxUpdate(smtp_port=587, is_active=False), "u", db)

    asyncio.run(_run())
    assert mailbox.port == 0
    assert mailbox.is_active is False


def test_google_access_token_encrypted_at_rest():
    mailbox = SimpleNamespace(google_access_token=None)
    plaintext = "ya29.example-access-token"
    store_google_access_token(mailbox, plaintext)
    assert mailbox.google_access_token != plaintext
    assert google_access_token_plain(mailbox) == plaintext
    assert decrypt_secret_compat(plaintext) == plaintext


def test_system_mailbox_read_omits_receive_password():
    assert "receive_password" not in SystemMailboxRead.model_fields


def test_oauth_state_is_server_side_and_one_time(monkeypatch):
    store: dict[str, str] = {}

    class FakeRedis:
        async def set(self, key, value, ex=None):
            store[key] = value

        async def getdel(self, key):
            return store.pop(key, None)

    monkeypatch.setattr("app.core.redis.get_redis", lambda: FakeRedis())

    async def _run():
        await store_mailbox_oauth_state(
            state="csrf-token",
            user_id="user-abc",
            campaign_id="camp-1",
        )
        first = await consume_mailbox_oauth_state("csrf-token")
        assert first["user_id"] == "user-abc"
        assert first["campaign_id"] == "camp-1"
        assert await consume_mailbox_oauth_state("csrf-token") is None

    asyncio.run(_run())
