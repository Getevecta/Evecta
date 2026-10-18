"""add_is_read_column_back_to_lead_logs

Revision ID: 1d6b313a537f
Revises: dcf0f630ec22
Create Date: 2026-01-18 15:05:56.388424

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '1d6b313a537f'
down_revision: Union[str, Sequence[str], None] = 'dcf0f630ec22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add is_read column to lead_logs table if it doesn't exist.
    This restores the column that was removed in migration 8b69d8731558.
    The model and application code still reference this column, so it needs to exist.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_columns = {col["name"] for col in inspector.get_columns("lead_logs")}

    # Add is_read column if it doesn't exist
    if "is_read" not in existing_columns:
        op.add_column(
            "lead_logs",
            sa.Column(
                "is_read",
                sa.Boolean(),
                nullable=True,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    """
    Remove is_read column from lead_logs table if it exists.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_columns = {col["name"] for col in inspector.get_columns("lead_logs")}

    # Remove is_read column if it exists
    if "is_read" in existing_columns:
        op.drop_column("lead_logs", "is_read")
