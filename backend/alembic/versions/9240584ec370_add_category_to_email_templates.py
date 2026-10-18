"""add_category_to_email_templates

Revision ID: 9240584ec370
Revises: 4afcf051d387
Create Date: 2025-11-27 11:29:55.385858

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '9240584ec370'
down_revision: Union[str, Sequence[str], None] = '4afcf051d387'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Define Enum type for PostgreSQL
templatecategory_enum = postgresql.ENUM(
    'professional',
    'value-proposition',
    'network-outreach',
    name='templatecategory',
    create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    # Create ENUM type (PostgreSQL requirement)
    templatecategory_enum.create(op.get_bind(), checkfirst=True)
    
    # Add category column to email_templates table
    op.add_column(
        'email_templates',
        sa.Column('category', sa.Enum(
            'professional',
            'value-proposition',
            'network-outreach',
            name='templatecategory'
        ), nullable=True)
    )
    
    # Create index on category column
    op.create_index('ix_email_templates_category', 'email_templates', ['category'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop index
    op.drop_index('ix_email_templates_category', table_name='email_templates')
    
    # Drop category column
    op.drop_column('email_templates', 'category')
    
    # Drop ENUM type
    templatecategory_enum.drop(op.get_bind(), checkfirst=True)
