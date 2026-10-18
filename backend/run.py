"""
Local Windows launcher that enables the LangGraph Postgres checkpointer.

Why this exists: `uvicorn app.main:app` creates its asyncio event loop BEFORE it
imports app.main, so any policy set inside main.py is too late and psycopg async
fails with "cannot use ProactorEventLoop". This launcher sets the Selector loop
policy FIRST (at process start), then runs uvicorn in-process.

Use it only when you want durable conversation history locally on Windows:

    python run.py

Notes:
- reload is OFF here: uvicorn's --reload spawns a worker subprocess that would NOT
  inherit this policy, so the checkpointer would fail again. For normal dev with
  auto-reload, keep using `uvicorn app.main:app` (the chat works fine; durable
  history is simply skipped locally and works in production / on Linux).
- The Celery worker keeps its own command (Proactor loop), so Playwright scraping
  is unaffected.
- On Linux/production none of this matters — `uvicorn app.main:app` is correct.
"""
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
