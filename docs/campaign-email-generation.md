# Step 4 — AI Email Generation + Compliance

Per-lead email generation runs after the user completes Step 3 (campaign draft). Each lead gets a unique email draft stored in `campaign_lead_emails`, validated through the compliance gate before send.

## Flow

```
Step 3 draft saved → POST /campaigns/{id}/emails/generate
  → First 3 leads: synchronous generation
  → Remaining leads: Celery `generate_campaign_emails_task`
  → Each lead: WritingSpec (#3) + LLM (#4) OR template merge
  → Compliance gate (hard phrases + spam score)
  → Repetition guard re-roll if too similar to prior emails
  → Save row (generation_status, compliance_status)
```

At send time, `mail_job` prefers a ready + compliance-passed per-lead draft over the campaign-level template.

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/campaigns/{id}/emails/generate` | Start/restart generation |
| `GET` | `/campaigns/{id}/emails/status` | Progress summary |
| `GET` | `/campaigns/{id}/emails` | List per-lead drafts |

## Model: `campaign_lead_emails`

- `subject`, `body` — per-lead draft (merge fields preserved)
- `generation_status` — `pending` \| `generating` \| `ready` \| `failed`
- `compliance_status` — `pending` \| `passed` \| `failed`
- `review_status` — reserved for Step 5 user review
- `variant_metadata` — JSON summary of writing spec used
- `regeneration_count` — compliance/repetition retries

## Compliance gate

`app/services/compliance_gate.py`:

1. Hard-blocked phrases from `email_engine/rules` (`get_prohibited_phrases`)
2. Aggressive sales pattern checks
3. Spam checker LLM score (`score_only=True`) — inbox safety ≥ 58%

Failed drafts auto-retry up to 3 times with a bumped variation index.

## Generation modes

| `draft_type` | Behavior |
|--------------|----------|
| `AI` | `generate_per_lead_email()` with per-lead `WritingSpec` |
| `TEMPLATE` / `MANUAL` | Placeholder merge from campaign draft + compliance only |

## Frontend

- **CreateCampaign**: triggers `generateCampaignLeadEmails` when advancing Step 3 → 4
- **PreviewCampaignDetail**: polls `/emails/status` and shows first lead's generated email when ready

## Celery

Task: `app.tasks.generate_campaign_emails.generate_campaign_emails_task`

Registered in `celery_app.py` alongside `enrich_leads` and `mail_job`.

## Migration

```bash
cd backend && .venv/bin/alembic upgrade head
# Head: f6a7b8c9d0e1
```

## Tests

```bash
cd backend && .venv/bin/pytest tests/unit/test_campaign_email_generation.py -v
```

## Deferred

- Credit charging per generated email
- Manual inline edit of subject/body during review
