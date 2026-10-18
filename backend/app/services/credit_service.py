import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from fastapi import HTTPException, status
from app.models.credit import UserCreditPool, CreditTransaction
from app.models.user import User
from app.models.subscription_initial_credit_grant import SubscriptionInitialCreditGrant
from app.core.plans import (
    ACTION_POOLS,
    CREDIT_COSTS,
    DEFAULT_PLAN,
    DEFAULT_POOL,
    PLANS,
    POOLS,
    POOL_LABELS,
    subscription_credit_amounts,
)

logger = logging.getLogger(__name__)

# Positive credit lines that are only the default free signup — not Stripe/paid inflow.
_FREE_SIGNUP_BONUS_DESCRIPTIONS = frozenset(
    {
        "Free plan signup bonus",
        "Free plan signup bonus (Google)",
        # One-time grant from the 93ea89485be5 pool-split migration — not paid inflow.
        "Credit pools launch grant",
    }
)


def normalize_pool(pool: str | None) -> str:
    """Coerce untrusted pool names (Stripe metadata, legacy rows) to a valid pool."""
    p = (pool or "").strip().lower()
    return p if p in POOLS else DEFAULT_POOL


def _insufficient_credits_detail(pool: str, required: int, available: int) -> dict:
    label = POOL_LABELS.get(pool, pool)
    return {
        "error": "insufficient_credits",
        "pool": pool,
        "pool_label": label,
        "message": (
            f"Not enough {label} credits. This action costs {required} "
            f"{label} credits, you have {available}."
        ),
        "required": required,
        "available": available,
        "shortfall": required - available,
    }


async def require_pool_credits(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    quantity: int = 1,
) -> None:
    """
    Affordability gate before starting batch work (e.g. per-lead email generation):
    raises HTTP 402 if the action's pool can't cover quantity × cost. Check only —
    nothing is reserved; the spend at success time still decides the actual charge.
    """
    cost_per_unit = CREDIT_COSTS.get(action)
    if cost_per_unit is None:
        raise ValueError(f"Unknown credit action: '{action}'")
    pool = ACTION_POOLS.get(action)
    required = cost_per_unit * max(quantity, 0)
    if required <= 0 or pool is None:
        return
    balance = await get_pool_balance(db, user_id, pool)
    if balance < required:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=_insufficient_credits_detail(pool, required, balance),
        )


def _pool_total(pool_row: UserCreditPool) -> int:
    return (pool_row.subscription_balance or 0) + (pool_row.topup_balance or 0)


