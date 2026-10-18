"""add_status_and_is_read_to_lead_logs

Revision ID: 8b69d8731558
Revises: 9a77e4fc2f49
Create Date: 2026-01-07 11:20:15.660075
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# Revision identifiers, used by Alembic
revision: str = "8b69d8731558"
down_revision: Union[str, Sequence[str], None] = "9a77e4fc2f49"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Safely remove is_read column from lead_logs table
    ONLY if it exists. This avoids PostgreSQL transaction
    aborts in async Alembic migrations.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_columns = {col["name"] for col in inspector.get_columns("lead_logs")}

    if "is_read" in existing_columns:
        op.drop_column("lead_logs", "is_read")


def downgrade() -> None:
    """
    Restore is_read column during downgrade
    ONLY if it does not already exist.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_columns = {col["name"] for col in inspector.get_columns("lead_logs")}

    if "is_read" not in existing_columns:
        op.add_column(
            "lead_logs",
            sa.Column(
                "is_read",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )