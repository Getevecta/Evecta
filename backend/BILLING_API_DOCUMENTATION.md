# Evecta Billing API Documentation

**Base URL:** `http://127.0.0.1:8000`
**Auth:** All endpoints (except `/billing/webhook`) require `Authorization: Bearer <access_token>`
**Test Mode:** All Stripe keys are in test mode — no real charges occur

---

## Credit Pools

Credits are split into **three independent pools**. An action can only spend from its
own pool — a full `outreach` balance cannot cover a `lead` search.

| Pool | Key | Pays for |
|---|---|---|
| Lead | `lead` | Lead generation (search / chat), enrichment hooks |
| Email Generation | `email_gen` | AI email drafts, spam checks |
| Outreach | `outreach` | Sending campaign emails (per recipient at launch) |

Each pool internally keeps two buckets:
- **subscription balance** — plan/signup/renewal credits; reset to the plan allowance
  each billing cycle (unused credits do not roll over)
- **top-up balance** — one-time purchases; never cleared by renewals

Spending always drains the subscription bucket first, then top-ups.

---

## Test Cards

| Scenario | Card Number | Expiry | CVC |
|---|---|---|---|
| Payment succeeds | `4242 4242 4242 4242` | `12/29` | `123` |
| Payment declined | `4000 0000 0000 0002` | `12/29` | `123` |
| Insufficient funds | `4000 0000 0000 9995` | `12/29` | `123` |
| 3D Secure required | `4000 0025 0000 3155` | `12/29` | `123` |
| Card expired | `4000 0000 0000 0069` | `12/29` | `123` |

---

## Plans Reference

Per-pool monthly allowances (annual billing grants 12× per period).
Source of truth: `backend/app/core/plans.py` `PLANS` — numbers below are the current
placeholders and can change.

| Plan | Lead/mo | Email Gen/mo | Outreach/mo | Leads/search | Top-up max per purchase (lead / email_gen / outreach) | Price |
|---|---|---|---|---|---|---|
| free | 50 | 50 | 50 | 20 | — (no top-up) | $0 |
| starter | 500 | 1,250 | 2,000 | 100 | 500 / 1,500 / 2,000 | $29/mo |
| growth | 1,150 | 2,800 | 4,500 | 300 | 1,500 / 3,000 / 4,500 | $59/mo |
| scale | 2,500 | 6,250 | 10,000 | 500 | 2,500 / 6,500 / 10,000 | $119/mo |

Top-up caps ≈ one month's allowance per purchase (rounded to clean slider values);
they limit single transactions, not total volume — users can buy again.

List prices live in `app.core.plans.PLAN_MONTHLY_USD` and Frontend `BillingPage` `PLANS`.
Stripe Price IDs in env must charge these same amounts (update Stripe dashboard if they differ).

---

## Credit Costs Reference

Source of truth: `backend/app/core/plans.py` `CREDIT_COSTS` + `ACTION_POOLS`.

