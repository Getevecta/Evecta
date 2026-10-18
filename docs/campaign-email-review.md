# Step 5 — User Review

After Step 4 generates per-lead emails, users review each draft before launch.

## Flow

```
Step 4 complete → Preview step shows review list
  → Approve / Reject / Regenerate per lead
  → "Approve all ready" batch action
  → Launch enabled when review gate passes
  → Only approved leads are queued on launch
```

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/campaigns/{id}/emails/review` | Review summary + `can_launch` |
| `POST` | `/campaigns/{id}/emails/review/approve` | Approve by ids or `approve_all` |
| `POST` | `/campaigns/{id}/emails/review/reject` | Reject by ids or `reject_all_pending` |
| `POST` | `/campaigns/{id}/emails/{email_id}/regenerate` | Regenerate one lead email |

## Launch rules

When `campaign_lead_emails` rows exist:

1. Generation must be finished (no `pending` / `generating`)
2. Every row must be **approved** or **rejected** (no pending review)
3. At least **one** email must be approved
4. Only **approved** leads are queued in `launch_campaign_service`
5. `mail_job` only sends per-lead drafts with `review_status = approved`

Campaigns without per-lead rows keep the legacy single-template launch path.

## Frontend

- **`CampaignEmailReview`** — list with approve / reject / regenerate + approve all
- **`PreviewCampaignDetail`** — review section on Step 5 (preview), launch button gated on `can_launch`

## Tests

```bash
cd backend && .venv/bin/pytest tests/unit/test_campaign_email_review.py -v
```
