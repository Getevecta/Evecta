"""updated mailbox field

Revision ID: b16dae384967
Revises: 4df1bd314f6b
Create Date: 2025-12-24 12:27:57.814015
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b16dae384967"
down_revision: Union[str, Sequence[str], None] = "4df1bd314f6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------
    # 1. CREATE ENUM TYPE (MUST EXIST BEFORE COLUMN)
    # ------------------------------------------------------------
    mailboxprovider_enum = postgresql.ENUM(
        "any_provider",
        "google",
        name="mailboxprovider"
    )
    mailboxprovider_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------
    # 2. ADD provider COLUMN WITH DEFAULT (SAFE FOR EXISTING ROWS)
    # ------------------------------------------------------------
    op.add_column(
        "mailboxes",
        sa.Column(
            "provider",
            mailboxprovider_enum,
            nullable=False,
            server_default="any_provider",
        ),
    )

    # ------------------------------------------------------------
    # 3. ADD user_id COLUMN
    # ------------------------------------------------------------
    op.add_column(
        "mailboxes",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_mailboxes_user_id",
        "mailboxes",
        ["user_id"],
        unique=False,
    )

    # ------------------------------------------------------------
    # 4. FIX domain_id FK → CASCADE (SYSTEM MAILBOX LIFECYCLE)
    # ------------------------------------------------------------
    op.drop_constraint(
        "mailboxes_domain_id_fkey",
        "mailboxes",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "mailboxes_domain_id_fkey",
        "mailboxes",
        "domains",
        ["domain_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # ------------------------------------------------------------
    # REVERSE SAFELY
    # ------------------------------------------------------------

    op.drop_constraint(
        "mailboxes_domain_id_fkey",
        "mailboxes",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "mailboxes_domain_id_fkey",
        "mailboxes",
        "domains",
        ["domain_id"],
        ["id"],
    )

    op.drop_index("ix_mailboxes_user_id", table_name="mailboxes")
    op.drop_column("mailboxes", "user_id")
    op.drop_column("mailboxes", "provider")

    mailboxprovider_enum = postgresql.ENUM(
        "any_provider",
        "google",
        name="mailboxprovider"
    )
    mailboxprovider_enum.drop(op.get_bind(), checkfirst=True)
