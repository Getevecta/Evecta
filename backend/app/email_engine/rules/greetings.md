---
# Greeting (salutation) variants — one is chosen per email by the variation engine and used
# verbatim as the email's first line. SALUTATION ONLY: what comes after the greeting is the
# structure's job (see structures.md), so these never describe the opening sentence.
# Rules: every variant must keep {{ business_name }}; keep them time-neutral (no "Good
# morning/afternoon" — emails send and open at unpredictable times).
variants:
  - "Hi {{ business_name }},"
  - "Hello {{ business_name }},"
  - "Hello team at {{ business_name }},"
  - "Hi everyone at {{ business_name }},"
  - "Greetings {{ business_name }},"
---

# Greeting Variants

The variation engine picks one salutation per email so a campaign's emails don't all open
the same way. These are **literal first lines**, used as written.

- Every variant preserves the `{{ business_name }}` merge field.
- Keep them **time-neutral** — no "Good morning/afternoon", since send/open time varies.
- Don't add opening-sentence behavior here (observations, questions, reasons) — that belongs
  to the structure in `structures.md`, which defines what follows the greeting.
