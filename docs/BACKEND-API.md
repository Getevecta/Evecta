# Backend and API

## Stack

| Piece | Location / notes |
|-------|------------------|
| Framework | FastAPI (`backend/app/main.py`) |
| Database | PostgreSQL + SQLAlchemy async sessions (`app/database/`) |
| Cache / broker | Redis — sessions, rate limiting support, Celery broker |
| Background jobs | Celery (`app/core/celery_app.py`) + beat schedule |
| Email | Brevo API, SMTP (OTP, contact form), AWS SES webhooks |
| Payments | Stripe (billing router) |
| LLM | Google Gemini via LangChain (`chat` and related services) |
| Maps / places | Google Maps / Places (lead enrichment; see cost docs in repo root) |

**Settings** are loaded from environment via Pydantic (`app/core/config.py`): database URL, JWT secrets, Google OAuth, Gemini, Brevo, Stripe, Redis, SMTP, etc.

## Application lifecycle

On startup (`lifespan` in `main.py`):

1. Initialize Redis.
2. Check database connectivity.
3. If DB is up, start the **reply fetcher** background loop (`reply_fetcher_loop` from `app/core/scheduler.py`).

Shutdown closes Redis cleanly.

## HTTP middleware and cross-cutting concerns

- **SlowAPI** — rate limiting (`app.state.limiter`, `RateLimitExceeded` handler).
- **Security headers** — `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, HSTS on HTTPS.
- **CORS** — allows local Vite (`http://localhost:5173`) and production/staging Evecta domains; `allow_credentials=True` for refresh-token cookies.

## Health endpoints

| Path | Purpose |
|------|---------|
| `GET /` | Project name / success payload |
| `GET /health` | Process liveness |
| `GET /ready` | DB + Redis readiness (503 if not ready) |

## Router map (prefixes)

Routers are included at the **app root** in FastAPI (no global `/api` prefix in Python). In production, the reverse proxy typically serves the same logical paths under the host’s `/api` base URL that the frontend uses—so a route defined as `/auth/login` is called as `{BASE_URL}/auth/login` where `BASE_URL` is `https://evecta.io/api` in production or `http://localhost:8000` locally.

| Prefix / file | Responsibility |
|---------------|----------------|
| `/auth` — `auth.py` | Login, register, refresh, logout, me, password, waitlist status, forgot/reset password |
| `/auth/google` — `google_auth.py` | Google OAuth login/callback |
| `/otp` — `otp.py` | Email OTP verification flows |
| `/users` — `user.py` | User profile CRUD |
| `/roles` — `role.py` | Roles and permissions |
| `/chat`, `/chat/reset` — `chat.py` | AI chat (guest vs authenticated); rate limited |
| `/leads` — `lead.py` | Lead CRUD, logs, enrichment, promotion, etc. |
| `/campaigns` — `campaign.py`, `campaign_launch.py`, `campaign_preview.py`, `campaign_insight.py` | Campaigns, launch, preview, insights |
| `/campaigns/{id}/draft` — `campaign_draft.py` | Draft content |
| `/campaigns/{id}/leads` — `campaign_lead.py` | Leads attached to a campaign |
| `/campaign-categories` — `campaign_category.py` | Categories |
| `/campaign-goals` — `campaign_goal.py` | Goals |
| `/email-templates` — `email_template.py` | Templates |
| `/company` — `company.py` | Company profile |
| `/domains` — `domain.py` | Sending domains |
| `/mailboxes` — `mailbox.py` | User mailboxes |
| `/system/domains`, `/system/mailboxes` — `system_domain.py`, `system_mailbox.py` | Managed pool (admin/system) |
| `/inbox` — `inbox.py` | Threaded inbox (campaign threads, replies) |
| `/emails` — `email_replies.py` | Email reply handling |
| `/email-accounts` — `email_insight.py` | Account-level insights |
| `/billing` — `billing.py` | Stripe checkout, subscriptions, credits |
| `/contact` — `contact.py` | Public contact form (rate limited) |
| `/webhook/email-events` — `webhook_brevo.py` | Brevo events (token: `X-Key`) |
| `/webhook/ses` — `webhook_ses.py` | AWS SES / SNS notifications |
| `/v1/unsubscribe` — `unsubscribe.py` | Unsubscribe / preferences links in emails |

**Note:** Some generated email links use `/api/v1/unsubscribe/...` on the public site; the router prefix is `/v1/unsubscribe` on the API host—confirm nginx/host mapping in deployment if debugging link 404s.

## Services and tasks

Business logic lives under `app/services/` (chat, campaigns, lead enrichment, billing, email sending, etc.). Long-running or scheduled work uses **`app/tasks/`** with Celery. Beat schedule is configured in `celery_app.py`.

## Data model (SQLAlchemy)

Models live in `backend/app/models/` — for example `user.py`, `lead.py`, `lead_log.py`, `campaign.py`, `campaign_lead.py`, `mailbox.py`, `domain.py`, `email_thread.py`, `email_message.py`, `credit.py`, `company.py`, etc. Use these as the source of truth for DB schema relationships.

## API documentation elsewhere

- **`INBOX_API_DOCS.md`** — Inbox thread levels, endpoints, examples (may reference `/api/v1` as a logical API base; align with actual deployment path).
- **`backend/BILLING_API_DOCUMENTATION.md`** — Billing and Stripe-related API details.
- **`TOPUP_API.md`**, **`PRICING_AND_LEAD_GENERATION.md`**, **`CREDIT_SYSTEM_PLAN.md`** — Credits and pricing behavior.

## Local backend commands

From `backend/` (after venv and `.env`):

```bash
uvicorn app.main:app --reload
celery -A app.core.celery_app.celery_app beat -l info
celery -A app.core.celery_app worker -P threads -c 4 --loglevel=info
```

See `CELERY_CONCURRENCY_GUIDE.md` for worker tuning.

Interactive API docs: FastAPI auto-generates **OpenAPI** at `/docs` and `/redoc` when the server runs locally.
