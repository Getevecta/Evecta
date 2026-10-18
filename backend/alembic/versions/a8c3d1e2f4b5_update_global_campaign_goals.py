"""Update global campaign goals to outreach-focused options

Revision ID: a8c3d1e2f4b5
Revises: 93ea89485be5
Create Date: 2026-07-16 11:50:00.000000

"""
from typing import Sequence, Union
from uuid import uuid4
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision: str = "a8c3d1e2f4b5"
down_revision: Union[str, Sequence[str], None] = "93ea89485be5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_GOALS = [
    "Brand Awareness",
    "Lead Generation",
    "Customer Engagement",
    "Sales Conversion",
    "Product Promotion",
]

NEW_GOALS = [
    "Generate Replies",
    "Book Meetings",
    "Promote a Service",
    "Send Announcement",
    "Sell a Product",
    "Reconnect with Old Leads",
    "Start Partnership Conversation",
    "Test Message Angle",
]


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    # Clear campaign references to old global goals before removing them
    conn.execute(
        sa.text(
            """
            UPDATE campaigns
            SET goal_id = NULL
            WHERE goal_id IN (
                SELECT id FROM campaign_goals
                WHERE user_id IS NULL AND name = ANY(:names)
            )
            """
        ),
        {"names": OLD_GOALS},
    )

    conn.execute(
        sa.text(
            """
            DELETE FROM campaign_goals
            WHERE user_id IS NULL AND name = ANY(:names)
            """
        ),
        {"names": OLD_GOALS},
    )

    for name in NEW_GOALS:
        conn.execute(
            sa.text(
                """
                INSERT INTO campaign_goals (id, name, user_id, created_at, updated_at)
                SELECT :id, CAST(:name AS VARCHAR), NULL, :created_at, :updated_at
                WHERE NOT EXISTS (
                    SELECT 1 FROM campaign_goals
                    WHERE name = CAST(:name AS VARCHAR) AND user_id IS NULL
                )
                """
            ),
            {
                "id": str(uuid4()),
                "name": name,
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    conn.execute(
        sa.text(
            """
            UPDATE campaigns
            SET goal_id = NULL
            WHERE goal_id IN (
                SELECT id FROM campaign_goals
                WHERE user_id IS NULL AND name = ANY(:names)
            )
            """
        ),
        {"names": NEW_GOALS},
    )

    conn.execute(
        sa.text(
            """
            DELETE FROM campaign_goals
            WHERE user_id IS NULL AND name = ANY(:names)
            """
        ),
        {"names": NEW_GOALS},
    )

    for name in OLD_GOALS:
        conn.execute(
            sa.text(
                """
                INSERT INTO campaign_goals (id, name, user_id, created_at, updated_at)
                SELECT :id, CAST(:name AS VARCHAR), NULL, :created_at, :updated_at
                WHERE NOT EXISTS (
                    SELECT 1 FROM campaign_goals
                    WHERE name = CAST(:name AS VARCHAR) AND user_id IS NULL
                )
                """
            ),
            {
                "id": str(uuid4()),
                "name": name,
                "created_at": now,
                "updated_at": now,
            },
        )
