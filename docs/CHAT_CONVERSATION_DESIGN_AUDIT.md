# Chat Conversation Design Audit — Findings & Fix List

Consolidated from a multi-round review of the lead-generation chat (`chat_service.py`, `chat_graph.py`,
`chat_helper.py`, `understanding.py`) against conversation-design guidance from Google (Assistant
Conversation Design + Dialogflow CX), Anthropic, OpenAI, Microsoft (Bot Framework), and Amazon (Alexa),
plus a direct comparison against Instantly's Copilot chat.

**Status:** diagnosis only — nothing below has been fixed yet. Every item is grounded in a specific
file/line and, where applicable, the source guidance that flags it. Numbering is a flat checklist, not
a strict priority order (priority notes are called out per section) — grouping may not match any prior
informal tally 1:1 since some findings can be split or merged depending on how you count them.

---

## A. Architecture / structural (fix these first — everything else compounds on top)

| # | Finding | Where | Source |
|---|---|---|---|
| 1 | `ChatState` has no retry/failure counter. A user stuck on ambiguity, scope, or repeated no-results loops forever with no escalation and no exit. | `chat_graph.py:39-44` | Google Assistant Errors page ("max 3 consecutive"); Dialogflow CX agent-design (error-counter + condition route); OpenAI agent guide ("set limits on agent retries... escalate") — 3 independent vendors |
| 2 | Explicit "say go" confirmation is used for every search, including fully-specified, reversible, low-cost ones. Explicit confirmation should be rare, reserved for hard-to-undo/high-stakes actions. | `chat_service.py:914-918`, `build_confirm_message` at `chat_service.py:416` | Google Confirmations page (explicit = "Rare"); OpenAI guardrails guide (human oversight for "sensitive, irreversible, high-stakes" actions) |
| 3 | Scope-family question fires even when the user named a specific, non-family type — the prompt explicitly instructs this. | `understanding.py:218` | Contradicts Google's "balance clearly defined paths with users' desire for shortcuts" (Write Sample Dialogs) |
| 4 | Full conversation history is re-serialized into every LLM call, unbounded — no summarization/compaction as the conversation grows. Cost and latency grow with every turn. | `understanding.py:120` (`_format_history`), `chat_helper.py:528-539` | Anthropic "Effective context engineering for AI agents" — names this exact fix as "compaction" |
| 5 | No declared precedence between the prompts' own internal rules (e.g. "remember everything" vs "keep responses to 1-2 sentences"). | `chat_helper.py:549` (prompt), `understanding.py:178` (prompt) | OpenAI Model Spec's instruction-authority hierarchy (Root > System > Developer > User > Guideline) has no analog here |
| 6 | Existing `user_profile` / `company_profile` data (already built for email personalization) is never used by the lead-search chat — every conversation starts from zero even for a user whose ICP is already known. | `writing_spec_service.py:20-21`, `personalization_service.py` — zero references from `chat_service.py` | Direct gap vs. Instantly Copilot, which opens with known ICP data instead of asking from scratch |
| 7 | Disambiguation (`candidate_meanings`) and scope (`scope_siblings`) are asked as free-text prose when they're really enumerable option sets — a case where conversation may be the wrong medium at all. | `build_ambiguous_clarification` / `build_scope_question`, `chat_service.py:322-413` | Google "Is Conversation the Right Fit?" (browsing many options "feels clunky" in pure text/voice); Chips page's hard limits (max 8 items, 25 chars) |

## B. Prompt engineering (the calls themselves are built wrong, per the vendor whose model you call)

| # | Finding | Where | Source |
|---|---|---|---|
| 8 | `understand()`'s classification call runs at `temperature=0.7` — high randomness on intent/ambiguity/scope/confirmation decisions that should be deterministic. Inconsistent with your own `overture_category_service.py:139`, which uses `temperature=0` for a comparable classification task. | `understanding.py:108` | Gemini's own prompting docs: "temperature 0 is deterministic... we strongly recommend keeping at default values" |
| 9 | Two "mega-prompts" each cram many unrelated instructions into one call instead of being decomposed. | `build_understanding_prompt`, `understanding.py:178`; `generate_human_response`'s prompt, `chat_helper.py:549` | Gemini's own docs: "instead of having many instructions in one prompt, create one prompt per instruction" |
| 10 | No true few-shot example turns in the understanding prompt — relies on abstract rules + tiny inline examples. | `understanding.py:178-244` | Gemini's own docs: "always include few-shot examples... prompts without them are likely to be less effective" |
| 11 | No chain-of-thought/scratchpad step before the structured JSON output — `json_mode` may suppress deliberation on hard calls. | `understanding.py:113` | Anthropic: "giving Claude time to think through its response before producing the final answer leads to better performance" |
| 12 | No grounding/retrieval for ambiguity or scope-family detection — the model invents a taxonomy from memory instead of being given real candidate data. | `understanding.py` AMBIGUITY/SCOPE sections | Contrast with your own `overture_category_service.py:156-179`, which retrieves real candidates before asking the model to choose (RAG pattern) |
| 13 | Every call — simple reply wording *and* hard judgment calls — runs on the same model tier (`gemini-3.5-flash`, per `backend/.env`). No routing of harder decisions to a stronger model. | `understanding.py`, `chat_helper.py` | Anthropic: "routing easy questions to cheaper models, hard ones to capable models" |
| 14 | No growing few-shot/golden-set loop fed by real production misses — the only test set is a small, static, hand-written list. | `tests/integration/test_understanding.py` | Vendor-common "test and iterate" guidance; Anthropic's evaluator-optimizer pattern |

