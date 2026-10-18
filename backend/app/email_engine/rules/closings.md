---
# Closing (sign-off) variants — one is chosen per email by the variation engine and used
# verbatim. Always followed by the sender's name on its own line. Keep professional and
# cross-tone safe (each should read fine whether the tone is formal or friendly).
variants:
  - "Best regards,"
  - "Kind regards,"
  - "Warm regards,"
  - "All the best,"
  - "Best,"
  - "Sincerely,"
---

# Closing Variants

The variation engine picks one closing per email, used as written and followed by the
sender's name on its own line.

- **Literal text** — used verbatim (like greetings, unlike CTAs).
- **Cross-tone safe** — keep variants that fit any tone. (A later enhancement could bias the
  choice by tone, e.g. "Sincerely," for formal vs "Best," for friendly — but the pool stays
  safe across all tones for now.)

## Integration note (for wiring #3 into generation)
The legacy generator/spam-checker only recognize `best regards`, `sincerely,`, and
`kind regards` as a closing (`_ensure_body_closing`, `_finalize_rewritten_body_html`). If a
varied closing like `Warm regards,` or `All the best,` is used, that code will think the
closing is missing and append a duplicate. When integrating, the closing-detection must read
this list instead of a hardcoded set.
