"""add chat_knowledge_retrieval_events table

Revision ID: m7a8b9c0d1e2
Revises: l6f7a8b9c0d1
Create Date: 2026-08-06 12:00:00.000000

Additive only — creates one new table and its indexes, touches nothing existing,
and is therefore safe against a populated staging database. Reversible.

Originally authored as i3c4d5e6f7a8/h2b3c4d5e6f7, which collided with the
pre-existing add_user_memory_items on dev — same id, same parent. Alembic stamps
an id once, so whichever file it reached first marked the other applied and the
second table was never created, silently. Renumbered onto the current head so
this appends cleanly when the branch merges.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "k9c0d1e2f3g4"
down_revision: Union[str, Sequence[str], None] = "l6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "chat_knowledge_retrieval_events"


def upgrade() -> None:
    # This revision was authored twice under ids that already belonged to other
    # migrations (i3c4d5e6f7a8, then m7a8b9c0d1e2). On any database that ran a
    # colliding id, the table was created but this revision was never stamped,
    # so a straight create_table raises DuplicateTable. Skip when the table is
    # already present; a fresh database still gets it built normally.
    if sa.inspect(op.get_bind()).has_table(TABLE_NAME):
        return

    op.create_table(
        "chat_knowledge_retrieval_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("retrieved", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("top_score", sa.Float(), nullable=True),
        sa.Column("fallback_fired", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("index_unavailable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retrieval_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_knowledge_events_created_at",
        "chat_knowledge_retrieval_events",
        ["created_at"],
    )
    op.create_index(
        "ix_chat_knowledge_events_fallback_fired",
        "chat_knowledge_retrieval_events",
        ["fallback_fired"],
    )
    op.create_index(
        "ix_chat_knowledge_events_user_id",
        "chat_knowledge_retrieval_events",
        ["user_id"],
    )


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table(TABLE_NAME):
        return

    op.drop_index(
        "ix_chat_knowledge_events_user_id", table_name="chat_knowledge_retrieval_events"
    )
    op.drop_index(
        "ix_chat_knowledge_events_fallback_fired",
        table_name="chat_knowledge_retrieval_events",
    )
    op.drop_index(
        "ix_chat_knowledge_events_created_at",
        table_name="chat_knowledge_retrieval_events",
    )
    op.drop_table("chat_knowledge_retrieval_events")
