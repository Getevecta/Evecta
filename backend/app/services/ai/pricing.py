from __future__ import annotations

from decimal import Decimal
from typing import Optional, Tuple

from app.services.ai.dynamic_pricing import (
    get_live_model_prices,
    schedule_live_price_refresh_if_stale,
)
from app.services.ai.token_usage import TokenUsage
from app.utils.money import as_decimal, quantize_cost, quantize_rate

# USD per million tokens — Gemini Developer API Standard (paid) tier.
# Fallback when live fetch is unavailable. Prefer live rates from
# app.services.ai.dynamic_pricing (Google pricing page / JSON feed).
# Snapshot rates onto each usage event at write time; admin recompute refreshes.
#
# Notes:
# - Output price includes thinking/reasoning tokens.
# - Context caching "processing" rate is used for cached prompt tokens (cache reads).
# - Cache storage ($/1M tokens/hour) and grounding ($/1k prompts) are tracked separately
#   when those signals exist; most Evecta calls are text-only Standard.
MODEL_PRICES: dict[Tuple[str, str], dict[str, float]] = {
    # Gemini 2.5 Flash — hybrid reasoning, 1M context (primary Evecta model)
    ("gemini", "gemini-2.5-flash"): {
        "input_per_million": 0.30,          # text / image / video
        "input_audio_per_million": 1.00,    # audio
        "output_per_million": 2.50,         # includes thinking tokens
        "cached_per_million": 0.03,         # text / image / video cache read
        "cached_audio_per_million": 0.10,   # audio cache read
        "cache_storage_per_million_per_hour": 1.00,
        "grounding_search_per_1k_prompts": 35.0,
        "grounding_maps_per_1k_prompts": 25.0,
    },
    # Gemini 2.5 Pro — rates for prompts <= 200k tokens (typical Evecta usage)
    ("gemini", "gemini-2.5-pro"): {
        "input_per_million": 1.25,
        "output_per_million": 10.00,
        "cached_per_million": 0.125,
        "cache_storage_per_million_per_hour": 4.50,
        "grounding_search_per_1k_prompts": 35.0,
        "grounding_maps_per_1k_prompts": 25.0,
        # >200k token prompts: input 2.50 / output 15.00 / cached 0.25
        "input_per_million_long": 2.50,
        "output_per_million_long": 15.00,
        "cached_per_million_long": 0.25,
        "long_context_token_threshold": 200_000,
    },
    # Gemini 2.5 Flash-Lite
    ("gemini", "gemini-2.5-flash-lite"): {
        "input_per_million": 0.10,
        "input_audio_per_million": 0.30,
        "output_per_million": 0.40,
        "cached_per_million": 0.01,
        "cached_audio_per_million": 0.03,
        "cache_storage_per_million_per_hour": 1.00,
        "grounding_search_per_1k_prompts": 35.0,
        "grounding_maps_per_1k_prompts": 25.0,
    },
    # Deprecated Gemini 2.0 (kept for historical event recompute)
    ("gemini", "gemini-2.0-flash"): {
        "input_per_million": 0.10,
        "input_audio_per_million": 0.70,
        "output_per_million": 0.40,
        "cached_per_million": 0.025,
    },
    ("gemini", "gemini-2.0-flash-lite"): {
        "input_per_million": 0.075,
        "output_per_million": 0.30,
        "cached_per_million": 0.01875,
    },
    # Legacy 1.5 (historical)
    ("gemini", "gemini-1.5-flash"): {
        "input_per_million": 0.075,
        "output_per_million": 0.30,
        "cached_per_million": 0.01875,
    },
    ("gemini", "gemini-1.5-pro"): {
        "input_per_million": 1.25,
        "output_per_million": 5.00,
        "cached_per_million": 0.3125,
    },
    # Alias / internal nicknames → same as 2.5 Flash
    ("gemini", "gemini-3.6-flash"): {
        "input_per_million": 0.30,
        "input_audio_per_million": 1.00,
        "output_per_million": 2.50,
        "cached_per_million": 0.03,
        "cached_audio_per_million": 0.10,
        "cache_storage_per_million_per_hour": 1.00,
    },
    # Groq (placeholder rates for future multi-provider support)
    ("groq", "openai/gpt-oss-20b"): {
        "input_per_million": 0.10,
        "output_per_million": 0.50,
        "cached_per_million": 0.05,
    },
    ("groq", "llama-3.3-70b-versatile"): {
        "input_per_million": 0.59,
        "output_per_million": 0.79,
        "cached_per_million": 0.30,
    },
    # OpenAI placeholders
    ("openai", "gpt-4o-mini"): {
        "input_per_million": 0.15,
        "output_per_million": 0.60,
        "cached_per_million": 0.075,
    },
    ("openai", "gpt-4o"): {
        "input_per_million": 2.50,
        "output_per_million": 10.00,
        "cached_per_million": 1.25,
    },
    # DeepSeek placeholders
    ("deepseek", "deepseek-chat"): {
        "input_per_million": 0.27,
        "output_per_million": 1.10,
        "cached_per_million": 0.07,
    },
    ("deepseek", "deepseek-reasoner"): {
        "input_per_million": 0.55,
        "output_per_million": 2.19,
        "cached_per_million": 0.14,
    },
}

