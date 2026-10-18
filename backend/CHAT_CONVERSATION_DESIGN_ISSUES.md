# Chat Conversation Design Issues

Findings from reviewing the lead-generation chatbot's conversation design and prompt
engineering (`chat_service.py`, `chat_graph.py`, `chat_helper.py`), compiled during the
streaming implementation work. Status reflects what's fixed vs. still open as of this
writeup.

---

## 1. Raw exception text can leak into chat error replies

**Status: not fixed**

Pattern like `except Exception as e: raise HTTPException(..., detail=f"Unexpected error:
{str(e)}")` appears at multiple points in `chat_service.py` `_understand_phase`,
`_interact_phase`, `_search_phase`. If one of these fires, the user could see raw
Python/SQL error text instead of a clean, human-facing message.

**Why it matters:** breaks the "transparency without jargon" principle — internal
implementation details (stack traces, DB error strings) are not something an end user
should ever see, and can look unprofessional or even leak infrastructure details.

**Fix direction:** replace these with the same pattern already used elsewhere in this
file — catch, log the real exception server-side, return a clean generic user-facing
message (e.g. reusing `llm_error_result()`'s style).

---

## 2. Inconsistent copy for the same conversational state

**Status: not fixed**

The same logical state ("ask the user for industry," "ask the user for location") has
3+ different hardcoded fallback strings depending on which code path produces it:
`chat_service.py`'s own inline fallback strings vs. `chat_helper.py`'s
`generate_human_response`/`generate_human_response_stream` except-block fallback
strings. These read differently from each other and from the LLM-generated version of
the same ask.

**Why it matters:** breaks persona consistency — the assistant should sound like one
consistent "voice," not 3 different fallback voices depending on which error path was
hit.

**Fix direction:** consolidate all fallback copy for a given conversational state into
one shared source of truth, rather than duplicating slightly-different wording at each
call site.

---

## 3. Dead code in suggestion-generating functions

**Status: fixed** (resolved while converting these to streaming)

`chat_helper.py`'s `generate_suggestions` and `generate_suggestions_with_verification`
each contained ~100-150 lines of a fully-written, carefully tone-engineered LLM prompt
that was unreachable — every branch of the code that actually ran ended in an early
`return`, so the dead prompt below it never executed. Live behavior was a terse
deterministic f-string, not the "professional consultant" tone the dead prompt
described. This likely explained why suggestion replies felt flat/repetitive compared
to the rest of the conversation.

**Resolution:** both functions were rewritten as part of the streaming work — the dead
code was deleted (not just left unused), and the reachable path now genuinely calls the
LLM, grounded in verified city names only (never inventing a city), and streams like
every other reply.

---

## 4. No escalation or variation on repeated failures

**Status: partially fixed**

`build_ambiguous_clarification`'s variant pick used to be a **deterministic hash** of
`(industry, location, choices)` — so a user stuck giving an unparseable answer to the
same ambiguous query saw the literal identical message on every retry, with no
graceful exit after N failed attempts. The same applies to the scope and confirm gates.

**What's fixed:** the "identical message every retry" half. `build_ambiguous_clarification`
/ `build_scope_question` / `build_confirm_message` were replaced with real LLM calls
(`generate_ambiguous_clarification`, `generate_scope_question`, `generate_confirm_message`),
so phrasing now naturally varies turn to turn instead of being hash-locked to one of a
handful of pre-written variants.

**What's still missing:** actual escalation logic. There is still no mechanism anywhere
that counts how many times a user has been asked the same clarification/scope/confirm
question and does something different after N failed attempts — no retry counter, no
"let's just search broadly instead" fallback, no graceful exit. A user could
theoretically be asked the same *kind* of question indefinitely if their replies keep
failing to parse.

**Fix direction:** track an attempt counter in `context` for each gate; after N failed
attempts, either auto-resolve to the most likely option and proceed, or offer an
explicit "skip"/"just search broadly" escape hatch.

---

## 5. Unbounded list crammed into one sentence

**Status: not fixed**

`build_scope_question` (and now `generate_scope_question`, which was built on the same
`siblings` list without noticing this was a flagged problem) joins **every** sibling
business type into one prose sentence via `_format_choice_list()`
(`chat_service.py:522-531`), with no cap — unlike `search_terms` elsewhere in the
codebase, which is capped at 3 for exactly this reason.

**How bad in practice:** `understanding.py:233` explicitly instructs the model to
produce "3-6 practical search terms" for `scope_siblings`. A 6-item list crammed into
one clause reads like: *"...broaden it to include related types like motels, hostels,
resorts, guesthouses, inns, or bed-and-breakfasts."* — an awkward run-on sentence.

**Fix direction:** cap the sibling list (e.g. to 2-3) before formatting, matching the
existing `search_terms` precedent.

---

## 6. Conflicting rules inside the main reply prompt

**Status: not fixed**

`generate_human_response`'s prompt (`chat_helper.py:511-569`) contains directly
self-contradicting instructions:

- **The word "acknowledge" is both commanded and forbidden.** Rule 5: *"acknowledge what
  the user said earlier"*; Rule 3: *"acknowledge it"* (referring to a previously-asked
  question) — vs. the Response Structure section: *"NO unnecessary acknowledgments"* and
  *"DO NOT start with acknowledgments."* Same word, opposite instructions, no guidance on
  which wins.
