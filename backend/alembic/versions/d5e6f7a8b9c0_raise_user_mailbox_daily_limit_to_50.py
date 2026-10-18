"""Raise USER mailbox daily_limit default to 50.

Revision ID: d5e6f7a8b9c0
Revises: a8c3d1e2f4b5
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "a8c3d1e2f4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing connected accounts still have daily_limit=2 stored in DB.
    # Bump USER mailboxes only (leave SYSTEM managed pool alone).
    op.execute(
        """
        UPDATE mailboxes
        SET daily_limit = 50
        WHERE mailbox_type = 'USER'
          AND daily_limit = 2
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE mailboxes
        SET daily_limit = 2
        WHERE mailbox_type = 'USER'
          AND daily_limit = 50
        """
    )
