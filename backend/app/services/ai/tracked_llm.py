from __future__ import annotations

import logging
import time
import uuid
from typing import Any, AsyncIterator, Optional, Union
from uuid import UUID

from app.services.ai.adapters import extract_usage_metadata, normalize_usage
from app.services.ai.pricing import estimate_cost_usd
from app.services.ai.token_usage import TokenUsage

logger = logging.getLogger(__name__)


def llm_model_name(llm: Any, fallback: str = "unknown") -> str:
    """Best-effort model id from a LangChain chat model instance."""
    for attr in ("model", "model_name", "model_id"):
        val = getattr(llm, attr, None)
        if val:
            return str(val)
    return fallback


def _coerce_user_id(user_id: Optional[Union[str, UUID]]) -> Optional[UUID]:
    if user_id is None:
        return None
    if isinstance(user_id, UUID):
        return user_id
    try:
        return UUID(str(user_id))
    except (TypeError, ValueError):
        return None


def _request_id_from_response(response: Any) -> Optional[str]:
    if response is None:
        return None
    rid = getattr(response, "id", None)
    if rid:
        return str(rid)[:128]
    if isinstance(response, dict):
        raw = response.get("raw")
        if raw is not None:
            return _request_id_from_response(raw)
    meta = getattr(response, "response_metadata", None) or {}
    if isinstance(meta, dict):
        for key in ("request_id", "id", "response_id"):
            if meta.get(key):
                return str(meta[key])[:128]
    return None


async def _persist_usage_event(
    *,
    user_id: Optional[Union[str, UUID]],
    feature: str,
    provider: str,
    model: str,
    usage: TokenUsage,
    latency_ms: int,
    status: str,
    request_id: Optional[str],
) -> None:
    """Write a usage row in an isolated session. Never raises to the caller."""
    try:
        cost, in_rate, out_rate = estimate_cost_usd(provider, model, usage)
        from app.database.session import async_session_factory
        from app.models.ai_usage_event import AiUsageEvent

        async with async_session_factory() as session:
            event = AiUsageEvent(
                id=uuid.uuid4(),
                user_id=_coerce_user_id(user_id),
                feature=(feature or "unknown")[:64],
                provider=(provider or "unknown")[:32],
                model=(model or "unknown")[:128],
                input_tokens=int(usage.input_tokens or 0),
                output_tokens=int(usage.output_tokens or 0),
                reasoning_tokens=int(usage.reasoning_tokens or 0),
                cached_tokens=int(usage.cached_tokens or 0),
                total_tokens=int(usage.total_tokens or 0),
                input_rate_per_million=in_rate,
                output_rate_per_million=out_rate,
                estimated_cost_usd=cost,
                latency_ms=latency_ms,
                status=status[:16],
                request_id=(request_id[:128] if request_id else None),
            )
            session.add(event)
            await session.commit()
    except Exception:
        logger.warning(
            "[AI_USAGE] Failed to persist usage event feature=%s provider=%s model=%s",
            feature,
            provider,
            model,
            exc_info=True,
        )


async def tracked_ainvoke(
    *,
    llm: Any,
    prompt: Any,
    provider: str,
    model: str,
    feature: str,
    user_id: Optional[Union[str, UUID]] = None,
):
    """
    Invoke an async chat model and record token usage.

    Returns the original model response. Usage-tracking failures never fail the request.
    """
    started = time.perf_counter()
    status = "success"
    response = None
    caught: Optional[BaseException] = None
    try:
        response = await llm.ainvoke(prompt)
        return response
    except Exception as e:
        status = "failed"
        caught = e
        raise
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            raw_meta = extract_usage_metadata(response) if response is not None else {}
            usage = normalize_usage(provider, raw_meta)
            rid = _request_id_from_response(response)
            await _persist_usage_event(
                user_id=user_id,
                feature=feature,
                provider=provider,
                model=model,
                usage=usage,
                latency_ms=latency_ms,
                status=status,
                request_id=rid,
            )
        except Exception:
            logger.warning("[AI_USAGE] tracked_ainvoke post-process failed", exc_info=True)
        if caught is not None and (provider or "").lower() == "gemini":
            try:
                from app.services.gemini_status_service import record_gemini_api_error

                await record_gemini_api_error(
                    exc=caught,
                    feature=feature,
                    model=model,
                    user_id=user_id,
                )
            except Exception:
                logger.warning("[GEMINI_STATUS] tracked_ainvoke status hook failed", exc_info=True)


