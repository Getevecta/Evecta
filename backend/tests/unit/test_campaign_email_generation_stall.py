"""Stuck "0/N Queued" email generation: a campaign whose leads have no
campaign_lead_emails rows.

The worker skips leads without a row, so:
- GET /status must not keep auto-dispatching Celery chunks for such leads, nor for a
  campaign whose draft is not saved (POST /generate rejects it with 400);
- POST /resume must create the missing rows so a stuck campaign can recover;
- a crash after a row is claimed must be logged and mark the row FAILED, not leave it
  GENERATING to be re-queued and crash again forever.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.campaign import CampaignStatus
from app.models.campaign_lead_email import GenerationStatus
from app.services import campaign_email_generation_service as svc

STALLED_SUMMARY = {
    "total": 1, "complete": 0, "queued": 1, "generating": 0, "pending": 1,
    "ready": 0, "failed": 0, "compliance_passed": 0, "compliance_failed": 0,
    "is_complete": False,
}


def _campaign(**overrides):
    values = dict(id=uuid.uuid4(), user_id=uuid.uuid4(), status=CampaignStatus.DRAFT,
                  email_subject="Hello", email_content="Body")
    values.update(overrides)
    return SimpleNamespace(**values)


def _lead():
    return SimpleNamespace(id=uuid.uuid4(), lead_id=uuid.uuid4())


def _status_db(campaign_leads, email_rows):
    """db whose scalars() returns the campaign leads and execute() the (lead_id, status) rows."""
    db = MagicMock()
    db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=campaign_leads)))
    db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=email_rows)))
    return db


def _run_status(campaign, db):
    schedule = MagicMock(return_value="celery")
    svc._campaign_email_last_dispatch.pop(str(campaign.id), None)
    with patch.object(svc, "get_owned_campaign_or_404", AsyncMock(return_value=campaign)), \
            patch.object(svc, "_requeue_stale_generating_rows", AsyncMock(return_value=0)), \
            patch.object(svc, "count_campaign_leads", AsyncMock(return_value=1)), \
            patch.object(svc, "fetch_generation_status_summary", AsyncMock(return_value=dict(STALLED_SUMMARY))), \
            patch.object(svc, "_schedule_remaining_campaign_email_generation", schedule):
        result = asyncio.run(svc.get_campaign_email_generation_status(str(campaign.id), str(campaign.user_id), db))
    return result, schedule


# ── GET /status auto-resume ───────────────────────────────────────────────────

def test_status_does_not_dispatch_when_draft_is_not_saved():
    campaign = _campaign(email_content=None)
    lead = _lead()
    result, schedule = _run_status(campaign, _status_db([lead], [(lead.lead_id, GenerationStatus.PENDING)]))
    assert result["generation_stalled"] is True  # still reported to the UI
    schedule.assert_not_called()


def test_status_does_not_dispatch_when_campaign_left_draft():
    campaign = _campaign(status=CampaignStatus.ONGOING)
    lead = _lead()
    _, schedule = _run_status(campaign, _status_db([lead], [(lead.lead_id, GenerationStatus.PENDING)]))
    schedule.assert_not_called()


def test_status_does_not_dispatch_for_leads_without_rows():
    campaign = _campaign()
    _, schedule = _run_status(campaign, _status_db([_lead()], []))
    schedule.assert_not_called()


def test_status_dispatches_existing_pending_rows():
    campaign = _campaign()
    leads = [_lead(), _lead()]
    rows = [(leads[1].lead_id, GenerationStatus.PENDING), (leads[0].lead_id, GenerationStatus.READY)]
    _, schedule = _run_status(campaign, _status_db(leads, rows))
    schedule.assert_called_once()
    assert schedule.call_args.kwargs["chunk_ranges"] == [(1, svc.GENERATION_CHUNK_SIZE)]
    assert schedule.call_args.kwargs["regenerate_all"] is False


# ── POST /resume creates missing rows ─────────────────────────────────────────

def _run_resume(campaign, leads, rows_by_lead_id):
    upsert = AsyncMock(return_value=rows_by_lead_id)
    schedule = MagicMock(return_value="celery")
    with patch.object(svc, "_should_stop_generation", AsyncMock(return_value=False)), \
            patch.object(svc, "_get_campaign_or_404", AsyncMock(return_value=campaign)), \
            patch.object(svc, "_requeue_stale_generating_rows", AsyncMock(return_value=0)), \
            patch.object(svc, "_fetch_campaign_leads", AsyncMock(return_value=leads)), \
            patch.object(svc, "_upsert_campaign_email_rows", upsert), \
            patch.object(svc, "_generation_already_running", AsyncMock(return_value=False)), \
            patch.object(svc, "_campaign_uses_ai_per_lead_generation", MagicMock(return_value=False)), \
            patch.object(svc, "_schedule_remaining_campaign_email_generation", schedule):
        result = asyncio.run(svc.resume_campaign_email_generation(str(campaign.id), str(campaign.user_id), MagicMock()))
    return result, upsert, schedule


def test_resume_creates_missing_rows_then_dispatches():
    campaign, lead = _campaign(), _lead()
    created = SimpleNamespace(generation_status=GenerationStatus.PENDING,
                              compliance_status=SimpleNamespace(value="pending"))
    result, upsert, schedule = _run_resume(campaign, [lead], {str(lead.lead_id): created})
    upsert.assert_awaited_once()
    assert upsert.call_args.kwargs == {"regenerate_all": False}  # never resets existing rows
    assert result["resumed"] is True
    assert schedule.call_args.kwargs["chunk_ranges"] == [(0, svc.GENERATION_CHUNK_SIZE)]


def test_resume_does_not_dispatch_completed_campaign():
    campaign, lead = _campaign(), _lead()
    ready = SimpleNamespace(generation_status=GenerationStatus.READY,
                            compliance_status=SimpleNamespace(value="passed"))
    result, _, schedule = _run_resume(campaign, [lead], {str(lead.lead_id): ready})
    assert result["resumed"] is False
    schedule.assert_not_called()


def test_upsert_adds_pending_row_for_missing_lead_and_keeps_ready_rows():
    campaign = _campaign()
    have, missing = _lead(), _lead()
    ready_row = SimpleNamespace(lead_id=have.lead_id, lead_index=0,
                                generation_status=GenerationStatus.READY)
    db = MagicMock()
    db.scalars = AsyncMock(return_value=[ready_row])
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    added = []
    db.add = added.append

    rows = asyncio.run(svc._upsert_campaign_email_rows(campaign, [have, missing], db, regenerate_all=False))

    assert rows[str(have.lead_id)] is ready_row
    assert ready_row.generation_status == GenerationStatus.READY
    assert len(added) == 1
    new = added[0]
    assert new.lead_id == missing.lead_id and new.campaign_lead_id == missing.id
    assert new.generation_status == GenerationStatus.PENDING and new.lead_index == 1
    db.commit.assert_awaited_once()


# ── Worker: a crash after claiming a row ──────────────────────────────────────

def _run_chunk(generate_side_effect):
    """Run _process_chunk_leads for one lead whose generation raises."""
    campaign = _campaign()
    lead = SimpleNamespace(id=uuid.uuid4(), lead_id=uuid.uuid4(), lead=None)
    row = SimpleNamespace(id=uuid.uuid4(), lead_id=lead.lead_id, generation_status=GenerationStatus.PENDING)

    db = MagicMock()
    db.get = AsyncMock(return_value=campaign)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.scalars = AsyncMock(side_effect=[
        MagicMock(all=MagicMock(return_value=[row])),  # email rows
        MagicMock(all=MagicMock(return_value=[])),     # READY rows for prior bodies
    ])
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=lead)))

    @asynccontextmanager
    async def session_factory():
        yield db

    mark_failed = AsyncMock()
    with patch.object(svc, "_fetch_campaign_leads", AsyncMock(return_value=[lead])), \
            patch.object(svc, "_should_stop_generation", AsyncMock(return_value=False)), \
            patch.object(svc, "_fetch_email_row_for_lead", AsyncMock(return_value=row)), \
            patch.object(svc, "_row_was_cancelled", AsyncMock(return_value=False)), \
            patch.object(svc, "_claim_email_row_for_generation", AsyncMock(return_value=row)), \
            patch.object(svc, "_load_profiles", AsyncMock(return_value=(None, None, None))), \
            patch.object(svc, "generate_lead_email_row", AsyncMock(side_effect=generate_side_effect)), \
            patch.object(svc, "_mark_claimed_row_failed", mark_failed):
        asyncio.run(svc._process_chunk_leads(
            campaign_id=str(campaign.id), user_id=str(campaign.user_id), start_index=0, count=25,
            regenerate_all=False, session_factory=session_factory,
        ))
    return row, mark_failed


def test_crash_after_claim_marks_row_failed_and_logs_traceback(caplog):
    with caplog.at_level(logging.ERROR, logger=svc.logger.name):
        row, mark_failed = _run_chunk(RuntimeError("boom"))
    mark_failed.assert_awaited_once()
    assert mark_failed.call_args.args[1] == row.id
    assert isinstance(mark_failed.call_args.args[2], RuntimeError)
    crash = [r for r in caplog.records if "Email generation crashed" in r.getMessage()]
    assert crash and crash[0].exc_info and "boom" in crash[0].getMessage()


def test_out_of_credits_keeps_row_for_resume_instead_of_failing():
    _, mark_failed = _run_chunk(HTTPException(status_code=402, detail="insufficient credits"))
    mark_failed.assert_not_awaited()


def test_mark_claimed_row_failed_sets_failed_with_error_type():
    fresh = MagicMock()
    fresh.execute = AsyncMock()
    fresh.commit = AsyncMock()

    @asynccontextmanager
    async def session_factory():
        yield fresh

    asyncio.run(svc._mark_claimed_row_failed(session_factory, uuid.uuid4(), ValueError("x")))
    stmt = fresh.execute.call_args.args[0]
    params = stmt.compile().params
    assert params["generation_status"] == GenerationStatus.FAILED
    assert params["last_error"] == "generation_error: ValueError"
    # WHERE generation_status = GENERATING: a row another worker already finished is left alone.
    assert params["generation_status_1"] == GenerationStatus.GENERATING
    fresh.commit.assert_awaited_once()


def test_mark_claimed_row_failed_never_raises(caplog):
    @asynccontextmanager
    async def broken_factory():
        raise ConnectionError("db down")
        yield  # pragma: no cover

    with caplog.at_level(logging.ERROR, logger=svc.logger.name):
        asyncio.run(svc._mark_claimed_row_failed(broken_factory, uuid.uuid4(), RuntimeError("x")))
    assert any("Could not mark crashed email row" in r.getMessage() for r in caplog.records)
