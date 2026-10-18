"""Admin-only credit top-up (no Stripe). Adds to topup_balance + credit_transactions."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.plans import POOLS, POOL_LABELS
from app.database.session import get_session
from app.dependencies.auth import require_role
from app.models.credit import CreditTransaction
from app.models.user import User
from app.services.credit_service import add_topup_credits, get_balances, get_or_create_pools

router = APIRouter(prefix="/billing/admin", tags=["Billing Admin"])

# Hard cap per pool per request — prevents accidental huge grants.
_MAX_PER_POOL = 500_000
_ADMIN_TOPUP_PREFIX = "Admin top-up:"


class AdminTopupRequest(BaseModel):
    user_id: UUID
    lead: int = Field(0, ge=0, le=_MAX_PER_POOL)
    email_gen: int = Field(0, ge=0, le=_MAX_PER_POOL)
    outreach: int = Field(0, ge=0, le=_MAX_PER_POOL)
    reason: Optional[str] = Field(None, max_length=500)


class AdminTopupPoolGrant(BaseModel):
    pool: str
    amount: int
    balance_after: int


class AdminTopupResponse(BaseModel):
    user_id: UUID
    email: Optional[str] = None
    grants: list[AdminTopupPoolGrant]
    balances: dict[str, int]


class AdminUserBalanceResponse(BaseModel):
    user_id: UUID
    email: Optional[str] = None
    username: Optional[str] = None
    balances: dict[str, int]
    topup_balances: dict[str, int]
    subscription_balances: dict[str, int]


class AdminTopupHistoryItem(BaseModel):
    id: UUID
    user_id: UUID
    email: Optional[str] = None
    username: Optional[str] = None
    pool: str
    amount: int
    action: str
    description: Optional[str] = None
    created_at: datetime


def _amounts_by_pool(body: AdminTopupRequest) -> dict[str, int]:
    return {
        "lead": int(body.lead or 0),
        "email_gen": int(body.email_gen or 0),
        "outreach": int(body.outreach or 0),
    }


@router.post(
    "/topup",
    response_model=AdminTopupResponse,
    status_code=status.HTTP_200_OK,
)
async def admin_topup_credits(
    body: AdminTopupRequest,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_role("admin")),
):
    """
    Grant top-up credits to any user (or the admin themselves) without Stripe.

    Uses the same path as paid top-ups: increments topup_balance and writes
    credit_transactions rows with action=\"topup\". Admin-only.
    """
    amounts = _amounts_by_pool(body)
    if sum(amounts.values()) <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one pool amount must be greater than 0.",
        )

    result = await session.execute(select(User).where(User.id == body.user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    reason = (body.reason or "").strip()
    admin_label = admin.email or admin.username or str(admin.id)
    grants: list[AdminTopupPoolGrant] = []

    for pool in POOLS:
        amount = amounts[pool]
        if amount <= 0:
            continue
        label = POOL_LABELS.get(pool, pool)
        description = f"{_ADMIN_TOPUP_PREFIX} {amount} {label} credits by {admin_label}"
        if reason:
            description = f"{description} — {reason}"
        # credit_transactions.description is String(255)
        if len(description) > 255:
            description = description[:252] + "…"
        balance_after = await add_topup_credits(
            session,
            target.id,
            amount,
            description=description,
            pool=pool,
            commit=False,
        )
        grants.append(
            AdminTopupPoolGrant(pool=pool, amount=amount, balance_after=balance_after)
        )

    await session.commit()
    balances = await get_balances(session, target.id)
    return AdminTopupResponse(
        user_id=target.id,
        email=target.email,
        grants=grants,
        balances=balances,
    )


@router.get(
    "/users/{user_id}/balance",
    response_model=AdminUserBalanceResponse,
)
async def admin_user_credit_balance(
    user_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    result = await session.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    pools = await get_or_create_pools(session, target.id)
    balances = await get_balances(session, target.id)
    return AdminUserBalanceResponse(
        user_id=target.id,
        email=target.email,
        username=target.username,
        balances=balances,
        topup_balances={p: int(pools[p].topup_balance or 0) for p in POOLS},
        subscription_balances={p: int(pools[p].subscription_balance or 0) for p in POOLS},
    )


@router.get(
    "/topup/history",
    response_model=list[AdminTopupHistoryItem],
)
async def admin_topup_history(
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin")),
):
    """Recent admin top-ups (credit_transactions with Admin top-up: description)."""
    stmt = (
        select(CreditTransaction, User)
        .outerjoin(User, User.id == CreditTransaction.user_id)
        .where(
            CreditTransaction.action == "topup",
            CreditTransaction.amount > 0,
            CreditTransaction.description.isnot(None),
            CreditTransaction.description.startswith(_ADMIN_TOPUP_PREFIX),
        )
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        AdminTopupHistoryItem(
            id=tx.id,
            user_id=tx.user_id,
            email=user.email if user else None,
            username=user.username if user else None,
            pool=tx.pool or "",
            amount=int(tx.amount or 0),
            action=tx.action,
            description=tx.description,
            created_at=tx.created_at,
        )
        for tx, user in rows
    ]