## C. Error handling / recovery

| # | Finding | Where | Source |
|---|---|---|---|
| 15 | Raw Python/SQL exception text can leak into the user-facing error message. | `chat_service.py:743, 930, 1513` (`detail=f"...{str(e)}"`) | Google: "be transparent without being overly technical" |
| 16 | Failure recovery is generic and not state-aware — same message regardless of which phase failed, doesn't acknowledge preserved context. | `llm_error_result`, `llm_errors.py:30-35` | — |
| 17 | `LLM_UNAVAILABLE_USER_MESSAGE` says "please try again in a moment" — the literal named anti-pattern. | `llm_errors.py:26` | Google Endings page: "don't give vague advice like 'try again later'" |
| 18 | No escalation or wording variation on repeated failures — a stuck user sees the identical disambiguation message every retry (deterministic hash-based variant pick). | `build_ambiguous_clarification`, `chat_service.py:322-392` | Google: "don't repeat the same thing over and over... it will sound robotic" |
| 19 | "done" / "that's all" / "forget it" are treated only as a proceed-with-search signal, but these are also the canonical abandon-request phrases — no cancel/abandon intent exists to disambiguate. | `chat_service.py:902`; `Understanding` intent enum, `understanding.py:40-42` | Google Endings page names these exact phrases as the abandon signal |

## D. Copy & consistency

| # | Finding | Where | Source |
|---|---|---|---|
| 20 | The same conversational state ("ask for industry," "ask for location") has 3+ different hardcoded phrasings depending on which code path fires. | `chat_service.py:764, 781, 787` vs. `chat_helper.py:617-623` | Google Scale Your Design: "don't design prompts that feel like they're coming from different personas" |
| 21 | No written persona spec exists anywhere in the repo for those scattered strings to be checked against — root cause of #20. | — | Google Create-a-Persona page (4-6 core traits doc); Anthropic's own published Claude persona values |
| 22 | `build_confirm_message` bundles up to 5 options into a single turn. | `chat_service.py:416-486` | Google: "don't offer more than 3 options simultaneously"; "prompt with only a single question at a time" |
| 23 | Exclamation marks appear throughout deterministic fallback copy while the LLM prompt tells the model to avoid them — self-contradictory. | `chat_helper.py:606` (rule) vs. `:619, 621`; `chat_service.py:473` | Google style guide: "avoid exclamation points, they can be perceived as shouting" |
| 24 | `.title()` mangles apostrophes in chat titles/prose (`"mcdonald's".title()` → `"Mcdonald'S"`, verified). | `chat_service.py:290-306, 362` | — |
| 25 | Title Case is the wrong convention regardless of the bug — style guide calls for sentence case on titles/labels. | same as #24 | Google Capitalization & Punctuation: "use sentence case... capitalizing only the first word" |
| 26 | `build_scope_question`'s sibling list has no cap, unlike `search_terms` (capped at 3) — can produce a long run-on sentence. | `chat_service.py:395-413` | Chips page's ~8-item ceiling as an eventual UI constraint |
| 27 | Acknowledgments are banned outright in the prompt ("NO unnecessary acknowledgments"), further than the sourced guidance ("vary and don't overuse," not "never"). | `chat_helper.py:581` | Google Acknowledgements page: skipping them "makes dialogue feel abrupt" |
| 28 | Heavy, uniform em-dash "Opener — clause. Tail" cadence repeats across nearly every canned message — reads as one template stamped many times. | `chat_service.py:462` (openers list) and similar across `build_*` functions | Minor/stylistic |

## E. Efficiency

| # | Finding | Where | Source |
|---|---|---|---|
| 29 | A simple single-fact turn ("which industry?") already costs 2 Gemini calls, even though a deterministic fallback string for exactly that question already exists and is only used when the LLM call fails. | `chat_service.py:760-791` | — |
| 30 | ~150 lines of tone-engineered prompt are dead code — unreachable after an earlier unconditional `return`, so that tone work never executes; the real reply is a terse hardcoded sentence. | `chat_helper.py:292-406`, `:435-498` | — |

## F. Testing

| # | Finding | Where | Source |
|---|---|---|---|
| 31 | The only test touching this system asserts on structured extraction fields from a single call — nothing exercises the graph, the gates, or reply-copy quality across a multi-turn conversation. | `tests/integration/test_understanding.py` | Vendor-common "test and iterate" guidance |
| 32 | No usability-style testing method in place (someone unfamiliar with the project trying the dialog, documenting unanticipated phrasings). | — | Google Test-and-Iterate page |

## G. Frontend continuity / post-results conversation

