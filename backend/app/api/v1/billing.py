import asyncio
import logging
import uuid
import stripe
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from pydantic import BaseModel, Field
from typing import Optional

from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.webhook_event import ProcessedWebhookEvent
from app.services.credit_service import (
    get_balances,
    get_pool_snapshot,
    get_transaction_history,
    grant_plan_credits,
    apply_subscription_renewal,
    try_grant_initial_subscription_credits,
    grant_topup_credits_if_new,
    get_credit_display_denominator,
    normalize_pool,
)
from app.services.otp_service import send_payment_failed_email
from app.services.contact_form_service import (
    send_cancellation_feedback_email,
    send_stripe_portal_cancellation_survey_email,
)
from app.core.plans import (
    ACTION_POOLS,
    CREDIT_COSTS,
    PLANS,
    POOLS,
    POOL_LABELS,
    TOPUP_MIN_CHARGE_USD,
    TOPUP_MIN_CREDITS,
    TOPUP_STEP,
    subscription_credit_amounts,
    topup_caps,
    topup_usd_per_credit,
)
from app.core.config import get_settings

router = APIRouter(prefix="/billing", tags=["Billing"])


def _get_stripe():
    """Return stripe with API key set. Called per-request, not at module load."""
    settings = get_settings()
    key = (settings.STRIPE_SECRET_KEY or "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Stripe is not configured on the server. Set APP_STRIPE_SECRET_KEY in the backend "
                ".env (Dashboard → Developers → API keys → Secret key, sk_test_… or sk_live_…)."
            ),
        )
    stripe.api_key = key
    return stripe


def _annual_price_to_plan(settings) -> dict:
    m = {}
    if settings.STRIPE_STARTER_ANNUAL_PRICE:
        m[settings.STRIPE_STARTER_ANNUAL_PRICE] = "starter"
    if settings.STRIPE_GROWTH_ANNUAL_PRICE:
        m[settings.STRIPE_GROWTH_ANNUAL_PRICE] = "growth"
    if settings.STRIPE_SCALE_ANNUAL_PRICE:
        m[settings.STRIPE_SCALE_ANNUAL_PRICE] = "scale"
    return m


def get_price_map(settings):
    """Stripe price_id -> plan key (monthly and annual catalog)."""
    m = {
        settings.STRIPE_STARTER_PRICE: "starter",
        settings.STRIPE_SCALE_PRICE:   "scale",
    }
    if settings.STRIPE_GROWTH_PRICE:
        m[settings.STRIPE_GROWTH_PRICE] = "growth"
    m.update(_annual_price_to_plan(settings))
    return m


def _billing_interval_from_price_id(price_id: str | None, settings) -> str:
    if not price_id:
        return "month"
    annual = _annual_price_to_plan(settings)
    if price_id in annual:
        return "year"
    return "month"


def _billing_interval_from_subscription(sub) -> str:
    if sub is None:
        return "month"
    try:
        items = sub.get("items") if isinstance(sub, dict) else getattr(sub, "items", None)
        if items is None:
            return "month"
        data = (
            items.get("data", [])
            if isinstance(items, dict)
            else (getattr(items, "data", None) or [])
        )
        if not data:
            return "month"
        first = data[0]
        price = first.get("price") if isinstance(first, dict) else getattr(first, "price", None)
        if price is None:
            return "month"
        rec = price.get("recurring") if isinstance(price, dict) else getattr(price, "recurring", None)
        if not rec:
            pid = price.get("id") if isinstance(price, dict) else getattr(price, "id", None)
            settings = get_settings()
            return _billing_interval_from_price_id(pid, settings)
        interval = rec.get("interval") if isinstance(rec, dict) else getattr(rec, "interval", None)
        if interval in ("month", "year"):
            return interval
    except Exception:
        pass
    return "month"


def get_price_id(plan: str, settings, billing_interval: str = "month") -> str:
    interval = (billing_interval or "month").strip().lower()
    if interval == "year":
        mapping = {
            "starter": settings.STRIPE_STARTER_ANNUAL_PRICE,
            "growth":  settings.STRIPE_GROWTH_ANNUAL_PRICE,
            "scale":   settings.STRIPE_SCALE_ANNUAL_PRICE,
        }
        price_id = mapping.get(plan)
        if not price_id:
            raise HTTPException(
                status_code=400,
                detail=f"Annual billing is not configured for plan '{plan}'. Set APP_STRIPE_*_ANNUAL_PRICE.",
            )
        return price_id
    mapping = {
        "starter": settings.STRIPE_STARTER_PRICE,
        "growth":  settings.STRIPE_GROWTH_PRICE,
        "scale":   settings.STRIPE_SCALE_PRICE,
    }
    price_id = mapping.get(plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Plan '{plan}' is not available.")
    return price_id


PLAN_RANK = {"free": 0, "starter": 1, "growth": 2, "scale": 3}


def _topup_credits_from_metadata(meta: dict) -> dict[str, int]:
    """
    Per-pool credit amounts from Stripe Checkout metadata (credits_lead,
    credits_email_gen, credits_outreach). Sessions created before the pool split
    only carry a single "credits" value — treat it as the lead pool (or the pool
    named in legacy "pool" metadata, when present).
    """
    out: dict[str, int] = {}
    for pool in POOLS:
        try:
            out[pool] = max(int(meta.get(f"credits_{pool}", 0) or 0), 0)
        except (TypeError, ValueError):
            out[pool] = 0
    if sum(out.values()) == 0:
        try:
            legacy = max(int(meta.get("credits", 0) or 0), 0)
        except (TypeError, ValueError):
            legacy = 0
        if legacy > 0:
            out[normalize_pool(meta.get("pool"))] = legacy
    return out


# ── Request schemas ────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str  # "starter" | "growth" | "scale"
    billing_interval: str = "month"  # "month" | "year" (year needs APP_STRIPE_*_ANNUAL_PRICE)


class TopupRequest(BaseModel):
    """Per-pool credit amounts for a single top-up checkout. 0 = don't buy that pool."""
    lead: int = 0
    email_gen: int = 0
    outreach: int = 0

    def by_pool(self) -> dict[str, int]:
        return {"lead": self.lead, "email_gen": self.email_gen, "outreach": self.outreach}



class ConfirmCheckoutSessionRequest(BaseModel):
    session_id: str


CANCELLATION_FEEDBACK_REASONS = frozenset(
    {
        "It's too expensive",
        "I no longer need it",
        "Quality was less than expected",
        "I need more features",
        "I found an alternative",
        "Other reason",
    }
)


class CancellationFeedbackRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200)
    details: Optional[str] = Field(None, max_length=5000)


