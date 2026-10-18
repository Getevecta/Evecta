"""add email_sending_mode to users and campaigns

Revision ID: 604494657b52
Revises: c1c22e2a69ab
Create Date: 2025-12-25 20:09:02.364979
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "604494657b52"
down_revision: Union[str, Sequence[str], None] = "c1c22e2a69ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Upgrade schema:
    - Create emailsendingmode ENUM
    - Add email_sending_mode column to users
    - Add email_sending_mode column to campaigns
    """

    # ---- Create ENUM type (PostgreSQL) ----
    email_sending_mode_enum = sa.Enum(
        "SYSTEM",
        "USER",
        name="emailsendingmode",
    )
    email_sending_mode_enum.create(
        bind=op.get_bind(),
        checkfirst=True,
    )

    # ---- Add column to users ----
    op.add_column(
        "users",
        sa.Column(
            "email_sending_mode",
            sa.Enum(
                "SYSTEM",
                "USER",
                name="emailsendingmode",
            ),
            nullable=True,  # NULL = not chosen yet
        ),
    )

    # ---- Add column to campaigns ----
    op.add_column(
        "campaigns",
        sa.Column(
            "email_sending_mode",
            sa.Enum(
                "SYSTEM",
                "USER",
                name="emailsendingmode",
            ),
            nullable=True,  # NULL = cannot launch
        ),
    )

    # ---- Optional index for campaign filtering ----
    op.create_index(
        "ix_campaigns_email_sending_mode",
        "campaigns",
        ["email_sending_mode"],
        unique=False,
    )


def downgrade() -> None:
    """
    Downgrade schema:
    - Remove email_sending_mode columns
    - Drop emailsendingmode ENUM
    """

    # ---- Drop columns first ----
    op.drop_index(
        "ix_campaigns_email_sending_mode",
        table_name="campaigns",
    )

    op.drop_column(
        "campaigns",
        "email_sending_mode",
    )

    op.drop_column(
        "users",
        "email_sending_mode",
    )

    # ---- Drop ENUM type ----
    sa.Enum(
        "SYSTEM",
        "USER",
        name="emailsendingmode",
    ).drop(
        bind=op.get_bind(),
        checkfirst=True,
    )
