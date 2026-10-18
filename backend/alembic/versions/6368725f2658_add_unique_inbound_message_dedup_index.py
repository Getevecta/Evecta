"""add unique inbound message dedup index

Reply fetch used to re-ingest the same unread message on every sync,
inserting a duplicate INBOUND row each time. This index is the arbiter
for ON CONFLICT DO NOTHING in the fetch services, so concurrent fetches
cannot store the same reply twice.

NOTE: existing duplicate INBOUND rows must be removed before this
migration can run — a unique index cannot be built over duplicates.

Revision ID: 6368725f2658
Revises: 143218f69972
Create Date: 2026-07-10 12:52:12.327220

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6368725f2658'
down_revision: Union[str, Sequence[str], None] = '143218f69972'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'uq_email_messages_inbound_dedup',
        'email_messages',
        ['thread_id', 'lead_id', 'message_id'],
        unique=True,
        postgresql_where=sa.text("direction = 'INBOUND' AND message_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_email_messages_inbound_dedup', table_name='email_messages')
