<div align="center">

# Evecta

**AI-powered B2B lead generation and cold email outreach, in one workflow.**

Find the right businesses, write a personalized email for each one, check it for spam risk,
send it from a real mailbox, and manage every reply — without stitching together five tools.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-PostGIS-4169E1?logo=postgresql&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-Redis-37814A?logo=celery&logoColor=white)

</div>

---

## Table of contents

- [Overview](#overview)
- [Features](#features)
- [How it works](#how-it-works)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Running tests](#running-tests)
- [Documentation](#documentation)
- [License](#license)

## Overview

Evecta is built for founders, small and medium businesses, and sales teams who rely on outbound
sales. A user describes the businesses they want to reach — by industry, market, or location —
and Evecta finds matching prospects, drafts an email tailored to each prospect's business,
and runs the campaign end to end, from sending to tracking opens and replies.

## Features

| | Feature | What it does |
|---|---|---|
| 🔎 | **AI Lead Generation** | Describe a target audience in plain language; Evecta resolves it to business categories and returns matching prospects with contact details. |
| 🗂️ | **Search History & Lead Database** | Every search is kept permanently; selected prospects are saved to a curated, editable lead list. Leads can also be imported from Excel. |
| ✍️ | **AI-Personalized Emails** | One draft per lead, written from the campaign goal and that prospect's business context — not just a name swap. |
| 🛡️ | **Spam Check** | Scores a message for spam and deliverability risk before it is sent. |
| 📬 | **Mailbox Integration** | Send from a connected Google or IMAP/SMTP mailbox, or from an Evecta warmed address. |
| 🚀 | **Campaign Management** | Pick leads, review drafts, schedule sending, and respect per-mailbox sending limits. |
| 📥 | **Unified Inbox** | Prospect replies are threaded per campaign and can be answered without leaving Evecta. |
| 📊 | **Campaign Insights** | Opens, replies, bounces, unsubscribes, and unopened emails at a glance. |
| 💬 | **AI Assistant** | A chat assistant that runs lead searches and answers product questions from a curated knowledge base. |
| 💳 | **Credits & Billing** | Monthly plans and credit top-ups through Stripe, with per-feature usage tracking. |

## How it works

```
Describe audience ─► Generate leads ─► Save to Lead Database ─► Create campaign
        │                                                           │
        ▼                                                           ▼
  AI assistant              Personalized drafts ─► Spam check ─► Send from mailbox
                                                                    │
                                     Campaign Insights ◄─ Unified Inbox ◄─ Replies
```

Lead discovery draws on open [Overture Maps](https://overturemaps.org/) places data (queried with
DuckDB and cached by area in PostGIS) alongside Google Places, and contacts are enriched in the
background. Long-running work — enrichment, sending, reply fetching, and scheduled refreshes —
runs on Celery workers.

## Tech stack

**Backend**
- [FastAPI](https://fastapi.tiangolo.com/) with async [SQLAlchemy](https://www.sqlalchemy.org/) and [Alembic](https://alembic.sqlalchemy.org/) migrations
- PostgreSQL with the **PostGIS** and **pg_trgm** extensions
- [Celery](https://docs.celeryq.dev/) workers and beat scheduler, backed by **Redis**
- Google Gemini via [LangChain](https://www.langchain.com/) / [LangGraph](https://www.langchain.com/langgraph) for lead understanding, email writing, and chat
- DuckDB for querying Overture Maps data
- Stripe (billing), Amazon SES and Brevo (email delivery), Google OAuth (sign-in and mailboxes)

**Frontend**
- React + TypeScript, built with [Vite](https://vitejs.dev/)
- Tailwind CSS, Radix UI, and MUI components
- React Router, Framer Motion / GSAP for animation, Recharts for charts

## Project structure

```
.
├── backend/               FastAPI application
│   ├── app/
│   │   ├── api/           HTTP routers (auth, leads, campaigns, inbox, billing, …)
│   │   ├── services/      Business logic (lead generation, email, AI, billing)
│   │   ├── models/        SQLAlchemy models
│   │   ├── schemas/       Pydantic request/response schemas
│   │   ├── tasks/         Celery tasks
│   │   ├── email_engine/  Sending and reply handling
│   │   ├── knowledge/     Knowledge base used by the AI assistant
│   │   └── main.py        Application entry point
│   ├── alembic/           Database migrations
│   └── tests/             Unit and integration tests
├── Frontend/              React single-page app (marketing site, auth, dashboard)
│   └── src/features/      Feature modules: dashboard, auth, homepage, blog, …
└── docs/                  Architecture and developer documentation
```

## Getting started

### Prerequisites

- **Python 3.11**
- **Node.js 18+** and npm
- **PostgreSQL** with the **PostGIS** extension available
- **Redis**

### 1. Backend
The API runs at `http://localhost:8000`, with interactive docs at `http://localhost:8000/docs`.


### 2. Frontend

The app runs at `http://localhost:5173`. Create `Frontend/.env` and point it at the API:

```env
VITE_API_BASE_URL=http://localhost:8000
```

For a production build, run `npm run build`; output goes to `Frontend/build/`.

`app/core/config.py` is the authoritative list, including defaults.

## Documentation

Detailed developer documentation lives in [`docs/`](./docs/README.md):

- [Frontend architecture](./docs/FRONTEND.md) — routing, features, auth, API client
- [Backend & API](./docs/BACKEND-API.md) — routers, services, Celery, data model
- [Design system](./docs/DESIGN.md) — typography, spacing, UI patterns
- [Operations](./docs/OPERATIONS.md) — environments, deployment, local commands
- [Overture lead generation](./docs/OVERTURE_LEAD_GENERATION.md) — how lead discovery works

## License

This repository does not include an open-source license. All rights reserved.
