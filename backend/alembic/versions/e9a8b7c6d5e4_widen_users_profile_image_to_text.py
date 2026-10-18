"""widen users.profile_image to TEXT for base64 data URLs

Revision ID: e9a8b7c6d5e4
Revises: f8a9c0d1e2f3
Create Date: 2026-04-26

VARCHAR(500) truncates profile photos; base64 data URLs need TEXT.
(Uses a new revision id — a1b2c3d4e5f6 was already taken in this repo.)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9a8b7c6d5e4"
down_revision: Union[str, Sequence[str], None] = "f8a9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "profile_image",
        existing_type=sa.String(500),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "profile_image",
        existing_type=sa.Text(),
        type_=sa.String(500),
        existing_nullable=True,
    )
