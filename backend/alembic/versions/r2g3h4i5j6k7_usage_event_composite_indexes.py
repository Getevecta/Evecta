"""Composite indexes for usage-event analytics filter + order patterns.

Admin AI usage filters a date window and optionally provider/feature/model/user,
then the events list orders by created_at DESC. External usage always filters
provider then created_at (and groups by api_name). Single-column indexes could
not serve those (filter, order) prefixes.

Revision ID: r2g3h4i5j6k7
Revises: q1e2f3a4b5c6
Create Date: 2026-08-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "r2g3h4i5j6k7"
down_revision: Union[str, Sequence[str], None] = "q1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_ai_usage_events_provider_created",
        "ai_usage_events",
        ["provider", "created_at"],
    )
    op.create_index(
        "ix_ai_usage_events_feature_created",
        "ai_usage_events",
        ["feature", "created_at"],
    )
    op.create_index(
        "ix_ai_usage_events_model_created",
        "ai_usage_events",
        ["model", "created_at"],
    )
    op.create_index(
        "ix_ai_usage_events_user_created",
        "ai_usage_events",
        ["user_id", "created_at"],
    )
    op.drop_index("ix_ai_usage_events_provider", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_feature", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_model", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_user_id", table_name="ai_usage_events")

    op.create_index(
        "ix_external_api_usage_events_provider_created",
        "external_api_usage_events",
        ["provider", "created_at"],
    )
    op.create_index(
        "ix_external_api_usage_events_provider_api_created",
        "external_api_usage_events",
        ["provider", "api_name", "created_at"],
    )
    op.drop_index(
        "ix_external_api_usage_events_created_at",
        table_name="external_api_usage_events",
    )
    op.drop_index(
        "ix_external_api_usage_events_provider",
        table_name="external_api_usage_events",
    )
    op.drop_index(
        "ix_external_api_usage_events_api_name",
        table_name="external_api_usage_events",
    )
    op.drop_index(
        "ix_external_api_usage_events_feature",
        table_name="external_api_usage_events",
    )


def downgrade() -> None:
    op.create_index(
        "ix_external_api_usage_events_feature",
        "external_api_usage_events",
        ["feature"],
    )
    op.create_index(
        "ix_external_api_usage_events_api_name",
        "external_api_usage_events",
        ["api_name"],
    )
    op.create_index(
        "ix_external_api_usage_events_provider",
        "external_api_usage_events",
        ["provider"],
    )
    op.create_index(
        "ix_external_api_usage_events_created_at",
        "external_api_usage_events",
        ["created_at"],
    )
    op.drop_index(
        "ix_external_api_usage_events_provider_api_created",
        table_name="external_api_usage_events",
    )
    op.drop_index(
        "ix_external_api_usage_events_provider_created",
        table_name="external_api_usage_events",
    )

    op.create_index("ix_ai_usage_events_user_id", "ai_usage_events", ["user_id"])
    op.create_index("ix_ai_usage_events_model", "ai_usage_events", ["model"])
    op.create_index("ix_ai_usage_events_feature", "ai_usage_events", ["feature"])
    op.create_index("ix_ai_usage_events_provider", "ai_usage_events", ["provider"])
    op.drop_index("ix_ai_usage_events_user_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_model_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_feature_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_provider_created", table_name="ai_usage_events")
