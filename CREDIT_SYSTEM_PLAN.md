# Evecta Credit System Plan

> **⚠️ Historical planning document — superseded (2026-07-12).**
> The shipped system differs from this plan in two big ways:
>
> 1. **Credits are split into three independent pools** — `lead` (lead generation),
>    `email_gen` (AI drafts + spam checks), `outreach` (campaign sends). An action can
>    only spend from its own pool; there is no single combined balance anymore.
> 2. **Costs and plan allowances are different** — every charged action costs 1 credit
>    (`lead_found`, `ai_draft`, `spam_check`, `email_sent`; enrichment is free), and
>    plans/prices are free $0 / starter $29 / growth $59 / scale $119 with per-pool
>    allowances defined in `backend/app/core/plans.py`.
>
> The DB schema below is also outdated: `user_credits` was replaced by
> `user_credit_pools` (one row per user per pool, each with subscription + top-up
> buckets), and `credit_transactions` gained a `pool` column.
>
> **Current source of truth:** `backend/app/core/plans.py` (numbers),
> `backend/BILLING_API_DOCUMENTATION.md` (API contract), `TOPUP_API.md` (top-up flow).
> The revenue/margin projections below predate the shipped pricing and have not been
> recalculated.

## Overview

Evecta uses a **credit-based pricing system**. Every meaningful action costs credits.
When a user's balance reaches 0, all credit-consuming actions are blocked.
Users connect their **own email account (Gmail/Outlook)** — so email sending costs nothing to the org.

---

## Credit Costs Per Action

| Action | Credits | Notes |
|---|---|---|
| Chat search | 1 per lead found | 20 leads = 20 credits |
| Email enrichment | 2 per email found | background after search |
| AI draft | 10 flat | per draft generated |
| Spam check | 2 flat | per check |
| Campaign launch | 3 per email sent | 20 leads = 60 credits |
| Manual draft | 0 | free |
| Template draft | 0 | free |
| Preview campaign | 0 | free |
| Promote leads to DB | 0 | free |
| View inbox/replies | 0 | free |

---

## Full User Journey — Where Credits Are Spent

### Step 1 — Chat Search
```
User types: "find restaurants in Kathmandu"
→ 20 leads found → -20 credits
Balance: 80
```

### Step 2 — Email Enrichment (auto background)
```
20 leads enriched → 12 emails found → -24 credits
Balance: 56
```

### Step 3 — Promote Leads to DB
```
User clicks Save → FREE
Balance: 56
```

### Step 4 — Create Campaign
```
User fills name, category, goal → FREE
Balance: 56
```

### Step 5 — Write Draft
```
Manual or Template draft → FREE
Balance: 56

AI draft → -10 credits
Balance: 46
```

### Step 6 — Spam Check
```
User clicks Check Spam → -2 credits
Balance: 44
```

### Step 7 — Preview
```
User views campaign preview → FREE
Balance: 44
```

### Step 8 — Launch
```
User has 20 leads → needs 60 credits (20 × 3)
Balance: 44 → NOT ENOUGH → BLOCKED ✗
Prompt: "Launching to 20 leads costs 60 credits. You have 44. Top up 16 more."
```

---

## Where Users Hit the Credit Wall

| # | Action | Credits Needed | Blocked When |
|---|---|---|---|
| 1 | Chat search | leads × 1 | balance = 0 |
| 2 | Email enrichment | emails × 2 | balance = 0 (bg task) |
| 3 | AI draft | 10 flat | balance < 10 |
| 4 | Spam check | 2 flat | balance < 2 |
| 5 | Campaign launch | leads × 3 | balance < (leads × 3) |

**Most users hit the wall at launch** — they've already done all the setup work and are motivated to complete it. This is the best natural paywall for conversion.

---

## Error Messages at Each Wall

```
Chat search with 0 balance:
→ "You have 0 credits. Top up to search for leads."

AI draft with balance < 10:
→ "AI draft costs 10 credits. You have 6. Top up to continue."

Spam check with balance < 2:
→ "Spam check costs 2 credits. You have 1. Top up to continue."

Launch with balance < (leads × 3):
→ "Launching to 20 leads costs 60 credits. You have 44. Top up 16 more credits."
```

---

## What Stays Free at 0 Balance