- **The length budget can't fit both mandatory things.** Rule 7 caps answers at *"1-2
  sentences maximum"*; Rule 8 separately mandates *"ALWAYS...smoothly transition to
  mention how you can help with lead generation"* after answering — but the
  Response Structure section caps the **whole reply** at *"1-2 sentences maximum"* too.
  There's no way to always satisfy both the answer and the mandatory lead-gen transition
  within a 1-2 sentence budget.
- **Weaker, third tension:** Rule 9 says *"NEVER ask for clarification... just proceed
  with the search"*, but the prompt's own labeled "CORRECT" example — *"Would you like me
  to search in Helsinki or Tampere?"* — is itself a clarifying question (asking for a
  missing city). Arguably a different case (missing sub-detail vs. re-litigating
  meaning), so weaker than the other two, but still worth noting.

**Why it matters:** an LLM given contradictory instructions has no consistent way to
resolve the tension, so behavior varies unpredictably turn to turn — likely contributing
to replies feeling inconsistent or "off."

**Fix direction:** see issue #8 below — this should be resolved as part of a broader
prompt simplification, not patched in isolation.

---

## 7. Too much permission-asking before any value is delivered

**Status: decided, not yet implemented**

The full possible gate sequence before a search runs: ask for industry → ask for
location → ask whether to include sibling categories (scope, broad "family" terms
only) → ask for explicit confirmation → finally search. The confirmation gate
(`chat_service.py:1473`, `elif context.get("confirmed_goal") != goal_key:`) fires
**unconditionally** for any new industry|location combination — including a user who
already gave complete info in a single message (e.g. "restaurants in Kathmandu" still
gets stopped with a "want to refine, or say go?" prompt before searching).

**Why it matters:** confirmation doesn't actually catch misunderstandings — by the time
industry+location are resolved, the system is already confident it understood
correctly. It just re-asks permission for something the user already made clear,
adding a forced round-trip that delivers no value and was called out as "too much
restriction, leading to bad LLM responses."

**Decision:** remove the mandatory confirmation gate entirely. Once industry+location
are resolved (however they were resolved — one message or several), search runs
immediately. Refinement (best-rated first, different radius, etc.) becomes a follow-up
on real results instead of a blind pre-search negotiation.

**Resulting flow:** ask industry (only if missing) → ask location (only if missing) →
ask scope (only for broad "family" terms) → search.

---

## 8. Prompts are over-constrained — the model isn't "free"

**Status: decided, not yet implemented**

