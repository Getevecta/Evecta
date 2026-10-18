"""Live Gemini pricing parsers (Google HTML / markdown + JSON feed)."""

from pathlib import Path

from app.services.ai.dynamic_pricing import (
    parse_aipricing_json,
    parse_google_pricing_html,
    parse_google_pricing_markdown,
)

SAMPLE_MD = """
## Gemini 2.5 Flash

`gemini-2.5-flash`

### Standard

| | Free Tier | Paid Tier, per 1M tokens in USD |
| --- | --- | --- |
| Input price | Free of charge | $0.30 (text / image / video) $1.00 (audio) |
| Output price (including thinking tokens) | Free of charge | $2.50 |
| Context caching price | Not available | $0.03 (text / image / video) $0.1 (audio) $1.00 / 1,000,000 tokens per hour (storage price) |
| Grounding with Google Search | Free of charge | then $35 / 1,000 grounded prompts |
| Grounding with Google Maps | 500 RPD | then $25 / 1,000 grounded prompts |

### Batch

| | Free Tier | Paid Tier, per 1M tokens in USD |
| --- | --- | --- |
| Input price | Not available | $0.15 |

## Gemini 2.5 Pro

`gemini-2.5-pro`

### Standard

| | Free Tier | Paid Tier, per 1M tokens in USD |
| --- | --- | --- |
| Input price | Free of charge | $1.25, prompts <= 200k tokens $2.50, prompts > 200k tokens |
| Output price (including thinking tokens) | Free of charge | $10.00, prompts <= 200k tokens $15.00, prompts > 200k |
| Context caching price | Not available | $0.125, prompts <= 200k tokens $0.25, prompts > 200k $4.50 / 1,000,000 tokens per hour (storage price) |
"""

SAMPLE_HTML = """
<code>gemini-2.5-flash</code>
<div>Standard Free Tier Paid Tier, per 1M tokens in USD
Input price Free of charge $0.30 (text / image / video) $1.00 (audio)
Output price (including thinking tokens) Free of charge $2.50
Context caching price Not available $0.03 (text / image / video) $0.1 (audio) $1.00 / 1,000,000 tokens per hour (storage price)
Batch Free Tier Paid Tier
Input price Not available $0.15</div>
<code>gemini-2.5-pro</code>
<div>Standard Free Tier Paid Tier
Input price Free of charge $1.25, prompts $2.50, prompts > 200k tokens
Output price (including thinking tokens) Free of charge $10.00, prompts $15.00, prompts > 200k
Context caching price Not available $0.125, prompts $0.25, prompts > 200k $4.50 / 1,000,000 tokens per hour (storage price)
</div>
"""


def test_parse_markdown_flash_and_pro():
    models = parse_google_pricing_markdown(SAMPLE_MD)
    flash = models["gemini-2.5-flash"]
    assert flash["input_per_million"] == 0.30
    assert flash["input_audio_per_million"] == 1.00
    assert flash["output_per_million"] == 2.50
    assert flash["cached_per_million"] == 0.03
    assert flash["cached_audio_per_million"] == 0.1
    assert flash["grounding_search_per_1k_prompts"] == 35.0

    pro = models["gemini-2.5-pro"]
    assert pro["input_per_million"] == 1.25
    assert pro["input_per_million_long"] == 2.50
    assert pro["output_per_million"] == 10.00
    assert pro["output_per_million_long"] == 15.00
    assert pro["cached_per_million"] == 0.125
    assert pro["long_context_token_threshold"] == 200_000


def test_parse_html_flash_and_pro():
    models = parse_google_pricing_html(SAMPLE_HTML)
    assert models["gemini-2.5-flash"]["input_per_million"] == 0.30
    assert models["gemini-2.5-flash"]["output_per_million"] == 2.50
    assert models["gemini-2.5-pro"]["input_per_million"] == 1.25
    assert models["gemini-2.5-pro"]["input_per_million_long"] == 2.50


def test_parse_aipricing_json_merges_long_context():
    data = {
        "models": [
            {
                "id": "gemini-2.5-flash",
                "provider": "google",
                "pricing": {"inputPerM": 0.3, "cachedInputPerM": 0.03, "outputPerM": 2.5},
            },
            {
                "id": "gemini-2.5-pro",
                "provider": "google",
                "pricing": {"inputPerM": 1.25, "cachedInputPerM": 0.125, "outputPerM": 10},
            },
            {
                "id": "gemini-2.5-pro-long-context",
                "provider": "google",
                "pricing": {"inputPerM": 2.5, "cachedInputPerM": 0.25, "outputPerM": 15},
            },
        ]
    }
    models = parse_aipricing_json(data)
    assert models["gemini-2.5-flash"]["cached_per_million"] == 0.03
    pro = models["gemini-2.5-pro"]
    assert pro["input_per_million"] == 1.25
    assert pro["input_per_million_long"] == 2.5
    assert pro["output_per_million_long"] == 15


def test_parse_live_google_html_fixture_if_present():
    """Optional: parse a saved Google pricing HTML dump when available."""
    path = Path("/tmp/gpricing.html")
    if not path.exists():
        return
    models = parse_google_pricing_html(path.read_text(errors="ignore"))
    assert "gemini-2.5-flash" in models
    assert models["gemini-2.5-flash"]["input_per_million"] == 0.30
    assert models["gemini-2.5-flash"]["output_per_million"] == 2.50
