"""allow duplicate usernames; email remains unique

Revision ID: b8e2c1d4f5a6
Revises: c3f9a2b1e0d1
Create Date: 2026-04-08

"""
from alembic import op


revision = "b8e2c1d4f5a6"
down_revision = "c3f9a2b1e0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=False)


def downgrade() -> None:
    # Fails if duplicate usernames exist — re-run dedupe before downgrade.
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