# Fallback when a specific model is unknown for a known provider.
_PROVIDER_DEFAULTS: dict[str, dict[str, float]] = {
    "gemini": {
        "input_per_million": 0.30,
        "input_audio_per_million": 1.00,
        "output_per_million": 2.50,
        "cached_per_million": 0.03,
        "cached_audio_per_million": 0.10,
    },
    "groq": {
        "input_per_million": 0.50,
        "output_per_million": 0.80,
        "cached_per_million": 0.25,
    },
    "openai": {
        "input_per_million": 0.15,
        "output_per_million": 0.60,
        "cached_per_million": 0.075,
    },
    "deepseek": {
        "input_per_million": 0.27,
        "output_per_million": 1.10,
        "cached_per_million": 0.07,
    },
}


def _normalize_model_key(model: str) -> str:
    name = (model or "").strip().lower()
    # Strip models/ prefix sometimes returned by Google APIs.
    if name.startswith("models/"):
        name = name[len("models/") :]
    return name


def get_model_prices(provider: str, model: str) -> dict[str, Optional[float]]:
    """Return the price snapshot dict for (provider, model).

    Gemini rates prefer the live registry (refreshed from Google's pricing page).
    Static MODEL_PRICES remain as offline fallback / fill-in for missing fields
    (e.g. audio rates when a JSON feed only ships text input/output).
    """
    p = (provider or "").strip().lower()
    m = _normalize_model_key(model)
    prices = MODEL_PRICES.get((p, m))
    if prices is None:
        # Try prefix match (e.g. gemini-2.5-flash-001 → gemini-2.5-flash)
        # Prefer longest matching key so flash-lite wins over flash.
        best: Optional[tuple[str, dict[str, float]]] = None
        for (pp, mm), val in MODEL_PRICES.items():
            if pp != p:
                continue
            if m.startswith(mm) or mm.startswith(m):
                if best is None or len(mm) > len(best[0]):
                    best = (mm, val)
        if best is not None:
            prices = best[1]
    if prices is None:
        prices = _PROVIDER_DEFAULTS.get(p) or {
            "input_per_million": None,
            "output_per_million": None,
            "cached_per_million": None,
        }
    merged: dict[str, Optional[float]] = dict(prices)

    if p == "gemini":
        schedule_live_price_refresh_if_stale()
        live = get_live_model_prices(m)
        if live:
            for key, value in live.items():
                if value is not None:
                    merged[key] = value

    return merged


