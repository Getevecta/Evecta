"""Fetch live Gemini list prices from Google's pricing page (with JSON fallback)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

GOOGLE_PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"
AIPRICING_JSON_URL = "https://www.aipricing.guru/api/pricing.json"

# Refresh at most this often unless force=True.
DEFAULT_TTL_SECONDS = 6 * 60 * 60

_MONEY_RE = re.compile(r"\$(\d+(?:\.\d+)?)")
_MODEL_CODE_RE = re.compile(
    r"<code[^>]*>\s*(gemini-[a-z0-9][a-z0-9.\-]*)\s*</code>",
    re.IGNORECASE,
)
_MD_MODEL_RE = re.compile(r"^`(gemini-[a-z0-9][a-z0-9.\-]*)`\s*$", re.MULTILINE | re.IGNORECASE)


@dataclass
class LivePricingSnapshot:
    models: dict[str, dict[str, float]] = field(default_factory=dict)
    source: str = "static"
    source_url: Optional[str] = None
    fetched_at: Optional[float] = None
    fingerprint: str = ""
    error: Optional[str] = None

    @property
    def age_seconds(self) -> Optional[float]:
        if self.fetched_at is None:
            return None
        return max(0.0, time.time() - self.fetched_at)

    def as_status(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "age_seconds": self.age_seconds,
            "model_count": len(self.models),
            "fingerprint": self.fingerprint,
            "error": self.error,
            "models": {
                mid: {
                    k: v
                    for k, v in rates.items()
                    if k
                    in (
                        "input_per_million",
                        "input_audio_per_million",
                        "output_per_million",
                        "cached_per_million",
                        "cached_audio_per_million",
                        "input_per_million_long",
                        "output_per_million_long",
                        "cached_per_million_long",
                        "long_context_token_threshold",
                    )
                }
                for mid, rates in sorted(self.models.items())
            },
        }


_lock = asyncio.Lock()
_sync_lock = threading.Lock()
_snapshot = LivePricingSnapshot()
_ttl_seconds = DEFAULT_TTL_SECONDS


def _fingerprint(models: dict[str, dict[str, float]]) -> str:
    payload = repr(sorted((k, sorted(v.items())) for k, v in models.items())).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def _strip_tags(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _money_values(text: str) -> list[float]:
    return [float(m.group(1)) for m in _MONEY_RE.finditer(text or "")]


def _extract_standard_block(section_text: str) -> str:
    """Keep the Standard paid-tier table; drop Batch / Flex / Priority."""
    lower = section_text.lower()
    std = lower.find("standard")
    if std < 0:
        return section_text
    chunk = section_text[std:]
    for stopper in (" batch ", " flex ", " priority ", "\n## ", " used to improve our products"):
        idx = chunk.lower().find(stopper)
        # Prefer cutting at Batch when present after Standard header.
        if stopper.strip() in {"batch", "flex", "priority"} and idx > 20:
            return chunk[:idx]
    # Soft cut before next model-ish heading length
    return chunk[:4000]


def _parse_rate_row(block: str, label: str) -> Optional[str]:
    """Return the paid-tier cell text for a pricing row label."""
    # Match "Input price ... Output price" style spans in flattened text.
    pattern = re.compile(
        rf"{re.escape(label)}\s+(.*?)(?="
        r"Output price|Context caching price|Grounding with Google|"
        r"Used to improve|Batch|Flex|Priority|$)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(block)
    if not m:
        return None
    cell = m.group(1)
    # Drop free-tier preamble when both tiers are present.
    paid = re.split(r"Free of charge|Not available", cell, maxsplit=1, flags=re.I)
    if len(paid) > 1:
        cell = paid[-1]
    return cell.strip(" |")


def _parse_model_rates(section_text: str) -> dict[str, float]:
    block = _extract_standard_block(section_text)
    rates: dict[str, float] = {}

    input_cell = _parse_rate_row(block, "Input price") or ""
    output_cell = _parse_rate_row(block, "Output price") or ""
    cache_cell = _parse_rate_row(block, "Context caching price") or ""

    in_vals = _money_values(input_cell)
    out_vals = _money_values(output_cell)
    cache_vals = _money_values(cache_cell)

    long_context = bool(re.search(r">\s*200k|prompts\s*>\s*200k|<=\s*200k", block, re.I))

    if long_context and len(in_vals) >= 2:
        rates["input_per_million"] = in_vals[0]
        rates["input_per_million_long"] = in_vals[1]
        rates["long_context_token_threshold"] = 200_000
    elif in_vals:
        rates["input_per_million"] = in_vals[0]
        if "audio" in input_cell.lower() and len(in_vals) >= 2:
            rates["input_audio_per_million"] = in_vals[1]

    if long_context and len(out_vals) >= 2:
        rates["output_per_million"] = out_vals[0]
        rates["output_per_million_long"] = out_vals[1]
    elif out_vals:
        rates["output_per_million"] = out_vals[0]

    # Cache cell: text/audio rates then optional storage $/hour
    storage = re.search(
        r"\$(\d+(?:\.\d+)?)\s*/\s*1[,.]?000[,.]?000\s*tokens\s*per\s*hour",
        cache_cell,
        re.I,
    )
    cache_money = _money_values(cache_cell)
    if storage:
        rates["cache_storage_per_million_per_hour"] = float(storage.group(1))
        # Exclude the storage dollar from processing rates when it's the last amount.
        storage_val = float(storage.group(1))
        if cache_money and abs(cache_money[-1] - storage_val) < 1e-9:
            cache_money = cache_money[:-1]

    if long_context and len(cache_money) >= 2:
        rates["cached_per_million"] = cache_money[0]
        rates["cached_per_million_long"] = cache_money[1]
    elif cache_money:
        rates["cached_per_million"] = cache_money[0]
        if "audio" in cache_cell.lower() and len(cache_money) >= 2:
            rates["cached_audio_per_million"] = cache_money[1]

    ground_search = re.search(
        r"Grounding with Google Search.*?\$(\d+(?:\.\d+)?)\s*/\s*1[,.]?000",
        block,
        re.I | re.S,
    )
    if ground_search:
        rates["grounding_search_per_1k_prompts"] = float(ground_search.group(1))
    ground_maps = re.search(
        r"Grounding with Google Maps.*?\$(\d+(?:\.\d+)?)\s*/\s*1[,.]?000",
        block,
        re.I | re.S,
    )
    if ground_maps:
        rates["grounding_maps_per_1k_prompts"] = float(ground_maps.group(1))

    return rates


def parse_google_pricing_html(html: str) -> dict[str, dict[str, float]]:
    """Parse model Standard paid rates from Google's pricing HTML page."""
    models: dict[str, dict[str, float]] = {}
    matches = list(_MODEL_CODE_RE.finditer(html))
    for i, match in enumerate(matches):
        model_id = match.group(1).strip().lower()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(html), start + 12000)
        section = _strip_tags(html[start:end])
        rates = _parse_model_rates(section)
        if rates.get("input_per_million") is not None or rates.get("output_per_million") is not None:
            models[model_id] = rates
    return models


