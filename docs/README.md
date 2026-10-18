# Evecta / LeadZen — Developer documentation

This folder explains how the product is built so a new engineer can navigate the codebase, run it locally, and know where to change behavior.

| Document | What it covers |
|----------|----------------|
| [Frontend](./FRONTEND.md) | React/Vite app, routing, features, auth, API client |
| [Backend & API](./BACKEND-API.md) | FastAPI, routers, services, Celery, data model pointers |
| [Design system](./DESIGN.md) | Typography, spacing, Tailwind, dashboard UI patterns |
| [Operations](./OPERATIONS.md) | Environments, deploy, local commands, related repo docs |
| [Security audit](./SECURITY_AND_EFFICIENCY_FIXED.md) | Findings-only security and efficiency audit |
| [Security-first plan](./SECURITY_FIRST_PLAN.md) | Implementation order for security fixes |

**Quick repo map**

- **`Frontend/`** — Single-page app (Vite + React + TypeScript). Production build output: `Frontend/build/`.
- **`backend/`** — FastAPI application (`app/main.py`), SQLAlchemy models, Celery workers, tasks.

**Product surface (high level)**

1. **Marketing / public site** — Home, blog, about, contact, legal pages; guest **chat** for lead discovery.
2. **Auth** — Email/password, OTP verification, Google OAuth, password reset.
3. **Dashboard** (authenticated) — AI lead generation, lead database & logs, email campaigns, inbox, mailboxes/domains, billing (Stripe), profile.

For deep dives on specific subsystems, the repository root also contains focused notes (for example `INBOX_API_DOCS.md`, `backend/BILLING_API_DOCUMENTATION.md`, `CELERY_CONCURRENCY_GUIDE.md`). This `docs/` set ties them together with the architecture.
