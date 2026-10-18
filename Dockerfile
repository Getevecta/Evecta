# Evecta — single Cloud Run service (React frontend + FastAPI backend)
#
#   /api/*  -> FastAPI (backend/app/main.py, mounted by backend/app/cloudrun.py)
#   /*      -> built React app from Frontend/
#
# Build:  docker build -t evecta .
# Run:    docker run -p 8080:8080 --env-file backend/.env evecta
#
# Configuration comes from APP_* environment variables (see backend/.env.example);
# no .env file is baked into the image.

# ── Stage 1: build the frontend ───────────────────────────────────────────────
FROM node:20-slim AS frontend

WORKDIR /src/Frontend

COPY Frontend/package.json Frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY Frontend/ ./

# Same-origin API: the backend is served under /api by this container.
# VITE_ENABLE_BANNER_PREVIEW matches the existing production build.
ARG VITE_API_BASE_URL=/api
ARG VITE_SITE_URL=
ARG VITE_ENABLE_BANNER_PREVIEW=true
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_SITE_URL=${VITE_SITE_URL} \
    VITE_ENABLE_BANNER_PREVIEW=${VITE_ENABLE_BANNER_PREVIEW}

RUN npm run build

# ── Stage 2: backend runtime ──────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080 \
    FRONTEND_DIST_DIR=/app/frontend

# libpq5: runtime library for psycopg 3 (installed without its bundled binary).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
COPY --from=frontend /src/Frontend/build /app/frontend

# Run as a non-root user with a writable home (DuckDB stores its extensions there).
RUN useradd --create-home --uid 10001 evecta \
    && chown -R evecta:evecta /app
USER evecta

EXPOSE 8080

# Cloud Run sets $PORT (8080). One worker: the API process also runs the in-process
# reply fetcher loop, which must not be duplicated. Scale with Cloud Run instances.
CMD ["sh", "-c", "exec uvicorn app.cloudrun:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips '*' --workers 1"]
