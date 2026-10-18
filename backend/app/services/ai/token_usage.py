from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenUsage:
    """Normalized token counts across Gemini / Groq / OpenAI / DeepSeek."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        # Dataclass is frozen; use object.__setattr__ for derived total when omitted.
        if self.total_tokens <= 0:
            computed = (
                int(self.input_tokens or 0)
                + int(self.output_tokens or 0)
                + int(self.reasoning_tokens or 0)
            )
            object.__setattr__(self, "total_tokens", computed)