| Action | Pool | Cost |
|---|---|---|
| lead_found | lead | 1 credit per lead |
| email_enriched | lead | 0 (included) |
| email_scraped | lead | 0 (included) |
| ai_draft | email_gen | 1 credit per AI-generated email — the campaign-level draft (`POST /campaigns/{id}/draft/ai`) **and** every per-lead email (`POST /campaigns/{id}/emails/generate`, `?regenerate_all=true`, and `POST /campaigns/{id}/emails/{email_id}/regenerate`). Regenerating charges again; template-merge campaigns (no AI) are free |
| spam_check | email_gen | 1 credit per spam check (the review UI's "Spam Email Test" also goes through this endpoint) |
| email_sent | outreach | 1 credit per recipient at campaign launch |

**Per-lead email generation rules:**
- `POST /campaigns/{id}/emails/generate` (and `/resume`) run an **affordability gate**:
  402 up front if the email_gen balance can't cover every row about to be generated —
  nothing starts and nothing is charged.
- The charge lands **per row, only on success** (row reaches READY) — cancelled and
  failed rows are never charged. If credits run out mid-run (concurrent spending),
  the unpaid draft is discarded, the row returns to pending with
  `last_error: "insufficient_email_gen_credits"`, and the run stops; top up and hit
  generate/resume to continue.
- Single regenerate: gated up front; a failed regeneration restores the previous
  draft and costs nothing. Manual edits (`PATCH /emails/{email_id}`) are free.

---

## Endpoints

---

### 1. GET /billing/credits/balance

Returns per-pool credit balances and plan info. There is **no combined total** —
pools are independent.

**Request**
```
GET http://127.0.0.1:8000/billing/credits/balance
Authorization: Bearer <access_token>
```

**Response — 200 OK**
```json
{
  "pools": {
    "lead":      { "balance": 460,  "display_denominator": 500,  "label": "Lead" },
    "email_gen": { "balance": 1210, "display_denominator": 1250, "label": "Email Generation" },
    "outreach":  { "balance": 2000, "display_denominator": 2000, "label": "Outreach" }
  },
  "plan": "starter",
  "costs": {
    "lead_found": 1,
    "email_enriched": 0,
    "email_scraped": 0,
    "ai_draft": 1,
    "spam_check": 1,
    "email_sent": 1
  },
  "action_pools": {
    "lead_found": "lead",
    "email_enriched": "lead",
    "email_scraped": "lead",
    "ai_draft": "email_gen",
    "spam_check": "email_gen",
    "email_sent": "outreach"
  }
}
```

`display_denominator` is the per-pool denominator for UI labels like `231/250 remaining`
(it accounts for top-ups and grants beyond the plan allowance).

**Test Cases**

| Case | Expected |
|---|---|
| Free plan, just registered | `lead: 50, email_gen: 50, outreach: 50` |
| After upgrading to starter | `lead: +500, email_gen: +1250, outreach: +2000` |
| After a 30-lead search | `lead` decremented by 30; other pools untouched |
| Invalid/expired token | `401 Unauthorized` |

---

### 2. GET /billing/credits/history

Returns last 50 credit transactions (newest first). Each row is tagged with its pool.

**Request**
```
GET http://127.0.0.1:8000/billing/credits/history
Authorization: Bearer <access_token>
```

**Response — 200 OK**
```json
{
  "transactions": [
    {
      "id": "uuid",
      "amount": 250,
      "action": "subscription_grant",
      "pool": "lead",
      "description": "Upgraded to starter plan",
      "created_at": "2026-07-12T10:00:00Z"
    },
    {
      "id": "uuid",
      "amount": -20,
      "action": "lead_found",
      "pool": "lead",
      "description": "Search: fitness gym in los angeles",
      "created_at": "2026-07-12T09:30:00Z"
    },
    {
      "id": "uuid",
      "amount": -1,
      "action": "spam_check",
      "pool": "email_gen",
      "description": "Spam check for campaign 42",
      "created_at": "2026-07-12T09:00:00Z"
    }
  ]
}
```

`pool` can be `null` only on rows created before the pool split that weren't backfilled
(should not happen — the migration backfills all rows).

Possible `action` values: `lead_found`, `email_enriched`, `email_scraped`, `ai_draft`,
`spam_check`, `email_sent` (spends, negative) · `subscription_grant`, `topup`,
`refund` (grants, positive — `refund` reverses a spend whose work then failed) ·
`free_plan_cap` (negative — free-plan balance trimmed down to the allowance).

**Test Cases**

| Case | Expected |
|---|---|
| New user, no actions | Three signup grant entries (one per pool) |
| After plan upgrade | `subscription_grant` entry per pool |
| After search | Negative `lead_found` entry with `pool: "lead"` |
| After launch | Negative `email_sent` entry with `pool: "outreach"` |

---

### 3. GET /billing/subscription

Returns current subscription status. `credits` and `credits_per_period` are per-pool objects.

**Request**
```
GET http://127.0.0.1:8000/billing/subscription
Authorization: Bearer <access_token>
```

**Response — Free plan (200 OK)**
```json
{
  "plan": "free",
  "plan_billing_interval": null,
  "credits_per_period": { "lead": 50, "email_gen": 50, "outreach": 50 },
  "stripe_customer_id": null,
  "stripe_subscription_id": null,
  "credits": { "lead": 50, "email_gen": 50, "outreach": 50 },
  "leads_per_search": 20,
  "cancel_at": null
}
```

**Response — Paid plan (200 OK)**
```json
{
  "plan": "starter",
  "plan_billing_interval": "month",
  "credits_per_period": { "lead": 500, "email_gen": 1250, "outreach": 2000 },
  "stripe_customer_id": "cus_abc123",
  "stripe_subscription_id": "sub_xyz789",
  "credits": { "lead": 500, "email_gen": 1250, "outreach": 2000 },
  "leads_per_search": 100,
  "cancel_at": null
}
```

Annual billing (`plan_billing_interval: "year"`) returns 12× the monthly numbers in
`credits_per_period`.

---

### 4. POST /billing/create-checkout-session

Creates a Stripe subscription checkout session. (Unchanged by the pool split.)

**Request**
```
POST http://127.0.0.1:8000/billing/create-checkout-session
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "plan": "starter",
  "billing_interval": "month"
}
```

**Request Body**

| Field | Type | Required | Values |
|---|---|---|---|
| plan | string | yes | `"starter"` / `"growth"` / `"scale"` |
| billing_interval | string | no | `"month"` (default) / `"year"` |

**Response — 200 OK**
```json
{
  "checkout_url": "https://checkout.stripe.com/pay/cs_test_..."
}
```

On completion, **all three pools** receive the plan's allowance. Downgrades reset each
pool's subscription bucket to the new allowance; upgrades add on top.

---

### 5. GET /billing/topup/options

Returns top-up configuration. `min` / `step` are shared; **each pool has its own
`max` and `price_per_credit`**. One checkout can combine amounts for several pools.

**Request**
```
GET http://127.0.0.1:8000/billing/topup/options
Authorization: Bearer <access_token>
```

**Response — paid plan (starter, 200 OK)**
```json
{
  "available": true,
  "min": 100,
  "step": 100,
  "pools": [
    { "pool": "lead",      "label": "Lead",             "price_per_credit": 0.0175, "max": 500 },
    { "pool": "email_gen", "label": "Email Generation", "price_per_credit": 0.015,  "max": 1500 },
    { "pool": "outreach",  "label": "Outreach",         "price_per_credit": 0.005,  "max": 2000 }
  ]
}
```

Rates (same on every plan): **lead $1.75 / email_gen $1.50 / outreach $0.50 per 100
credits**. Source of truth: `backend/app/core/plans.py` — `TOPUP_USD_PER_CREDIT`
(rates) and `PLANS[*]['topup_max']` (per-pool caps). The frontend should still read
`price_per_credit` from this endpoint at runtime rather than hardcoding.

> Stripe's $0.50 charge floor: at these rates the smallest valid basket
> (100 outreach credits) is exactly $0.50, so every selection is payable. The
> backend still 422s sub-$0.50 baskets as a safety net if a rate is ever lowered.

**Response — free plan (200 OK)**
```json
{
  "available": false,
  "reason": "Top-up is not available on the free plan. Upgrade to a paid plan.",
  "min": 0,
  "step": 100,
  "pools": [ ...each with "max": 0... ]
}
```

---

### 6. POST /billing/topup/create-checkout-session

Creates a one-time top-up checkout covering up to three pools in a single Stripe payment.
Each non-zero pool amount becomes its own Stripe line item.

**Request**
```
POST http://127.0.0.1:8000/billing/topup/create-checkout-session
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "lead": 300,
  "email_gen": 100,
  "outreach": 0
}
```

**Request Body**

| Field | Type | Required | Constraints |
|---|---|---|---|
| lead | integer | no (default 0) | 0, or min–max per plan, multiple of 100 |
| email_gen | integer | no (default 0) | same |
| outreach | integer | no (default 0) | same |

At least one field must be > 0.

**Response — 200 OK**
```json
{
  "checkout_url": "https://checkout.stripe.com/pay/cs_test_...",
  "credits": { "lead": 300, "email_gen": 100, "outreach": 0 },
  "total_credits": 400,
  "price_usd_by_pool": { "lead": 5.25, "email_gen": 1.5 },
  "price_usd": 6.75
}
```

Each pool is priced at **its own rate** and becomes its own Stripe line item;
`price_usd` is the sum of `price_usd_by_pool`
(here: 300 × $0.0175 = $5.25, plus 100 × $0.015 = $1.50).

**Test Cases**

| Case | Body | Expected |
|---|---|---|
| Single pool | `{ "lead": 500 }` | `checkout_url`, one line item |
| Multi pool | `{ "lead": 300, "outreach": 100 }` | two line items, `total_credits: 400` |
| All zero | `{}` | `422 — "Select at least one pool's credit amount to top up."` |
| Below minimum | `{ "email_gen": 50 }` | `422` |
| Smallest valid basket | `{ "outreach": 100 }` ($0.50) | `checkout_url, price_usd: 0.5` |
| Above plan max | `{ "lead": 99999 }` | `422` |
| Not multiple of 100 | `{ "lead": 150 }` | `422` |
| Free plan | any | `403 — top-up not available` |

**After payment:**
- Each pool's top-up bucket is credited (idempotent per session + pool — the webhook
  and the success-page confirm call cannot double-credit)
