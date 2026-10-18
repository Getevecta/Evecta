"""campaign_lead_emails table for per-lead email drafts

Revision ID: f6a7b8c9d0e1
Revises: e5f9a2b3c4d5
Create Date: 2026-06-22 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f9a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

generation_status = postgresql.ENUM(
    "pending", "generating", "ready", "failed",
    name="generationstatus",
    create_type=False,
)
compliance_status = postgresql.ENUM(
    "pending", "passed", "failed",
    name="compliancestatus",
    create_type=False,
)
review_status = postgresql.ENUM(
    "pending", "approved", "rejected",
    name="reviewstatus",
    create_type=False,
)


def upgrade() -> None:
    generation_status.create(op.get_bind(), checkfirst=True)
    compliance_status.create(op.get_bind(), checkfirst=True)
    review_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "campaign_lead_emails",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("campaign_lead_id", sa.UUID(), nullable=True),
        sa.Column("lead_id", sa.UUID(), nullable=True),
        sa.Column("lead_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "generation_status",
            generation_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "compliance_status",
            compliance_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("spam_score", sa.Integer(), nullable=True),
        sa.Column("risk_level", sa.String(length=32), nullable=True),
        sa.Column(
            "review_status",
            review_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("regeneration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("variant_metadata", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_lead_id"], ["campaign_leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "lead_id", name="uq_campaign_lead_email_pair"),
    )
    op.create_index(
        "idx_campaign_lead_email_status",
        "campaign_lead_emails",
        ["campaign_id", "generation_status"],
    )
    op.create_index(
        op.f("ix_campaign_lead_emails_campaign_id"),
        "campaign_lead_emails",
        ["campaign_id"],
    )
    op.create_index(
        op.f("ix_campaign_lead_emails_campaign_lead_id"),
        "campaign_lead_emails",
        ["campaign_lead_id"],
    )
    op.create_index(
        op.f("ix_campaign_lead_emails_lead_id"),
        "campaign_lead_emails",
        ["lead_id"],
    )
    op.create_index(
        op.f("ix_campaign_lead_emails_generation_status"),
        "campaign_lead_emails",
        ["generation_status"],
    )
    op.create_index(
        op.f("ix_campaign_lead_emails_compliance_status"),
        "campaign_lead_emails",
        ["compliance_status"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_campaign_lead_emails_compliance_status"), table_name="campaign_lead_emails")
    op.drop_index(op.f("ix_campaign_lead_emails_generation_status"), table_name="campaign_lead_emails")
    op.drop_index(op.f("ix_campaign_lead_emails_lead_id"), table_name="campaign_lead_emails")
    op.drop_index(op.f("ix_campaign_lead_emails_campaign_lead_id"), table_name="campaign_lead_emails")
    op.drop_index(op.f("ix_campaign_lead_emails_campaign_id"), table_name="campaign_lead_emails")
    op.drop_index("idx_campaign_lead_email_status", table_name="campaign_lead_emails")
    op.drop_table("campaign_lead_emails")
    review_status.drop(op.get_bind(), checkfirst=True)
    compliance_status.drop(op.get_bind(), checkfirst=True)
    generation_status.drop(op.get_bind(), checkfirst=True)