| # | Finding | Where | Source |
|---|---|---|---|
| 33 | The chat and the results are mutually exclusive views. When `currentLeads.length > 0`, the component switches to the results branch instead of keeping the conversation beside the results. | `frontend/src/features/dashboard/components/LeadGeneration/LeadGeneration.tsx` (`currentLeads.length > 0` render branch) | Google Cloud conversational-agent design recommends an integrated/co-browse experience where results and conversational refinement remain together |
| 34 | The composer disappears once results exist because the bottom input is rendered only when `currentLeads.length === 0`. Users therefore cannot naturally say "only premium ones," "change to Sydney," or "exclude chains" while looking at the current results. | `LeadGeneration.tsx` bottom-input condition | Conversation should remain available until the task is complete; corrections and refinements should not require restarting |
| 35 | Transcript messages are explicitly hidden when the lead table is visible, removing the common ground that explains how the current result set was produced. | `LeadGeneration.tsx` `shouldHideMessages = currentLeads.length > 0` | Google confirmations/common-ground guidance; multimodal guidance treats visible screen state as part of the conversation |
| 36 | Submitting a new message resets the current leads, result title, selection, filters, and pagination before the backend has decided whether the message is a new search, a refinement, or ordinary conversation. | `LeadGeneration.tsx` `handleSubmit` reset block | A conversational refinement should update an active object rather than destructively resetting it before intent is known |
| 37 | Suggestion tags are static welcome prompts rather than context-aware next actions derived from the current pending question, active search, or result set. | `LeadGeneration.tsx` `suggestionTags` | Google Suggestions/Chips guidance; Instantly and lemlist use workflow- and context-aware task starters |

## H. Response quality / adaptive depth

| # | Finding | Where | Source |
|---|---|---|---|
| 38 | One global "VERY SHORT (1-2 sentences maximum)" rule controls greetings, explanations, missing-slot prompts, search summaries, and recovery. These conversational acts need different amounts and structures of information. | `chat_helper.py` `generate_human_response` prompt | Conversation-design guidance favors concise but sufficient answers; response length should follow the task and turn, not one universal ceiling |
| 39 | No explicit response-mode contract exists. The response writer is not told whether it is producing a greeting, clarification, search acknowledgement, result summary, refinement summary, no-results recovery, or general answer. | `chat_helper.py`, `chat_service.py` | Structured output/policy patterns: determine the act first, then generate copy appropriate to that act |
| 40 | Search-completion copy is not given a structured result summary containing applied filters, total matches, displayed matches, contact coverage, unverifiable assumptions, and useful next actions. This prevents meaningful explanations even if the length restriction is removed. | `_search_phase` → `generate_human_response` passes raw context plus top 3 leads | Competitor pattern: explain the interpreted goal and return structured, editable output rather than generic completion prose |
| 41 | The prompt forces a lead-generation redirect after general questions, which can make answers feel transactional and dismissive even when the user asked a legitimate product or informational question. | `chat_helper.py` rule "ALWAYS include lead generation" | Microsoft conversational UX: respond to the user's need first and guide without creating a repetitive forced redirect |
| 42 | The system does not track recent wording, opener, response mode, or repair strategy, so "variation" is local randomness rather than conversation-level style control. | `ChatState` / `context` have no response-style state | Google variation guidance: frequent prompts should vary while maintaining one persona and avoiding repetition across adjacent turns |

### Required response modes

The conversation policy should select a response mode before wording is generated:

| Response mode | Expected behavior |
|---|---|
| `greeting` | One or two warm sentences; use known context only when helpful |
| `missing_information` | Ask one focused question and do not repeat known fields |
| `clarification` | Briefly explain why the distinction matters, present choices, ask one question |
| `search_acknowledgement` | State the understood goal and begin work without requiring a low-risk "say go" turn |
| `search_summary` | State what was searched, what was found, material limitations, and relevant next actions |
| `refinement_summary` | State what changed and what important filters were retained |
| `general_answer` | Answer to the depth needed; do not force every answer into two sentences |
| `no_results` | Preserve the goal, explain what was attempted, and offer concrete recovery choices |
| `error_recovery` | Identify the failed phase in user language, preserve valid context, and offer a real next step |

## I. Structured conversation state / memory

| # | Finding | Where | Source |
|---|---|---|---|
| 43 | The active goal is stored as a loose context dictionary mixed with transient routing keys such as `_intent`, `_scope_choice`, `_new_city`, and pending-gate flags. There is no explicit versioned `active_goal` object. | `chat_service.py` context mutation throughout `_understand_phase` and `_interact_phase` | State-machine design: durable task state should be separated from transient execution state |
| 44 | `Understanding` has no calibrated `confidence`, `missing_fields`, `changes`, or `should_search` output. Policy therefore cannot cleanly distinguish "proceed," "state an assumption," and "ask one smart question." | `understanding.py` `Understanding` schema | Confidence-aware clarification pattern; clarification should be proportional to uncertainty and consequence |
| 45 | No `pending_question` object records what was asked, acceptable answer types, attempt count, or whether the user interrupted instead of answering. Pending behavior is distributed across flags. | `context["awaiting_*"]` flags | Frame-based dialog management; repair needs to know the exact pending frame and retry state |
| 46 | Short-term transcript, rolling summary, active task state, stable user preferences, and retrievable product knowledge are not separated into distinct memory layers. | `ChatState.messages` plus `ChatState.context` only | LangGraph/agent memory guidance: trim or summarize short-term history and separate durable memory from the active thread |
| 47 | The frontend can restore old messages from `sessionStorage` while the backend may use `MemorySaver` and lose state after restart. The screen can therefore show a conversation the assistant no longer remembers. | `LeadGeneration.tsx` storage restoration; `main.py` in-memory checkpointer fallback | User-visible transcript and server-side conversation state must agree |
| 48 | There is no explicit `last_search` / `active_result` reference tying a follow-up turn to the result set currently visible to the user. | `ChatState`, chat response schema, frontend state | Conversational refinement requires a stable active object and one-step corrections |

