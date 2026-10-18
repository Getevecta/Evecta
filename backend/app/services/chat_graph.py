"""
LangGraph chat flow + checkpointer (Step 2b — the multi-node graph).

The conversation is a three-node state machine over a durable `ChatState`:

    START → understand ─(conversational / ambiguous / no-credits)─→ END
                       └─(continue)─→ interact ─(slot/clarify/scope/confirm)─→ END
                                              └─(proceed)─→ search → END

Each node reads conversation state (context + history) from the checkpointed
`ChatState`, runs one phase of the pipeline (`_understand_phase` / `_interact_phase`
/ `_search_phase` in chat_service), mutates the state in place, and writes it back —
the checkpointer (Postgres, or in-memory on the Windows Proactor loop) is the single
source of truth. Redis no longer holds conversation state.

Per-request, non-serializable dependencies (db session, user, background_tasks, llm,
the raw message) ride on `config["configurable"]` and are NOT checkpointed.

A 6-node split (promoting interact's slot/clarify/scope/confirm branches to their own
nodes) is a clean future step — see CHAT_INTELLIGENCE_SOLUTIONS.md — and not needed now.
"""

import logging
from datetime import datetime
from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from langchain_core.runnables import RunnableConfig

from app.services.chat_service import (
    _understand_phase,
    _interact_phase,
    _search_phase,
)
from app.utils.chat_history import compact_chat_history

logger = logging.getLogger(__name__)


class ChatState(TypedDict, total=False):
    messages: list      # durable transcript: [{"role": ..., "message": ...}, ...]
    context: dict       # resolved goal (industry/location/.../quality/ambiguous/...)
    last_turn: dict     # the full per-turn result returned to the API (serializable)
    route: str          # transient routing signal set by each node ("interact"/"search"/"end")


def _serializable(result: dict) -> dict:
    """Make the turn result safe to checkpoint (datetime -> ISO string)."""
    out = {}
    for k, v in (result or {}).items():
        out[k] = v.isoformat() if isinstance(v, datetime) else v
    return out


async def understand_node(state: ChatState, config: RunnableConfig) -> dict:
    """Phase 1 — understand + merge. Routes to `interact`, or ends the turn with a
    terminal reply (greeting / clarify / insufficient-credits)."""
    cfg = config["configurable"]
    context = dict(state.get("context") or {})
    history = compact_chat_history(state.get("messages"))
    out = await _understand_phase(cfg["message"], cfg["db"], cfg["llm"], cfg["user"], context, history)
    upd = {"context": context, "messages": compact_chat_history(history)}
    if out.get("_continue"):
        upd["route"] = "interact"
    else:
        upd["route"] = "end"
        upd["last_turn"] = _serializable(out)
    return upd


async def interact_node(state: ChatState, config: RunnableConfig) -> dict:
    """Phase 2 — slot-fill + clarify/scope/confirm gates. Routes to `search`, or ends
    the turn with a pending question."""
    cfg = config["configurable"]
    context = dict(state.get("context") or {})
    history = compact_chat_history(state.get("messages"))
    out = await _interact_phase(cfg["message"], cfg["db"], cfg["llm"], cfg["user"], context, history)
    upd = {"context": context, "messages": compact_chat_history(history)}
    if out.get("_continue"):
        upd["route"] = "search"
    else:
        upd["route"] = "end"
        upd["last_turn"] = _serializable(out)
    return upd


async def search_node(state: ChatState, config: RunnableConfig) -> dict:
    """Phase 3 — the full search + persistence pipeline. Always ends the turn."""
    cfg = config["configurable"]
    context = dict(state.get("context") or {})
    history = compact_chat_history(state.get("messages"))
    out = await _search_phase(
        cfg["message"], cfg["db"], cfg["llm"], cfg["user"], cfg["background_tasks"],
        context, history,
    )
    return {
        "context": context,
        "messages": compact_chat_history(history),
        "last_turn": _serializable(out),
        "route": "end",
    }


def _route_after_understand(state: ChatState) -> str:
    return "interact" if state.get("route") == "interact" else "end"


def _route_after_interact(state: ChatState) -> str:
    return "search" if state.get("route") == "search" else "end"


async def delete_chat_thread(graph, thread_id: str) -> bool:
    """Hard-delete all checkpointer rows for one conversation thread.

    Used by New Chat (/chat/reset). Long-term memory (user_memory_items) is separate
    and is never touched here. Returns True when delete was attempted successfully,
    False when there is no checkpointer or delete failed (caller should still rotate).
    """
    if not thread_id or graph is None:
        return False
    checkpointer = getattr(graph, "checkpointer", None)
    if checkpointer is None:
        logger.warning("[CHAT] delete_chat_thread: graph has no checkpointer")
        return False
    try:
        await checkpointer.adelete_thread(str(thread_id))
        logger.info("[CHAT] Deleted checkpointer thread %s", thread_id)
        return True
    except Exception:
        logger.exception("[CHAT] Failed to delete checkpointer thread %s", thread_id)
        return False


def build_chat_graph(checkpointer):
    """Compile the three-node chat graph with the given checkpointer."""
    g = StateGraph(ChatState)
    g.add_node("understand", understand_node)
    g.add_node("interact", interact_node)
    g.add_node("search", search_node)

    g.add_edge(START, "understand")
    g.add_conditional_edges("understand", _route_after_understand, {"interact": "interact", "end": END})
    g.add_conditional_edges("interact", _route_after_interact, {"search": "search", "end": END})
    g.add_edge("search", END)

    return g.compile(checkpointer=checkpointer)