Even with 0 credits, users can still:
- Create campaigns (just can't launch)
- Write manual and template drafts
- Preview campaigns
- View inbox and replies
- Add leads to campaigns (if leads already in DB)

---

## Cost of One Full Campaign

| Action | Volume | Credits |
|---|---|---|
| Chat search | 20 leads found | 20 |
| Email enrichment | 12 emails found (60% hit) | 24 |
| AI draft | 1 draft | 10 |
| Spam check | 1 check | 2 |
| Launch | 20 emails sent | 60 |
| **Total** | | **~116 credits** |

**1 campaign end-to-end ≈ 100–120 credits**

---

## Pricing Tiers

| Tier | Price | Credits/month | Campaigns/month | Intent |
|---|---|---|---|---|
| **Free** | $0 | 150 (one-time, no refresh) | ~1 | Try the product once |
| **Starter** | $29/mo | 600 | ~5 | Small business |
| **Growth** | $79/mo | 1,800 | ~15 | Scaling team |
| **Scale** | $199/mo | 6,000 | ~50 | Agency / high volume |

### Credit Refresh Rules
- **Free tier** — one-time only, never refreshes, when gone → upgrade prompt
- **Paid tiers** — credits reset on billing date every month
- **Unused credits** — do NOT roll over (keeps it simple)
- **Optional for Growth/Scale** — allow up to 50% of unused credits to carry over to reduce churn

---

## Org API Costs Per Campaign

Since users connect their own SMTP, email sending = $0 to org.

| API | Details | Cost |
|---|---|---|
| Google Places | 20 leads found | ~$0.05 |
| Hunter.io enrichment | 12 emails found | ~$0.24 |
| OpenAI AI draft | 1 GPT-4 call | ~$0.02 |
| Spam check | 1 check | ~$0.005 |
| Email sending | User's own SMTP | $0 |
| **Total** | **per campaign** | **~$0.315** |

**1 credit costs org ~$0.0026**

---

## Profit Per Tier (Per User Per Month)

| Tier | Price | Credits | API Cost (100% use) | Stripe Fee | Net Profit | Margin |
|---|---|---|---|---|---|---|
| Free | $0 | 150 one-time | $0.39 (lifetime) | $0 | -$0.39 | — |
| Starter | $29 | 600 | $1.56 | $1.14 | **$26.30** | **90.7%** |
| Growth | $79 | 1,800 | $4.68 | $2.59 | **$71.73** | **90.8%** |
| Scale | $199 | 6,000 | $15.60 | $6.08 | **$177.32** | **89.1%** |

> Stripe fee = 2.9% + $0.30 per transaction

### At 70% Credit Utilization (realistic)

| Tier | API Cost | Net Profit | Margin |
|---|---|---|---|
| Starter | $1.09 | **$26.77** | 92.3% |
| Growth | $3.28 | **$73.13** | 92.6% |
| Scale | $10.92 | **$181.80** | 91.3% |

---

## Revenue Scenarios

### Scenario A — Early Stage (100 paying users)

| Tier | Users | MRR | API Cost | Net |
|---|---|---|---|---|
| Starter | 60 | $1,740 | $93.60 | $1,578 |
| Growth | 30 | $2,370 | $140.40 | $2,149 |
| Scale | 10 | $1,990 | $156 | $1,765 |
| **Total** | **100** | **$6,100** | **$390** | **$5,492** |

### Scenario B — Growth Stage (500 paying users)

| Tier | Users | MRR | API Cost | Net |
|---|---|---|---|---|
| Starter | 300 | $8,700 | $468 | $7,891 |
| Growth | 150 | $11,850 | $702 | $10,744 |
| Scale | 50 | $9,950 | $780 | $9,025 |
| **Total** | **500** | **$30,500** | **$1,950** | **$27,660** |

---

## Fixed Monthly Infrastructure Costs

| Cost | Estimated/month |
|---|---|
| Server (AWS/Railway/Vercel) | $50–$200 |
| Redis (Upstash) | $10–$30 |
| Hunter.io base plan | $49–$149 |
| OpenAI API | pay-as-you-go |
| Domain/SSL | ~$5 |
| **Total fixed** | **~$150–$400/mo** |

---

## Bottom Line

```
Early stage (100 users):
MRR:          $6,100
API costs:    -$390
Fixed costs:  -$300
──────────────────
Net profit:   ~$5,410/mo  (~88% margin)

Growth stage (500 users):
MRR:          $30,500
API costs:    -$1,950
Fixed costs:  -$400
──────────────────
Net profit:   ~$28,150/mo  (~92% margin)
```

---

## Why This Model Works

1. Users pay upfront for credits — cash flow is positive from day one
2. Unused credits = pure profit for the org
3. Email delivery cost is $0 (user's own account)
4. Margins improve as you scale (fixed costs stay flat)
5. Natural paywall at campaign launch — user is most motivated to convert at that exact moment

---

## Implementation Touch Points (Backend)

| Action | File | Where to add credit check |
|---|---|---|
| Chat search | `backend/app/api/v1/chat.py` | before calling `get_leads()` |
| Email enrichment | `backend/app/services/lead_generation_service.py` | before enrichment loop |
| AI draft | `backend/app/api/v1/campaign_draft.py:80` | before calling OpenAI |
| Spam check | `backend/app/api/v1/campaign_draft.py:87` | before spam check call |
| Campaign launch | `backend/app/api/v1/campaign_launch.py` | before creating email jobs |

### Credit Check Pattern (all endpoints follow this)

```python
# 1. Check balance before action
balance = await get_user_credits(user_id, db)
required = leads_count * CREDIT_COSTS["launch"]
if balance < required:
    raise HTTPException(
        status_code=402,
        detail=f"Insufficient credits. Need {required}, have {balance}."
    )

# 2. Perform the action
result = await do_the_action(...)

# 3. Deduct credits after success
await deduct_credits(user_id, required, action="campaign_launch", db=db)
```

### Credit Costs Config

```python
CREDIT_COSTS = {
    "lead_found": 1,
    "email_enriched": 2,
    "ai_draft": 10,
    "spam_check": 2,
    "email_sent": 3,
}

FREE_TIER_CREDITS = 150  # one-time on signup
```

### DB Tables Needed

```sql
-- User credit balance
user_credits (
    user_id        UUID FK,
    balance        INT DEFAULT 0,
    updated_at     TIMESTAMP
)

-- Credit transaction log
credit_transactions (
    id             UUID PK,
    user_id        UUID FK,
    amount         INT,          -- negative = deduct, positive = top-up
    action         VARCHAR,      -- "launch", "ai_draft", "purchase", etc.
    reference_id   UUID,         -- campaign_id or purchase_id
    created_at     TIMESTAMP
)
```