### Target state shape

```json
{
  "active_goal": {
    "industry": "dental clinics",
    "location": "Melbourne",
    "country": "Australia",
    "radius_km": 10,
    "quality": "top_rated",
    "include": [],
    "exclude": ["chains"],
    "requires_email": false,
    "confidence": 0.94,
    "version": 3
  },
  "pending_question": null,
  "active_result": {
    "search_id": "search_123",
    "result_count": 31,
    "displayed_count": 20
  },
  "recent_messages": [],
  "conversation_summary": "",
  "retry_state": {
    "clarification": 0,
    "no_results": 0,
    "system_error": 0
  },
  "last_response_mode": "search_summary",
  "last_response_style": {
    "opener": "I found",
    "repair_strategy": null
  }
}
```

## J. Conversation policy / corrections and interruptions

| # | Finding | Where | Source |
|---|---|---|---|
| 49 | The model currently performs interpretation, slot carry-forward, taxonomy generation, gate-question writing, and some policy decisions in one structured call. The backend then layers additional gates on top. Responsibility for "what happens next" is not cleanly owned. | `understanding.py` + `_understand_phase` + `_interact_phase` | Hybrid policy pattern: model interprets language; deterministic policy applies product rules; response writer controls natural expression |
| 50 | No explicit confidence policy exists for proceeding versus clarifying. Clear requests can be over-confirmed while uncertain but non-flagged requests can proceed. | `_interact_phase` confirmation and ambiguity branches | Clarify only when uncertainty materially changes the outcome |
| 51 | Corrections are supported in some confirmation cases, but there is no general interruption policy for a user who answers a different question, changes topic, cancels, returns to a previous search, or modifies multiple fields at once. | `Understanding.intent` and pending-flag prompt blocks | Google cooperative principle and one-step corrections; users often provide more or different information than literally requested |
| 52 | The backend decides some actions deterministically but also asks Gemini to generate simple transition copy without a response plan. Correctness and natural wording are coupled. | missing-industry/location paths call `generate_human_response` | Target pattern: backend decides **what** (`ask_missing_field: location`); Gemini or varied templates decide **how** to say it |

### Target decision policy

```text
Interpret message
    ↓
Apply corrections to active goal
    ↓
If cancel/abandon → stop safely and preserve useful state
If high-confidence + required fields present → proceed
If medium-confidence → state the assumption and proceed
If low-confidence and alternatives materially differ → ask one clarification
If a high-impact/irreversible action is requested → explicit confirmation
Otherwise → implicit confirmation through the next response
```

The thresholds must be calibrated using real evaluation data rather than treated as universal constants.

## K. Streaming / perceived performance / cancellation

| # | Finding | Where | Source |
|---|---|---|---|
| 53 | The current chat endpoint returns one completed response; normal assistant text and phase progress are not streamed. | `backend/app/api/v1/chat.py` | Dialogflow/LLM latency guidance distinguishes time-to-first-response from total completion time |
| 54 | The frontend shows one generic "Thinking..." indicator and does not communicate whether the system is understanding, checking stored leads, searching external data, ranking, or recovering. | `LeadGeneration.tsx` loader bubble | Progress visibility and system-status heuristic |
| 55 | There is no user-facing cancellation contract for an active chat/search run. Disabling the composer is not equivalent to safely stopping work. | chat API + `LeadGeneration.tsx` loading state | User control and freedom; long-running agent/tool operations need bounded cancellation |
| 56 | There is no resumable run/event identifier, event ordering, terminal-state contract, or reconnect behavior for interrupted streaming connections. | chat API and response schema | Production streaming requires idempotent run identity, ordered events, and explicit completion/failure/cancellation |
| 57 | Raw model reasoning is not an appropriate progress payload. If a "Thinking" panel is added, it should expose concise, truthful activity summaries and tool states rather than private chain-of-thought. | future UI/API requirement | Safe agent UX pattern; observable execution summaries are more useful and stable than raw internal monologue |

### Minimum streaming event contract