def _billable_output_tokens(usage: TokenUsage) -> int:
    """
    Output billable tokens including thinking/reasoning.

    Gemini bills thinking at the output rate. LangChain usually reports
    candidates in ``output_tokens`` and thoughts in ``reasoning_tokens``.
    If ``total_tokens`` shows output already includes reasoning, do not double-count.
    """
    output = max(0, int(usage.output_tokens or 0))
    reasoning = max(0, int(usage.reasoning_tokens or 0))
    input_tokens = max(0, int(usage.input_tokens or 0))
    total = max(0, int(usage.total_tokens or 0))

    if reasoning <= 0:
        return output

    # If input + output alone already accounts for total, output likely includes thoughts.
    if total > 0 and (input_tokens + output) >= total - 1:
        return output

    # If adding reasoning would clearly overshoot total, keep output as-is.
    if total > 0 and (input_tokens + output + reasoning) > total + max(1, total // 100):
        return output

    return output + reasoning


def estimate_cost_usd(
    provider: str,
    model: str,
    usage: TokenUsage,
    *,
    audio_input_tokens: int = 0,
) -> tuple[Decimal, Optional[Decimal], Optional[Decimal]]:
    """
    Estimate USD cost from TokenUsage using the registry snapshot.

    Returns (estimated_cost_usd, input_rate_per_million, output_rate_per_million).
    Reasoning/thinking tokens are billed at the output rate.
    Cached tokens are billed at the cached (context-caching processing) rate.
    """
    prices = get_model_prices(provider, model)
    in_rate = prices.get("input_per_million")
    out_rate = prices.get("output_per_million")
    cache_rate = prices.get("cached_per_million")
    audio_in_rate = prices.get("input_audio_per_million")
    audio_cache_rate = prices.get("cached_audio_per_million")

    # Gemini 2.5 Pro long-context tier (>200k prompt tokens)
    threshold = prices.get("long_context_token_threshold")
    if threshold and int(usage.input_tokens or 0) > int(threshold):
        in_rate = prices.get("input_per_million_long") or in_rate
        out_rate = prices.get("output_per_million_long") or out_rate
        cache_rate = prices.get("cached_per_million_long") or cache_rate

    if in_rate is None and out_rate is None:
        return Decimal("0"), None, None

    million = Decimal("1000000")
    in_rate_d = as_decimal(in_rate or 0)
    out_rate_d = as_decimal(out_rate or 0)
    cache_rate_d = as_decimal(cache_rate if cache_rate is not None else in_rate_d)
    audio_in_rate_d = as_decimal(audio_in_rate if audio_in_rate is not None else in_rate_d)
    audio_cache_rate_d = as_decimal(
        audio_cache_rate if audio_cache_rate is not None else cache_rate_d
    )

    input_tokens = max(0, int(usage.input_tokens or 0))
    cached = max(0, int(usage.cached_tokens or 0))
    audio_in = max(0, min(int(audio_input_tokens or 0), input_tokens))
    text_input = max(0, input_tokens - audio_in)
    # Cached portion attributed to audio when we know audio input; else all text rates.
    audio_cached = min(cached, audio_in) if audio_in else 0
    text_cached = max(0, cached - audio_cached)
    billable_text_input = max(0, text_input - text_cached)
    billable_audio_input = max(0, audio_in - audio_cached)
    billable_output = _billable_output_tokens(usage)

    cost = (
        (Decimal(billable_text_input) / million) * in_rate_d
        + (Decimal(billable_audio_input) / million) * audio_in_rate_d
        + (Decimal(text_cached) / million) * cache_rate_d
        + (Decimal(audio_cached) / million) * audio_cache_rate_d
        + (Decimal(billable_output) / million) * out_rate_d
    )
    return (
        quantize_cost(cost),
        quantize_rate(in_rate) if in_rate is not None else None,
        quantize_rate(out_rate) if out_rate is not None else None,
    )


def estimate_cost_from_event_fields(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int = 0,
    cached_tokens: int = 0,
    total_tokens: int = 0,
) -> tuple[Decimal, Optional[Decimal], Optional[Decimal]]:
    """Recompute cost for a stored usage event using current list prices."""
    usage = TokenUsage(
        input_tokens=int(input_tokens or 0),
        output_tokens=int(output_tokens or 0),
        reasoning_tokens=int(reasoning_tokens or 0),
        cached_tokens=int(cached_tokens or 0),
        total_tokens=int(total_tokens or 0),
    )
    return estimate_cost_usd(provider, model, usage)
