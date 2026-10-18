# Credit Top-Up API — Frontend Integration Guide

## Contract changes (2026-07-13) — read first if you integrated before

1. **Request body changed**: `POST /topup/create-checkout-session` takes
   `{ "lead": n, "email_gen": n, "outreach": n }` — the old single `credits` field
   is gone.
2. **`max` moved into `pools[]`**: `/topup/options` no longer has a top-level
   `max`. Each entry in `pools[]` carries its own `max` (and `price_per_credit`) —
   bound and price each slider from its own pool object. Top-level `min`/`step`
   remain shared.
3. **Per-pool prices are final** (same on every plan): lead **$0.0175**, email_gen
   **$0.015**, outreach **$0.005** per credit ($1.75 / $1.50 / $0.50 per 100).
   Still read the rate from `/topup/options` at runtime instead of hardcoding.
   At these rates the smallest valid basket (100 outreach = $0.50) meets Stripe's
   $0.50 minimum charge; the backend 422s sub-$0.50 baskets as a safety net should
   a rate ever be lowered.
4. **Response shape**: checkout response returns `credits` (per-pool object),
   `total_credits`, `price_usd_by_pool`, and `price_usd` (the sum).

## Overview

Credits are split into three pools — **Lead** (`lead`), **Email Generation**
(`email_gen`), and **Outreach** (`outreach`) — and top-ups are bought **per pool**.
One checkout can combine amounts for several pools in a single Stripe payment.

The flow is: **fetch range config → show one slider per pool → call checkout →
redirect to Stripe → done**.

---

## Endpoints

### 1. GET `/api/v1/billing/topup/options`

Fetch the top-up rules to configure the sliders. Call this when the top-up page/modal loads.

**Auth:** Required (Bearer token)
**Request:** None

**Response (starter plan example):**
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

Notes:
- `min` / `step` are shared; **each pool has its own `max` and `price_per_credit`**
  (both depend on the user's plan) — bound and price each slider from its own entry.
- The `max` is per purchase (≈ one month's allowance); buying again later is allowed.
- Free plan gets `"available": false` with a `reason` (every `max` is 0) — hide the
  sliders and show the upgrade prompt instead.

Use these values to:
- Render one slider per entry in `pools` (range `0`–`pools[i].max`, step `step`;
  treat any value below `min` as 0 / "not buying this pool")
- Calculate live price preview:
  `lead × pools.lead.price_per_credit + email_gen × pools.email_gen.price_per_credit + outreach × pools.outreach.price_per_credit`

---

### 2. POST `/api/v1/billing/topup/create-checkout-session`

Call this when the user clicks "Buy Now". Redirects them to Stripe to complete payment.

**Auth:** Required (Bearer token)
**Request body:**
```json
{
  "lead": 300,
  "email_gen": 100,
  "outreach": 0
}
```

**Rules (validated on backend):**
- Each field defaults to `0` (= don't buy that pool); at least one must be `> 0`
- Every non-zero amount must be between `min` and **that pool's** `max` for the user's plan
- Every non-zero amount must be a multiple of `step` (e.g. 100, 200 — not 150)

**Success response `200`:**
```json
{
  "checkout_url": "https://checkout.stripe.com/...",
  "credits": { "lead": 300, "email_gen": 100, "outreach": 0 },
  "total_credits": 400,
  "price_usd_by_pool": { "lead": 5.25, "email_gen": 1.50 },
  "price_usd": 6.75
}
```
→ Redirect the user to `checkout_url`
(`price_usd` = sum of the per-pool prices; each pool is priced at its own rate and
appears as its own line item in Stripe checkout.)

**Error responses:**
```json
// Nothing selected
{ "detail": "Select at least one pool's credit amount to top up." }            // 422

// Invalid range (message names the pool)
{ "detail": "Lead credits must be between 100 and 500 for your plan." }        // 422

// Not a valid step
{ "detail": "Email Generation credits must be a multiple of 100." }            // 422

// Safety net (unreachable at current rates): basket under Stripe's $0.50 minimum
{ "detail": "Minimum top-up purchase is $0.50 — your selection totals $0.40. Add more credits." } // 422

// Free plan
{ "detail": "Top-up is not available on the free plan. Upgrade to a paid plan." } // 403

// Stripe error
{ "detail": "..." }                                                             // 400
```

---

## After Payment

Stripe redirects the user to:
- **Success:** `{FRONTEND_URL}/billing/success?session_id=...`
- **Cancel:**  `{FRONTEND_URL}/billing/cancel`

The backend webhook automatically credits each pool's top-up bucket — no extra call
needed (the success page's `confirm-checkout-session` call is idempotent with it;
`credits_added` in its response is a per-pool object). On the success page, fetch the
updated balances from:

```
GET /api/v1/billing/credits/balance
```

which returns per-pool balances (`pools.lead.balance`, `pools.email_gen.balance`,
`pools.outreach.balance`).

---

## UI Suggestion

```
┌──────────────────────────────────────────────┐
│  Top Up Credits                              │
│                                              │
│  Lead credits           ($1.75 per 100)      │
│  [ 0 ] ────────●───────────────── [ 500 ]    │
│                  300 credits · $5.25         │
│                                              │
│  Email Generation       ($1.50 per 100)      │
│  [ 0 ] ─●──────────────────────── [ 1500 ]   │
│                  100 credits · $1.50         │
│                                              │
│  Outreach               ($0.50 per 100)      │
│  [ 0 ] ●───────────────────────── [ 2000 ]   │
│                    0 credits · $0.00         │
│                                              │
│  Total: 400 credits · $6.75                  │
│                                              │
│              [ Buy Now ]                     │
└──────────────────────────────────────────────┘
```

- One slider per pool, range `0`–`that pool's max`, step `100`
- Live price per slider: `amount × that pool's price_per_credit`; total = sum of the three
- On "Buy Now" → POST `{ lead, email_gen, outreach }` to
  `/topup/create-checkout-session` → redirect to `checkout_url`
