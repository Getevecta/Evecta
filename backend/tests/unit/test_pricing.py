"""Gemini Developer API Standard paid-tier cost estimates."""
from decimal import Decimal

from app.services.ai.pricing import estimate_cost_usd, estimate_cost_from_event_fields
from app.services.ai.token_usage import TokenUsage
from app.utils.money import as_decimal, quantize_cost, quantize_rate


def test_flash_text_input_output_rates():
    # 1M input @ $0.30 + 1M output @ $2.50
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000, total_tokens=2_000_000)
    cost, in_rate, out_rate = estimate_cost_usd("gemini", "gemini-2.5-flash", usage)
    assert in_rate == quantize_rate("0.30")
    assert out_rate == quantize_rate("2.50")
    assert cost == quantize_cost("2.80")


def test_flash_cached_tokens_use_cache_rate():
    # 500k cached @ $0.03 + 500k billable input @ $0.30 + 100k output @ $2.50
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=100_000,
        cached_tokens=500_000,
        total_tokens=1_100_000,
    )
    cost, _, _ = estimate_cost_usd("gemini", "gemini-2.5-flash", usage)
    expected = (
        as_decimal("500000") / Decimal("1000000") * as_decimal("0.30")
        + as_decimal("500000") / Decimal("1000000") * as_decimal("0.03")
        + as_decimal("100000") / Decimal("1000000") * as_decimal("2.50")
    )
    assert cost == quantize_cost(expected)


def test_flash_reasoning_billed_at_output_when_separate():
    usage = TokenUsage(
        input_tokens=100_000,
        output_tokens=10_000,
        reasoning_tokens=40_000,
        total_tokens=150_000,
    )
    cost, _, _ = estimate_cost_usd("gemini", "gemini-2.5-flash", usage)
    expected = (
        as_decimal("100000") / Decimal("1000000") * as_decimal("0.30")
        + as_decimal("50000") / Decimal("1000000") * as_decimal("2.50")
    )
    assert cost == quantize_cost(expected)


def test_flash_reasoning_not_double_counted_when_in_output():
    usage = TokenUsage(
        input_tokens=100_000,
        output_tokens=50_000,
        reasoning_tokens=40_000,
        total_tokens=150_000,
    )
    cost, _, _ = estimate_cost_usd("gemini", "gemini-2.5-flash", usage)
    expected = (
        as_decimal("100000") / Decimal("1000000") * as_decimal("0.30")
        + as_decimal("50000") / Decimal("1000000") * as_decimal("2.50")
    )
    assert cost == quantize_cost(expected)


def test_recompute_helper_matches_estimate():
    cost_a, _, _ = estimate_cost_from_event_fields(
        provider="gemini",
        model="gemini-2.5-flash",
        input_tokens=200_000,
        output_tokens=80_000,
        reasoning_tokens=0,
        cached_tokens=0,
        total_tokens=280_000,
    )
    cost_b, _, _ = estimate_cost_usd(
        "gemini",
        "gemini-2.5-flash",
        TokenUsage(input_tokens=200_000, output_tokens=80_000, total_tokens=280_000),
    )
    assert cost_a == cost_b
    assert isinstance(cost_a, Decimal)
