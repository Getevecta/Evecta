---
# CTA (call-to-action) variants — one is chosen per email by the variation engine and fills
# the structure's "soft call to action" step. These are DIRECTIVES (intent), not literal text:
# the generator phrases the ask in the email's own context. Each is a DISTINCT archetype so
# rotation produces genuinely different asks. All must be soft / low-pressure — never use the
# aggressive_sales_phrases from spam_safe.md ("act now", "last chance", "book now").
variants:
  - "Soft meeting ask: invite a short 10-15 minute conversation, their convenience"
  - "Reply ask: invite a one-line reply to gauge interest, no pressure"
  - "Resource offer: offer to send a relevant example or resource and let them decide"
  - "Yes/no question: ask a single low-commitment yes/no question"
  - "Permission ask: ask if it's okay to share a little more detail"
  - "Right-person ask: ask if they're the right person, or who is best to speak with"
  - "Specific-time ask: suggest one specific, easy-to-decline time for a short call, no pressure"
  - "Feedback ask: ask for their brief opinion or perspective rather than pitching"
  - "Open door: invite a reply only if it resonates, with no follow-up pressure"
---

# CTA (Call-To-Action) Variants

The variation engine picks one CTA archetype per email and the generator phrases it to fit
the email's value proposition.

- **Directives, not literal text** — the LLM writes the actual sentence in context. (This is
  the opposite of greetings, which are used verbatim.)
- **Always soft** — low-commitment, no pressure. Hard-sell wording is forbidden by the
  `aggressive_sales_phrases` list in `spam_safe.md`.
- **Distinct archetypes** — keep each variant a different *kind* of ask (meeting, reply,
  resource, question, permission, referral, open door) so rotation feels varied, not reworded.
