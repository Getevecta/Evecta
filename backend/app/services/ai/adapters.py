from __future__ import annotations

from typing import Any, Mapping, Optional

from app.services.ai.token_usage import TokenUsage


def _as_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    return {}


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _nested_get(data: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, Mapping) or key not in cur:
            return default
        cur = cur[key]
    return cur


def extract_usage_metadata(response: Any) -> dict:
    """
    Pull raw usage metadata from a LangChain AIMessage, LLMResult, or dict.
    Prefer ``usage_metadata``; fall back to nested response_metadata / llm_output.
    """
    if response is None:
        return {}

    # Structured-output include_raw=True → {"raw": AIMessage, "parsed": ..., ...}
    if isinstance(response, Mapping) and "raw" in response:
        return extract_usage_metadata(response.get("raw"))

    usage = getattr(response, "usage_metadata", None)
    if usage:
        return _as_dict(usage)

    meta = getattr(response, "response_metadata", None) or {}
    meta_d = _as_dict(meta)
    if "usage_metadata" in meta_d:
        return _as_dict(meta_d["usage_metadata"])
    if "token_usage" in meta_d:
        return _as_dict(meta_d["token_usage"])
    if "usage" in meta_d:
        return _as_dict(meta_d["usage"])

    # LLMResult from agenerate
    llm_output = getattr(response, "llm_output", None) or {}
    llm_d = _as_dict(llm_output)
    if "token_usage" in llm_d:
        return _as_dict(llm_d["token_usage"])
    if "usage" in llm_d:
        return _as_dict(llm_d["usage"])

    # generations[0][0].message.usage_metadata
    generations = getattr(response, "generations", None)
    if generations:
        try:
            gen0 = generations[0][0]
            msg = getattr(gen0, "message", None) or gen0
            return extract_usage_metadata(msg)
        except (IndexError, TypeError, AttributeError):
            pass

    if isinstance(response, Mapping):
        for key in ("usage_metadata", "token_usage", "usage"):
            if key in response:
                return _as_dict(response[key])

    return {}


def gemini_to_token_usage(metadata: Optional[Mapping[str, Any]]) -> TokenUsage:
    """
    Gemini / LangChain Google GenAI usage_metadata → TokenUsage.

    Typical shape:
      input_tokens, output_tokens, total_tokens,
      input_token_details.cache_read,
      output_token_details.reasoning
    """
    m = _as_dict(metadata)
    input_tokens = _int(m.get("input_tokens") or m.get("prompt_token_count") or m.get("prompt_tokens"))
    output_tokens = _int(m.get("output_tokens") or m.get("candidates_token_count") or m.get("completion_tokens"))
    total_tokens = _int(m.get("total_tokens") or m.get("total_token_count"))

    cached = _int(
        _nested_get(m, "input_token_details", "cache_read")
        or m.get("cached_content_token_count")
        or m.get("cached_tokens")
    )
    reasoning = _int(
        _nested_get(m, "output_token_details", "reasoning")
        or m.get("thoughts_token_count")
        or m.get("reasoning_tokens")
    )

    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning,
        cached_tokens=cached,
        total_tokens=total_tokens,
    )


def groq_to_token_usage(metadata: Optional[Mapping[str, Any]]) -> TokenUsage:
    """Groq (OpenAI-compatible) usage → TokenUsage."""
    m = _as_dict(metadata)
    input_tokens = _int(m.get("prompt_tokens") or m.get("input_tokens"))
    output_tokens = _int(m.get("completion_tokens") or m.get("output_tokens"))
    total_tokens = _int(m.get("total_tokens"))
    cached = _int(
        _nested_get(m, "prompt_tokens_details", "cached_tokens")
        or m.get("cached_tokens")
    )
    reasoning = _int(
        _nested_get(m, "completion_tokens_details", "reasoning_tokens")
        or m.get("reasoning_tokens")
    )
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning,
        cached_tokens=cached,
        total_tokens=total_tokens,
    )


def openai_to_token_usage(metadata: Optional[Mapping[str, Any]]) -> TokenUsage:
    """OpenAI usage → TokenUsage."""
    m = _as_dict(metadata)
    input_tokens = _int(m.get("prompt_tokens") or m.get("input_tokens"))
    output_tokens = _int(m.get("completion_tokens") or m.get("output_tokens"))
    total_tokens = _int(m.get("total_tokens"))
    cached = _int(
        _nested_get(m, "prompt_tokens_details", "cached_tokens")
        or m.get("cached_tokens")
    )
    reasoning = _int(
        _nested_get(m, "completion_tokens_details", "reasoning_tokens")
        or m.get("reasoning_tokens")
    )
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning,
        cached_tokens=cached,
        total_tokens=total_tokens,
    )


def deepseek_to_token_usage(metadata: Optional[Mapping[str, Any]]) -> TokenUsage:
    """DeepSeek usage → TokenUsage (OpenAI-compatible + reasoning_tokens)."""
    m = _as_dict(metadata)
    input_tokens = _int(m.get("prompt_tokens") or m.get("input_tokens"))
    output_tokens = _int(m.get("completion_tokens") or m.get("output_tokens"))
    total_tokens = _int(m.get("total_tokens"))
    cached = _int(
        _nested_get(m, "prompt_tokens_details", "cached_tokens")
        or m.get("prompt_cache_hit_tokens")
        or m.get("cached_tokens")
    )
    reasoning = _int(
        m.get("reasoning_tokens")
        or _nested_get(m, "completion_tokens_details", "reasoning_tokens")
    )
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning,
        cached_tokens=cached,
        total_tokens=total_tokens,
    )


_ADAPTERS = {
    "gemini": gemini_to_token_usage,
    "google": gemini_to_token_usage,
    "google_genai": gemini_to_token_usage,
    "groq": groq_to_token_usage,
    "openai": openai_to_token_usage,
    "deepseek": deepseek_to_token_usage,
}


def normalize_usage(provider: str, metadata: Optional[Mapping[str, Any]]) -> TokenUsage:
    """Route provider-specific metadata into TokenUsage."""
    key = (provider or "").strip().lower()
    adapter = _ADAPTERS.get(key, gemini_to_token_usage)
    return adapter(metadata)