```json
{"type":"run.started","run_id":"run_123","sequence":1}
{"type":"status","stage":"understanding","sequence":2}
{"type":"goal.updated","goal":{"industry":"dentists","location":"Melbourne"},"sequence":3}
{"type":"status","stage":"checking_existing_leads","sequence":4}
{"type":"status","stage":"searching_external_sources","sequence":5}
{"type":"result.count","count":31,"sequence":6}
{"type":"response.delta","text":"I found 31","sequence":7}
{"type":"run.completed","sequence":8}
```

Required terminal states:

- `run.completed`
- `run.failed`
- `run.cancelled`
- `run.waiting_for_user`

Do not emit a status unless the corresponding operation has actually started.

## L. RAG boundary / grounded product knowledge

| # | Finding | Where | Source |
|---|---|---|---|
| 58 | Product/help questions are answered from the model prompt and general model knowledge; there is no retrieval path for approved Evecta documentation. | `understanding.py` general-question handling; `generate_human_response` | RAG is appropriate for versioned product knowledge and support answers |
| 59 | No intent boundary distinguishes structured lead retrieval, conversational state, documentation retrieval, and general conversation. Using one mechanism for all four would reduce reliability. | chat routing | Structured databases/tools for lead records; state for current dialogue; RAG for knowledge; LLM for natural response |
| 60 | No source metadata, audience designation, version, freshness policy, or stale-document strategy is defined for a future chat knowledge index. | — | Retrieval quality depends on document governance, not only embeddings |

RAG must **not** be used as a substitute for:

- remembering the active industry/location;
- resolving a pending question;
- applying a correction such as "change Melbourne to Sydney";
- querying structured lead records;
- deciding whether a search is allowed to proceed.

The first RAG collection should contain approved, user-facing product documentation and FAQs only. It should exclude secrets, environment files, raw server logs, stale internal notes, and implementation details not intended for customers.

## M. Measurement / conversational quality

| # | Finding | Where | Source |
|---|---|---|---|
| 61 | No conversational funnel metrics distinguish understanding latency, unnecessary clarification, successful refinement, repeated questions, recovery, and abandonment. | logging/analytics gap | Conversation quality needs journey-level measurement |
| 62 | Existing logs expose implementation activity but do not form an anonymized, reviewable evaluation record with expected goal state and outcome labels. | chat logging | Evaluator/golden-set iteration pattern |
| 63 | No response-quality rubric tests whether an answer is meaningful, acknowledges retained context, states material limitations, and offers appropriate next actions. | tests gap | Human and model-assisted evaluation should use explicit criteria |
| 64 | No performance budgets are defined for time to first progress event, time to first response text, decision latency, or time to usable results. | API/UI gap | Streaming improves perceived latency only when events are prompt, truthful, and useful |

### Core chat metrics

- time to first visible progress;
- time to first assistant text;
- turns before a usable result;
- unnecessary clarification rate;
- repeated-question rate;
- correction success rate;
- post-results refinement success rate;
- active-goal retention accuracy;
- no-results recovery success;
- abandonment after each assistant turn;
- user-rated helpfulness/relevance;
- percentage of conversations completed without restarting.

## N. Prioritized implementation plan

This remains a **chat-only** roadmap. Campaign builders, outreach agents, and unrelated workspace automation are out of scope.

### Phase 1 — Policy and response quality

1. Add response modes and remove the universal 1-2 sentence ceiling.
2. Extend `Understanding` with structured changes, missing fields, ambiguity, and a confidence signal.
3. Introduce one deterministic conversation-policy function that chooses answer/clarify/search/refine/cancel.
4. Remove explicit "say go" confirmation from clear, reversible searches.
5. Add cancel/abandon and general interruption handling.
6. Sanitize all user-facing exceptions.

### Phase 2 — State and continuity

1. Separate durable `active_goal` from transient routing state.
2. Add `pending_question`, retry counters, and `active_result`.
3. Add token-aware recent-history limits and a rolling conversation summary.
4. Keep the composer and relevant transcript available after results.
5. Apply refinements to the active result/search instead of resetting frontend state immediately.
6. Add structured, context-aware quick replies.

### Phase 3 — Streaming and control

1. Add a run ID and streaming event endpoint/response.
2. Emit truthful progress events from understand/interact/search operations.
3. Stream final response text where supported.
4. Add cancellation, terminal events, timeout handling, and reconnection behavior.
5. Render a collapsible activity panel without exposing raw chain-of-thought.

### Phase 4 — Grounded help and evaluation

1. Add documentation-RAG routing for approved product/help questions.
2. Create multi-turn graph tests and golden conversation journeys.
3. Add response-quality rubrics and anonymized production-miss review.
4. Instrument the core metrics above and calibrate clarification thresholds.

## O. Acceptance criteria

The chat redesign is not complete until these behaviors pass automated multi-turn tests and human UX review:

1. A clear request such as "Find dentists in Melbourne" proceeds without requiring "say go."
2. The assistant asks only one focused question when a required field is genuinely missing.
3. "Actually, Sydney" changes only the location and retains the industry and applicable filters.
4. A user can change industry while the assistant is waiting for a location; the new industry is not misread as the location answer.
5. A user can cancel with "never mind," "stop," or an unambiguous equivalent without accidentally triggering search.
6. Repeating or failing a clarification causes a different repair strategy and reaches a bounded exit/escalation path.
7. Long conversations remain within a declared prompt-token budget and retain a tested rolling summary.
8. A backend restart cannot silently leave the visible transcript and server context disagreeing; the UI recovers or clearly starts a new state.
9. Results do not remove the chat composer. Users can refine the visible result set conversationally.
10. Ambiguity and scope options are available as selectable controls while free-text answers remain supported.
11. Search summaries state the interpreted goal, applied filters, result count, material uncertainty, and relevant next actions.
12. General questions receive a useful answer before any optional lead-search guidance.
13. User-facing failures never contain raw Python, SQL, provider, or stack-trace text.
14. The first progress event arrives within the declared performance budget and names a real operation.
15. Cancellation produces a terminal `run.cancelled` state and stops scheduling new expensive work.
16. Product/help answers use approved retrieved sources; lead searches continue to use structured database/tool queries.
17. Multi-turn tests cover direct search, missing slots, ambiguity, scope, correction, interruption, cancellation, no results, system failure, refinement after results, long history, and restart/resume.
18. The measured unnecessary-clarification and repeated-question rates improve against a recorded pre-change baseline.

## P. Architecture position — workflow vs. agentic AI

### What the current system is

Evecta currently presents one AI assistant to the user, so calling it a "single agent" at the product
level is understandable. Technically, it is a **single stateful, LLM-powered workflow**, not a fully
autonomous agent.

The graph has a predetermined execution shape:

```text
START
  ↓
understand
  ↓
interact
  ↓
search
  ↓
END
```

`backend/app/services/chat_graph.py` defines the graph, and
`backend/app/services/chat_service.py` implements the three main phases:

- `_understand_phase`
- `_interact_phase`
- `_search_phase`

Gemini currently interprets the message and supplies fields such as intent, industry, location,
search terms, quality, ambiguity, scope, and some response wording. Fixed Python code still decides:

- whether required information is missing;
- whether to ask ambiguity, scope, or confirmation questions;
- which search implementation runs;
- how credit and rate limits are enforced;
- when DB-first and external retrieval occur;
- how results are ranked and persisted;
- when enrichment is scheduled;
- when the turn is complete.

The model does not independently create a plan, select arbitrary tools, reorder the workflow, keep
calling tools until satisfied, or decide by itself that the overall goal is complete.

### Classification

| Description | Current fit |
|---|---|
| One user-facing AI assistant | Yes |
| Single stateful chat workflow | Yes |
| LLM-powered workflow | Yes |
| Single autonomous planning agent | No |
| Dynamic tool-selection agent | No |
| Multi-agent system | No |

### Why a controlled workflow is appropriate

Lead search is a bounded task with known operations:

1. Understand the target.
2. Collect genuinely required information.
3. Resolve material ambiguity.
4. Search approved sources.
5. Rank and persist results.
6. Explain the outcome.
7. Accept corrections and refinements.

A controlled workflow keeps:

- credit charging predictable;
- tool access constrained;
- search order observable;
- retries and costs bounded;
- failures traceable;
- behavior testable;
- cancellation implementable;
- results reproducible enough for product support.

Replacing this with a fully autonomous agent would not directly fix shallow responses, excessive
confirmation, weak context state, missing post-results chat, or absent multi-turn tests. It would add
more planning calls, latency, cost, duplicate-tool risk, and debugging complexity before those
underlying conversation problems were solved.

### Recommended target

Strengthen the current workflow into a hybrid conversational assistant:

```text
User message
    ↓
LLM language understanding
    ↓
Update structured active goal
    ↓
Deterministic conversation policy
    ├── answer
    ├── ask one clarification
    ├── cancel
    ├── search
    └── refine active results
    ↓
Approved tool execution
    ↓
Structured result
    ↓
Natural response composition
```

The division of responsibility should be:

```text
LLM interpretation       → What did the user mean?
Backend state update     → What changed and what must be retained?
Conversation policy      → What is the allowed next action?
Approved tools           → Perform the search or retrieval.
Response writer          → How should the outcome be expressed naturally?
```

This preserves natural language without allowing wording generation to control product policy.

### Where bounded agentic behavior may help

Limited agentic reasoning can be used for genuinely complex subproblems:

- resolving an unusual or poorly mapped business category;
- selecting among approved retrieval sources after a failure;
- expanding a complex ICP into structured search criteria;
- choosing a bounded no-results recovery strategy;
- investigating a company across a small approved source set;
- retrieving and synthesizing relevant product documentation.

Every such sub-agent/tool loop must declare:

- allowed tools;
- maximum tool calls;
- maximum retries;
- maximum runtime;
- cost/credit budget;
- required output schema;
- cancellation behavior;
- terminal success and failure conditions.

Example boundary:

```text
Allowed tools: 3
Maximum tool calls: 4
Maximum retries: 2
Maximum runtime: 30 seconds
Required structured result: yes
```

### When broader agentic AI would become justified

A broader planning agent becomes appropriate only if the product scope expands to goals where the
required steps cannot be selected reliably in advance, for example:

