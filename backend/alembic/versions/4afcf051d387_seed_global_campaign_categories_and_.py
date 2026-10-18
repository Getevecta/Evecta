"""Seed global campaign categories and goals

Revision ID: 4afcf051d387
Revises: 9ddc6c7bd910
Create Date: 2025-11-24 15:24:25.343091

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from uuid import uuid4
from datetime import datetime, timezone

# revision identifiers, used by Alembic.
revision: str = '4afcf051d387'
down_revision: Union[str, Sequence[str], None] = '9ddc6c7bd910'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None





# ---- GLOBAL DEFAULT DATA ----

DEFAULT_CATEGORIES = [
    "General",
    "Marketing",
    "Sales",
    "Retargeting",
    "Awareness"
]

DEFAULT_GOALS = [
    "Generate Replies",
    "Book Meetings",
    "Promote a Service",
    "Send Announcement",
    "Sell a Product",
    "Reconnect with Old Leads",
    "Start Partnership Conversation",
    "Test Message Angle",
]


def insert_global_items(conn, table_name: str, items: list[str]):
    """
    Helper function to insert global (user_id=NULL) items into a table.
    """
    for name in items:
        conn.execute(
            sa.text(f"""
                INSERT INTO {table_name} (id, name, user_id, created_at, updated_at)
                SELECT :id, CAST(:name AS VARCHAR), NULL, :created_at, :updated_at
                WHERE NOT EXISTS (
                    SELECT 1 FROM {table_name}
                    WHERE name = CAST(:name AS VARCHAR) AND user_id IS NULL
                )
            """),
            {
                "id": str(uuid4()),
                "name": name,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )


def upgrade():
    conn = op.get_bind()

    # Insert global categories
    insert_global_items(conn, "campaign_categories", DEFAULT_CATEGORIES)

    # Insert global goals
    insert_global_items(conn, "campaign_goals", DEFAULT_GOALS)


def downgrade():
    conn = op.get_bind()

    conn.execute(
        sa.text("""
            DELETE FROM campaign_categories
            WHERE user_id IS NULL AND name IN :names
        """),
        {"names": tuple(DEFAULT_CATEGORIES)}
    )

    conn.execute(
        sa.text("""
            DELETE FROM campaign_goals
            WHERE user_id IS NULL AND name IN :names
        """),
        {"names": tuple(DEFAULT_GOALS)}
    )