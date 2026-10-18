"""cleanup_invalid_email_template_categories

Revision ID: 870df9424937
Revises: 883ed5d7c483
Create Date: 2025-12-01 11:43:23.362531

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '870df9424937'
down_revision: Union[str, Sequence[str], None] = '883ed5d7c483'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Clean up invalid email template categories and remove deleted templates."""
    conn = op.get_bind()
    
    # Valid category values from TemplateCategory enum
    valid_categories = ['professional', 'value-proposition', 'network-outreach']
    
    # Delete templates with names that were removed: "Gentle Follow-up" and "Final Follow-up"
    # Use case-insensitive matching to catch all variations
    conn.execute(
        sa.text("""
            DELETE FROM email_templates 
            WHERE LOWER(name) IN ('gentle follow-up', 'final follow-up', 'gentle-followup', 'final-followup')
        """)
    )
    
    # Update any remaining templates with invalid categories to NULL
    # This handles cases where templates have categories that don't match the enum
    conn.execute(
        sa.text("""
            UPDATE email_templates 
            SET category = NULL 
            WHERE category IS NOT NULL 
            AND category::text NOT IN ('professional', 'value-proposition', 'network-outreach')
        """)
    )
    
    print("Cleaned up invalid email template categories and removed deleted templates")


def downgrade() -> None:
    """Downgrade schema - no action needed."""
    pass