```text
Find companies matching my ICP, identify the right contacts, enrich them,
research each account, prepare an outreach strategy, draft a sequence,
configure the workflow, and stop for my approval before launch.
```

That is a materially different product scope from conversational lead search. It should not be
introduced merely to imitate an agent-style "Thinking" interface.

### Decision

Do **not** replace the current chat with a fully autonomous or multi-agent architecture as part of
this audit. Implement the conversation-policy, response-quality, state, continuity, streaming, and
evaluation phases first. Add bounded agentic capabilities only when a measured use case cannot be
handled reliably by the controlled workflow.

## Q. Competitive chat differentiators

The following capabilities are required if Evecta is intended to provide a better conversational
lead-discovery experience than broader competitors. They stay within the chat and lead-search scope;
they do not require a campaign builder or a multi-agent redesign.

### Q1. Explain why each lead matched

Evecta should not only return businesses. It should explain the strongest, user-relevant reasons
each result matched the active goal.

Example:

```text
Strong match

- Categorized as a dental clinic
- Located 4.2 km from the requested search center
- Website and business email available
- Independent-business indicators found
- Lead quality score: 86/100

Uncertain:
- Ownership could not be fully verified
```

The explanation must be derived from stored/retrieved evidence. It must not claim that a business is
independent, premium, highly rated, or otherwise qualified when the supporting data is absent.

Recommended structured shape:

```json
{
  "lead_id": "lead_123",
  "match_score": 86,
  "matched_reasons": [
    {
      "criterion": "category",
      "value": "dental clinic",
      "source": "overture_category"
    },
    {
      "criterion": "distance_km",
      "value": 4.2,
      "source": "geocoded_coordinates"
    },
    {
      "criterion": "contactability",
      "value": ["website", "email"],
      "source": "lead_record"
    }
  ],
  "uncertainties": [
    {
      "criterion": "independent_ownership",
      "reason": "No verified ownership source"
    }
  ]
}
```

Requirements:

- Explain the criteria that affected ranking, not generic marketing language.
- Separate observed facts, inferences, and unknowns.
- Make explanations available on demand or in a compact expandable UI to avoid clutter.
- Keep the explanation synchronized when the user changes the active goal.
- Never expose private model reasoning; expose evidence and product-level rationale only.

### Q2. Treat corrections as first-class conversation operations

Corrections must update only the fields the user changed while preserving all still-valid context.

Example:

```text
User:
Not Sydney — Melbourne, and exclude cosmetic-only clinics.

Evecta:
Corrected to Melbourne. I kept the dental-clinic search and excluded
cosmetic-only practices.
```

Required correction operations:

- replace a location, industry, radius, quality preference, inclusion, or exclusion;
- modify several fields in one message;
- answer a pending question while volunteering additional filters;
- change topic while a pending question exists;
- undo the most recent change;
- return to the previous active search;
- correct an assistant assumption without restarting the conversation.

The state update should be represented explicitly:

```json
{
  "intent": "correction",
  "changes": {
    "location": {
      "operation": "replace",
      "value": "Melbourne"
    },
    "exclude": {
      "operation": "add",
      "value": ["cosmetic-only clinics"]
    }
  },
  "retained_fields": [
    "industry",
    "radius_km",
    "quality"
  ]
}
```

The response must briefly say what changed and, when useful, what important criteria were retained.
Corrections must not silently reset unrelated filters or the visible result set.

### Q3. Communicate uncertainty honestly

Evecta must distinguish verified facts from model/data inferences and unavailable information.

Example:

```text
I found 28 likely matches. Independence could be verified for 17 businesses.
Six appear independent but need review, and five belong to identifiable groups.
```

Recommended confidence labels:

- `verified` — supported by a declared data source;
- `likely` — supported by indirect indicators;
- `uncertain` — insufficient or conflicting evidence;
- `unknown` — the required information is unavailable.

Requirements:

- Do not convert missing data into a positive claim.
- Do not present ranking score as factual certainty.
- State material uncertainty in search summaries.
- Allow users to hide uncertain matches or review them separately.
- Preserve provenance for claims that influence ranking.
- Prefer "unknown" or "could not verify" over fabricated completion.

This uncertainty contract applies to category fit, ownership, quality, contact availability,
company size, business status, and any inferred ICP attribute.

### Q4. Provide intelligent no-results recovery

A no-results response must preserve the understood goal, identify the limiting constraint when
known, and offer concrete recovery actions.

Poor recovery:

```text
No results found. Try another search.
```

Target recovery:

```text
I couldn't find enough physiotherapy clinics within 5 km of Thapathali.
I can expand to 10 km, search all of Kathmandu, or include rehabilitation
centers while keeping physiotherapy as the priority.
```

The recovery policy should consider, in a bounded order:

1. confirm that geocoding/category resolution succeeded;
2. expand radius within declared product limits;
3. move from an anchor/neighbourhood to the full city;
4. broaden a strict category with approved adjacent categories;
5. suggest nearby locations supported by real geographic data;
6. offer a new search while retaining reusable preferences.

Requirements:

