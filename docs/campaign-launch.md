# Step 6 — Campaign Launch Flow

Launch is gated until generation, compliance, review, and sending setup are complete. Only approved per-lead emails are queued and sent.

## Flow

```
Review complete (Step 5)
  → GET /campaigns/{id}/launch/readiness (checklist)
  → User confirms launch
  → POST /campaigns/{id}/launch
  → Email jobs queued (staggered schedule)
  → Celery dispatcher → mail_job sends approved drafts
  → GET /campaigns/{id}/launch/status (progress)
  → Campaign marked COMPLETED when all jobs terminal
```

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/campaigns/{id}/launch/readiness` | Unified launch checklist |
| `POST` | `/campaigns/{id}/launch` | Queue approved leads |
| `GET` | `/campaigns/{id}/launch/status` | Send queue progress |

## Launch checklist

1. Campaign is draft
2. Email draft saved
3. No unresolved `[placeholders]`
4. Leads attached
5. Email sending method + mailbox available
6. Per-lead generation complete (if applicable)
7. User review complete — at least one approved

## Launch behavior

- Only **approved** leads are queued
- **Rejected** leads are skipped (`skipped_rejected` in response)
- Jobs are **staggered** (90s apart) to reduce burst sending
- `mail_job` requires approved per-lead draft when per-lead rows exist
- Campaign auto-completes when all jobs are `sent` or `failed`

## Frontend

- **`LaunchReadinessChecklist`** on preview step
- Launch confirmation modal with approved count
- Launch button disabled until `can_launch`

## Tests

```bash
cd backend && .venv/bin/pytest tests/unit/test_campaign_launch.py -v
```

## Deferred

- Domain warm-up scoring
- Sending reputation monitoring
