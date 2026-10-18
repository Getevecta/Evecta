import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)
from app.services.chat_service import chat_guest, chat_guest_stream
from app.database.session import get_session
from app.models.lead_log import LeadLog
from app.models.user import User
from app.dependencies.auth import get_current_user_optional, get_current_user
from app.utils.redis_context import arun, get_or_create_thread_id, peek_thread_id, rotate_thread_id
from app.core.config import get_settings
from langchain_google_genai import ChatGoogleGenerativeAI
from app.schemas.chat import ChatRequest, ChatResetRequest
from app.schemas.response import BaseResponse
from app.core.limiter import limiter
from app.services.chat_graph import delete_chat_thread
from app.utils.chat_recovery import build_chat_timeout_recovery

CHAT_TIMEOUT_SECONDS = 90

router = APIRouter()


async def _recovery_for_graph_timeout(*, graph, config, message, db, user) -> dict:
    """After a graph timeout, pick search vs enrichment recovery from checkpoint + recent logs."""
    context: dict = {}
    try:
        snap = await graph.aget_state(config)
        values = getattr(snap, "values", None) or {}
        context = values.get("context") or {}
    except Exception:
        logger.warning("[CHAT] Could not read graph state after timeout", exc_info=True)

    saved_log_id = None
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=CHAT_TIMEOUT_SECONDS + 15)
        recent_log = await db.scalar(
            select(LeadLog)
            .where(
                LeadLog.user_id == user.id,
                LeadLog.query == message,
                LeadLog.created_at >= cutoff,
            )
            .order_by(LeadLog.created_at.desc())
            .limit(1)
        )
        if recent_log:
            saved_log_id = str(recent_log.id)
    except Exception:
        logger.warning("[CHAT] Could not look up lead log after timeout", exc_info=True)

    return build_chat_timeout_recovery(
        context,
        user_message=message,
        saved_log_id=saved_log_id,
    )

# --- Initialize LLM once ---
settings = get_settings()
llm = ChatGoogleGenerativeAI(
    model=settings.GEMINI_MODEL,
    google_api_key=settings.GEMINI_API_KEY,
    temperature=0.7,
    max_retries=1,  # fail fast on 429 instead of ~67s of backoff
)


@router.post("/chat", response_model=BaseResponse)
@limiter.limit("60/hour")
async def chat_route(
    request: Request,
    payload: ChatRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_current_user_optional),
):
    """
    Main chat entrypoint:
    - If guest: responds without saving to DB
    - If logged in: extracts query, fetches leads, stores to DB
    """
    try:
        message = payload.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="Message cannot be empty.")

        if user:
            # Authenticated turns run through the LangGraph graph, which owns the durable
            # conversation state via its checkpointer. The graph is always available
            # (Postgres or in-memory checkpointer — see main.py lifespan).
            graph = getattr(request.app.state, "chat_graph", None)
            if graph is None:
                raise HTTPException(status_code=503, detail="Chat is starting up. Please retry in a moment.")
            # Prefer a frontend-supplied conversation id (namespaced per user so one user
            # can't reach another's thread). New Chat = a new conversation_id = a fresh
            # thread, with no server-side rotate race. Older clients that don't send one
            # fall back to the per-user rotating thread.
            if payload.conversation_id:
                thread_id = f"{user.id}:{payload.conversation_id}"
            else:
                thread_id = await arun(get_or_create_thread_id, str(user.id))
            config = {"configurable": {
                "thread_id": thread_id,
                "message": message,
                "db": db,
                "llm": llm,
                "user": user,
                "background_tasks": background_tasks,
            }}
            try:
                final = await asyncio.wait_for(
                    graph.ainvoke({}, config),
                    timeout=CHAT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[CHAT] Graph timed out after %ss for user %s",
                    CHAT_TIMEOUT_SECONDS, user.id,
                )
                result = await _recovery_for_graph_timeout(
                    graph=graph,
                    config=config,
                    message=message,
                    db=db,
                    user=user,
                )
                return BaseResponse(
                    status="success",
                    message="Chat processed successfully.",
                    data=result,
                )
            result = final.get("last_turn") or {}
        else:
            result = await chat_guest(message, llm)

        return BaseResponse(status="success", message="Chat processed successfully.", data=result)

    except HTTPException:
        raise
    except Exception:
        logger.exception("Chat processing failed")
        raise HTTPException(status_code=500, detail="Chat processing failed. Please try again.")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/chat/stream")
