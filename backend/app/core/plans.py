"""
Credits are split into three independent pools; an action can only spend from its
own pool (see ACTION_POOLS):

  - "lead"      → lead generation (1 credit per lead returned from search / chat)
  - "email_gen" → AI email drafting + spam checks
  - "outreach"  → sending campaign emails (1 credit per recipient at launch)

Subscription allowances are defined per plan *per pool*. Paid plans receive
subscription-bucket credits on checkout and again on each Stripe `invoice.paid`
renewal (see billing webhook). Free plan receives the free allowance once at signup.

Unused subscription credits do not carry into the next billing period (monthly or
yearly). One-time credit top-ups are stored separately per pool and are not cleared
when the subscription renews.

NOTE: per-pool allowance numbers below are placeholders — adjust anytime; they only
apply to future grants/renewals (never retroactively).
"""

POOLS = ("lead", "email_gen", "outreach")

POOL_LABELS = {
    "lead":      "Lead",
    "email_gen": "Email Generation",
    "outreach":  "Outreach",
}

DEFAULT_POOL = "lead"  # legacy rows / old Stripe sessions without pool metadata

# Per-pool allowances + list prices — Final Price sheet 2026-07-14
# (email_gen = spam-check / AI drafts). Keep Frontend BillingPage PLANS in sync.
# topup_max: per-pool cap PER PURCHASE ≈ one month's allowance rounded to a clean
# slider value. Users can buy repeatedly — this limits single transactions, not volume.
PLAN_MONTHLY_USD = {
    "free": 0,
    "starter": 29,
    "growth": 59,
    "scale": 119,
}

PLANS = {
    "free": {
        "credits":   {"lead": 50, "email_gen": 50, "outreach": 50},
        "leads_per_search": 20,
        "topup_max": {"lead": 0, "email_gen": 0, "outreach": 0},  # no top-up: upgrading is the free tier's top-up
    },
    "starter": {
        "credits":   {"lead": 500, "email_gen": 1250, "outreach": 2000},
        "leads_per_search": 100,
        "topup_max": {"lead": 500, "email_gen": 1500, "outreach": 2000},
    },
    "growth": {
        "credits":   {"lead": 1150, "email_gen": 2800, "outreach": 4500},
        "leads_per_search": 300,
        "topup_max": {"lead": 1500, "email_gen": 3000, "outreach": 4500},
    },
    "scale": {
        "credits":   {"lead": 2500, "email_gen": 6250, "outreach": 10000},
        "leads_per_search": 500,
        "topup_max": {"lead": 2500, "email_gen": 6500, "outreach": 10000},
    },
}


def topup_caps(plan_key: str | None) -> dict[str, int]:
    """Per-pool, per-purchase top-up caps for a plan (0 = pool not top-uppable)."""
    p = (plan_key or "free").strip().lower()
    caps = PLANS.get(p, PLANS["free"]).get("topup_max") or {}
    return {pool: int(caps.get(pool, 0) or 0) for pool in POOLS}

CREDIT_COSTS = {
    "lead_found":       1,  # per lead returned from search / chat lead gen
    "email_enriched":   0,  # included — no charge
    "email_scraped":    0,  # included — no charge
    "ai_draft":         1,  # per AI-generated campaign email
    "spam_check":       1,  # per spam check
    "email_sent":       1,  # per recipient at campaign launch
}

# Which pool each spendable action deducts from.
ACTION_POOLS = {
    "lead_found":     "lead",
    "email_enriched": "lead",
    "email_scraped":  "lead",
    "ai_draft":       "email_gen",
    "spam_check":     "email_gen",
    "email_sent":     "outreach",
}

# Ledger-only actions (grants, purchases, reversals, cap trims) — not in CREDIT_COSTS.
CREDIT_LEDGER_ACTIONS = (
    "subscription_grant",
    "topup",
    "refund",
    "free_plan_cap",
)

# Every value CreditTransaction.action is allowed to store.
CREDIT_TRANSACTION_ACTIONS = tuple(CREDIT_COSTS) + CREDIT_LEDGER_ACTIONS

DEFAULT_PLAN = "free"

MONTHS_PER_BILLING_YEAR = 12


def subscription_credit_amounts(plan_key: str, billing_interval: str = "month") -> dict[str, int]:
    """
    Per-pool credits granted on subscribe/renew. PLANS[*]['credits'] is the monthly
    allowance; annual Stripe prices get 12× that per billing period.
    Free/unknown plans renew nothing (their allowance is granted once at signup).
    """
    if plan_key not in PLANS or plan_key == DEFAULT_PLAN:
        return {pool: 0 for pool in POOLS}
    base = PLANS[plan_key]["credits"]
    interval = (billing_interval or "month").strip().lower()
    factor = MONTHS_PER_BILLING_YEAR if interval == "year" else 1
    return {pool: base.get(pool, 0) * factor for pool in POOLS}


# ── Credit top-up config ───────────────────────────────────────────────────────
# min/step are shared by every pool; the per-purchase max is per plan per pool
# (PLANS[*]['topup_max'], see topup_caps). A single checkout can combine amounts
# for several pools; each non-zero pool amount must respect min/step/max.
TOPUP_MIN_CREDITS = 100
TOPUP_STEP        = 100


# USD per credit for one-time top-ups, per pool — same rate on every plan
# ($1.75 / $1.50 / $0.40 per 100 credits).
# Whole cents per 100 credits + TOPUP_STEP of 100 ⇒ every valid basket is exact cents.
TOPUP_USD_PER_CREDIT: dict[str, float] = {
    "lead":      0.0175,
    "email_gen": 0.0150,
    "outreach":  0.0040,
}

# Stripe rejects payments below $0.50. Outreach-only min (100 × $0.004 = $0.40)
# is below the floor — checkout still enforces this (buy more or mix pools).
TOPUP_MIN_CHARGE_USD = 0.50


def topup_usd_per_credit(plan_key: str | None, pool: str) -> float:
    """USD per credit for one-time top-ups of one pool (same for every plan)."""
    return TOPUP_USD_PER_CREDIT.get(pool, TOPUP_USD_PER_CREDIT["lead"])