Counting the actual directives in `generate_human_response`'s prompt alone: **9
"CRITICAL RULES — NEVER VIOLATE," 6 tone/style bullets, 5 "Response Structure" bullets
(one of which contradicts the CRITICAL RULES — see #6), 6 hardcoded right/wrong
examples, and 9 more "General Rules."** That's 30+ individual directives the model must
simultaneously satisfy to answer something as simple as "hello."

**Why it matters:** an LLM buried under 30 competing constraints tends to produce
mechanical, checklist-shaped output instead of natural conversation. When some of those
constraints actively contradict each other (see #6), the model has no consistent way to
resolve the tension — likely the root cause behind replies feeling stiff, forced, or
inconsistent.

**Decision:** trim the prompt substantially:
- Keep a short persona statement (warm, professional lead-gen consultant)
- Keep only the genuinely functional rules: remember conversation context, don't re-ask
  for info already known, stay oriented toward lead generation
- Drop the hard "1-2 sentences maximum" cap and the "always must transition to lead-gen"
  mandate — replace with something softer that doesn't force a math problem every reply
- Drop the acknowledgment ban entirely (self-contradicting, not clearly necessary)
- Drop or drastically shrink the 6 rigid CORRECT/WRONG examples

The same philosophy applies to the newer prompts
(`generate_ambiguous_clarification`/`generate_scope_question`/`generate_confirm_message`/
`generate_suggestions*`) for their **stylistic** instructions — but their **functional**
constraints (never invent a city that wasn't verified, must convey "say go" to proceed)
should stay exactly as strict as they are now; those aren't restricting the model's
freedom, they're correctness requirements that prevent hallucination and broken
conversation flow.

---

## 9. No single agent — 6 independently-authored prompts

**Status: not fixed, plan below**

There are currently **6 separate places** that each independently write "You are a
professional business lead generation consultant..." (or similar) and define their own
tone/persona rules, with no shared source of truth between them:

1. `understand()` (`understanding.py`) — the classification call
2. `generate_human_response_stream` (`chat_helper.py`)
3. `generate_ambiguous_clarification_stream` (`chat_service.py`)
4. `generate_scope_question_stream` (`chat_service.py`)
5. `generate_confirm_message_stream` (`chat_service.py`)
6. `_stream_grounded_suggestion` (`chat_helper.py`, shared by the two suggestion functions)

**Why it matters:** this is the structural root cause behind #2 (inconsistent copy) and
#6/#8 (conflicting/over-constrained prompts). With 6 independently-maintained persona
definitions, tuning tone in one place doesn't propagate to the other 5 — they drift out
of sync over time, and there's no single "voice" the assistant actually has.

**A concrete cost leak this surfaced:** `understanding.py` still instructs the model to
write `reply`, `clarify_question`, and `scope_question` (lines 90, 220, 234) on every
applicable turn — but **none of these three are read by anything anymore** (verified via
grep — only `context.pop(...)` cleanup calls remain). These fields became dead once the
`u.reply`/`u.clarify_question`/`u.scope_question` short-circuits were removed earlier in
this work (see the "always stream" fixes above). Every relevant turn is generating real
output tokens for text that gets silently discarded — pure wasted cost and latency.

---

## How we'll fix #6, #8, and #9 together

These three are one underlying problem (fragmented, inconsistent, over-constrained
prompting), so we'll fix them as a single piece of work rather than patching each prompt
separately.

**Step 1 — stop the wasted generation (quick, no design decision needed).**
Remove `reply`, `clarify_question`, and `scope_question` from the `Understanding`
schema and prompt in `understanding.py`. Nothing reads them anymore, so this is a pure
cost/latency win with zero behavior change. Also remove the now-pointless
`context["_refine_reply"] = u.reply` line and the `context.pop("clarify_question", ...)`
/ `context.pop("scope_question", ...)` cleanup calls in `chat_service.py`, since the
fields won't exist to pop.

**Step 2 — define one shared persona, once.**
Add a single constant (e.g. `CHAT_PERSONA` in `chat_helper.py`, since `chat_service.py`
already imports from it — no circular import) that holds the assistant's identity and
the handful of rules that are genuinely universal:
- Who it is (warm, professional lead-gen consultant)
- Remember and use conversation history — never re-ask for known info
- Keep replies natural and concise — no hard sentence-count cap, let content dictate
  length
- Naturally lean toward lead generation when it fits, without forcing it into every
  reply
- No acknowledgment ban (removes the #6 contradiction entirely, rather than patching it)

**Step 3 — rewrite all 6 prompt-builders to include the shared persona instead of
re-declaring it.**
Each of the 6 functions keeps its own **task-specific** instructions (what makes each
one different — e.g. "list these exact verified candidates" for ambiguous
clarification, "the message must convey saying 'go' to proceed" for confirm, "return
structured JSON for intent classification" for `understand()`) but no longer writes its
own version of "who you are and how you sound." That part is included from the one
shared definition. Functional/correctness constraints specific to each prompt (never
invent a city, must preserve the exact candidate list, must include "go") stay exactly
as strict as they are now — only the stylistic over-constraining gets trimmed, per #8.

**Step 4 — implement the confirmation-gate removal (#7, already decided separately).**
Delete the mandatory confirm step in `_interact_phase` so search runs immediately once
industry+location are resolved, regardless of how many turns it took to get there.

**Step 5 — test.**
Re-run the standalone streaming checks for all 6 functions with the new shared prompt,
then a live end-to-end pass through `/chat/stream` covering: greeting, ask-industry,
ask-location, ambiguous, scope, results-present, and the no-confirmation-gate search
flow.

---

## 10. Scope clarification is over-applied

**Status: decided, not yet implemented**

The `understand()` prompt explicitly instructs the model to treat ordinary, specific
searches as members of a broader "family" and gate them behind a scope question —
turning a plain search like "hotels" into an unnecessary taxonomy interview.

**Relevant code:**
- [`understanding.py:224-231`](app/services/understanding.py) — the SCOPE prompt
  section. Line 225 explicitly says: *"Do not skip scope just because the user asked
  for a specific member. If a buyer asking for that member might reasonably want
  adjacent family types too, ask scope first."* It hardcodes 5 trigger families
  (accommodation, education, healthcare facilities, fitness, travel services) —
  "hotels, resorts, motels, hostels, guesthouses, B&Bs" all map to
  `scope_family="accommodation"`.
- [`chat_service.py:1197-1202`](app/services/chat_service.py) — the only thing that
  suppresses the gate is `_strict_narrow`, which requires the user's message to contain
  an explicit "only"/"just"-type qualifier (`OVERTURE_STRICT_INTENT_MARKERS`). A plain
  first message like "hotels in Kathmandu" has no such qualifier, so the gate fires
  every time.

**Why it matters:** most users saying "hotels" mean hotels. Being interrupted with
"did you want just hotels, or also motels, resorts, hostels, guesthouses, and B&Bs?"
before any search happens is exactly the kind of unnecessary permission-asking flagged
in #7/#8 — just via a different trigger (the scope gate specifically, not the
confirmation gate).

**Recommended policy (from review):**
1. Search the literal category first — don't gate the first search on this.
2. Present adjacent categories as optional expansion chips after results, instead of a
   blocking chat question before results.
3. Only ask before searching when two interpretations would create substantially
   different lead pools — tighten the SCOPE prompt so `scope_family` is reserved for
   genuinely ambiguous cases, not applied by default to every family-adjacent term.
4. Learn from interaction — if a user repeatedly broadens a search themselves, remember
   that preference.

**Split by ownership:**
- **1 and 3 are backend-only** and follow the same philosophy as #7: search
  immediately with the literal term; tighten the SCOPE prompt instructions so the gate
  only fires for genuinely ambiguous cases.
- **2 (expansion chips) is a joint effort** — backend can search immediately and
  include `scope_family`/`scope_siblings` in the response `data` as metadata so nothing
  is lost, but rendering an actual clickable chip is frontend work, handed off the same
  way the streaming SSE contract was.
- **4 (learned preference) is a separate, larger feature** — needs persisting a
  per-user/per-industry preference somewhere; not scoped here.

---

## Summary table

| # | Issue | Status |
|---|---|---|
| 1 | Raw exception leaks in error replies | Not fixed |
| 2 | Inconsistent fallback copy (3+ versions of same state) | Not fixed |
| 3 | Dead code in suggestion functions | **Fixed** |
| 4 | No escalation on repeated failures | Partially fixed (variation yes, escalation no) |
| 5 | Unbounded sibling list in one sentence | Not fixed |
| 6 | Conflicting rules in main reply prompt | Not fixed |
| 7 | Too much permission-asking (confirmation gate) | Decided — pending implementation |
| 8 | Over-constrained prompts, LLM not "free" | Plan written (see "How we'll fix #6, #8, and #9") |
| 9 | No single agent — 6 independently-authored prompts, wasted `understand()` generation | Plan written (see "How we'll fix #6, #8, and #9") |
| 10 | Scope clarification over-applied (plain "hotels" triggers a taxonomy interview) | Decided — backend part pending implementation, chips part needs frontend |
