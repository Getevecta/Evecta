"""keep_only_three_email_templates

Revision ID: keep_only_three_templates
Revises: 4c25b67cd6a4
Create Date: 2026-02-26

Keep only the three canonical email templates: Professional, Network Outreach, Value Proportion.
Removes all other templates from the database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'keep_only_three_templates'
down_revision: Union[str, Sequence[str], None] = '4c25b67cd6a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The three templates to keep (exact names as in the UI)
KEEP_NAMES = ('Professional', 'Network Outreach', 'Value Proportion')


def upgrade() -> None:
    """Remove all email templates except Professional, Network Outreach, and Value Proportion."""
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            DELETE FROM email_templates
            WHERE name NOT IN (:n1, :n2, :n3)
        """),
        {"n1": KEEP_NAMES[0], "n2": KEEP_NAMES[1], "n3": KEEP_NAMES[2]}
    )
    print("Removed extra email templates; kept only Professional, Network Outreach, Value Proportion")


def downgrade() -> None:
    """No-op: we cannot restore deleted templates."""
    pass
