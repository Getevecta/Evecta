"""add has_more to overture_loaded_areas

Revision ID: da85a3f499e9
Revises: 0c3c54e50e8d
Create Date: 2026-07-24 12:45:16.878365

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'da85a3f499e9'
down_revision: Union[str, Sequence[str], None] = '0c3c54e50e8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Hand-stripped of alembic autogenerate drift (LangGraph checkpointer tables and an
    # unrelated ix_roles_name uniqueness change) — this migration only adds has_more.
    op.add_column(
        'overture_loaded_areas',
        sa.Column('has_more', sa.Boolean(), server_default='true', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('overture_loaded_areas', 'has_more')
