"""unique index on lower(mailboxes.email) and lower(waitlist.email)

Case-sensitive UNIQUE on these columns allowed John@x.com and john@x.com as
two identities. Replace it with a functional unique index so mailbox and
waitlist identity is case-insensitive regardless of application write paths.

Fails loudly if colliding rows already exist — resolve those before rerunning.
Existing emails are then stored in lowercase so exact-match lookups stay valid.

Lead.email is intentionally out of scope: it is not globally unique.

Revision ID: q1e2f3a4b5c6
Revises: p0d1e2f3a4b5
Create Date: 2026-08-20 10:51:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "p0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMAIL_TABLES = frozenset({"mailboxes", "waitlist"})


def _fail_on_email_collisions(conn, table: str) -> None:
    if table not in _EMAIL_TABLES:
        raise ValueError(f"unexpected table: {table}")
    collisions = conn.execute(
        sa.text(
            f"""
            SELECT lower(email) AS normalized,
                   string_agg(email, ', ' ORDER BY email) AS emails,
                   string_agg(id::text, ', ') AS ids
            FROM {table}
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
            f"Cannot create unique index on lower({table}.email); "
            f"resolve case-colliding rows first: {details}"
        )


def _replace_raw_email_unique(table: str, btree_index: str) -> None:
    if table not in _EMAIL_TABLES:
        raise ValueError(f"unexpected table: {table}")
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dropped = False
    for constraint in insp.get_unique_constraints(table):
        if constraint.get("column_names") == ["email"]:
            op.drop_constraint(constraint["name"], table, type_="unique")
            dropped = True

    insp = sa.inspect(bind)
    for index in insp.get_indexes(table):
        if index.get("unique") and index.get("column_names") == ["email"]:
            op.drop_index(index["name"], table_name=table)
            dropped = True

    if not dropped:
        raise RuntimeError(
            f"Expected a unique constraint or unique index on {table}.email"
        )

    op.create_index(btree_index, table, ["email"], unique=False)


def upgrade() -> None:
    conn = op.get_bind()
    _fail_on_email_collisions(conn, "mailboxes")
    _fail_on_email_collisions(conn, "waitlist")

    op.execute(
        sa.text("UPDATE mailboxes SET email = lower(email) WHERE email <> lower(email)")
    )
    op.execute(
        sa.text("UPDATE waitlist SET email = lower(email) WHERE email <> lower(email)")
    )

    _replace_raw_email_unique("mailboxes", "ix_mailboxes_email")
    op.execute("CREATE UNIQUE INDEX ix_mailboxes_email_lower ON mailboxes (lower(email))")

    _replace_raw_email_unique("waitlist", "ix_waitlist_email")
    op.execute("CREATE UNIQUE INDEX ix_waitlist_email_lower ON waitlist (lower(email))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_mailboxes_email_lower")
    op.drop_index("ix_mailboxes_email", table_name="mailboxes")
    op.create_unique_constraint("mailboxes_email_key", "mailboxes", ["email"])

    op.execute("DROP INDEX IF EXISTS ix_waitlist_email_lower")
    op.drop_index("ix_waitlist_email", table_name="waitlist")
    op.create_unique_constraint("waitlist_email_key", "waitlist", ["email"])