async def get_or_create_pool(
    db: AsyncSession, user_id: uuid.UUID, pool: str, for_update: bool = False
) -> UserCreditPool:
    if pool not in POOLS:
        raise ValueError(f"Unknown credit pool: '{pool}'")
    stmt = select(UserCreditPool).where(
        UserCreditPool.user_id == user_id, UserCreditPool.pool == pool
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if not row:
        row = UserCreditPool(user_id=user_id, pool=pool, subscription_balance=0, topup_balance=0)
        db.add(row)
        await db.flush()
    return row


async def get_or_create_pools(
    db: AsyncSession, user_id: uuid.UUID, for_update: bool = False
) -> dict[str, UserCreditPool]:
    """All pool rows for a user, created on first touch.

    Write paths lock one pool at a time in fixed POOLS order. Read paths load
    every pool in a single query so balance + denominator share the same rows.
    """
    if for_update:
        return {pool: await get_or_create_pool(db, user_id, pool, for_update=True) for pool in POOLS}

    rows = (
        await db.scalars(select(UserCreditPool).where(UserCreditPool.user_id == user_id))
    ).all()
    by_pool = {row.pool: row for row in rows if row.pool in POOLS}
    created = False
    for pool in POOLS:
        if pool in by_pool:
            continue
        row = UserCreditPool(user_id=user_id, pool=pool, subscription_balance=0, topup_balance=0)
        db.add(row)
        by_pool[pool] = row
        created = True
    if created:
        await db.flush()
    return {pool: by_pool[pool] for pool in POOLS}


async def _free_user_has_paid_credit_inflow(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """True if user received credits from Stripe/top-up/admin (anything other than free signup bonus)."""
    paid_rows = await db.scalar(
        select(func.count())
        .select_from(CreditTransaction)
        .where(
            CreditTransaction.user_id == user_id,
            CreditTransaction.amount > 0,
            CreditTransaction.action != "refund",  # refunds reverse spends — not new inflow
            or_(
                CreditTransaction.description.is_(None),
                ~CreditTransaction.description.in_(_FREE_SIGNUP_BONUS_DESCRIPTIONS),
            ),
        )
    )
    return (paid_rows or 0) > 0


def _trim_pool_to_cap(db: AsyncSession, user_id: uuid.UUID, row: UserCreditPool, cap: int) -> bool:
    """
    Reduce a pool row's balance to cap (subscription bucket first). True if changed.
    Writes a ledger row so the transaction history still reconstructs the balance.
    """
    total = _pool_total(row)
    if total <= cap:
        return False
    excess = total - cap
    take_sub = min(row.subscription_balance or 0, excess)
    row.subscription_balance = (row.subscription_balance or 0) - take_sub
    row.topup_balance = max((row.topup_balance or 0) - (excess - take_sub), 0)
    row.updated_at = datetime.now(timezone.utc)
    db.add(
        CreditTransaction(
            user_id=user_id,
            amount=-excess,
            action="free_plan_cap",
            pool=row.pool,
            description="Free plan cap adjustment",
        )
    )
    return True


async def enforce_free_plan_credit_cap(db: AsyncSession, user_id: uuid.UUID) -> None:
    """
    Free-plan allowance per pool is PLANS['free']['credits'][pool]. Older signups may
    still hold more after policy changes; cap excess balance so chat and billing match.
    Skips when the user has any paid credit history (top-up, subscription, etc.).

    Commits the session — only call from read paths (balance endpoints) where the
    session holds no unrelated pending work. Spend paths apply the cap inline inside
    their own transaction (see spend_credits).
    """
    plan = await db.scalar(select(User.plan).where(User.id == user_id))
    if (plan or "").strip().lower() != "free":
        return
    caps = PLANS["free"]["credits"]
    pools = await get_or_create_pools(db, user_id)
    over_cap = [p for p in POOLS if _pool_total(pools[p]) > caps.get(p, 0)]
    if not over_cap:
        await db.commit()
        return
    if await _free_user_has_paid_credit_inflow(db, user_id):
        await db.commit()
        return
    for pool in over_cap:
        row = await get_or_create_pool(db, user_id, pool, for_update=True)
        prev = _pool_total(row)
        if _trim_pool_to_cap(db, user_id, row, caps.get(pool, 0)):
            logger.info(
                "[CREDITS] Capped free-plan %s balance for user=%s from %s to %s",
                pool,
                user_id,
                prev,
                _pool_total(row),
            )
    await db.commit()


async def try_grant_initial_subscription_credits(
    db: AsyncSession,
    user_id: uuid.UUID,
    plan: str,
    stripe_subscription_id: str,
    credits_by_pool: dict[str, int],
) -> bool:
    """
    Atomically record that initial credits were granted for this Stripe subscription.
    Returns True if this invocation added credits; False if already granted for sub_id.
    """
    if (
        plan not in PLANS
        or plan == DEFAULT_PLAN
        or not stripe_subscription_id
        or sum(credits_by_pool.values()) <= 0
    ):
        return False

    stmt = (
        pg_insert(SubscriptionInitialCreditGrant)
        .values(stripe_subscription_id=stripe_subscription_id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=["stripe_subscription_id"])
        .returning(SubscriptionInitialCreditGrant.stripe_subscription_id)
    )
    res = await db.execute(stmt)
    inserted_id = res.scalar_one_or_none()
    if inserted_id is None:
        return False

    await grant_plan_credits(
        db,
        user_id,
        credits_by_pool,
        f"Upgraded to {plan} plan",
        commit=True,
    )
    logger.info(
        "[CREDITS] Initial subscription credits | user=%s | plan=%s | sub=%s | +%s",
        user_id,
        plan,
        stripe_subscription_id,
        credits_by_pool,
    )
    return True


async def repair_missing_subscription_credits(db: AsyncSession, user: User) -> None:
    """
    Paid plan + active Stripe subscription should receive subscription_credit_amounts(...)
    when checkout completes. If that grant never landed, backfill once (idempotent per sub_id).
    """
    plan = (user.plan or "").strip().lower()
    if plan not in PLANS or plan == DEFAULT_PLAN:
        return
    sub_id = user.stripe_subscription_id
    if not sub_id:
        return

    has_grant = await db.scalar(
        select(func.count())
        .select_from(SubscriptionInitialCreditGrant)
        .where(SubscriptionInitialCreditGrant.stripe_subscription_id == sub_id)
    )
    if (has_grant or 0) > 0:
        return

    interval = (getattr(user, "plan_billing_interval", None) or "month").strip().lower()
    if interval not in ("month", "year"):
        interval = "month"
    expected = subscription_credit_amounts(plan, interval)

    await enforce_free_plan_credit_cap(db, user.id)
    balances = await get_balances(db, user.id)
    if all(balances.get(pool, 0) >= expected.get(pool, 0) for pool in POOLS):
        return

    granted = await try_grant_initial_subscription_credits(
        db, user.id, plan, sub_id, expected
    )
    if granted:
        logger.info(
            "[CREDITS] Backfilled missing subscription credits | user=%s | plan=%s | +%s",
            user.id,
            plan,
            expected,
        )


async def repair_missing_free_signup_grant(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """
    Self-heal for signups whose free-plan grant failed: a free user with every pool
    at zero AND a completely empty ledger never received the signup bonus — grant it
    once. Pool-row locks make concurrent callers serialize; the second re-checks and
    finds the grant's ledger rows, so no double grant.
    """
    plan = await db.scalar(select(User.plan).where(User.id == user_id))
    if (plan or "").strip().lower() != "free":
        return False
    pools = await get_or_create_pools(db, user_id, for_update=True)
    if any(_pool_total(row) > 0 for row in pools.values()):
        await db.commit()
        return False
    ledger_rows = await db.scalar(
        select(func.count())
        .select_from(CreditTransaction)
        .where(CreditTransaction.user_id == user_id)
    )
    if (ledger_rows or 0) > 0:
        await db.commit()
        return False
    await grant_plan_credits(
        db, user_id, PLANS[DEFAULT_PLAN]["credits"], "Free plan signup bonus", commit=True
    )
    logger.warning("[CREDITS] Backfilled missing free signup grant | user=%s", user_id)
    return True


async def get_pool_snapshot(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[dict[str, UserCreditPool], dict[str, int]]:
    """Pool rows and combined balances after cap/self-heal — one read of all pools."""
    await enforce_free_plan_credit_cap(db, user_id)
    pools = await get_or_create_pools(db, user_id)
    balances = {pool: _pool_total(pools[pool]) for pool in POOLS}
    if all(balance == 0 for balance in balances.values()):
        # All-zero + empty ledger = the signup grant never landed; heal it here so
        # the affected user recovers on their next balance read.
        if await repair_missing_free_signup_grant(db, user_id):
            pools = await get_or_create_pools(db, user_id)
            balances = {pool: _pool_total(pools[pool]) for pool in POOLS}
    return pools, balances


async def get_balances(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """Per-pool spendable balances (subscription + top-up buckets combined)."""
    _, balances = await get_pool_snapshot(db, user_id)
    return balances


async def get_pool_balance(db: AsyncSession, user_id: uuid.UUID, pool: str) -> int:
    balances = await get_balances(db, user_id)
    return balances.get(pool, 0)


def get_credit_display_denominator(
    pool: str,
    plan_key: str | None,
    plan_billing_interval: str | None,
    balance: int,
    topup_balance: int,
) -> int:
    """
    Pool size for UI labels like \"939/1000 remaining\" (per pool).

    Uses the current plan's period allowance plus any unused top-up credits in that
    pool. Do NOT use lifetime grant sums — plan switches leave historical grant
    rows that inflate the bar into nonsense (e.g. 1150/2670 after a growth reset).
    """
    pk = (plan_key or "free").strip().lower()
    if pk == "free" or pk not in PLANS:
        credits_period = PLANS["free"]["credits"].get(pool, 0)
    else:
        interval = (plan_billing_interval or "month").strip().lower()
        if interval not in ("month", "year"):
            interval = "month"
        credits_period = subscription_credit_amounts(pk, interval).get(pool, 0)

    topup = int(topup_balance or 0)
    # Capacity = this period's subscription allowance + leftover top-ups.
    # If balance somehow exceeds that (edge grants), expand so labels never
    # show remaining > total.
    return max(int(credits_period or 0) + topup, int(balance or 0), 1)


def topup_checkout_description(checkout_session_id: str, credits: int, pool: str) -> str:
    """Stable, unique per (Stripe Checkout session, pool) — used for idempotent top-up grants (webhook + confirm)."""
    return f"Top-up purchase: {credits} {pool} credits [session:{checkout_session_id}]"


async def grant_topup_credits_if_new(
    db: AsyncSession,
    user_id: uuid.UUID,
    checkout_session_id: str,
    credits_by_pool: dict[str, int],
) -> bool:
    """
    Idempotent grant for a one-time credit top-up (Stripe Checkout payment mode). A single
    checkout can carry amounts for several pools; each pool is granted at most once.
    Same session_id from webhook and confirm-checkout-session dedupes double credit.
    SELECT FOR UPDATE on the pool rows serializes concurrent calls so the
    dedupe check + insert are atomic — no TOCTOU double-credit possible.
    Dedupe matches on the \"[session:…]\" marker (not the whole description) so rows
    written before the pool split still block re-grants for their pool.
    """
    if not checkout_session_id:
        return False
    wanted = {p: int(credits_by_pool.get(p, 0) or 0) for p in POOLS}
    wanted = {p: c for p, c in wanted.items() if c > 0}
    if not wanted:
        return False
    # Acquire row locks first (fixed POOLS order) — concurrent webhook + confirm serialize here
    for pool in POOLS:
        if pool in wanted:
            await get_or_create_pool(db, user_id, pool, for_update=True)
    session_marker = f"%[session:{checkout_session_id}]%"
    granted_any = False
    for pool in POOLS:
        credits = wanted.get(pool, 0)
        if credits <= 0:
            continue
        exists = await db.scalar(
            select(func.count())
            .select_from(CreditTransaction)
            .where(
                CreditTransaction.user_id == user_id,
                CreditTransaction.description.like(session_marker),
                or_(
                    CreditTransaction.pool == pool,
                    CreditTransaction.pool.is_(None),  # pre-pool legacy rows were lead-only grants
                ),
            )
        )
        if (exists or 0) > 0:
            continue
        await add_topup_credits(
            db,
            user_id,
            credits,
            topup_checkout_description(checkout_session_id, credits, pool),
            pool=pool,
            commit=False,
        )
        granted_any = True
    await db.commit()
    return granted_any


async def apply_subscription_renewal(
    db: AsyncSession,
    user_id: uuid.UUID,
    amounts_by_pool: dict[str, int],
    description: str,
    *,
    commit: bool = True,
) -> dict[str, int]:
    """
    Sets each pool's subscription-bucket credits to the new period allowance.

    Unused subscription credits from the prior month (or prior year for annual billing)
    do not roll forward. Top-up balances are never modified here.
    """
    pools = await get_or_create_pools(db, user_id, for_update=True)
    for pool in POOLS:
        new_amount = max(int(amounts_by_pool.get(pool, 0) or 0), 0)
        row = pools[pool]
        prev = row.subscription_balance or 0
        net = new_amount - prev
        row.subscription_balance = new_amount
        row.updated_at = datetime.now(timezone.utc)
        if net != 0:
            db.add(
                CreditTransaction(
                    user_id=user_id,
                    amount=net,
                    action="subscription_grant",
                    pool=pool,
                    description=description,
                )
            )
    if commit:
        await db.commit()
    else:
        await db.flush()
    return {pool: _pool_total(pools[pool]) for pool in POOLS}


async def add_subscription_credits(
    db: AsyncSession,
    user_id: uuid.UUID,
    amount: int,
    description: str = "Subscription credits",
    *,
    pool: str,
    commit: bool = True,
) -> int:
    """Add credits to one pool's subscription bucket (signup, upgrades, proration — not one-time top-ups)."""
    row = await get_or_create_pool(db, user_id, pool, for_update=True)
    row.subscription_balance = (row.subscription_balance or 0) + amount
    row.updated_at = datetime.now(timezone.utc)
    db.add(
        CreditTransaction(
            user_id=user_id,
            amount=amount,
            action="subscription_grant",
            pool=pool,
            description=description,
        )
    )
    if commit:
        await db.commit()
        await db.refresh(row)
    else:
        await db.flush()
    return _pool_total(row)


async def grant_plan_credits(
    db: AsyncSession,
    user_id: uuid.UUID,
    amounts_by_pool: dict[str, int],
    description: str,
    *,
    commit: bool = True,
) -> None:
    """Add plan credits to every pool's subscription bucket (signup bonus, plan upgrades)."""
    for pool in POOLS:
        amount = int(amounts_by_pool.get(pool, 0) or 0)
        if amount <= 0:
            continue
        await add_subscription_credits(
            db, user_id, amount, description, pool=pool, commit=False
        )
    if commit:
        await db.commit()
    else:
        await db.flush()


async def add_topup_credits(
    db: AsyncSession,
    user_id: uuid.UUID,
    amount: int,
    description: str = "Credit top-up",
    *,
    pool: str,
    commit: bool = True,
) -> int:
    """Add purchased top-up credits to one pool (usable anytime; never cleared on subscription renewal)."""
    row = await get_or_create_pool(db, user_id, pool, for_update=True)
    row.topup_balance = (row.topup_balance or 0) + amount
    row.updated_at = datetime.now(timezone.utc)
    db.add(
        CreditTransaction(
            user_id=user_id,
            amount=amount,
            action="topup",
            pool=pool,
            description=description,
        )
    )
    if commit:
        await db.commit()
        await db.refresh(row)
    else:
        await db.flush()
    return _pool_total(row)


async def spend_credits(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    quantity: int = 1,
    description: str = "",
) -> int:
    """
    Deduct credits for an action from the action's pool (ACTION_POOLS). Within the
    pool, subscription-bucket credits are used first, then top-ups.

    Atomic: the free-plan cap trim, balance check, deduction and ledger row share one
    transaction and one row lock — nothing is committed until the spend succeeds.
    Raises HTTP 402 (committing nothing) if the pool's balance is insufficient —
    other pools cannot cover it. Callers' uncommitted session work survives on
    success (committed together) and is rolled back with the 402 by get_session.
    Returns the pool's remaining balance after deduction.
    """
    cost_per_unit = CREDIT_COSTS.get(action)
    if cost_per_unit is None:
        raise ValueError(f"Unknown credit action: '{action}'")
    pool = ACTION_POOLS.get(action)
    if pool is None:
        raise ValueError(f"No credit pool mapped for action: '{action}'")

    if cost_per_unit == 0:
        # Nothing to charge — report the pool total without locking or committing
        # (callers may hold unrelated uncommitted work in this session).
        row = await get_or_create_pool(db, user_id, pool)
        return _pool_total(row)

    total_cost = cost_per_unit * quantity
    row = await get_or_create_pool(db, user_id, pool, for_update=True)

    # Free-plan cap applied to the locked row inside THIS transaction, so a stale
    # over-cap balance is never spendable and the trim commits with the spend.
    plan = await db.scalar(select(User.plan).where(User.id == user_id))
    if (plan or "").strip().lower() == "free":
        cap = PLANS["free"]["credits"].get(pool, 0)
        if _pool_total(row) > cap and not await _free_user_has_paid_credit_inflow(db, user_id):
            prev = _pool_total(row)
            _trim_pool_to_cap(db, user_id, row, cap)
            logger.info(
                "[CREDITS] Capped free-plan %s balance for user=%s from %s to %s (on spend)",
                pool,
                user_id,
                prev,
                _pool_total(row),
            )

    total = _pool_total(row)

    if total < total_cost:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=_insufficient_credits_detail(pool, total_cost, total),
        )

    take_sub = min(row.subscription_balance or 0, total_cost)
    row.subscription_balance = (row.subscription_balance or 0) - take_sub
    remainder = total_cost - take_sub
    row.topup_balance = (row.topup_balance or 0) - remainder
    row.updated_at = datetime.now(timezone.utc)
    db.add(
        CreditTransaction(
            user_id=user_id,
            amount=-total_cost,
            action=action,
            pool=pool,
            description=description or f"{action} × {quantity}",
        )
    )
    await db.commit()
    await db.refresh(row)
    return _pool_total(row)


async def refund_credits(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    quantity: int = 1,
    description: str = "",
) -> None:
    """
    Reverse a spend after the paid-for work failed (e.g. the AI call errored after
    the charge). Refunds into the pool's subscription bucket — the bucket spending
    drains first, so the net effect matches the original charge.

    Never raises: a failed refund is logged loudly instead of masking the original
    error the caller is about to re-raise.
    """
    try:
        cost_per_unit = CREDIT_COSTS.get(action) or 0
        pool = ACTION_POOLS.get(action)
        if cost_per_unit <= 0 or pool is None or quantity <= 0:
            return
        total = cost_per_unit * quantity
        row = await get_or_create_pool(db, user_id, pool, for_update=True)
        row.subscription_balance = (row.subscription_balance or 0) + total
        row.updated_at = datetime.now(timezone.utc)
        db.add(
            CreditTransaction(
                user_id=user_id,
                amount=total,
                action="refund",
                pool=pool,
                description=description or f"Refund: {action} × {quantity}",
            )
        )
        await db.commit()
        logger.info(
            "[CREDITS] Refunded %s %s credits | user=%s | action=%s",
            total,
            pool,
            user_id,
            action,
        )
    except Exception:
        logger.exception(
            "[CREDITS] REFUND FAILED — user may be owed credits | user=%s | action=%s | qty=%s",
            user_id,
            action,
            quantity,
        )


async def get_transaction_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 50,
) -> list[CreditTransaction]:
    result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user_id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()
