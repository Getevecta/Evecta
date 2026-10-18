"""Unit tests for the shared campaign DRAFT guard and CampaignLeadResponse shape."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.campaign import CampaignStatus
from app.schemas.campaign_lead import CampaignLeadResponse
from app.services.campaign_guard import (
    EDITABLE_STATUSES,
    ensure_campaign_editable,
    is_campaign_editable,
)


def _campaign(status: CampaignStatus):
    return SimpleNamespace(status=status)


class TestEnsureCampaignEditable:
    def test_draft_is_editable(self):
        campaign = _campaign(CampaignStatus.DRAFT)
        assert is_campaign_editable(campaign) is True
        ensure_campaign_editable(campaign, action="edit")

    @pytest.mark.parametrize("status", [CampaignStatus.ONGOING, CampaignStatus.COMPLETED])
    def test_non_draft_is_not_editable(self, status: CampaignStatus):
        campaign = _campaign(status)
        assert is_campaign_editable(campaign) is False
        with pytest.raises(HTTPException) as exc:
            ensure_campaign_editable(campaign, action="edit")
        assert exc.value.status_code == 400
        assert exc.value.detail == "Cannot edit draft after campaign launch."

    def test_action_specific_messages(self):
        campaign = _campaign(CampaignStatus.ONGOING)
        cases = {
            "generate": "Cannot generate emails after campaign launch.",
            "review": "Cannot review emails after campaign launch.",
            "modify_leads": "Cannot modify leads after campaign launch.",
            "save": "Only draft campaigns can be saved.",
            "launch": "Only draft campaigns can be launched.",
            "delete": "Only draft campaigns can be deleted.",
            "modify": "Campaign cannot be modified after launch.",
        }
        for action, detail in cases.items():
            with pytest.raises(HTTPException) as exc:
                ensure_campaign_editable(campaign, action=action)
            assert exc.value.detail == detail

    def test_editable_statuses_is_the_single_rule(self):
        assert EDITABLE_STATUSES == frozenset({CampaignStatus.DRAFT})


class TestCampaignLeadResponseShape:
    def test_live_lead_is_nested_only(self):
        lead_id = uuid4()
        campaign_lead_id = uuid4()
        campaign_id = uuid4()
        lead = SimpleNamespace(
            id=lead_id,
            business_name="Acme Bakery",
            email="hello@acme.test",
            industry="Food",
            address="1 Main St",
            contact_number="555-0100",
            website="https://acme.test",
            lead_score=80,
            services="Bread",
            website_summary="A bakery.",
            business_description="Family-owned.",
            lead_log_id=None,
        )
        campaign_lead = SimpleNamespace(
            id=campaign_lead_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
            created_at=datetime.now(timezone.utc),
            lead=lead,
            business_name="Snapshot Name",
            email="snapshot@acme.test",
            industry="Snapshot",
            address="Snapshot Addr",
            contact_number="000",
            website="https://snapshot.test",
            lead_score=1,
            services="Snapshot services",
            website_summary="Snapshot summary",
            business_description="Snapshot description",
            context_score="full",
            effective_depth="deep",
            email_status="sent",
            email_sent_at=datetime.now(timezone.utc),
        )

        payload = CampaignLeadResponse.from_orm_with_snapshot(campaign_lead).model_dump()

        duplicated_fields = {
            "business_name",
            "email",
            "industry",
            "address",
            "contact_number",
            "website",
            "lead_score",
            "services",
            "website_summary",
            "business_description",
        }
        assert duplicated_fields.isdisjoint(payload.keys())
        assert payload["lead"]["business_name"] == "Acme Bakery"
        assert payload["lead"]["email"] == "hello@acme.test"
        assert payload["is_user_added"] is True
        assert payload["context_score"] == "full"

    def test_deleted_lead_uses_snapshot_under_lead(self):
        lead_id = uuid4()
        campaign_lead = SimpleNamespace(
            id=uuid4(),
            campaign_id=uuid4(),
            lead_id=lead_id,
            created_at=datetime.now(timezone.utc),
            lead=None,
            business_name="Deleted Co",
            email="gone@example.test",
            industry="Retail",
            address="2 Oak St",
            contact_number=None,
            website=None,
            lead_score=12,
            services=None,
            website_summary=None,
            business_description=None,
        )

        payload = CampaignLeadResponse.from_orm_with_snapshot(campaign_lead).model_dump()

        assert payload["lead"]["id"] == lead_id
        assert payload["lead"]["business_name"] == "Deleted Co"
        assert payload["lead"]["email"] == "gone@example.test"
        assert "business_name" not in payload
        assert payload["is_user_added"] is False
