from datetime import date
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.services.campaign_insight_service import (
    _build_daily_stats_stmt,
    _build_failed_leads_stmt,
)


def test_daily_stats_excludes_failed_send_attempts():
    stmt = _build_daily_stats_stmt(
        str(uuid4()),
        date(2026, 6, 5),
        date(2026, 6, 11),
    )

    sql = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "email_activities.status != 'FAILED'" in sql


def test_failed_leads_counts_activity_and_job_failures():
    stmt = _build_failed_leads_stmt(str(uuid4()), str(uuid4()))

    sql = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "email_activities.status = 'FAILED'" in sql
    assert "email_jobs.status = 'failed'" in sql
    assert "UNION" in sql