- Plan stays unchanged
- History shows one `topup` row per pool, e.g.
  `"Top-up purchase: 300 lead credits [session:cs_test_...]"`

---

### 7. POST /billing/confirm-checkout-session

Called from the success page when webhooks are delayed. Idempotent with the webhook.

For **top-up** sessions, `credits_added` is a per-pool object:
```json
{
  "status": "ok",
  "credits_added": { "lead": 300, "email_gen": 100 },
  "already_applied": false
}
```
(`credits_added: {}` when the webhook already applied it.)

---

### 8. POST /billing/cancel

Cancels the active subscription at end of current billing period. (Unchanged.)

---

### 9. POST /billing/webhook

Stripe webhook — called automatically by Stripe. Not called by frontend.

**Events Handled**

| Event | Action |
|---|---|
| `checkout.session.completed` (subscription) | Updates `user.plan`, grants all pools' allowances |
| `checkout.session.completed` (payment/topup) | Grants per-pool top-up amounts from metadata (`credits_lead`, `credits_email_gen`, `credits_outreach`; legacy single `credits` → lead pool) |
| `invoice.paid` (`subscription_cycle` only) | Resets every pool's subscription bucket to the plan allowance |
| `customer.subscription.updated` | Upgrade: adds new allowances per pool. Downgrade: resets each pool. Interval change: grants positive per-pool deltas |
| `customer.subscription.deleted` | Downgrades to free, clears subscription ID |
| `invoice.payment_failed` | Sends payment failed email to user |