- Never silently broaden the search and present it as the original request.
- State exactly which constraint would change.
- Present no more than three high-value recovery choices at once.
- Make recovery choices selectable while supporting free-text corrections.
- Track repeated no-results attempts and stop repeating the same strategy.
- Do not advise "try again later" unless a temporary external failure is actually known.

Recommended recovery object:

```json
{
  "failure_type": "no_results",
  "preserved_goal": {
    "industry": "physiotherapy clinics",
    "location": "Kathmandu",
    "anchor": "Thapathali",
    "radius_km": 5
  },
  "recovery_options": [
    {
      "action": "expand_radius",
      "value": 10,
      "label": "Expand to 10 km"
    },
    {
      "action": "remove_anchor",
      "label": "Search all Kathmandu"
    },
    {
      "action": "add_related_category",
      "value": "rehabilitation centers",
      "label": "Include rehabilitation centers"
    }
  ]
}
```

### Q5. Make the chat observably fast

Actual and perceived performance are both product requirements. Streaming alone does not make the
search faster; the backend path must also avoid unnecessary model and provider calls.

Required performance techniques:

- deterministic fast paths for simple pending answers and unambiguous control commands;
- one structured interpretation call per ordinary turn;
- lower-randomness structured extraction;
- DB-first lead reuse;
- cached category and geocode resolution;
- parallel execution only for independent operations;
- bounded external-provider calls and retries;
- meaningful streamed progress;
- partial/usable results before optional enrichment completes;
- cancellation that stops scheduling new work.

The progress UI must expose real stages:

```text
✓ Understood your search
✓ Checked existing lead records
• Searching additional businesses
• Ranking the strongest matches
✓ 31 businesses found
```

It must not simulate progress or expose raw chain-of-thought.

Initial performance budgets should be measured and calibrated in staging:

| Metric | Initial target |
|---|---|
| Time to first visible progress | ≤ 1 second |
| Simple conversational response | ≤ 2 seconds at p50 |
| Structured understanding decision | instrument p50/p95 before setting a hard SLA |
| Cancellation acknowledgement | ≤ 1 second |
| Duplicate external searches for one run | 0 |
| Unbounded retries/tool calls | 0 |

Total lead-search time depends on data sources and enrichment, so the UI must distinguish:

- request understood;
- initial candidates available;
- ranked results usable;
- optional enrichment complete.

### Competitive acceptance criteria

1. Every ranked lead can return evidence-based match reasons and material uncertainties.
2. Match explanations update when the active goal changes.
3. Corrections modify only requested fields and retain unrelated valid context.
4. Multi-field corrections work in one turn without restarting.
5. Users can undo the latest refinement and return to the previous active search.
6. Search summaries distinguish verified, likely, uncertain, and unknown information.
7. Users can exclude uncertain matches without losing the rest of the active goal.
8. No-results recovery preserves the goal and offers at most three relevant actions.
9. Repeated no-results attempts change strategy and terminate within the configured retry bound.
10. No recovery path silently broadens location, radius, or category.
11. First truthful progress appears within the declared performance budget.
12. Simple turns do not trigger avoidable duplicate Gemini calls.
13. Search runs have bounded provider calls, retries, runtime, and cancellation behavior.
14. Initial usable results are not blocked by optional enrichment when partial display is safe.

---

## What's already right (don't touch these while fixing the above)

- **Graph-as-workflow shape** (`understand → interact → search`, fixed code paths) is the correct architecture for a bounded task like this per Anthropic's own workflows-vs-agents framework — not a case for a more "agentic" rebuild.
- **Frame-based slot extraction** — `understand()` fills whatever slots are present regardless of what was literally asked — matches Amazon Alexa's stated best practice.
- **Context-before-instructions prompt ordering** — both big prompts already put context/history first and instructions last, which Gemini's own docs recommend.
- **Randomized variant pools** (`build_confirm_message`, `build_ambiguous_clarification`) — matches "add variation to frequent prompts to avoid monotony."
- **One-step correction mid-confirmation** — a user can redirect ("actually make it dentists") without restarting the flow, matching Google's Confirmations page.
- **No apologies in error/no-results copy** — matches "offer solutions, not apologies."
- **Spelling correction inline in `understand()`** — is genuine error *prevention*, which every guide ranks above error recovery.

---

## Sources referenced

- Google Assistant Conversation Design (Learn about Conversation, Errors, Confirmations, Questions,
  Suggestions, Language, Capitalization & Punctuation, Apologies, Endings, Greetings, Acknowledgements,
  Discourse Markers, Commands, Design for the Long Tail, Write Sample Dialogs, Create a Persona,
  Test and Iterate, Is Conversation the Right Fit?, Chips)
- Dialogflow CX — Best Practices, Agent Design
- Anthropic — [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), [Building Effective AI Agents](https://www.anthropic.com/research/building-effective-agents)
- OpenAI — [Model Spec](https://model-spec.openai.com/2025-12-18.html), A Practical Guide to Building Agents
- Google Gemini API — [Prompt design strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies)
- Microsoft — [Conversational UX / Bot Framework SDK](https://learn.microsoft.com/en-us/azure/bot-service/bot-service-design-principles)
- Amazon Alexa — 4 Principles of Conversational Voice Design
