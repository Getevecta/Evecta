"""Shared campaign status guards.

Pre-launch mutations (edit, generate, review, lead sync, save, launch, delete)
must all go through ``ensure_campaign_editable`` so the "campaign must be DRAFT"
rule lives in one place. To allow another status later (e.g. paused), update
``EDITABLE_STATUSES`` here rather than hunting through services.
"""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign, CampaignStatus

DraftAction = Literal[
    "edit",
    "generate",
    "review",
    "modify_leads",
    "save",
    "launch",
    "delete",
    "modify",
]

EDITABLE_STATUSES = frozenset({CampaignStatus.DRAFT})

_DRAFT_REQUIRED_DETAIL: dict[str, str] = {
    "edit": "Cannot edit draft after campaign launch.",
    "generate": "Cannot generate emails after campaign launch.",
    "review": "Cannot review emails after campaign launch.",
    "modify_leads": "Cannot modify leads after campaign launch.",
    "save": "Only draft campaigns can be saved.",
    "launch": "Only draft campaigns can be launched.",
    "delete": "Only draft campaigns can be deleted.",
    "modify": "Campaign cannot be modified after launch.",
}


def is_campaign_editable(campaign: Campaign) -> bool:
    """True while the campaign may still be edited, generated, reviewed, or launched."""
    return campaign.status in EDITABLE_STATUSES


def ensure_campaign_editable(campaign: Campaign, *, action: DraftAction) -> None:
    """Raise 400 unless the campaign is still in an editable (currently DRAFT) status."""
    if is_campaign_editable(campaign):
        return
    raise HTTPException(
        status_code=400,
        detail=_DRAFT_REQUIRED_DETAIL.get(action, _DRAFT_REQUIRED_DETAIL["modify"]),
    )


async def get_owned_campaign_or_404(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or str(campaign.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail="Campaign not found or unauthorized.")
    return campaign


async def get_editable_campaign_or_404(
    campaign_id: str,
    user_id: str,
    db: AsyncSession,
    *,
    action: DraftAction,
) -> Campaign:
    campaign = await get_owned_campaign_or_404(campaign_id, user_id, db)
    ensure_campaign_editable(campaign, action=action)
    return campaign
