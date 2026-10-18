"""add lead promote and list composite indexes

Revision ID: l6f7a8b9c0d1
Revises: k5e6f7a8b9c0
Create Date: 2026-08-12 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "l6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "k5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_leads_lead_log_id",
        "leads",
        ["lead_log_id"],
        unique=False,
    )
    op.create_index(
        "idx_leads_user_created_id",
        "leads",
        ["user_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "idx_leads_user_overture",
        "leads",
        ["user_id", "overture_id"],
        unique=False,
    )
    op.create_index(
        "idx_lead_log_leads_log_promoted",
        "lead_log_leads",
        ["lead_log_id", "promoted"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_lead_log_leads_log_promoted", table_name="lead_log_leads")
    op.drop_index("idx_leads_user_overture", table_name="leads")
    op.drop_index("idx_leads_user_created_id", table_name="leads")
    op.drop_index("ix_leads_lead_log_id", table_name="leads")
