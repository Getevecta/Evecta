"""updated campaign model for email template

Revision ID: 5f6664713cc0
Revises: 068b40f65d0e
Create Date: 2025-11-13 15:18:43.000759
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5f6664713cc0'
down_revision: Union[str, Sequence[str], None] = '068b40f65d0e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Define Enum type for PostgreSQL
drafttype_enum = postgresql.ENUM('TEMPLATE', 'AI', 'MANUAL', name='drafttype', create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    # ----------------------------------------------------------
    # Create ENUM type (PostgreSQL requirement)
    # ----------------------------------------------------------
    drafttype_enum.create(op.get_bind(), checkfirst=True)

    # ----------------------------------------------------------
    # Add columns related to email draft system
    # ----------------------------------------------------------
    op.add_column(
        'campaigns',
        sa.Column('draft_type', sa.Enum('TEMPLATE', 'AI', 'MANUAL', name='drafttype'), nullable=True)
    )
    op.add_column('campaigns', sa.Column('template_id', sa.UUID(), nullable=True))
    op.add_column('campaigns', sa.Column('email_subject', sa.String(length=255), nullable=True))
    op.add_column('campaigns', sa.Column('email_content', sa.Text(), nullable=True))

    # ----------------------------------------------------------
    # Add index + foreign key
    # ----------------------------------------------------------
    op.create_index(op.f('ix_campaigns_draft_type'), 'campaigns', ['draft_type'], unique=False)
    op.create_foreign_key(
        'fk_campaigns_template_id_email_templates',
        'campaigns',
        'email_templates',
        ['template_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # ----------------------------------------------------------
    # Preserve Alembic’s roles index behavior (cleanup)  
    # ----------------------------------------------------------
    op.drop_index(op.f('ix_roles_name'), table_name='roles')
    op.create_index('ix_roles_name', 'roles', ['name'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # ----------------------------------------------------------
    # Revert roles index change
    # ----------------------------------------------------------
    op.drop_index('ix_roles_name', table_name='roles')
    op.create_index(op.f('ix_roles_name'), 'roles', ['name'], unique=True)

    # ----------------------------------------------------------
    # Drop FK, index, and columns
    # ----------------------------------------------------------
    op.drop_constraint('fk_campaigns_template_id_email_templates', 'campaigns', type_='foreignkey')
    op.drop_index(op.f('ix_campaigns_draft_type'), table_name='campaigns')
    op.drop_column('campaigns', 'email_content')
    op.drop_column('campaigns', 'email_subject')
    op.drop_column('campaigns', 'template_id')
    op.drop_column('campaigns', 'draft_type')

    # ----------------------------------------------------------
    # Drop ENUM type safely
    # ----------------------------------------------------------
    drafttype_enum.drop(op.get_bind(), checkfirst=True)
