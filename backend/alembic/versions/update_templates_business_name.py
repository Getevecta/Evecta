"""update_templates_business_name

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2024-12-20 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def update_templates_business_name(conn):
    """
    Update template subjects to use {{business_name}} instead of {{company}}.
    """
    # Update Professional template subject
    conn.execute(
        sa.text("""
            UPDATE email_templates 
            SET subject = REPLACE(subject, '{{company}}', '{{business_name}}'),
                updated_at = :updated_at
            WHERE name = 'Professional' AND subject LIKE '%{{company}}%'
        """),
        {"updated_at": datetime.now(timezone.utc)}
    )
    
    # Update Value Proportion template subject
    conn.execute(
        sa.text("""
            UPDATE email_templates 
            SET subject = REPLACE(subject, '{{company}}', '{{business_name}}'),
                updated_at = :updated_at
            WHERE name = 'Value Proportion' AND subject LIKE '%{{company}}%'
        """),
        {"updated_at": datetime.now(timezone.utc)}
    )
    
    print("Updated template subjects to use {{business_name}} instead of {{company}}")


def upgrade() -> None:
    """Upgrade schema - update template subjects to use {{business_name}}."""
    conn = op.get_bind()
    update_templates_business_name(conn)


def downgrade() -> None:
    """Downgrade schema - revert to {{company}}."""
    conn = op.get_bind()
    # Revert back to {{company}}
    conn.execute(
        sa.text("""
            UPDATE email_templates 
            SET subject = REPLACE(subject, '{{business_name}}', '{{company}}'),
                updated_at = :updated_at
            WHERE (name = 'Professional' OR name = 'Value Proportion') AND subject LIKE '%{{business_name}}%'
        """),
        {"updated_at": datetime.now(timezone.utc)}
    )
    print("Reverted template subjects back to {{company}}")