def parse_google_pricing_markdown(md: str) -> dict[str, dict[str, float]]:
    """Parse model Standard paid rates from Google's pricing.md.txt style markdown."""
    models: dict[str, dict[str, float]] = {}
    matches = list(_MD_MODEL_RE.finditer(md))
    for i, match in enumerate(matches):
        model_id = match.group(1).strip().lower()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        section = md[start:end]
        # Prefer flattened whitespace for the shared row parser.
        flat = re.sub(r"\s+", " ", section)
        rates = _parse_model_rates(flat)
        if rates.get("input_per_million") is not None or rates.get("output_per_million") is not None:
            models[model_id] = rates
    return models


def parse_aipricing_json(data: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Parse Google Gemini rows from aipricing.guru /api/pricing.json."""
    models: dict[str, dict[str, float]] = {}
    long_context: dict[str, dict[str, float]] = {}
    for row in data.get("models") or []:
        if str(row.get("provider") or "").lower() not in {"google", "gemini"}:
            continue
        mid = str(row.get("id") or "").strip().lower()
        if not mid.startswith("gemini"):
            continue
        pricing = row.get("pricing") or {}
        if mid.endswith("-long-context"):
            base = mid[: -len("-long-context")]
            long_context[base] = {
                "input_per_million_long": float(pricing["inputPerM"]),
                "output_per_million_long": float(pricing["outputPerM"]),
                "cached_per_million_long": float(pricing["cachedInputPerM"])
                if pricing.get("cachedInputPerM") is not None
                else None,  # type: ignore[dict-item]
                "long_context_token_threshold": 200_000,
            }
            # drop Nones
            long_context[base] = {k: v for k, v in long_context[base].items() if v is not None}
            continue
        rates: dict[str, float] = {}
        if pricing.get("inputPerM") is not None:
            rates["input_per_million"] = float(pricing["inputPerM"])
        if pricing.get("outputPerM") is not None:
            rates["output_per_million"] = float(pricing["outputPerM"])
        if pricing.get("cachedInputPerM") is not None:
            rates["cached_per_million"] = float(pricing["cachedInputPerM"])
        if rates:
            models[mid] = rates

    for base, extra in long_context.items():
        models.setdefault(base, {}).update(extra)
    return models


def _http_get_text(url: str, timeout: float = 20.0) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; EvectaPricingBot/1.0; +https://evecta.io) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/json,text/plain,*/*",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


async def _http_get_text_async(url: str, timeout: float = 20.0) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; EvectaPricingBot/1.0; +https://evecta.io) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/json,text/plain,*/*",
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def _fetch_snapshot_sync() -> LivePricingSnapshot:
    errors: list[str] = []

    # 1) Official Google HTML pricing page
    try:
        html = _http_get_text(GOOGLE_PRICING_URL)
        models = parse_google_pricing_html(html)
        if models:
            return LivePricingSnapshot(
                models=models,
                source="google_pricing_page",
                source_url=GOOGLE_PRICING_URL,
                fetched_at=time.time(),
                fingerprint=_fingerprint(models),
            )
        errors.append("google_pricing_page: no models parsed")
    except Exception as exc:  # noqa: BLE001 — fall through to secondary source
        errors.append(f"google_pricing_page: {exc}")
        logger.warning("[AI_PRICING] Google pricing fetch failed: %s", exc)

    # 2) Machine-readable aggregator (scrapes Google; refreshed frequently)
    try:
        raw = _http_get_text(AIPRICING_JSON_URL)
        import json

        data = json.loads(raw)
        models = parse_aipricing_json(data)
        if models:
            return LivePricingSnapshot(
                models=models,
                source="aipricing_guru",
                source_url=AIPRICING_JSON_URL,
                fetched_at=time.time(),
                fingerprint=_fingerprint(models),
            )
        errors.append("aipricing_guru: no gemini models")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"aipricing_guru: {exc}")
        logger.warning("[AI_PRICING] aipricing.guru fetch failed: %s", exc)

    return LivePricingSnapshot(
        models=dict(_snapshot.models),
        source=_snapshot.source if _snapshot.models else "static",
        source_url=_snapshot.source_url,
        fetched_at=_snapshot.fetched_at,
        fingerprint=_snapshot.fingerprint,
        error="; ".join(errors) if errors else "unknown fetch failure",
    )


async def _fetch_snapshot_async() -> LivePricingSnapshot:
    """Async HTTP so admin/recompute refresh does not block the event loop."""
    errors: list[str] = []

    try:
        html = await _http_get_text_async(GOOGLE_PRICING_URL)
        models = parse_google_pricing_html(html)
        if models:
            return LivePricingSnapshot(
                models=models,
                source="google_pricing_page",
                source_url=GOOGLE_PRICING_URL,
                fetched_at=time.time(),
                fingerprint=_fingerprint(models),
            )
        errors.append("google_pricing_page: no models parsed")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"google_pricing_page: {exc}")
        logger.warning("[AI_PRICING] Google pricing fetch failed: %s", exc)

    try:
        import json

        raw = await _http_get_text_async(AIPRICING_JSON_URL)
        models = parse_aipricing_json(json.loads(raw))
        if models:
            return LivePricingSnapshot(
                models=models,
                source="aipricing_guru",
                source_url=AIPRICING_JSON_URL,
                fetched_at=time.time(),
                fingerprint=_fingerprint(models),
            )
        errors.append("aipricing_guru: no gemini models")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"aipricing_guru: {exc}")
        logger.warning("[AI_PRICING] aipricing.guru fetch failed: %s", exc)

    return LivePricingSnapshot(
        models=dict(_snapshot.models),
        source=_snapshot.source if _snapshot.models else "static",
        source_url=_snapshot.source_url,
        fetched_at=_snapshot.fetched_at,
        fingerprint=_snapshot.fingerprint,
        error="; ".join(errors) if errors else "unknown fetch failure",
    )


def get_live_snapshot() -> LivePricingSnapshot:
    return _snapshot


def get_live_model_prices(model: str) -> Optional[dict[str, float]]:
    """Return live rates for a model id if present in the cache."""
    name = (model or "").strip().lower()
    if name.startswith("models/"):
        name = name[len("models/") :]
    if not name:
        return None
    snap = _snapshot
    if name in snap.models:
        return dict(snap.models[name])
    # Prefix match (gemini-2.5-flash-001 → gemini-2.5-flash)
    best: Optional[tuple[str, dict[str, float]]] = None
    for mid, rates in snap.models.items():
        if name.startswith(mid) or mid.startswith(name):
            if best is None or len(mid) > len(best[0]):
                best = (mid, rates)
    return dict(best[1]) if best else None


def _cache_is_fresh(ttl: Optional[int] = None) -> bool:
    ttl = DEFAULT_TTL_SECONDS if ttl is None else ttl
    if not _snapshot.models or _snapshot.fetched_at is None:
        return False
    return (time.time() - _snapshot.fetched_at) < ttl


def refresh_live_prices_sync(*, force: bool = False, ttl: Optional[int] = None) -> LivePricingSnapshot:
    """Synchronous refresh used from sync LLM write paths."""
    global _snapshot
    with _sync_lock:
        if not force and _cache_is_fresh(ttl):
            return _snapshot
        snap = _fetch_snapshot_sync()
        if snap.models:
            _snapshot = snap
            logger.info(
                "[AI_PRICING] Live Gemini prices refreshed source=%s models=%s fingerprint=%s",
                snap.source,
                len(snap.models),
                snap.fingerprint,
            )
        elif snap.error:
            _snapshot = LivePricingSnapshot(
                models=dict(_snapshot.models),
                source=_snapshot.source,
                source_url=_snapshot.source_url,
                fetched_at=_snapshot.fetched_at,
                fingerprint=_snapshot.fingerprint,
                error=snap.error,
            )
        return _snapshot


async def refresh_live_prices(*, force: bool = False, ttl: Optional[int] = None) -> LivePricingSnapshot:
    """Async refresh for admin / recompute paths."""
    global _snapshot
    async with _lock:
        if not force and _cache_is_fresh(ttl):
            return _snapshot
        snap = await _fetch_snapshot_async()
        if snap.models:
            _snapshot = snap
            logger.info(
                "[AI_PRICING] Live Gemini prices refreshed source=%s models=%s fingerprint=%s",
                snap.source,
                len(snap.models),
                snap.fingerprint,
            )
        elif snap.error:
            _snapshot = LivePricingSnapshot(
                models=dict(_snapshot.models),
                source=_snapshot.source,
                source_url=_snapshot.source_url,
                fetched_at=_snapshot.fetched_at,
                fingerprint=_snapshot.fingerprint,
                error=snap.error,
            )
        return _snapshot


_refresh_task: Optional[asyncio.Task] = None


def _in_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def ensure_live_prices_sync() -> LivePricingSnapshot:
    """Best-effort ensure cache is populated (never raises). Sync callers only."""
    if _in_pytest():
        return _snapshot
    try:
        return refresh_live_prices_sync(force=False)
    except Exception:  # noqa: BLE001
        logger.warning("[AI_PRICING] ensure_live_prices_sync failed", exc_info=True)
        return _snapshot


def schedule_live_price_refresh_if_stale() -> None:
    """Refresh prices without blocking an already-running event loop.

    Cost tracking runs inside ``tracked_ainvoke`` (async). A sync HTTP fetch
    there stalls every request on the worker. If a loop is running, kick off
    ``refresh_live_prices`` in the background and use the current cache for
    this call. Sync callers still fetch inline.
    """
    if _in_pytest():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        ensure_live_prices_sync()
        return
    if _cache_is_fresh():
        return
    global _refresh_task
    if _refresh_task is not None and not _refresh_task.done():
        return

    async def _run() -> None:
        try:
            await refresh_live_prices(force=False)
        except Exception:  # noqa: BLE001
            logger.warning("[AI_PRICING] background refresh failed", exc_info=True)

    _refresh_task = loop.create_task(_run())
