"""unique index on lower(users.email)

Case-sensitive UNIQUE on users.email allowed John@x.com and john@x.com as
two accounts. Replace it with a functional unique index so identity is
case-insensitive regardless of application write paths.

Fails loudly if colliding rows already exist — resolve those before rerunning.
Existing emails are then stored in lowercase so exact-match lookups stay valid.

Revision ID: m7a8b9c0d1e2
Revises: l6f7a8b9c0d1
Create Date: 2026-08-18 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "l6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    collisions = conn.execute(
        sa.text(
            """
            SELECT lower(email) AS normalized,
                   string_agg(email, ', ' ORDER BY email) AS emails,
                   string_agg(id::text, ', ') AS ids
            FROM users
            GROUP BY lower(email)
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if collisions:
        details = "; ".join(
            f"{row.normalized} -> [{row.emails}] ids=[{row.ids}]" for row in collisions
        )
        raise RuntimeError(
            "Cannot create unique index on lower(users.email); "
            f"resolve case-colliding rows first: {details}"
        )

    op.execute(sa.text("UPDATE users SET email = lower(email) WHERE email <> lower(email)"))

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)
    op.execute("CREATE UNIQUE INDEX ix_users_email_lower ON users (lower(email))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_email_lower")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