@limiter.limit("60/hour")
async def chat_stream_route(
    request: Request,
    payload: ChatRequest,
    background_tasks: BackgroundTasks,
    user: User | None = Depends(get_current_user_optional),
):
    """
    Streaming counterpart to /chat. Emits Server-Sent Events:
      - {"type": "token", "content": "..."}   (repeated, the reply text as it's generated)
      - {"type": "done", "data": {...}}        (once, same shape as /chat's BaseResponse.data)
      - {"type": "error", "message": "..."}    (in place of "done", on failure)

    Note: unlike /chat, this does NOT take Depends(get_session) — for a StreamingResponse,
    FastAPI tears down yield-dependencies right after the route function returns, which
    happens almost immediately here (before event_stream() below has actually run). A
    session grabbed that way would already be closed by the time the graph tries to use
    it. Instead, the authenticated branch opens its own session from async_session_factory
    inside the generator, at the point the work actually happens.
    """
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    graph = None
    thread_id = None
    if user:
        graph = getattr(request.app.state, "chat_graph", None)
        if graph is None:
            raise HTTPException(status_code=503, detail="Chat is starting up. Please retry in a moment.")
        if payload.conversation_id:
            thread_id = f"{user.id}:{payload.conversation_id}"
        else:
            thread_id = await arun(get_or_create_thread_id, str(user.id))

    async def event_stream():
        try:
            if user:
                from app.database.session import async_session_factory
                from app.dependencies.auth import load_user_with_permissions
                from app.utils.chat_stream_sink import attach_token_queue, detach_token_queue

                async with async_session_factory() as stream_db:
                    fresh_user = await load_user_with_permissions(stream_db, user.id)
                    if fresh_user is None:
                        yield _sse({"type": "error", "message": "Chat processing failed. Please try again."})
                        return

                    token_q: asyncio.Queue = asyncio.Queue()
                    result_box: dict = {"result": {}, "error": None}

                    async def run_graph():
                        sink_token = attach_token_queue(token_q)
                        try:
                            config = {"configurable": {
                                "thread_id": thread_id,
                                "message": message,
                                "db": stream_db,
                                "llm": llm,
                                "user": fresh_user,
                                "background_tasks": background_tasks,
                            }}
                            try:
                                async with asyncio.timeout(CHAT_TIMEOUT_SECONDS):
                                    final = await graph.ainvoke({}, config)
                                    result_box["result"] = (final or {}).get("last_turn") or {}
                            except TimeoutError:
                                logger.warning(
                                    "[CHAT STREAM] Graph timed out after %ss for user %s",
                                    CHAT_TIMEOUT_SECONDS, user.id,
                                )
                                result_box["result"] = await _recovery_for_graph_timeout(
                                    graph=graph,
                                    config=config,
                                    message=message,
                                    db=stream_db,
                                    user=fresh_user,
                                )
                                result_box["error"] = None
                        except Exception as exc:
                            logger.exception("Chat streaming failed")
                            result_box["result"] = {
                                "status": "error",
                                "message": "Chat processing failed. Please try again.",
                                "context": {},
                                "recovery_kind": "understanding_failed",
                                "actions": [
                                    {"id": "retry_same", "label": "Try again", "message": message},
                                ],
                            }
                            result_box["error"] = None
                            result_box["exc"] = exc
                        finally:
                            detach_token_queue(sink_token)
                            await token_q.put(None)

                    graph_task = asyncio.create_task(run_graph())
                    try:
                        while True:
                            piece = await token_q.get()
                            if piece is None:
                                break
                            if piece:
                                yield _sse({"type": "token", "content": piece})
                        await graph_task
                    except Exception:
                        graph_task.cancel()
                        raise

                    if result_box.get("error"):
                        yield _sse({"type": "error", "message": result_box["error"]})
                        return
                    result = result_box["result"]
            else:
                result = {}
                async for ev in chat_guest_stream(message, llm):
                    if ev["type"] == "token":
                        yield _sse(ev)
                    else:
                        result = ev["data"]

            yield _sse({"type": "done", "data": result})
        except Exception:
            logger.exception("Chat streaming failed")
            yield _sse({"type": "error", "message": "Chat processing failed. Please try again."})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/reset")
async def reset_chat(
    request: Request,
    payload: ChatResetRequest = Body(default_factory=ChatResetRequest),
    user: User = Depends(get_current_user),
):
    """
    Explicitly reset the user's active chat (New Chat / open AI Lead Gen).

    Hard-deletes the abandoned thread's LangGraph checkpoints so old transcripts
    do not pile up. Long-term memory (recent searches, prefs) is left intact so
    greetings like "last time you searched hotels in …" still work.
    """
    graph = getattr(request.app.state, "chat_graph", None)
    user_key = str(user.id)
    deleted_ids: list[str] = []

    try:
        # Frontend-owned conversation: delete that exact namespaced thread.
        if payload.conversation_id:
            thread_id = f"{user.id}:{payload.conversation_id}"
            if await delete_chat_thread(graph, thread_id):
                deleted_ids.append(thread_id)

        # Fallback Redis/in-memory thread map (older clients / no conversation_id):
        # delete the mapped thread, then rotate to a fresh id.
        old_fallback = await arun(peek_thread_id, user_key)
        if old_fallback and old_fallback not in deleted_ids:
            if await delete_chat_thread(graph, old_fallback):
                deleted_ids.append(old_fallback)

        new_thread = await arun(rotate_thread_id, user_key)
        logger.info(
            "[CHAT RESET] User %s: deleted=%s new_fallback_thread=%s",
            user.id,
            deleted_ids or "none",
            new_thread,
        )
    except Exception:
        logger.exception("[CHAT RESET] Failed to reset chat for user %s", user.id)
        raise HTTPException(status_code=500, detail="Failed to reset chat. Please try again.")

    return {
        "status": "success",
        "message": "New chat started.",
    }