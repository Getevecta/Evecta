# Operations: environments, deploy, and commands

## Environments

| Environment | Frontend host | API base (typical) |
|-------------|----------------|---------------------|
| Local | `http://localhost:5173` | `http://localhost:8000` |
| Staging | `https://staging.evecta.io` | `https://staging.evecta.io/api` |
| Production | `https://evecta.io` | `https://evecta.io/api` |

The frontend resolves the API URL automatically in `Frontend/src/config/api.ts` (see **FRONTEND.md**). Backend CORS in `main.py` must include the frontend origin.

## Minimal local setup

1. **Backend** — Python 3.11 venv, `pip install -r requirements.txt`, configure `.env` using `app/core/config.py` as the checklist of variables.
2. **Database** — PostgreSQL reachable from the settings in `.env`.
3. **Redis** — For Celery and app features that use Redis.
4. **Frontend** — `npm install` and `npm run dev` in `Frontend/`.

Root **`README.md`** lists the basic uvicorn and Celery commands.

## CI / deploy

GitHub Actions workflow **`.github/workflows/deploy.yml`** (branch `main`):

- Installs frontend deps, runs `npm run build`, verifies output directory `Frontend/build/` (matches Vite `outDir`).
- Installs backend deps and runs a syntax check on `app/main.py`.
- SSH deploy step (secrets: host, key, user) — details are server-specific.

Staging may use **`.github/workflows/deploy-staging.yml`**.

## Celery

Workers and beat are required for scheduled and async tasks (email pipeline, etc.). See **`CELERY_CONCURRENCY_GUIDE.md`** for pool type and concurrency recommendations.

## Cost and integration notes (reference docs)

These live at the repo root and are not duplicated here:

- `backend/GOOGLE_PLACES_COST_OPTIMIZATION.md`, `GRID_SEARCH_COST.md`, `LEADS_COST_BY_LIMIT.md` — Places API usage and lead generation cost.
- `backend/cost-analysis.md` — General cost analysis.

## Frontend deployment / cache

See **`Frontend/deployment/README-CACHE-FIX.md`** — production should serve `index.html` with short or no cache so clients pick up new hashed JS/CSS after deploy.

## Security reminders for contributors

- Never commit `.env` or secrets.
- Webhook endpoints (`/webhook/*`) validate tokens or AWS signatures—preserve those checks when changing handlers.
- Rate limits (SlowAPI) protect auth and public forms—coordinate with backend when adding new public POST routes.
