import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.core.http_client import mailbox_cycle_client
from app.models.mailbox import MailboxProvider
from app.models.campaign import Campaign
from app.models.email_activity import EmailActivity
from app.services.gmail_reply_fetch_service import fetch_gmail_replies
from app.services.thread_reply_service import _send_gmail_reply, send_thread_reply


def test_mailbox_cycle_client_is_reused():
    first = mailbox_cycle_client()
    second = mailbox_cycle_client()
    assert first is second


def test_gmail_reply_fetch_accepts_injected_cycle_client():
    sig = inspect.signature(fetch_gmail_replies)
    assert "client" in sig.parameters


def test_gmail_thread_send_does_not_take_a_db_session():
    assert "db" not in inspect.signature(_send_gmail_reply).parameters
    assert "access_token" in inspect.signature(_send_gmail_reply).parameters


def test_reply_activity_ownership_is_a_single_join():
    from sqlalchemy import select

    stmt = (
        select(EmailActivity, Campaign)
        .join(Campaign, EmailActivity.campaign_id == Campaign.id)
        .where(
            EmailActivity.id == uuid4(),
            Campaign.user_id == uuid4(),
        )
    )
    compiled = str(stmt.compile())
    assert "JOIN" in compiled.upper()
    assert "user_id" in compiled


def test_send_reply_and_thread_reply_use_joined_ownership():
    from app.services.reply_sender_service import send_reply_email

    reply_src = inspect.getsource(send_reply_email)
    assert "join(Campaign" in reply_src
    assert "Campaign.user_id == user_id" in reply_src
    assert "db.get(EmailActivity" not in reply_src

    thread_src = inspect.getsource(send_thread_reply)
    assert "join(Campaign" in thread_src
    assert "join(Lead" in thread_src
    assert "db.get(EmailThread" not in thread_src



def test_send_thread_reply_commits_before_network_send(monkeypatch):
    order: list[str] = []
    thread_id = uuid4()
    lead_id = uuid4()
    user_id = uuid4()
    campaign_id = uuid4()
    mailbox_id = uuid4()

    thread = SimpleNamespace(id=thread_id, user_id=user_id, campaign_id=campaign_id)
    lead = SimpleNamespace(id=lead_id, user_id=user_id, email="lead@example.com")
    campaign = SimpleNamespace(id=campaign_id, email_subject="Hello")
    inbound = SimpleNamespace(mailbox_id=mailbox_id, message_id="<in@evecta>")
    mailbox = SimpleNamespace(
        id=mailbox_id,
        email="from@example.com",
        provider=MailboxProvider.ANY_PROVIDER,
        is_active=True,
        smtp_host="smtp.example.com",
        port=587,
        smtp_user="from@example.com",
        smtp_pass="enc",
        receive_email=None,
    )

    class _InboundResult:
        def scalars(self):
            return self

        def first(self):
            return inbound

        def all(self):
            return ["<out@evecta>"]

    class _OwnedResult:
        def one_or_none(self):
            return (thread, campaign, lead)

    calls = {"n": 0}

    async def fake_execute(stmt):
        calls["n"] += 1
        if calls["n"] == 1:
            return _OwnedResult()
        return _InboundResult()

    async def fake_commit():
        order.append("commit")

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=fake_execute)
    db.commit = AsyncMock(side_effect=fake_commit)
    db.refresh = AsyncMock()
    db.add = MagicMock()

    monkeypatch.setattr(
        "app.services.thread_reply_service._get_reply_mailbox",
        AsyncMock(return_value=mailbox),
    )

    async def fake_smtp(**kwargs):
        order.append("smtp")

    monkeypatch.setattr(
        "app.services.thread_reply_service._send_smtp_reply",
        fake_smtp,
    )

    async def _run():
        return await send_thread_reply(
            thread_id=thread_id,
            lead_id=lead_id,
            user_id=user_id,
            body="Hi",
            db=db,
        )

    out = asyncio.run(_run())
    assert out.recipient_email == "lead@example.com"
    assert "smtp" in order
    assert order.index("commit") < order.index("smtp")
