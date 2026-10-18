"""Detect Gemini / LLM outages (quota, 429, billing) so chat can surface a real error."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional


class LLMUnavailableError(Exception):
    """Raised when the LLM cannot serve a request (quota exhausted, 429, etc.)."""


ErrorKind = Literal[
    "quota_exhausted",
    "billing",
    "rate_limit",
    "unavailable",
]


@dataclass(frozen=True)
class LlmErrorInfo:
    kind: ErrorKind
    http_status: Optional[int]
    message: str


_QUOTA_MARKERS = (
    "resourceexhausted",
    "resource exhausted",
    "prepayment credits are depleted",
    "quota exceeded",
    "exceeded your current quota",
    "insufficient_quota",
    "billing#prepay",
    "consume paid credits",
    "free tier",
)

_RATE_MARKERS = (
    "rate limit",
    "ratelimit",
    "too many requests",
)

_BILLING_MARKERS = (
    "billing",
    "payment required",
    "prepaid",
    "prepay",
    "credits are depleted",
)


def _exception_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def extract_http_status(exc: BaseException) -> Optional[int]:
    """Best-effort HTTP / gRPC-mapped status from LangChain / Google exceptions."""
    for attr in ("status_code", "code", "http_status", "status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int) and 100 <= val <= 599:
            return val
        # google.api_core / grpc sometimes use enums with .value
        code_val = getattr(val, "value", None)
        if isinstance(code_val, int) and 100 <= code_val <= 599:
            return code_val
        # gRPC ResourceExhausted is often code 8
        if isinstance(code_val, int) and code_val == 8:
            return 429

    text = _exception_text(exc)
    m = re.search(r"\b(429|402|403|401|500|503)\b", text)
    if m:
        return int(m.group(1))
    if "resourceexhausted" in text.lower() or "resource exhausted" in text.lower():
        return 429
    return None


def classify_llm_error(exc: BaseException) -> LlmErrorInfo:
    text = _exception_text(exc)
    lower = text.lower()
    http_status = extract_http_status(exc)
    message = text.strip()[:500]

    if any(m in lower for m in _QUOTA_MARKERS) or any(m in lower for m in _BILLING_MARKERS):
        # Prepay depleted / quota = purchase finished for admin tracking.
        if any(
            m in lower
            for m in (
                "prepayment credits are depleted",
                "credits are depleted",
                "billing#prepay",
                "insufficient_quota",
                "quota exceeded",
                "exceeded your current quota",
                "resourceexhausted",
                "resource exhausted",
            )
        ):
            return LlmErrorInfo(kind="quota_exhausted", http_status=http_status or 429, message=message)
        return LlmErrorInfo(kind="billing", http_status=http_status or 402, message=message)

    if http_status == 429 or any(m in lower for m in _RATE_MARKERS):
        # 429 can be either rate limit or quota; prefer quota wording when present (handled above).
        return LlmErrorInfo(kind="rate_limit", http_status=429, message=message)

    if http_status in (401, 403, 402):
        return LlmErrorInfo(kind="billing", http_status=http_status, message=message)

    return LlmErrorInfo(kind="unavailable", http_status=http_status, message=message)


def is_llm_unavailable(exc: BaseException) -> bool:
    text = _exception_text(exc).lower()
    markers = (
        "resourceexhausted",
        "resource exhausted",
        "429",
        "prepayment credits are depleted",
        "quota exceeded",
        "exceeded your current quota",
        "insufficient_quota",
        "billing#prepay",
        "rate limit",
        "ratelimit",
    )
    return any(m in text for m in markers)


LLM_UNAVAILABLE_USER_MESSAGE = (
    "Something went wrong. Our AI assistant is temporarily unavailable. Please try again in a moment."
)


def llm_error_result(context: dict | None = None, *, exc: BaseException | None = None) -> dict:
    """User-facing LLM outage payload with state-aware recovery actions."""
    from app.utils.chat_recovery import build_llm_unavailable_recovery

    rate_limited = False
    if exc is not None:
        try:
            rate_limited = classify_llm_error(exc).kind == "rate_limit"
        except Exception:
            rate_limited = False
    return build_llm_unavailable_recovery(context, rate_limited=rate_limited)
