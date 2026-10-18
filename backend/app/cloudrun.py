"""
Single-service entry point for Google Cloud Run.

Mirrors the production nginx layout in one process:
  /api/*  -> the unchanged FastAPI app (app.main:app), with the /api prefix stripped
  /*      -> the built React frontend, falling back to index.html for client-side routes

The frontend already calls `<origin>/api` (VITE_API_BASE_URL=/api at build time, and
`/api/auth/google/login` for Google sign-in), so nothing in app.main or the frontend
changes. Run with:

    uvicorn app.cloudrun:app --host 0.0.0.0 --port $PORT --proxy-headers

The existing VM deployment keeps using app.main:app behind nginx and never imports this.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from app.main import app as api_app

FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIST_DIR", "/app/frontend")).resolve()


class SPAStaticFiles(StaticFiles):
    """Static files that serve index.html for unknown paths (client-side routing)."""

    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # A missing hashed asset is a real 404; anything else is an app route.
            if exc.status_code != 404 or path.startswith("assets/"):
                raise
            response = await super().get_response("index.html", scope)
        if response.status_code == 404 and not path.startswith("assets/"):
            response = await super().get_response("index.html", scope)

        # index.html must not be cached (as in Frontend/deployment/nginx-cache-headers.conf)
        # so clients pick up new asset URLs; content-hashed assets can be cached for good.
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif isinstance(response, FileResponse) and str(response.path).endswith("index.html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Starlette does not run a mounted sub-app's lifespan, so run the API's own
    # startup/shutdown (Redis, DB check, chat graph, reply fetcher) explicitly.
    async with api_app.router.lifespan_context(api_app):
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Liveness probe that does not depend on the frontend build or the database."""
    return {"status": "ok"}


app.mount("/api", api_app)

if FRONTEND_DIR.is_dir():
    app.mount("/", SPAStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
