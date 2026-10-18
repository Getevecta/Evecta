"""add campaign ai_email_prompt

Revision ID: c7d8e9f0a1b2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("ai_email_prompt", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE campaigns
        SET ai_email_prompt = description
        WHERE draft_type = 'AI'
          AND ai_email_prompt IS NULL
          AND description IS NOT NULL
          AND TRIM(description) <> ''
        """
    )


def downgrade() -> None:
    op.drop_column("campaigns", "ai_email_prompt")
