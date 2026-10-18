"""normalize mailboxprovider enum to uppercase values

Revision ID: 143218f69972
Revises: 8443aa005e4c
Create Date: 2026-07-05 09:10:57.892827

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '143218f69972'
down_revision: Union[str, Sequence[str], None] = '8443aa005e4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Converge mailboxprovider on uppercase values in every environment.

    History: migration b16dae384967 created the type with lowercase labels
    while the model wrote uppercase names, and each environment was then
    hand-patched differently (labels added on local, renamed on servers).
    The model now uses uppercase values; this migration rebuilds the type
    so every database ends with exactly the two uppercase labels.
    """
    # Postgres cannot drop individual enum labels, so rebuild the type from
    # scratch. upper() in the USING clause converts any lowercase row values
    # in the same step, so this works regardless of an environment's current
    # labels (mixed on local, uppercase on servers, lowercase on fresh DBs).
    op.execute("ALTER TYPE mailboxprovider RENAME TO mailboxprovider_old")
    op.execute("CREATE TYPE mailboxprovider AS ENUM ('ANY_PROVIDER', 'GOOGLE')")
    op.execute("ALTER TABLE mailboxes ALTER COLUMN provider DROP DEFAULT")
    op.execute(
        "ALTER TABLE mailboxes ALTER COLUMN provider "
        "TYPE mailboxprovider USING upper(provider::text)::mailboxprovider"
    )
    op.execute(
        "ALTER TABLE mailboxes ALTER COLUMN provider "
        "SET DEFAULT 'ANY_PROVIDER'::mailboxprovider"
    )
    op.execute("DROP TYPE mailboxprovider_old")


def downgrade() -> None:
    """Mirror image: rebuild the type with lowercase labels only."""
    op.execute("ALTER TYPE mailboxprovider RENAME TO mailboxprovider_old")
    op.execute("CREATE TYPE mailboxprovider AS ENUM ('any_provider', 'google')")
    op.execute("ALTER TABLE mailboxes ALTER COLUMN provider DROP DEFAULT")
    op.execute(
        "ALTER TABLE mailboxes ALTER COLUMN provider "
        "TYPE mailboxprovider USING lower(provider::text)::mailboxprovider"
    )
    op.execute(
        "ALTER TABLE mailboxes ALTER COLUMN provider "
        "SET DEFAULT 'any_provider'::mailboxprovider"
    )
    op.execute("DROP TYPE mailboxprovider_old")