# ── Balance & history ──────────────────────────────────────────────────────────

@router.get("/credits/balance")
async def credit_balance(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Per-pool credit balances + cost reference."""
    try:
        pools_rows, balances = await get_pool_snapshot(db, user.id)
        interval = getattr(user, "plan_billing_interval", None)
        pools = {}
        for pool in POOLS:
            denom = get_credit_display_denominator(
                pool,
                user.plan,
                interval,
                balances[pool],
                int(pools_rows[pool].topup_balance or 0),
            )
            pools[pool] = {
                "balance": balances[pool],
                "display_denominator": denom,
                "label": POOL_LABELS[pool],
            }
        return {
            "pools": pools,
            "plan": user.plan,
            "costs": CREDIT_COSTS,
            "action_pools": ACTION_POOLS,
        }
    except Exception:
        logger.exception("[BILLING] Failed to fetch balance for user=%s", user.id)
        raise HTTPException(status_code=500, detail="Failed to fetch credit balance.")


@router.get("/credits/history")
async def credit_history(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Last 50 credit transactions."""
    try:
        transactions = await get_transaction_history(db, user.id)
        return {
            "transactions": [
                {
                    "id":          str(t.id),
                    "amount":      t.amount,
                    "action":      t.action,
                    "pool":        t.pool,
                    "description": t.description,
                    "created_at":  t.created_at,
                }
                for t in transactions
            ]
        }
    except Exception:
        logger.exception("[BILLING] Failed to fetch credit history for user=%s", user.id)
        raise HTTPException(status_code=500, detail="Failed to fetch credit history.")


# ── Subscription info ──────────────────────────────────────────────────────────

@router.get("/subscription")
async def get_subscription(
    user: User = Depends(get_current_user),
):
    """Current plan and subscription status."""
    try:
        pk = (user.plan or "free").strip().lower()
        if pk == "free" or pk not in PLANS:
            credits_period = dict(PLANS["free"]["credits"])
        else:
            interval = (getattr(user, "plan_billing_interval", None) or "month").strip().lower()
            if interval not in ("month", "year"):
                interval = "month"
            credits_period = subscription_credit_amounts(pk, interval)
        return {
            "plan":                   user.plan,
            "plan_billing_interval":  getattr(user, "plan_billing_interval", None),
            # Per-pool dict: {"lead": n, "email_gen": n, "outreach": n}
            "credits_per_period":     credits_period,
            "stripe_customer_id":     user.stripe_customer_id,
            "stripe_subscription_id": user.stripe_subscription_id,
            "credits":                PLANS.get(user.plan, {}).get("credits"),
            "leads_per_search":       PLANS.get(user.plan, {}).get("leads_per_search"),
            "cancel_at":              getattr(user, "subscription_cancel_at", None),
        }
    except Exception:
        logger.exception("[BILLING] Failed to fetch subscription for user=%s", user.id)
        raise HTTPException(status_code=500, detail="Failed to fetch subscription details.")


# ── Create checkout session ────────────────────────────────────────────────────

@router.post("/create-checkout-session")
async def create_checkout_session(
    body: CheckoutRequest,
    user: User = Depends(get_current_user),
):
    """Create a Stripe Checkout session. Returns the hosted checkout URL."""
    settings = get_settings()
    bi = (body.billing_interval or "month").strip().lower()
    if bi not in ("month", "year"):
        raise HTTPException(status_code=400, detail="billing_interval must be 'month' or 'year'.")
    price_id = get_price_id(body.plan, settings, bi)

    # ── Existing subscription: modify price directly (no new checkout needed) ──
    if user.stripe_subscription_id:
        is_cancelling = getattr(user, "subscription_cancel_at", None) is not None

        # Cancelled + same plan → blocked, must wait until subscription expires
        if is_cancelling and user.plan == body.plan:
            raise HTTPException(
                status_code=400,
                detail=f"Your {user.plan} subscription is cancelled. Please wait until it expires on {user.subscription_cancel_at.strftime('%B %d, %Y')} before subscribing again.",
            )

        # Already on same plan and not cancelling
        if user.plan == body.plan and getattr(user, "plan_billing_interval", "month") == bi:
            raise HTTPException(
                status_code=400,
                detail=f"You are already on the {body.plan} plan.",
            )

        # Downgrades are allowed: full new-plan price today, cycle resets today,
        # and on apply the credit bucket is SET to the new allowance (plan value
        # = credits, not time). Upgrades keep their additive credit behavior.
        is_downgrade = PLAN_RANK.get(body.plan, 0) < PLAN_RANK.get(user.plan, 0)

        customer_id = (user.stripe_customer_id or "").strip()
        if not customer_id:
            raise HTTPException(status_code=400, detail="No Stripe customer on this account.")

        # Redirect user to Stripe Checkout so they see the full price before being charged
        try:
            price_obj = await run_in_threadpool(lambda: _get_stripe().Price.retrieve(price_id))
            amount_cents = price_obj["unit_amount"]

            plan_labels = {"starter": "Starter", "growth": "Growth", "scale": "Scale"}
            plan_label = plan_labels.get(body.plan, body.plan.capitalize())
            interval_label = "year" if bi == "year" else "month"
            action_label = "Switch" if is_downgrade else "Upgrade"
            item_description = f"Full {interval_label}ly price · billing cycle resets today"
            if is_downgrade:
                item_description += f" · plan credits reset to the {plan_label} allowance"

            session = await run_in_threadpool(
                lambda: _get_stripe().checkout.Session.create(
                    mode="payment",
                    payment_method_types=["card"],
                    customer=customer_id,
                    line_items=[{
                        "price_data": {
                            "currency": "usd",
                            "unit_amount": amount_cents,
                            "product_data": {
                                "name": f"{action_label} to {plan_label} plan",
                                "description": item_description,
                            },
                        },
                        "quantity": 1,
                    }],
                    metadata={
                        "user_id": str(user.id),
                        "type": "upgrade",
                        "plan": body.plan,
                        "billing_interval": bi,
                    },
                    success_url=f"{settings.FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
                    cancel_url=f"{settings.FRONTEND_URL}/billing/cancel",
                )
            )
        except stripe.error.StripeError as e:
            raise HTTPException(status_code=400, detail="Something went wrong. Please try again.")
        except Exception:
            logger.exception("[BILLING] Unexpected error creating upgrade checkout | user=%s", user.id)
            raise HTTPException(status_code=500, detail="Failed to start upgrade checkout. Please try again.")

        return {"checkout_url": session.url}

    # ── No subscription: create new checkout session ───────────────────────────
    try:
        session = await run_in_threadpool(
            lambda: _get_stripe().checkout.Session.create(
                mode="subscription",
                payment_method_types=["card"],
                line_items=[{"price": price_id, "quantity": 1}],
                customer_email=user.email,
                metadata={
                    "user_id": str(user.id),
                    "plan": body.plan,
                    "billing_interval": bi,
                },
                subscription_data={
                    "metadata": {
                        "user_id": str(user.id),
                        "plan": body.plan,
                        "billing_interval": bi,
                    },
                },
                success_url=f"{settings.FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{settings.FRONTEND_URL}/billing/cancel",
            )
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail="Something went wrong. Please try again.")

    return {"checkout_url": session.url}



@router.post("/confirm-checkout-session")
async def confirm_checkout_session(
    body: ConfirmCheckoutSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    After Stripe Checkout redirect, sync subscription to our DB when webhooks are delayed
    or unreachable (local dev / ngrok misconfiguration). Idempotent with the webhook.
    """
    settings = get_settings()
    try:
        session = await run_in_threadpool(
            lambda: _get_stripe().checkout.Session.retrieve(
                body.session_id,
                expand=["subscription"],
            )
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail="Something went wrong. Please try again.")

    meta = session.get("metadata") or {}
    if meta.get("user_id") != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This checkout session does not belong to your account.",
        )

    session_mode = session.get("mode")
    pay_status = session.get("payment_status")
    if pay_status not in ("paid", "no_payment_required"):
        raise HTTPException(status_code=400, detail="Checkout is not paid yet.")

    session_id_str = session.get("id") or body.session_id

    # ── Upgrade payment: apply plan switch if webhook hasn't fired yet ────────
    if session_mode == "payment" and meta.get("type") == "upgrade":
        plan = meta.get("plan")
        bi   = meta.get("billing_interval", "month")
        if not plan or plan not in PLANS or plan == "free":
            raise HTTPException(status_code=400, detail="Invalid upgrade session.")

        # Already applied (webhook was faster)
        if user.plan == plan and getattr(user, "plan_billing_interval", "month") == bi:
            return {"status": "ok", "plan": plan, "already_active": True}

        # Webhook hasn't fired yet — apply now so UI updates immediately
        if user.stripe_subscription_id:
            try:
                upg_price_id = get_price_id(plan, settings, bi)
                upg_sub = await run_in_threadpool(
                    lambda: _get_stripe().Subscription.retrieve(user.stripe_subscription_id)
                )
                current_price = upg_sub["items"]["data"][0]["price"]["id"]
                if current_price != upg_price_id:
                    upg_item_id = upg_sub["items"]["data"][0]["id"]
                    await run_in_threadpool(
                        lambda: _get_stripe().Subscription.modify(
                            user.stripe_subscription_id,
                            items=[{"id": upg_item_id, "price": upg_price_id}],
                            proration_behavior="none",
                            billing_cycle_anchor="now",
                            cancel_at_period_end=False,
                            metadata={
                                "user_id": str(user.id),
                                "plan": plan,
                                "billing_interval": bi,
                            },
                        )
                    )
                old_plan = user.plan
                user.plan = plan
                user.plan_billing_interval = bi
                user.subscription_cancel_at = None
                new_credits = subscription_credit_amounts(plan, bi)
                if PLAN_RANK.get(plan, 0) < PLAN_RANK.get(old_plan, 0):
                    # Downgrade: replace each pool's bucket with the new allowance (never additive).
                    await apply_subscription_renewal(
                        db, user.id, new_credits, f"Switched from {old_plan} to {plan} plan"
                    )
                else:
                    await grant_plan_credits(db, user.id, new_credits, f"Upgraded from {old_plan} to {plan}")
                logger.info(
                    "[STRIPE] confirm plan change (webhook delay) | user=%s | %s → %s | credits=%s",
                    user.id, old_plan, plan, new_credits,
                )
            except HTTPException:
                raise
            except stripe.error.StripeError as e:
                raise HTTPException(status_code=400, detail="Something went wrong. Please try again.")
            except Exception:
                logger.exception("[STRIPE] FAILED confirm upgrade | user=%s", user.id)
                raise HTTPException(status_code=500, detail="Failed to apply upgrade. Try again or contact support.")

        return {"status": "ok", "plan": plan}

    # ── Top-up payment: add credits if webhook hasn't fired yet ───────────────
    if session_mode == "payment" and meta.get("type") == "topup":
        credits_by_pool = _topup_credits_from_metadata(meta)
        if sum(credits_by_pool.values()) <= 0:
            raise HTTPException(status_code=400, detail="Invalid top-up checkout session.")
        try:
            granted = await grant_topup_credits_if_new(db, user.id, session_id_str, credits_by_pool)
        except Exception:
            logger.exception("[BILLING] Failed to confirm topup | user=%s | session=%s", user.id, session_id_str)
            raise HTTPException(status_code=500, detail="Failed to add credits. Please contact support.")
        logger.info(
            "[STRIPE] confirm topup | user=%s | granted=%s | +%s | session=%s",
            user.id, granted, credits_by_pool, session_id_str,
        )
        return {
            "status": "ok",
            "credits_added": credits_by_pool if granted else {},
            "already_applied": not granted,
        }

    if session_mode != "subscription":
        raise HTTPException(status_code=400, detail="Not a subscription checkout.")

    plan = meta.get("plan")
    if not plan or plan not in PLANS or plan == "free":
        raise HTTPException(status_code=400, detail="Invalid or missing plan on checkout session.")

    sub_raw = session.get("subscription")
    sub_id = getattr(sub_raw, "id", None) or sub_raw
    if not sub_id:
        raise HTTPException(status_code=400, detail="No subscription on checkout session.")

    cust_raw = session.get("customer")
    customer_id = getattr(cust_raw, "id", None) or cust_raw

    interval = _billing_interval_from_subscription(sub_raw)
    prior_sub = user.stripe_subscription_id
    if prior_sub == sub_id:
        if user.plan != plan:
            user.plan = plan
        user.plan_billing_interval = interval
        await db.commit()
        return {"status": "ok", "plan": user.plan, "already_active": True}

    user.plan = plan
    user.plan_billing_interval = interval
    user.stripe_customer_id = customer_id
    user.stripe_subscription_id = sub_id
    try:
        credits = subscription_credit_amounts(plan, interval)
        granted = await try_grant_initial_subscription_credits(
            db, user.id, plan, sub_id, credits
        )
        if not granted:
            await db.commit()
        logger.info(
            "[STRIPE] confirm-checkout-session | user=%s | plan=%s | interval=%s | granted=%s | amount=%s",
            user.id,
            plan,
            interval,
            granted,
            credits,
        )
    except Exception:
        logger.exception(
            "[STRIPE] FAILED confirm-checkout-session | user=%s | plan=%s",
            user.id,
            plan,
        )
        raise HTTPException(status_code=500, detail="Failed to activate plan. Try again or contact support.")

    return {"status": "ok", "plan": plan}


# ── Top-up options ─────────────────────────────────────────────────────────────

@router.get("/topup/options")
async def topup_options(user: User = Depends(get_current_user)):
    """Return top-up range config for the frontend based on the user's plan."""
    plan = (user.plan or "free").strip().lower()
    caps = topup_caps(plan)

    # Each pool has its own USD rate AND its own per-purchase max — the frontend
    # prices and bounds each slider separately. min/step are shared.
    pools = [
        {
            "pool": p,
            "label": POOL_LABELS[p],
            "price_per_credit": topup_usd_per_credit(plan, p),
            "max": caps[p],
        }
        for p in POOLS
    ]

    if not any(caps.values()):
        return {
            "available": False,
            "reason": "Top-up is not available on the free plan. Upgrade to a paid plan.",
            "min": 0,
            "step": TOPUP_STEP,
            "pools": pools,
        }

    return {
        "available": True,
        "min": TOPUP_MIN_CREDITS,
        "step": TOPUP_STEP,
        "pools": pools,
    }


# ── Create top-up checkout session ────────────────────────────────────────────

@router.post("/topup/create-checkout-session")
async def create_topup_checkout_session(
    body: TopupRequest,
    user: User = Depends(get_current_user),
):
    """Create a one-time Stripe Checkout session for credit top-up."""
    plan = (user.plan or "free").strip().lower()
    caps = topup_caps(plan)

    if not any(caps.values()):
        raise HTTPException(
            status_code=403,
            detail="Top-up is not available on the free plan. Upgrade to a paid plan.",
        )

    requested = {pool: max(int(amount or 0), 0) for pool, amount in body.by_pool().items()}
    total_credits = sum(requested.values())
    if total_credits <= 0:
        raise HTTPException(
            status_code=422,
            detail="Select at least one pool's credit amount to top up.",
        )
    for pool, amount in requested.items():
        if amount == 0:
            continue
        label = POOL_LABELS[pool]
        cap = caps[pool]
        if cap == 0:
            raise HTTPException(
                status_code=422,
                detail=f"{label} credit top-ups are not available on your plan.",
            )
        if amount < TOPUP_MIN_CREDITS or amount > cap:
            raise HTTPException(
                status_code=422,
                detail=f"{label} credits must be between {TOPUP_MIN_CREDITS} and {cap} for your plan.",
            )
        if amount % TOPUP_STEP != 0:
            raise HTTPException(
                status_code=422,
                detail=f"{label} credits must be a multiple of {TOPUP_STEP}.",
            )

    settings = get_settings()
    price_usd_by_pool = {
        pool: round(amount * topup_usd_per_credit(plan, pool), 2)
        for pool, amount in requested.items()
        if amount > 0
    }
    total_usd = round(sum(price_usd_by_pool.values()), 2)
    if total_usd < TOPUP_MIN_CHARGE_USD:
        # Stripe rejects charges below $0.50 (e.g. 100 outreach credits = $0.40).
        raise HTTPException(
            status_code=422,
            detail=(
                f"Minimum top-up purchase is ${TOPUP_MIN_CHARGE_USD:.2f} — "
                f"your selection totals ${total_usd:.2f}. Add more credits."
            ),
        )

    line_items = [
        {
            "price_data": {
                "currency":     "usd",
                "unit_amount":  int(round(amount * topup_usd_per_credit(plan, pool) * 100)),
                "product_data": {
                    "name":        f"{amount} Evecta {POOL_LABELS[pool]} Credits",
                    "description": f"One-time top-up of {amount} {POOL_LABELS[pool].lower()} credits",
                },
            },
            "quantity": 1,
        }
        for pool, amount in requested.items()
        if amount > 0
    ]
    metadata = {"user_id": str(user.id), "type": "topup"}
    metadata.update({f"credits_{pool}": str(amount) for pool, amount in requested.items() if amount > 0})

    try:
        session = await run_in_threadpool(
            lambda: _get_stripe().checkout.Session.create(
                mode="payment",
                payment_method_types=["card"],
                line_items=line_items,
                customer_email=user.email,
                metadata=metadata,
                success_url=f"{settings.FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{settings.FRONTEND_URL}/billing/cancel",
            )
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail="Something went wrong. Please try again.")

    return {
        "checkout_url": session.url,
        "credits":      requested,
        "total_credits": total_credits,
        "price_usd_by_pool": price_usd_by_pool,
        "price_usd":    total_usd,
    }


# ── Cancel subscription ────────────────────────────────────────────────────────

@router.post("/cancel")
async def cancel_subscription(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Cancel the active subscription at period end."""
    if not user.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No active subscription found.")

    try:
        sub = await run_in_threadpool(
            lambda: _get_stripe().Subscription.modify(
                user.stripe_subscription_id,
                cancel_at_period_end=True,
            )
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail="Something went wrong. Please try again.")

    # Save the cancellation date so the frontend can display it
    from datetime import datetime, timezone as tz
    try:
        cancel_ts = (
            getattr(sub, "cancel_at", None)
            or getattr(sub, "current_period_end", None)
            or sub.get("cancel_at")
            or sub.get("current_period_end")
        )
        if cancel_ts:
            user.subscription_cancel_at = datetime.fromtimestamp(int(cancel_ts), tz=tz.utc)
            await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("[BILLING] Failed to save cancel_at for user=%s", user.id)
        # Don't raise — Stripe cancellation already succeeded

    return {
        "message": "Subscription will be cancelled at the end of the billing period.",
        "cancel_at": user.subscription_cancel_at,
    }


@router.post("/create-portal-session")
async def create_billing_portal_session(
    user: User = Depends(get_current_user),
):
    """
    Stripe Customer Portal — payment methods, invoices, cancel subscription at period end, etc.
    Configure the portal in Stripe Dashboard → Settings → Billing → Customer portal.
    """
    settings = get_settings()
    cid = (user.stripe_customer_id or "").strip()
    if not cid:
        raise HTTPException(
            status_code=400,
            detail="No Stripe customer on this account. Complete a subscription checkout in Plan & usage first.",
        )
    try:
        session = await run_in_threadpool(
            lambda: _get_stripe().billing_portal.Session.create(
                customer=cid,
                return_url=(
                    f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/settings/profile"
                    "?tab=account&portal_return=1"
                ),
            )
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail="Something went wrong. Please try again.")

    url = session.get("url") if isinstance(session, dict) else getattr(session, "url", None)
    if not url:
        raise HTTPException(status_code=500, detail="Stripe did not return a portal URL.")
    return {"url": url}


@router.post("/cancellation-feedback")
async def submit_cancellation_feedback(
    body: CancellationFeedbackRequest,
    user: User = Depends(get_current_user),
):
    """After the user cancels (or schedules cancel) in the Stripe portal, optional feedback to inbox."""
    reason = body.reason.strip()
    if reason not in CANCELLATION_FEEDBACK_REASONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid reason. Choose one of: {', '.join(sorted(CANCELLATION_FEEDBACK_REASONS))}",
        )
    name = (user.full_name or user.username or user.email or "User").strip()
    ok = await asyncio.to_thread(
        send_cancellation_feedback_email,
        user.email,
        name,
        reason,
        body.details,
    )
    if not ok:
        inbox = (get_settings().CONTACT_INBOX_EMAIL or "").strip() or "mail@evecta.io"
        raise HTTPException(
            status_code=503,
            detail=f"Could not send feedback right now. Please try again or email {inbox}.",
        )
    return {"status": "ok", "message": "Thanks for your feedback."}


# ── Dev-only test helpers (registered only for explicit local/dev) ─────────────

async def simulate_renewal(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    DEV ONLY — simulates an invoice.paid renewal for the current user.
    Adds full plan credits exactly as the real Stripe webhook would.
    Not registered unless APP_ENVIRONMENT is development/local/dev/test.
    """
    if not get_settings().allows_dev_only_routes:
        raise HTTPException(status_code=403, detail="Not available in production.")

    plan = (user.plan or "free").strip().lower()
    if plan == "free":
        raise HTTPException(status_code=400, detail="User is on the free plan — no renewal to simulate.")

    interval = (getattr(user, "plan_billing_interval", None) or "month").strip().lower()
    if interval not in ("month", "year"):
        interval = "month"

    amounts = subscription_credit_amounts(plan, interval)
    balances_before = await get_balances(db, user.id)
    new_balances = await apply_subscription_renewal(
        db,
        user.id,
        amounts,
        f"[TEST] Subscription renewal: {plan} plan",
        commit=True,
    )
    logger.info(
        "[TEST] simulate-renewal | user=%s | plan=%s | interval=%s | +%s credits | %s → %s",
        user.id, plan, interval, amounts, balances_before, new_balances,
    )
    return {
        "status": "ok",
        "plan": plan,
        "billing_interval": interval,
        "credits_added": amounts,
        "balance_before": balances_before,
        "balance_after": new_balances,
    }


def register_dev_only_billing_routes(target: APIRouter) -> None:
    """Mount free-credit test helpers only when APP_ENVIRONMENT is explicit local/dev."""
    if not get_settings().allows_dev_only_routes:
        return
    target.add_api_route(
        "/test/simulate-renewal",
        simulate_renewal,
        methods=["POST"],
        include_in_schema=False,
        summary="DEV ONLY — simulate subscription renewal credits",
    )


register_dev_only_billing_routes(router)


def _apply_stripe_cancel_to_user_from_subscription(user: User, sub: dict) -> None:
    """Keep subscription_cancel_at in sync with Stripe (portal cancel / resume)."""
    cap = bool(sub.get("cancel_at_period_end"))
    ca = sub.get("cancel_at")
    if cap and ca is not None:
        user.subscription_cancel_at = datetime.fromtimestamp(int(ca), tz=timezone.utc)
    elif not cap:
        user.subscription_cancel_at = None


def _stripe_portal_cancellation_survey_has_content(sub: dict) -> bool:
    """
    True when Stripe's Customer Portal collected survey data on the subscription
    (customer.subscription.updated → cancellation_details).
    """
    cd = sub.get("cancellation_details")
    if not isinstance(cd, dict):
        return False
    fb = (cd.get("feedback") or "").strip()
    comment = (cd.get("comment") or "").strip()
    return bool(fb or comment)


# ── Stripe webhook ─────────────────────────────────────────────────────────────

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """
    Stripe webhook handler. No JWT auth — verified via Stripe signature.
    Events handled:
      - checkout.session.completed   → assign plan + add credits
      - invoice.paid                 → monthly renewal, top up credits
      - customer.subscription.updated → plan change; sync cancel_at; email inbox with portal survey
      - customer.subscription.deleted → downgrade to free
      - invoice.payment_failed       → log (notify user via email later)
    """
    settings = get_settings()

    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = _get_stripe().Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SIGNING_SECRET
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")
    except Exception as e:
        logger.exception("[STRIPE] Webhook construct_event failed")
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")

    event_id   = event["id"]
    event_type = event["type"]
    data       = event["data"]["object"]

    # ── Idempotency: atomically claim the event before any side effects ───────
    # INSERT ... ON CONFLICT DO NOTHING — if another request already inserted
    # this event_id, rowcount=0 and we return immediately. No race possible.
    claim = await db.execute(
        pg_insert(ProcessedWebhookEvent)
        .values(event_id=event_id, event_type=event_type)
        .on_conflict_do_nothing(index_elements=["event_id"])
    )
    await db.commit()
    if claim.rowcount == 0:
        return {"status": "duplicate"}

    try:
        return await _process_stripe_event(db, background_tasks, settings, event_id, event_type, data)
    except Exception:
        # A failed event must stay re-processable: release the idempotency claim,
        # otherwise Stripe's retry is answered "duplicate" and the event's side
        # effects (renewal credits, top-ups, plan changes) are silently lost.
        # Re-running is safe — every handler is idempotent on its own (grant
        # markers, per-session top-up dedupe, SET-based renewals).
        try:
            await db.rollback()
            await db.execute(
                delete(ProcessedWebhookEvent).where(ProcessedWebhookEvent.event_id == event_id)
            )
            await db.commit()
        except Exception:
            logger.exception("[STRIPE] Failed to release webhook claim | event=%s", event_id)
        raise


async def _process_stripe_event(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    settings,
    event_id: str,
    event_type: str,
    data: dict,
):
    """Dispatch one verified, freshly-claimed Stripe event. Raising here releases the claim."""
    # ── checkout.session.completed ─────────────────────────────────────────────
    if event_type == "checkout.session.completed":
        session_mode = data.get("mode")
        user_id      = (data.get("metadata") or {}).get("user_id")

        if not user_id:
            logger.warning("[STRIPE] checkout.session.completed missing user_id in metadata")
            return {"status": "ignored"}

        try:
            uid = uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            logger.warning("[STRIPE] checkout.session.completed invalid user_id=%r", user_id)
            return {"status": "invalid_user_id"}

        user = await db.get(User, uid)
        if not user:
            logger.warning("[STRIPE] checkout.session.completed user not found: %s", user_id)
            return {"status": "user_not_found"}

        session_meta = (data.get("metadata") or {})

        # ── Upgrade payment: modify subscription to new plan ──────────────────
        if session_mode == "payment" and session_meta.get("type") == "upgrade":
            plan = session_meta.get("plan")
            bi   = session_meta.get("billing_interval", "month")
            if plan and plan in PLANS and plan != "free" and user.stripe_subscription_id:
                try:
                    upg_settings = get_settings()
                    upg_price_id = get_price_id(plan, upg_settings, bi)
                    upg_sub = await run_in_threadpool(
                        lambda: _get_stripe().Subscription.retrieve(user.stripe_subscription_id)
                    )
                    current_price = upg_sub["items"]["data"][0]["price"]["id"]
                    if current_price != upg_price_id:
                        upg_item_id = upg_sub["items"]["data"][0]["id"]
                        await run_in_threadpool(
                            lambda: _get_stripe().Subscription.modify(
                                user.stripe_subscription_id,
                                items=[{"id": upg_item_id, "price": upg_price_id}],
                                proration_behavior="none",
                                billing_cycle_anchor="now",
                                cancel_at_period_end=False,
                                metadata={
                                    "user_id": str(user_id),
                                    "plan": plan,
                                    "billing_interval": bi,
                                },
                            )
                        )
                        logger.info(
                            "[STRIPE] upgrade checkout completed | user=%s | plan=%s | webhook will credit",
                            user_id, plan,
                        )
                    else:
                        logger.info("[STRIPE] upgrade already applied | user=%s | plan=%s", user_id, plan)
                except Exception:
                    logger.exception("[STRIPE] FAILED upgrade in checkout.session.completed | user=%s", user_id)
                    raise HTTPException(status_code=500, detail="Failed to apply upgrade. Stripe will retry.")
            return {"status": "ok"}

        # One-time top-up payment (idempotent with confirm-checkout-session via session id in description)
        if session_mode == "payment" and session_meta.get("type") == "topup":
            credits_by_pool = _topup_credits_from_metadata(session_meta)
            total_credits = sum(credits_by_pool.values())
            sess_id = str(data.get("id") or "")
            if total_credits > 0 and sess_id:
                try:
                    granted = await grant_topup_credits_if_new(db, user.id, sess_id, credits_by_pool)
                    if granted:
                        logger.info(f"[STRIPE] topup | user={user_id} | +{credits_by_pool} credits | session={sess_id}")
                    else:
                        logger.info(f"[STRIPE] topup duplicate (already applied) | user={user_id} | session={sess_id}")
                except Exception:
                    logger.exception(f"[STRIPE] FAILED to add {credits_by_pool} credits for topup | user={user_id} | event={event_id}")
                    raise HTTPException(status_code=500, detail=f"Failed to add {total_credits} credits for user {user_id}. Stripe will retry.")
            elif total_credits > 0:
                logger.warning("[STRIPE] topup missing session id in payload; skipping grant")

        elif session_mode == "subscription":
            # Subscription checkout — sync plan + idempotent initial credits (shared with confirm-checkout-session)
            plan     = session_meta.get("plan")
            customer = data.get("customer")
            sub_id   = data.get("subscription")

            if plan and plan in PLANS and plan != "free":
                prior_sub = user.stripe_subscription_id
                sub_full = None
                if sub_id:
                    sub_full = await run_in_threadpool(
                        lambda sid=sub_id: _get_stripe().Subscription.retrieve(
                            sid, expand=["items.data.price"]
                        )
                    )
                interval = _billing_interval_from_subscription(sub_full) if sub_full else "month"

                user.plan = plan
                user.plan_billing_interval = interval
                user.stripe_customer_id = customer
                user.stripe_subscription_id = sub_id
                try:
                    if prior_sub != sub_id:
                        credits = subscription_credit_amounts(plan, interval)
                        granted = await try_grant_initial_subscription_credits(
                            db, user.id, plan, sub_id, credits
                        )
                        if not granted:
                            await db.commit()
                        logger.info(
                            "[STRIPE] checkout.session.completed | user=%s | plan=%s | interval=%s | granted=%s | amount=%s",
                            user_id,
                            plan,
                            interval,
                            granted,
                            credits,
                        )
                    else:
                        await db.commit()
                        logger.info(
                            "[STRIPE] checkout.session.completed already applied | user=%s | plan=%s",
                            user_id,
                            plan,
                        )
                except Exception:
                    logger.exception(
                        f"[STRIPE] FAILED to add credits on checkout | user={user_id} | plan={plan} | event={event_id}"
                    )
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to activate {plan} plan for user {user_id}. Stripe will retry.",
                    )
            elif plan:
                logger.warning("[STRIPE] checkout.session.completed unknown plan=%r user=%s", plan, user_id)

    # ── invoice.paid (recurring renewal only) ─────────────────────────────────
    elif event_type == "invoice.paid":
        # Initial subscription is credited on checkout / confirm; only true billing-cycle renewals top up.
        billing_reason = data.get("billing_reason")
        if billing_reason != "subscription_cycle":
            return {"status": "skipped_non_renewal_invoice"}

        customer = data.get("customer")
        result   = await db.execute(select(User).where(User.stripe_customer_id == customer))
        user     = result.scalar_one_or_none()

        if user and user.plan != "free":
            try:
                # Webhook order isn't guaranteed: when a plan change lands at the
                # cycle boundary, this invoice can arrive before subscription.updated,
                # while user.plan still holds the old plan. Trust the invoice's price
                # id over the DB whenever it maps to a known plan.
                plan = user.plan
                interval = (user.plan_billing_interval or "month").strip().lower()
                try:
                    line0 = ((data.get("lines") or {}).get("data") or [])[0]
                    price = line0.get("price") or {}
                    price_id = price.get("id") or (
                        ((line0.get("pricing") or {}).get("price_details") or {}).get("price")
                    )
                    line_plan = get_price_map(settings).get(price_id)
                    if line_plan:
                        plan = line_plan
                        line_iv = (price.get("recurring") or {}).get(
                            "interval"
                        ) or _billing_interval_from_price_id(price_id, settings)
                        if line_iv in ("month", "year"):
                            interval = line_iv
                except (IndexError, TypeError, AttributeError):
                    pass
                if interval not in ("month", "year"):
                    interval = "month"
                if plan != user.plan:
                    user.plan = plan
                    user.plan_billing_interval = interval
                amounts = subscription_credit_amounts(plan, interval)
                await apply_subscription_renewal(
                    db,
                    user.id,
                    amounts,
                    f"Subscription renewal: {plan} plan",
                    commit=True,
                )
                logger.info(
                    "[STRIPE] invoice.paid renewal | user=%s | plan=%s | interval=%s | +%s credits added",
                    user.id,
                    plan,
                    interval,
                    amounts,
                )
            except Exception:
                await db.rollback()
                logger.exception(f"[STRIPE] FAILED to add renewal credits | user={user.id} | plan={user.plan} | event={event_id}")
                raise HTTPException(status_code=500, detail="Failed to process renewal credits. Stripe will retry.")

    # ── customer.subscription.updated (plan change + portal cancel survey email) ─
    elif event_type == "customer.subscription.updated":
        customer = data.get("customer")
        try:
            item0        = data["items"]["data"][0]
            new_price_id = item0["price"]["id"]
            price_obj    = item0["price"]
        except (KeyError, IndexError):
            logger.warning("[STRIPE] subscription.updated missing items/price | event=%s", event_id)
            return {"status": "ignored"}

        rec          = price_obj.get("recurring") or {}
        new_interval = rec.get("interval") or _billing_interval_from_price_id(new_price_id, settings)
        if new_interval not in ("month", "year"):
            new_interval = "month"
        price_map    = get_price_map(settings)
        new_plan     = price_map.get(new_price_id)

        result = await db.execute(select(User).where(User.stripe_customer_id == customer))
        user   = result.scalar_one_or_none()

        # Defer in-app background email until after DB work succeeds. If a later step
        # raises, Starlette will not run BackgroundTasks, so we must not queue the email
        # until the whole handler block completes without error.
        pending_portal_survey: tuple | None = None
        try:
            if user:
                _apply_stripe_cancel_to_user_from_subscription(user, data)
                if _stripe_portal_cancellation_survey_has_content(data):
                    u_name = (user.full_name or user.username or user.email or "User").strip()
                    sub_id = str(data.get("id") or "")
                    ca_raw = data.get("cancel_at")
                    ca_un = int(ca_raw) if ca_raw is not None else None
                    cd = data.get("cancellation_details") or {}
                    pending_portal_survey = (
                        user.email,
                        u_name,
                        sub_id,
                        ca_un,
                        cd if isinstance(cd, dict) else {},
                    )

            if user and new_plan and new_plan != user.plan:
                old_plan = user.plan
                old_iv = (user.plan_billing_interval or "month").strip().lower()
                if old_iv not in ("month", "year"):
                    old_iv = "month"

                user.plan = new_plan
                user.plan_billing_interval = new_interval
                user.subscription_cancel_at = None  # clear any pending cancellation

                new_credits_amt = subscription_credit_amounts(new_plan, new_interval)
                is_upgrade = PLAN_RANK.get(new_plan, 0) > PLAN_RANK.get(old_plan, 0)
                if is_upgrade:
                    await grant_plan_credits(db, user.id, new_credits_amt, f"Upgraded from {old_plan} to {new_plan}")
                else:
                    # Downgrade: replace each pool's bucket with the new allowance (never additive).
                    await apply_subscription_renewal(
                        db, user.id, new_credits_amt, f"Switched from {old_plan} to {new_plan} plan"
                    )
                logger.info(f"[STRIPE] subscription.updated | user={user.id} | {old_plan} → {new_plan}")
            elif user and new_plan and new_plan == user.plan:
                # e.g. monthly ↔ annual on same tier, or only portal cancel (same price)
                old_iv = (user.plan_billing_interval or "month").strip().lower()
                if old_iv not in ("month", "year"):
                    old_iv = "month"
                if new_interval != old_iv:
                    old_amt = subscription_credit_amounts(new_plan, old_iv)
                    new_amt = subscription_credit_amounts(new_plan, new_interval)
                    user.plan_billing_interval = new_interval
                    deltas = {
                        pool: new_amt[pool] - old_amt[pool]
                        for pool in POOLS
                        if new_amt[pool] - old_amt[pool] > 0
                    }
                    if deltas:
                        await grant_plan_credits(db, user.id, deltas, f"Billing interval updated ({new_plan})")
                    else:
                        await db.commit()
                    logger.info(
                        "[STRIPE] subscription.updated interval | user=%s | plan=%s | %s → %s",
                        user.id,
                        new_plan,
                        old_iv,
                        new_interval,
                    )
                else:
                    await db.commit()
                    logger.info(
                        "[STRIPE] subscription.updated (no plan/interval change) | user=%s | plan=%s",
                        user.id,
                        new_plan,
                    )
            elif user:
                await db.commit()

            if pending_portal_survey:
                background_tasks.add_task(
                    send_stripe_portal_cancellation_survey_email,
                    *pending_portal_survey,
                )
                logger.info(
                    "[STRIPE] portal cancellation survey email queued | user=%s | event=%s",
                    user.id if user else "n/a",
                    event_id,
                )
        except Exception:
            await db.rollback()
            logger.exception("[STRIPE] FAILED subscription.updated | user=%s | event=%s", user.id if user else "unknown", event_id)
            raise HTTPException(status_code=500, detail="Failed to process plan update. Stripe will retry.")

    # ── customer.subscription.deleted (cancelled) ─────────────────────────────
    elif event_type == "customer.subscription.deleted":
        customer = data.get("customer")
        result   = await db.execute(select(User).where(User.stripe_customer_id == customer))
        user     = result.scalar_one_or_none()

        if user:
            try:
                user.plan                    = "free"
                user.plan_billing_interval   = None
                user.stripe_subscription_id  = None
                user.subscription_cancel_at  = None
                await db.commit()
                logger.info(f"[STRIPE] subscription.deleted | user={user.id} | downgraded to free")
            except Exception:
                await db.rollback()
                logger.exception("[STRIPE] FAILED subscription.deleted | user=%s | event=%s", user.id, event_id)
                raise HTTPException(status_code=500, detail="Failed to downgrade plan. Stripe will retry.")

    # ── invoice.payment_failed ─────────────────────────────────────────────────
    elif event_type == "invoice.payment_failed":
        try:
            customer = data.get("customer")
            result   = await db.execute(select(User).where(User.stripe_customer_id == customer))
            user     = result.scalar_one_or_none()
            if user:
                background_tasks.add_task(send_payment_failed_email, user.email)
        except Exception:
            logger.exception("[STRIPE] FAILED invoice.payment_failed handler | event=%s", event_id)

    return {"status": "ok"}