def tracked_invoke(
    *,
    llm: Any,
    prompt: Any,
    provider: str,
    model: str,
    feature: str,
    user_id: Optional[Union[str, UUID]] = None,
):
    """
    Sync invoke wrapper. Persists usage via a short-lived async loop when needed,
    otherwise fire-and-forget through asyncio if a loop is already running.
    """
    import asyncio

    started = time.perf_counter()
    status = "success"
    response = None
    caught: Optional[BaseException] = None
    try:
        response = llm.invoke(prompt)
        return response
    except Exception as e:
        status = "failed"
        caught = e
        raise
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            raw_meta = extract_usage_metadata(response) if response is not None else {}
            usage = normalize_usage(provider, raw_meta)
            rid = _request_id_from_response(response)

            async def _save():
                await _persist_usage_event(
                    user_id=user_id,
                    feature=feature,
                    provider=provider,
                    model=model,
                    usage=usage,
                    latency_ms=latency_ms,
                    status=status,
                    request_id=rid,
                )
                if caught is not None and (provider or "").lower() == "gemini":
                    from app.services.gemini_status_service import record_gemini_api_error

                    await record_gemini_api_error(
                        exc=caught,
                        feature=feature,
                        model=model,
                        user_id=user_id,
                    )

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                loop.create_task(_save())
            else:
                asyncio.run(_save())
        except Exception:
            logger.warning("[AI_USAGE] tracked_invoke post-process failed", exc_info=True)


async def tracked_astream(
    *,
    llm: Any,
    messages: Any,
    provider: str,
    model: str,
    feature: str,
    user_id: Optional[Union[str, UUID]] = None,
    config: Optional[dict] = None,
) -> AsyncIterator[Any]:
    """
    Stream ``llm.astream(...)`` chunk by chunk, tracking usage the same way as
    ``tracked_ainvoke``/``tracked_agenerate`` once the stream ends.

    Providers don't reliably put ``usage_metadata`` on the last chunk (Gemini
    puts it on the first content-bearing chunk and zeroes it out afterward), so
    usage is read off the chunks summed together via ``+`` rather than off any
    single chunk.
    """
    started = time.perf_counter()
    status = "success"
    accumulated = None
    try:
        from app.utils.chat_stream_sink import content_to_text, emit_chat_token

        async for chunk in llm.astream(messages, config=config):
            accumulated = chunk if accumulated is None else accumulated + chunk
            text = content_to_text(getattr(chunk, "content", None))
            if text:
                await emit_chat_token(text)
            yield chunk
    except Exception:
        status = "failed"
        raise
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            raw_meta = extract_usage_metadata(accumulated) if accumulated is not None else {}
            usage = normalize_usage(provider, raw_meta)
            rid = _request_id_from_response(accumulated)
            await _persist_usage_event(
                user_id=user_id,
                feature=feature,
                provider=provider,
                model=model,
                usage=usage,
                latency_ms=latency_ms,
                status=status,
                request_id=rid,
            )
        except Exception:
            logger.warning("[AI_USAGE] tracked_astream post-process failed", exc_info=True)


async def tracked_agenerate(
    *,
    llm: Any,
    messages: Any,
    provider: str,
    model: str,
    feature: str,
    user_id: Optional[Union[str, UUID]] = None,
):
    """Track ``llm.agenerate(...)`` the same way as ``tracked_ainvoke``."""
    started = time.perf_counter()
    status = "success"
    response = None
    caught: Optional[BaseException] = None
    try:
        response = await llm.agenerate(messages)
        return response
    except Exception as e:
        status = "failed"
        caught = e
        raise
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            raw_meta = extract_usage_metadata(response) if response is not None else {}
            usage = normalize_usage(provider, raw_meta)
            rid = _request_id_from_response(response)
            await _persist_usage_event(
                user_id=user_id,
                feature=feature,
                provider=provider,
                model=model,
                usage=usage,
                latency_ms=latency_ms,
                status=status,
                request_id=rid,
            )
        except Exception:
            logger.warning("[AI_USAGE] tracked_agenerate post-process failed", exc_info=True)
        if caught is not None and (provider or "").lower() == "gemini":
            try:
                from app.services.gemini_status_service import record_gemini_api_error

                await record_gemini_api_error(
                    exc=caught,
                    feature=feature,
                    model=model,
                    user_id=user_id,
                )
            except Exception:
                logger.warning("[GEMINI_STATUS] tracked_agenerate status hook failed", exc_info=True)
