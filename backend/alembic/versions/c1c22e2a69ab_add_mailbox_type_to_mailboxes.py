"""add mailbox_type to mailboxes

Revision ID: c1c22e2a69ab
Revises: b16dae384967
Create Date: 2025-12-25 08:57:56.952561
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'c1c22e2a69ab'
down_revision: Union[str, Sequence[str], None] = 'b16dae384967'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1️⃣ Create ENUM explicitly
    mailbox_type_enum = sa.Enum(
        'SYSTEM',
        'USER',
        name='mailboxtype'
    )
    mailbox_type_enum.create(op.get_bind(), checkfirst=True)

    # 2️⃣ Add column as NULLABLE first
    op.add_column(
        'mailboxes',
        sa.Column(
            'mailbox_type',
            mailbox_type_enum,
            nullable=True
        )
    )

    # 3️⃣ Backfill existing rows → SYSTEM
    op.execute(
        "UPDATE mailboxes SET mailbox_type = 'SYSTEM' WHERE mailbox_type IS NULL"
    )

    # 4️⃣ Make column NOT NULL
    op.alter_column(
        'mailboxes',
        'mailbox_type',
        nullable=False
    )


def downgrade() -> None:
    # Drop column first
    op.drop_column('mailboxes', 'mailbox_type')

    # Drop enum type
    sa.Enum(name='mailboxtype').drop(op.get_bind(), checkfirst=True)
