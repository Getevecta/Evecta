"""Routing: a product question is grounded, everything else on that branch is not,
and neither one disturbs the search the user is in the middle of."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services import chat_service as cs
from app.services.understanding import Understanding


def _run_understand_phase(understanding, context, history=None):
    """Drive the real conversational branch with the LLM and credit checks stubbed."""
    user = MagicMock()
    user.id = uuid4()
    db = AsyncMock()
    history = history if history is not None else []

    with (
        patch.object(cs, "understand", new=AsyncMock(return_value=understanding)),
        patch("app.services.credit_service.get_pool_balance", new=AsyncMock(return_value=25)),
        patch(
            "app.services.credit_service.repair_missing_subscription_credits",
            new=AsyncMock(return_value=None),
        ),
        patch.object(cs, "_knowledge_reply", new=AsyncMock(return_value="Grounded answer.")),
        patch.object(
            cs, "generate_human_response", new=AsyncMock(return_value="Ungrounded reply.")
        ) as ungrounded,
    ):
        result = asyncio.run(
            cs._understand_phase("does searching use my credits?", db, MagicMock(), user, context, history)
        )
    return result, ungrounded, context, history


def test_product_question_is_answered_from_the_corpus():
    """FR-1: about_evecta routes to grounded answering, not the free-form generator."""
    u = Understanding(intent="general_question", about_evecta=True)
    result, ungrounded, _, _ = _run_understand_phase(u, {})

    assert result["status"] == "conversation"
    assert result["message"] == "Grounded answer."
    ungrounded.assert_not_awaited()


def test_product_question_preserves_the_search_in_progress():
    """AC-3: slots and the pending confirmation survive; no search is started."""
    context = {
        "industry": "restaurants",
        "location": "Sydney",
        "country": "Australia",
        "awaiting_confirmation": True,
    }
    u = Understanding(intent="general_question", about_evecta=True)
    result, _, context_after, _ = _run_understand_phase(u, context)

    assert result["status"] == "conversation"  # not "searching", not "pending"
    assert context_after["industry"] == "restaurants"
    assert context_after["location"] == "Sydney"
    assert context_after["country"] == "Australia"
    assert context_after["awaiting_confirmation"] is True
    assert "leads" not in result


def test_world_knowledge_question_keeps_the_existing_reply():
    """AC-4 / FR-5: not about Evecta means no retrieval and no behaviour change."""
    u = Understanding(intent="general_question", about_evecta=False)

    with patch.object(cs, "retrieve", new=AsyncMock()) as retrieve:
        result, ungrounded, _, _ = _run_understand_phase(u, {})

    assert result["message"] == "Ungrounded reply."
    ungrounded.assert_awaited()
    retrieve.assert_not_awaited()


def test_greeting_is_never_grounded():
    u = Understanding(intent="greeting", about_evecta=False)
    result, ungrounded, _, _ = _run_understand_phase(u, {})

    assert result["message"] == "Ungrounded reply."
    ungrounded.assert_awaited()


def test_answer_is_appended_to_history():
    u = Understanding(intent="general_question", about_evecta=True)
    _, _, _, history = _run_understand_phase(u, {}, history=[])

    assert history[-1] == {"role": "assistant", "message": "Grounded answer."}


def test_guest_gets_a_grounded_answer_and_it_still_streams():
    """FR-11 plus FR-9: guests are answered from the corpus, token by token."""
    from tests.unit.test_knowledge_answering import StubLLM

    u = Understanding(intent="general_question", about_evecta=True)
    result = MagicMock()
    result.has_matches = True
    result.chunks = []

    async def _drain():
        return [
            event
            async for event in cs.chat_guest_stream("do searches cost credits?", StubLLM())
        ]

    with (
        patch.object(cs, "understand", new=AsyncMock(return_value=u)),
        patch.object(cs, "retrieve", new=AsyncMock(return_value=result)),
        patch.object(cs, "log_retrieval", new=AsyncMock()),
        patch.object(cs, "emit_chat_token", new=AsyncMock()),
        patch(
            "app.services.ai.tracked_llm._persist_usage_event",
            new=AsyncMock(return_value=None),
        ),
    ):
        events = asyncio.run(_drain())

    tokens = [e for e in events if e["type"] == "token"]
    assert len(tokens) > 1, "guest grounded answers must arrive incrementally"
    assert events[-1]["type"] == "done"
    assert events[-1]["data"]["message"] == "".join(t["content"] for t in tokens).strip()
