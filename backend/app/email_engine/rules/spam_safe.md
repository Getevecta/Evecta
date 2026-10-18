---
# ============================================================================
# Machine-read config, parsed from this YAML frontmatter by loader.py.
# Single source of truth shared by stage #3 (generator guidance) and stage #4
# (compliance gate). Edit only this file to keep both in sync.
#
# The lists are TIERED by strictness so the hard block stays false-positive safe:
#   prohibited_phrases     -> HARD block: #4 rejects an email containing any of these
#   spam_trigger_words     -> SOFT: generator avoids; #4 flags but does NOT reject
#   harmful_claim_phrases  -> overpromising claims to avoid ("harmful claims")
#   aggressive_sales_phrases -> pushy language to avoid ("aggressive sales language")
# All matching is case-insensitive (matching logic lives in stage #4).
# ============================================================================

# HARD block — only unambiguous spam. Multi-word / specific, near-zero false positives.
# Do NOT add common single words here (e.g. "free") — those go under spam_trigger_words.
prohibited_phrases:
  - this is not spam
  - buy now
  - order now
  - act now
  - act fast
  - click here
  - 100% free
  - risk-free
  - cash bonus
  - you have won
  - you've won
  - claim your prize
  - limited time offer
  - limited time only
  - no obligation
  - no credit card required
  - once in a lifetime

# SOFT — spammy in marketing but common in legitimate copy ("feel free", "our guarantee").
# The generator avoids them; the gate flags (does not reject) so good emails aren't bounced.
spam_trigger_words:
  - free
  - urgent
  - guarantee
  - guaranteed
  - winner
  - cheap
  - discount
  - exclusive
  - bonus
  - deal
  - promo
  - congratulations

# Overpromising / unverifiable claims — avoid entirely (PDF: "harmful claims").
harmful_claim_phrases:
  - guaranteed results
  - guaranteed returns
  - double your revenue
  - triple your sales
  - instant results
  - get rich
  - make money fast
  - risk-free investment

# Pushy / pressure-driven language (PDF: "aggressive sales language").
aggressive_sales_phrases:
  - don't miss out
  - last chance
  - hurry
  - only today
  - limited spots
  - don't wait
  - final notice

# Overused / low-deliverability openers — the generated email must not start with these.
openings_to_avoid:
  - Hope this finds you well
  - Hope this email finds you well
  - I hope you're doing well
  - I hope all is well

# Must appear (double-brace form) in every generated email.
required_merge_fields:
  - "{{ business_name }}"
  - "{{ industry }}"
  - "{{ address }}"

# General deliverability/writing rules applied to every email (soft guidance).
deliverability_rules:
  - No emojis or special characters.
  - No ALL CAPS words or shouting.
  - No excessive punctuation (no "!!!", "???").
  - Maximum 1-2 links; avoid link-heavy bodies.
  - Do not use URL shorteners (bit.ly, tinyurl, etc.).
  - Keep a healthy text-to-link ratio.
  - Proper grammar and spelling; natural sentence structure.
  - Never write in meta voice (do not say you are a copywriter, writer, or AI; do not open with "As a B2B...").
  - Subject line under 50 characters, professional, specific, no spam triggers.
  - Do not put "Re:" or "Fwd:" on a cold first-touch subject line.
  - Body ~100-160 words; finish every sentence (never stop mid-sentence).
---

# Spam-Safe Writing Rules

Single source of truth for spam-safe writing. The tiered lists in the frontmatter above are
parsed by `loader.py` and shared with stage #4's compliance gate. The notes below are human
guidance for whoever edits this file.

## How the tiers are meant to be used
- **`prohibited_phrases` (hard block):** keep this list conservative. Only add a phrase here
  if an email containing it should be **rejected outright**. Prefer multi-word, unambiguous
  spam. A wrong entry here bounces legitimate emails.
- **`spam_trigger_words` (soft):** single words that are fine in context. The generator is
  told to avoid them; the gate may lower a score or warn, but must not reject on these alone.
- **`harmful_claim_phrases` / `aggressive_sales_phrases`:** writing guidance for the
  generator and signals for the compliance review; tune freely.

## Merge field usage
- Greeting must be one of the approved salutations in `greetings.md` — all address
  `{{ business_name }}`.
- Use `{{ industry }}` and `{{ address }}` naturally in the body, not only the subject.
- Never hardcode a specific industry (e.g. "pharmacy", "restaurant") or a specific
  location/city (e.g. "London", "New York") — use the placeholders only.
