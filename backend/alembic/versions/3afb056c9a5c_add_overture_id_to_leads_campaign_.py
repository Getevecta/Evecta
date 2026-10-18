"""add overture_id to leads (campaign enrichment gate)

Revision ID: 3afb056c9a5c
Revises: 07dc3dc813d9
Create Date: 2026-07-17 15:01:53.734435

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3afb056c9a5c'
down_revision: Union[str, Sequence[str], None] = '07dc3dc813d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # HAND-EDITED after autogenerate: stripped the recurring unrelated drift
    # (checkpointer-table DROPs + ix_roles_name unique flip — see migration
    # 07dc3dc813d9). This migration is ONLY leads.overture_id (doc §6.5 / 5.8).
    op.add_column('leads', sa.Column('overture_id', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_leads_overture_id'), 'leads', ['overture_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_leads_overture_id'), table_name='leads')
    op.drop_column('leads', 'overture_id')
