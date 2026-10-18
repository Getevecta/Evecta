"""add locality to overture_places (GEO-4 nearby counts + city tier)

Revision ID: 0c3c54e50e8d
Revises: 3afb056c9a5c
Create Date: 2026-07-21 12:44:28.167619

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0c3c54e50e8d'
down_revision: Union[str, Sequence[str], None] = '3afb056c9a5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # HAND-EDITED after autogenerate: stripped the recurring unrelated drift
    # (checkpointer-table DROPs — LangGraph tables outside SQLAlchemy metadata; see
    # migration 07dc3dc813d9). This migration is ONLY overture_places.locality.
    op.add_column('overture_places', sa.Column('locality', sa.String(length=128), nullable=True))
    op.create_index(op.f('ix_overture_places_locality'), 'overture_places', ['locality'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_overture_places_locality'), table_name='overture_places')
    op.drop_column('overture_places', 'locality')
