"""Unit tests for automatic resume of stalled campaign email generation."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.core.celery_app import celery_app
from app.models.campaign_lead_email import GenerationStatus
from app.services.campaign_email_generation_service import (
    STALE_GENERATING_SECONDS,
    resume_stalled_campaign_email_generations,
    stalled_generation_campaign_ids,
)


def test_beat_schedule_resumes_stalled_campaign_emails():
    entry = celery_app.conf.beat_schedule["resume-stalled-campaign-emails-every-60s"]
    assert (
        entry["task"]
        == "app.tasks.resume_campaign_emails.resume_stalled_campaign_email_generations"
    )
    assert entry["schedule"] == 60.0
    assert (
        "app.tasks.resume_campaign_emails.resume_stalled_campaign_email_generations"
        in celery_app.tasks
    )


def test_stalled_ids_include_pending_with_no_live_generating():
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    ids = stalled_generation_campaign_ids(
        [
            ("camp-a", GenerationStatus.PENDING, now),
            ("camp-a", GenerationStatus.READY, now),
        ],
        now=now,
    )
    assert ids == ["camp-a"]


def test_stalled_ids_include_abandoned_generating_rows():
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    stale = now - timedelta(seconds=STALE_GENERATING_SECONDS + 1)
    ids = stalled_generation_campaign_ids(
        [
            ("camp-a", GenerationStatus.GENERATING, stale),
            ("camp-a", GenerationStatus.PENDING, now),
        ],
        now=now,
    )
    assert ids == ["camp-a"]


def test_stalled_ids_skip_campaigns_with_fresh_generating_heartbeat():
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    stale = now - timedelta(seconds=STALE_GENERATING_SECONDS + 30)
    ids = stalled_generation_campaign_ids(
        [
            ("camp-live", GenerationStatus.GENERATING, now - timedelta(seconds=10)),
            ("camp-live", GenerationStatus.PENDING, now),
            ("camp-dead", GenerationStatus.GENERATING, stale),
        ],
        now=now,
    )
    assert ids == ["camp-dead"]


def test_stalled_ids_ignore_ready_and_failed_only_campaigns():
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    ids = stalled_generation_campaign_ids(
        [
            ("camp-done", GenerationStatus.READY, now),
            ("camp-fail", GenerationStatus.FAILED, now),
        ],
        now=now,
    )
    assert ids == []


def test_resume_stalled_calls_existing_resume_without_in_process_fallback():
    session = MagicMock()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    async def _run():
        with (
            patch(
                "app.services.campaign_email_generation_service.find_stalled_generation_campaigns",
                new=AsyncMock(return_value=[("camp-1", "user-1"), ("camp-2", "user-2")]),
            ),
            patch(
                "app.services.campaign_email_generation_service.resume_campaign_email_generation",
                new=AsyncMock(
                    side_effect=[
                        {"campaign_id": "camp-1", "resumed": True},
                        {"campaign_id": "camp-2", "resumed": False, "already_running": True},
                    ]
                ),
            ) as resume,
        ):
            result = await resume_stalled_campaign_email_generations(session_factory)
            assert resume.await_count == 2
            assert resume.await_args_list[0].kwargs["allow_in_process"] is False
            assert resume.await_args_list[1].args[:2] == ("camp-2", "user-2")
        return result

    result = asyncio.run(_run())
    assert result == {"candidates": 2, "resumed": 1, "skipped": 1, "errors": 0}


def test_resume_stalled_continues_after_http_error():
    session = MagicMock()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    async def _run():
        with (
            patch(
                "app.services.campaign_email_generation_service.find_stalled_generation_campaigns",
                new=AsyncMock(return_value=[("camp-1", "user-1"), ("camp-2", "user-2")]),
            ),
            patch(
                "app.services.campaign_email_generation_service.resume_campaign_email_generation",
                new=AsyncMock(
                    side_effect=[
                        HTTPException(status_code=402, detail="insufficient credits"),
                        {"campaign_id": "camp-2", "resumed": True},
                    ]
                ),
            ),
        ):
            return await resume_stalled_campaign_email_generations(session_factory)

    result = asyncio.run(_run())
    assert result == {"candidates": 2, "resumed": 1, "skipped": 1, "errors": 0}
