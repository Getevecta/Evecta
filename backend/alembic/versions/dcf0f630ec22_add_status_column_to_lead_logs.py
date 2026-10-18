"""add_status_column_to_lead_logs

Revision ID: dcf0f630ec22
Revises: 18d35a14267f
Create Date: 2026-01-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'dcf0f630ec22'
down_revision: Union[str, Sequence[str], None] = '18d35a14267f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add status column to lead_logs table if it doesn't exist.
    This avoids PostgreSQL transaction aborts in async Alembic migrations.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_columns = {col["name"] for col in inspector.get_columns("lead_logs")}

    # Add status column if it doesn't exist
    if "status" not in existing_columns:
        op.add_column(
            "lead_logs",
            sa.Column(
                "status",
                sa.String(length=50),
                nullable=False,
                server_default="active",
            ),
        )


def downgrade() -> None:
    """
    Remove status column from lead_logs table if it exists.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_columns = {col["name"] for col in inspector.get_columns("lead_logs")}

    # Remove status column if it exists
    if "status" in existing_columns:
        op.drop_column("lead_logs", "status")