**Failure/retry semantics:** events are claimed by id (duplicates return
`{"status": "duplicate"}`), but a handler failure **releases the claim** before
returning 500 — so Stripe's automatic retry re-processes the event instead of being
answered "duplicate". Handlers are idempotent (grant markers, per-session top-up
dedupe, SET-based renewals), so re-runs can't double-credit.

---

### 10. POST /billing/test/simulate-renewal (dev only)

Simulates an `invoice.paid` renewal. Registered only when `APP_ENVIRONMENT` is an
explicit local/dev value (`development`, `local`, `dev`, `test`) — unset, `prod`,
`production`, `staging`, and similar names leave the route unregistered. Hidden
from OpenAPI (`include_in_schema=False`). Returns per-pool numbers:

```json
{
  "status": "ok",
  "plan": "starter",
  "billing_interval": "month",
  "credits_added": { "lead": 500, "email_gen": 1250, "outreach": 2000 },
  "balance_before": { "lead": 12, "email_gen": 3, "outreach": 88 },
  "balance_after": { "lead": 500, "email_gen": 1250, "outreach": 2088 }
}
```

Note: `outreach` after = 2088 because the top-up bucket (88) survives the renewal reset.

---

## End-to-End Test Flows

### Flow 1 — New user signup + upgrade
```
1. POST /auth/register           → creates user
2. GET  /billing/credits/balance → pools: lead 50 / email_gen 50 / outreach 50
3. POST /billing/create-checkout-session { plan: "starter" }
4. Open checkout_url in browser  → pay with 4242 4242 4242 4242
5. GET  /billing/credits/balance → lead 550 / email_gen 1300 / outreach 2050
6. GET  /billing/credits/history → signup grants + upgrade grants (one row per pool)
```

### Flow 2 — Multi-pool top-up
```
1. GET  /billing/topup/options   → min/max/step + pools
2. POST /billing/topup/create-checkout-session { lead: 300, outreach: 100 }
3. Open checkout_url → pay with 4242 4242 4242 4242
4. GET  /billing/credits/balance → lead +300, outreach +100, email_gen unchanged
5. GET  /billing/credits/history → two topup rows tagged with their pool
```

### Flow 3 — Insufficient credits in ONE pool
```
1. Drain email_gen (run spam checks / drafts until 0)
2. POST /campaigns/{id}/generate-draft
   → 402 { "error": "insufficient_credits", "pool": "email_gen", ... }
   → lead / outreach balances are irrelevant; only email_gen can pay for drafts
3. POST /billing/topup/create-checkout-session { email_gen: 100 }
4. Pay → draft generation works again
```

---

## Error Responses

### 402 — Insufficient Credits (now per pool)
```json
{
  "detail": {
    "error": "insufficient_credits",
    "pool": "outreach",
    "pool_label": "Outreach",
    "message": "Not enough Outreach credits. This action costs 120 Outreach credits, you have 40.",
    "required": 120,
    "available": 40,
    "shortfall": 80
  }
}
```

Endpoints that can now return 402 (were free before the pool split): campaign AI draft,
spam check, and campaign launch.

### 400 — No Active Subscription
```json
{ "detail": "No active subscription found." }
```

### 422 — Invalid Topup Amount
```json
{ "detail": "Lead credits must be between 100 and 500 for your plan." }
```

### 401 — Unauthorized
```json
{ "detail": "Not authenticated" }
```
