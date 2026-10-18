# Personalization Level Engine (Step 2)

Plan-tiered personalization depth, lead context scoring, tone selection, and
per-lead profiles that downstream email generation consumes.

Cross-references: Evecta Outreach Intelligence architecture §2, [`lead-enrichment-collection.md`](lead-enrichment-collection.md) §3 (context collection).

---

## 1. Purpose

The engine answers, for each lead in a campaign:

> Given the user's **subscription plan**, chosen **tone**, and **available lead context** — how deep should personalization go?

It does **not** send emails or run compliance (Steps 4–6). It is the decision layer between enrichment (Step 1) and template/generation (Steps 3–4).

```
Lead context (Step 1)  +  User plan  +  User tone
              ↓
    Personalization Level Engine
              ↓
    PersonalizationProfile (per lead)
              ↓
    AI draft / per-lead generation (Steps 3–4)
```

---

## 2. Plan tiers

| Plan | Max depth | Context fields used |
|------|-----------|---------------------|
| **Free** | `basic` | `business_name`, `industry`, `address` |
| **Starter** | `standard` | + `website_summary` |
| **Growth** | `deep` | + `services`, `business_description` |
| **Scale** | `deep` | Same as Growth; `external_research` flag for future Perplexity |

Config: [`backend/app/core/personalization.py`](../backend/app/core/personalization.py)

---

## 3. Context scoring

Each lead is scored from enrichment fields (never invented):

| Score | Condition |
|-------|-----------|
| `full` | All three: `services`, `website_summary`, `business_description` |
| `partial` | One or two present |
| `none` | None present |

**Effective depth** = `min(plan_max_depth, context_max_depth)`:

- `full` context → up to plan max
- `partial` → capped at `standard`
- `none` → `basic`, `fallback: sender_profile`

Implementation: [`personalization_service.py`](../backend/app/services/personalization_service.py)

---

## 4. Tone selection

User-selectable tones (campaign email step):

- professional, friendly, casual, partnership-focused, soft-introduction

Stored on `campaigns.tone`. Orthogonal to plan — plan controls **how much** context; tone controls **how it's written**.

---

## 5. Data model

| Table / field | Role |
|---------------|------|
| `campaigns.tone` | Selected tone for the campaign |
| `campaign_leads.services` | Snapshot at sync time |
| `campaign_leads.website_summary` | Snapshot at sync time |
| `campaign_leads.business_description` | Snapshot at sync time |

On lead sync (`sync_campaign_leads`):

- New leads get a full snapshot including context fields.
- Retained leads refresh context snapshot (enrichment may have finished since last visit).

Migrations:

- `d4e8f1a2b3c4_campaign_personalization_fields.py`
- `e5f9a2b3c4d5_backfill_campaign_lead_context_snapshot.py` (backfill from `leads`)

---

## 6. API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/personalization/capabilities` | Plan limits + tone options |
| GET | `/campaigns/{id}/personalization` | Per-lead profiles + summary counts |
| GET | `/campaigns/{id}/leads` | Includes `context_score`, `effective_depth` |
| POST | `/campaigns/{id}/draft/ai` | Saves `tone`; uses engine for lead samples |

---

## 7. UI

| Surface | What users see |
|---------|----------------|
| Campaign step 2 (lead pick) | Context badges: Rich / Partial / Thin |
| Campaign email step (AI) | Tone dropdown, plan hint, lead context summary |
| Campaign detail | Context column on lead table |

Frontend helpers: `leadContextScore.ts`, `ContextScoreBadge.tsx`

---

## 8. Graceful degradation

When lead context is thin:

1. Use mail-merge fields (`business_name`, `industry`, `address`).
2. Lean on sender `Company` profile (`fallback: sender_profile`).
3. Flag in UI (`thin_context: true`, badge).
4. Never LLM-invent lead descriptions.

---

## 9. Out of scope (later steps)

| Step | Not included here |
|------|-------------------|
| 4 | Per-lead unique AI emails, background queues, compliance (uses `WritingSpec` + `repetition.py`) |
| 5 | Batch approve / regenerate / reject UI |
| 1 (improvement) | Perplexity fallback for Scale, lead-website caching |
| 3 (enhancement) | `scoring.py` performance-based variant weighting |

---

## 10. Step 3 integration (Template + Variation Engine)

- Markdown rules: `backend/app/email_engine/rules/`
- Bridge: `backend/app/services/writing_spec_service.py`
- Prompt rendering: `backend/app/email_engine/prompt_builder.py`
- Wired into AI draft: `campaign_draft_service.py` → `ai_email_generator.py`
- Preview API includes `writing_spec` per lead on `GET /campaigns/{id}/personalization`

---

## 11. Tests

`backend/tests/unit/test_personalization.py` — Step 2 engine.

`backend/tests/unit/test_email_engine.py` — Step 3 loader, variation, spec builder, repetition.

Run: `pytest tests/unit/test_personalization.py tests/unit/test_email_engine.py`
