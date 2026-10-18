# Chat Intelligence — The Combined Solution

This is the single, agreed plan for making the Evecta lead-generation chat *intelligent*: it understands intent, disambiguates unclear queries (the "apple" problem), remembers the conversation durably, and ranks results by what the user actually asked for — all while staying cheap and predictable.

It replaces the earlier "four separate solutions" document. Those four are not gone — the best ideas from each are folded in here, and the ones we reject are listed with reasons (see [What we deliberately exclude](#what-we-deliberately-exclude) and [How the old four solutions fold in](#how-the-old-four-solutions-fold-in)).

---

## TL;DR

Build the chat as a **deterministic LangGraph state machine** with three parts:

1. **The brain** — one structured-output "understanding" call (Gemini `with_structured_output`) that returns intent + resolved slots + ambiguity + quality qualifier in a single call. This replaces ~6 brittle LLM calls and all the hand-written merge logic.
2. **The skeleton** — a LangGraph graph of plain Python nodes (`understand → clarify? → confirm? → search → rank → respond`). This dissolves the 670-line spaghetti in [chat_logged_in](../backend/app/services/chat_service.py#L446) into ~7 readable nodes.
3. **The memory** — a **Postgres checkpointer** persists the whole conversation state (messages **and** the resolved goal) durably per thread, replacing the ad-hoc single-key-per-user Redis history. Postgres (not Redis) so the **full chat is kept for later review** and we're **ready for a future agentic direction** (durable, resumable, inspectable state) — see [Open issues #1](#open-issues--resolutions).

We **do not** build an autonomous tool-calling agent, and we **defer** RAG/pgvector. We use the LLM only for *understanding and replies* — never to decide which API to call or whether to respect the rate limiter.

**Effort:** ~3 weeks total, delivered in three de-risked steps (2–3 days → ~1.5 weeks → ~1 week). Step 1 alone is a visible win.

---

## Table of Contents

1. [What's wrong today](#whats-wrong-today)
2. [The decision and why](#the-decision-and-why)
3. [Target architecture](#target-architecture)
4. [Component 1 — The Understanding node (the brain)](#component-1--the-understanding-node-the-brain)
5. [Component 2 — LangGraph + Postgres checkpointer (skeleton + memory)](#component-2--langgraph--postgres-checkpointer-skeleton--memory)
6. [Component 3 — Disambiguation node (the "apple" fix)](#component-3--disambiguation-node-the-apple-fix)
7. [Component 4 — Conditional goal confirmation](#component-4--conditional-goal-confirmation)
8. [Component 5 — Search node (reuse the Overture pipeline)](#component-5--search-node-reuse-the-overture-pipeline)
9. [Component 6 — Relevance ranking, and the "best hotels" problem](#component-6--relevance-ranking-and-the-best-hotels-problem)
10. [What we deliberately exclude](#what-we-deliberately-exclude)
11. [Rollout plan and effort](#rollout-plan-and-effort)
12. [Dependencies and migration](#dependencies-and-migration)
13. [Risks and mitigations](#risks-and-mitigations)
14. [How the old four solutions fold in](#how-the-old-four-solutions-fold-in)
15. clean-up old code 
16. [Implementation status — what's built so far](#implementation-status--whats-built-so-far)
17. [Step 2b — execution plan (the last step)](#step-2b--execution-plan-the-last-step)
18. [Radius & anchor from the prompt (planned)](#radius--anchor-from-the-prompt-planned)
---

## Implementation status — what's built so far

*Last updated 2026-06-30. This records what is actually implemented in the codebase, versus the forward-looking plan above. Where reality diverged from the original plan, it's flagged.*

**Done**

| Area | Status | Where / notes |
|---|---|---|
| **Step 1 — Understanding node** | ✅ | `understanding.py` — `Understanding` schema + `understand()`, one Gemini `with_structured_output` call (temp 0.7). Replaced the classifier chain + hand-merge; wired into `chat_logged_in`. |
| **Step 2a — LangGraph + Postgres checkpointer (foundation)** | ✅ | `chat_graph.py` single node wrapping the **unchanged** `chat_logged_in`; `AsyncPostgresSaver` + `AsyncConnectionPool` in `main.py` lifespan; thread-id per conversation (`get_or_create_thread_id` / `rotate_thread_id`). |
| Windows event-loop handling | ✅ | psycopg async needs the Selector loop; the lifespan skips the checkpointer cleanly on the Proactor loop, and `run.py` launches the API on the Selector loop for local durable history. |
| **Disambiguation / clarify** (apple) | ✅ | dynamic `candidate_meanings`, offered directly (see deviation ⚠️). |
| **Scope question** (hotels → accommodation family) | ✅ | dynamic `scope_siblings`; two-turn carry-forward fix; `only/just/exact/strict` suppress it. |
| **Confirm & refine** (pre-search) | ✅ | refine any number of times; search runs only on "go"; robust LLM intent classification (`AWAITING CONFIRMATION` prompt block). |
| **Relevance ranking** | ✅ | `rank_leads()` — completeness + name-match within location tiers + quality boost. |
| **Quality capture (Phase 1)** | ✅ | `quality` captured silently, never surfaced. |
| **Conversational replies** | ✅ | LLM-generated (`u.reply`), friendly/case-aware, temp 0.7. |
| **Tests** | ✅ | `tests/integration/test_understanding.py` (golden set) · `tests/unit/test_rank_leads.py`. |

**Step 2b — ✅ Done 2026-06-30 (the last step)** — see [Step 2b — execution plan](#step-2b--execution-plan-the-last-step) for the staged rollout:
- ✅ Conversation **context + history** moved off Redis into `ChatState` — the checkpointer is the single source of truth (was write-only).
- ✅ Single node split into a real multi-node graph (`understand` / `interact` / `search` + conditional edges).
- ✅ Graph **always available** (Postgres or `MemorySaver`); Redis conversation-state helpers deleted. *Pending only: the user's end-to-end live test.*

With 2b done, the core Chat Intelligence plan is complete; the deferred items (quality Phase 2, RAG, multi-source) remain explicitly out of scope.

**Deferred (after 2b, by design):** quality Phase 2 (external ratings) · RAG / pgvector · multi-source orchestrator · rank category-relevance + on-demand "why matched" · remaining clean-up of superseded helpers.

**Deviations from the original plan (intentional):**
- ⚠️ **Disambiguation does not pre-verify candidates with `quick_check_results`.** The plan's "model proposes, quick-check disposes" relied on Google Places; since this product uses **Overture for leads and Google for geocoding only**, the Places pre-check was removed and candidate meanings are offered directly. If the chosen meaning returns nothing, the existing no-results suggestion path handles it.
- **`ChatState` is pragmatic, not the rich typed schema** in Component 2. 2a wraps the existing function, so state is `{messages, context, last_turn}` and the resolved goal lives inside `context`.
- **Confirm is a pre-search refine-loop**, richer than the plan's "conditional confirm": refine repeatedly, search only on "go" (fits the one-shot product).
- **`temperature=0.7`** (not 0) for `understand()` — needed for non-robotic replies; structured extraction stays reliable.

---

## What's wrong today

Grounded in the current code, not theory:

| Problem | Evidence |
|---|---|
| **Understanding is a chain of narrow classifiers** — one message fires up to ~6 LLM calls | [is_general_question](../backend/app/utils/chat_helper.py#L192) + [run_extraction](../backend/app/services/chat_service.py#L523) + [extract_industry_from_history](../backend/app/services/chat_service.py#L174) + [suggest_correction](../backend/app/services/chat_service.py#L371) ×3 |
| **Brittle hand-written merge logic** | `is_industry_variation`, `industry_changed`, stale-country clearing, `_GENERAL_PHRASES`/`_neg_words` string sets across [chat_service.py:471–644](../backend/app/services/chat_service.py#L471-L644) |
| **Spaghetti orchestration** | [chat_logged_in](../backend/app/services/chat_service.py#L446) is ~670 lines of nested branching mixing credits, geocoding, search, persistence, enrichment — plus a dead commented-out [chat_guest block](../backend/app/services/chat_service.py#L1122) |
| **No durable chat** | conversation history is Redis with a **24h TTL** under a **single key per user** ([set_conversation_history](../backend/app/utils/redis_context.py#L96)) — messages vanish, and a user effectively has one rolling session |
| **No disambiguation** | "apple leads" goes straight to `industry="apple"` → garbage mix of stores/fruit. The PDF's headline problem is unsolved. |
| **No relevance ranking** | leads are ordered only by [email deliverability](../backend/app/utils/chat_helper.py#L82) (`lead_score` = MX + prefix) and [location proximity](../backend/app/services/chat_service.py#L168) — never by how well they match intent |
| **Can't honor "best/premium"** | qualifiers like "best" are silently dropped; and the Overture source has no quality data anyway (see Component 6) |

What already works and is **kept**: query expansion via `search_terms`, the DB-first + Overture/PostGIS search, rate limits, distributed locks, credit accounting, and enrichment. The intelligence upgrade wraps these — it does not rewrite them.

---

## The decision and why

**Chosen: deterministic LangGraph + single structured-understanding call + Postgres checkpointer.**

Why this and not the alternatives:

- **Why a single structured "understanding" call (not the current chain, and not a 5-step specialist pipeline):** the current chain is exactly what makes the bot feel mechanical and slow. Consolidating intent + slots + ambiguity + corrections into one call that sees full context produces a *holistic* read, cuts ~6 round-trips to 1, lowers latency and cost, and deletes the brittle heuristics. A multi-step specialist pipeline is more observable but adds 3–5× tokens per turn for no quality gain at our scale.
- **Why a deterministic graph (not an autonomous agent):** our flow is *known and fixed* — DB-first → fill from Overture → enrich → rank. We encode hard, cost-sensitive rules ([DB-before-API](../backend/app/services/chat_service.py#L788), [rate limits](../backend/app/services/chat_service.py#L823), [locks](../backend/app/services/chat_service.py#L844), plan limits). We must **not** let an LLM decide to skip the DB or ignore the rate limiter. A fixed graph is predictable, debuggable, and cost-controllable. The LLM is used only inside the `understand` and `respond` nodes.
- **Why a checkpointer (not a vector DB) for memory:** the chat is slot-filling. "Remember what we're searching" needs *state*, which is exactly what a LangGraph checkpointer holds — messages **and** the resolved goal — keyed by a real session/thread id (which also fixes the single-key-per-user limitation). We back it with **Postgres** (not Redis) so the **full conversation is kept durably** for later review and we stay **ready for a future agentic direction** (resume, time-travel, human-in-the-loop). A vector DB answers a different question (semantic recall) we don't need yet.

---

## Target architecture

```
                    ┌─────────────┐
   user message ──▶ │  understand │  1 structured LLM call → intent, slots,
                    └──────┬──────┘  ambiguity, quality, (optional) reply
                           │
                  ┌────────┴─────────┐  conditional routing on the result
                  ▼                  ▼
          intent in {greeting,   intent == lead_search
          general, negate}            │
                  │           ┌───────┴────────┐
                  │           ▼                ▼
                  │     ambiguous?        missing slot?
                  │     ▼                      ▼
                  │  ┌─────────┐         ┌───────────┐
                  │  │ clarify │         │ ask_slot  │  (industry / city)
                  │  │ meaning │         └───────────┘
                  │  └─────────┘
                  │           │  (both resolved)
                  │           ▼
                  │     ┌──────────┐  only when low-signal
                  │     │ confirm? │
                  │     └────┬─────┘
                  │          ▼
                  │     ┌─────────┐  reuse Overture pipeline:
                  │     │ search  │  DB-first → get_leads_overture →
                  │     └────┬────┘  credits, locks, enrichment
                  │          ▼
                  │     ┌─────────┐  relevance (+ optional quality)
                  │     │  rank   │
                  │     └────┬────┘
                  ▼          ▼
                    ┌─────────────┐
                    │   respond   │ ──▶ reply + persisted state (checkpointer)
                    └─────────────┘
```

**The state object** (`ChatState`) is the durable "goal" the PDF asked for — it is what the checkpointer persists per thread:

```python
from typing import TypedDict, Annotated, Literal
from langgraph.graph.message import add_messages

class ChatState(TypedDict):
    messages: Annotated[list, add_messages]
    intent: str
    goal: str | None                    # resolved one-line goal
    industry: str | None
    location: str | None                # city
    country: str | None
    search_terms: list[str]
    quality: Literal["any", "top_rated", "premium", "budget"] | None
    ambiguous: bool
    candidate_meanings: list[dict]
    chosen_meaning: str | None
    log_id: str | None                  # LeadLog id once a search runs
    leads: list[dict]
```

---

## Component 1 — The Understanding node (the brain)

A single Gemini call with guaranteed-valid structured output. This is the former Solution #2 ("super-prompt with goal extraction"), refined and made the centerpiece. It replaces [is_general_question](../backend/app/utils/chat_helper.py#L192), [run_extraction](../backend/app/services/chat_service.py#L523), [extract_industry_from_history](../backend/app/services/chat_service.py#L174), the three [suggest_correction](../backend/app/services/chat_service.py#L371) calls, and the entire [471–644 merge block](../backend/app/services/chat_service.py#L471-L644).

```python
from pydantic import BaseModel, Field
from typing import Literal

class Meaning(BaseModel):
    label: str                       # "Apple product/Mac stores"
    search_terms: list[str]          # ["apple store", "macbook reseller"]
    why: str                         # one-line justification (shown to user)

class Understanding(BaseModel):
    intent: Literal[
        "lead_search", "general_question", "refinement",
        "affirm", "negate", "greeting",
    ]
    goal: str | None = None          # "find Apple product stores in Sydney"
    # Resolved slots — the model returns the MERGED state, carrying forward
    # unchanged fields. Spelling is normalized here (no separate correction calls).
    industry: str | None = None
    location: str | None = None      # city
    country: str | None = None
    search_terms: list[str] = Field(default_factory=list)   # <= 3 Places/Overture keywords
    quality: Literal["any", "top_rated", "premium", "budget"] | None = None
    # Disambiguation (the "apple" fix)
    ambiguous: bool = False
    candidate_meanings: list[Meaning] = Field(default_factory=list)
    clarification_reason: str | None = None
    # For greeting / general / negate: a ready reply so we skip a second LLM call
    reply: str | None = None
    reasoning: str | None = None     # logged for observability, never shown
```

The node:

```python
async def understand(state: ChatState, llm) -> dict:
    structured = llm.with_structured_output(Understanding)
    prompt = build_understanding_prompt(state)   # current goal + history + few-shots
    u: Understanding = await structured.ainvoke(prompt)

    # Trust the resolved goal, with one guard: never blank a slot the user didn't change.
    return {
        "intent": u.intent,
        "goal": u.goal,
        "industry": u.industry or state.get("industry"),
        "location": u.location or state.get("location"),
        "country":  u.country  or state.get("country"),
        "search_terms": u.search_terms or state.get("search_terms", []),
        "quality": u.quality or state.get("quality"),
        "ambiguous": u.ambiguous,
        "candidate_meanings": [m.model_dump() for m in u.candidate_meanings],
        "clarification_reason": u.clarification_reason,
        "_reply": u.reply,
    }
```

Design choices worth keeping:

- **`ambiguous: bool` over a `confidence: float`.** A numeric confidence is hand-wavy and hard to threshold consistently. A boolean plus `candidate_meanings` is what the routing actually needs.
- **A `quality` qualifier field** so "best / premium / budget" is captured instead of dropped (used by Component 6).
- **The model owns the merge.** The prompt instructs: *carry forward unchanged slots; only change a field the user explicitly changed; clear a stale country only when the user gives a new city.* The `or state.get(...)` guards are the thin safety net — ~20 declarative lines replacing ~170 imperative ones.
- **Spelling normalization happens inside this call**, killing the three extra `suggest_correction` round-trips.

The prompt carries 15–20 few-shot examples for the hard cases (apple, amazon, "leads for my brand" → buyers not competitors, regional terms, "best/premium").

**Net for one message: ~6 LLM calls → 1; ~170 imperative lines → ~25; all heuristic string-sets gone.**

### General-question scope policy

When `intent` is `general_question` or `greeting`, the bot is a **scoped lead-gen assistant — not a general chatbot**. An open chatbot invites off-topic abuse, prompt-injection, credit waste, and hallucination. The `understand`/`respond` prompt enforces three buckets:

| Bucket | Behavior | Example |
|---|---|---|
| **In-domain / meta / light social** | Answer fully | "what can you do?" → explains it finds business leads; "can you dance?" → light deflect + redirect |
| **Short, safe, *known* fact** | 1-line answer **+ open redirect** (carry any grounded location, but **never suggest an industry**) | "capital of France" → *"The capital of France is Paris. Want me to find leads there?"* · "what's 2+2" → *"That's 4. Want me to find some business leads?"* |
| **Open-ended task OR uncertain/fabricable fact** | **Don't perform / don't invent** — redirect | "write me code" → *"Writing code isn't what I do — I find business leads. What would you like to search for?"* · "tell me about plutonictech" → *"I don't have details on specific companies, but I can find leads — what are you looking for?"* |

**Two guards:**
1. **Short *and* confidently-known *and* safe** → answer. Length alone isn't the test — "tell me about plutonictech" is short but fabricable, so it's redirected, not answered.
2. **Never fabricate** facts about specific companies/people; never assume an industry the user didn't state.

**One drift guard:** cap at **one short line + an open redirect every time**; if the user keeps asking off-topic, keep politely redirecting — don't get pulled into a trivia Q&A session.

The pattern is always: *brief safe answer → offer to find leads (carrying any grounded location) → let the user choose the industry.*

---

## Component 2 — LangGraph + Postgres checkpointer (skeleton + memory)

The graph turns the 670-line function into named nodes; the checkpointer persists the full conversation state durably per thread.

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

def route_after_understand(state: ChatState) -> str:
    if state["intent"] in ("greeting", "general_question", "negate"):
        return "respond"
    if state.get("ambiguous"):
        return "clarify"
    if not state.get("industry") or not (state.get("location") or state.get("country")):
        return "ask_slot"
    return "search"

builder = StateGraph(ChatState)
builder.add_node("understand", understand_node)
builder.add_node("clarify",    clarify_node)
builder.add_node("ask_slot",   ask_slot_node)
builder.add_node("confirm",    confirm_node)
builder.add_node("search",     search_node)     # existing Overture pipeline
builder.add_node("rank",       rank_node)
builder.add_node("respond",    respond_node)

builder.add_edge(START, "understand")
builder.add_conditional_edges("understand", route_after_understand)
builder.add_edge("search", "rank")
builder.add_edge("rank", "respond")
builder.add_edge("respond", END)
# clarify / ask_slot / confirm each end the turn and resume on the next message

# Durable conversation state in Postgres — replaces the ad-hoc Redis context + history
checkpointer = AsyncPostgresSaver.from_conn_string(DATABASE_URL)
graph = builder.compile(checkpointer=checkpointer)
```

Invocation per message uses a **thread id = conversation/session id** (e.g. the `LeadLog` id or a chat session uuid), so a user can have many independent chats — fixing the [single-key-per-user Redis](../backend/app/utils/redis_context.py#L96) limitation:

```python
async def chat_turn(message: str, thread_id: str, user) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke({"messages": [("user", message)]}, config)
    return result
```

What this gives you:

- **Spaghetti gone** — orchestration is the graph; each node does one job.
- **Durable full chat in DB** — the checkpointer persists messages *and* the resolved goal per thread in Postgres, with full checkpoint history (resume, time-travel, human-in-the-loop). This stores the **entire conversation** so you can later review how users asked and where they stopped, and keeps you ready for an agentic direction. (Heavy raw *lead results* still live in [LeadLog](../backend/app/models/lead_log.py) and are pruned at 3 months; conversation history here is separate, kept per your retention policy.)
- **Keep your relational tables for business data.** The checkpointer stores conversation *state* as serialized blobs; your queryable lead data stays in [LeadLog](../backend/app/models/lead_log.py) / [LeadLogLead](../backend/app/models/lead_log_lead.py). Rule of thumb: **checkpointer for conversation, your own tables for leads.**

---

## Component 3 — Disambiguation node (the "apple" fix)

Runs **only** when `understand` returns `ambiguous=true`. The candidates already exist in state, so this node just formats the question and maps the user's choice back into `search_terms` on the next turn.

```python
async def clarify_node(state: ChatState) -> dict:
    metas = state["candidate_meanings"]
    options = "\n".join(f"{i+1}. {m['label']} — {m['why']}" for i, m in enumerate(metas))
    reply = f"{state['clarification_reason']}\n\n{options}\n\nWhich did you mean?"
    return {"messages": [("assistant", reply)], "_pause": True}
```

Walkthrough — **"apple leads in Sydney"**:

1. `understand` → `ambiguous=true`, candidates = [Apple product stores, Apple repair, Apple fruit suppliers].
2. `clarify` asks the question; turn ends, state persisted.
3. User: "the stores". `understand` sees the pending candidates, sets `chosen_meaning` + the matching `search_terms`, `ambiguous=false`.
4. Routes to `search` with the correct terms. No more garbage results.

(The frontend needs a small change to render the options — budget for it in Step 3.)

---

## Component 4 — Conditional goal confirmation

The PDF wanted a confirmation step. We make it **conditional, not mandatory** — confirming every search adds friction. Only confirm when signal is weak (e.g., a vague industry the model flags). Otherwise proceed straight to `search`, exactly as the current code does when it has enough. The resolved `goal` string in state is what would be echoed back.

---

## Component 5 — Search node (reuse the Overture pipeline)

This node is **plain code**, not an LLM tool. It wraps the existing, battle-tested logic so all cost controls stay intact:

- DB-first via [fetch_leads_from_db](../backend/app/services/chat_service.py#L92) (free).
- Fill the remainder from [get_leads_overture](../backend/app/services/lead_generation_service.py) (PostGIS), using `chosen_meaning.search_terms` (or `search_terms`).
- Keep [rate limits](../backend/app/services/chat_service.py#L823), [distributed locks](../backend/app/services/chat_service.py#L844), the [cold-area background load](../backend/app/services/chat_service.py#L891), credit deduction, and enrichment enqueue **unchanged**.

> **Source note:** leads come from **Overture** (`LEAD_SOURCE=overture`). Google is used **only for geocoding** (turning "Kathmandu" → lat/lng), already [cached 7 days](../backend/app/utils/redis_context.py#L212). There is no Google Places Details cost in this flow.

### Broad terms — scope asked *before* searching

A broad term like **"hotels"** is *not* ambiguous (one clear meaning: lodging) — it has a **family** of related categories (resort, motel, hostel, inn, B&B, guesthouse). The question is **scope**, not meaning.

> **Product constraint:** the chat is **one-shot** — there is no chat interface after results (the user clicks "New Chat" and it starts fresh). So there is **no post-result refinement**. Scope must therefore be settled **before** searching, in the chat that exists pre-search.

> **Decision:** for broad **family** terms, ask once before searching — *"Should I include resorts, motels, and B&Bs too, or just hotels?"* Include-all → search the whole family; "hotels only" → narrow to the `hotel` leaf. This is **not** nagging, because it fires **only for family terms** (never for precise terms like dentist/restaurant) and is **batched** with any pending missing-city or disambiguation question in the same turn.

Today this fails regardless: [`OVERTURE_CATEGORY_MAP["hotel"] = ["hotel"]`](../backend/app/services/lead_generation_service.py#L72) resolves to the `hotel` category only, and the lodging siblings **don't share a substring** (`%hotel%` can't match "motel"/"inn"), so they're missed. LLM `search_terms` expansion doesn't rescue it — unmapped terms fall back to noisy name matching in [resolve_overture_filter](../backend/app/services/lead_generation_service.py#L123).

**Mechanism:**

1. **Curated category families in the map** — group siblings that don't share a substring:
   ```python
   ACCOMMODATION = ["hotel", "motel", "resort", "hostel",
                    "bed_and_breakfast", "guest_house", "inn", "lodging"]
   "hotel": ACCOMMODATION, "hotels": ACCOMMODATION, "accommodation": ACCOMMODATION,
   ```
   Hand-curated for the top broad industries (accommodation, food, legal, medical, fitness), **excluding** unrelated categories — e.g. `lounge` is food-and-drink, **not** lodging. Families are only needed where siblings lack a common substring; "restaurant" already broadens via `%restaurant%` → `pizza_restaurant`.
2. **`understand` flags family terms** — when the resolved industry maps to a category family, it returns the sibling labels so the bot can ask about them.
3. **New `ask_scope` node** (sibling to `ask_slot` / `clarify`) — asks the include-all-vs-just-X question once, before search. Batched with `ask_slot` / `clarify` when more than one is pending, so it never costs an extra turn.
4. **Resolve categories from the answer** — include-all → full family; "only / just hotels" → the `hotel` leaf, reusing the existing [strict-intent markers](../backend/app/services/lead_generation_service.py#L98). **Default if the user just proceeds: include-all** (recall-first).

**The three pre-search question types — all resolved before searching (no after-results step exists):**

| Trigger | Node | Question |
|---|---|---|
| Ambiguous **meaning** (apple) | `clarify` | "Which did you mean — stores, repair, or fruit?" |
| Missing **field** (no city) | `ask_slot` | "Which city?" |
| Broad **family** (hotel) | `ask_scope` | "Include resorts/motels/B&Bs, or just hotels?" |

"lounge" is never folded into "hotels".

---

## Component 6 — Relevance ranking, and the "best hotels" problem

Two **different** axes — keep them separate, and separate from the existing `lead_score` (which measures email deliverability, not relevance or quality):

### Relevance ranking — works on Overture
"Does this lead match the chosen meaning, the location, and the intent?" Rank using signals you already have: category/taxonomy match against `search_terms`, [location proximity](../backend/app/services/chat_service.py#L168), and data completeness. A cheap heuristic handles most; reserve an LLM call for borderline cases. Generate the per-lead "why this matched" string **on demand** (when a lead is expanded), not for all 100 — keeps cost sane.

### Quality ranking ("best / premium / top-rated") — the hard case
**Overture has no rating, review count, or price level.** The [OverturePlace model](../backend/app/models/overture_place.py#L39-L62) stores only name, categories, contact fields, `operating_status`, and `confidence` — and `confidence` means *"how sure we are this record is correct,"* not *"how good is the hotel."* So "best hotels in Kathmandu" **cannot be answered from the lead source's own data.** This is a product decision, independent of the LangGraph work. Handled in two phases:

**Phase 1 (now) — capture silently, return normal results.** The `understand` node still **captures** `quality` (e.g. `top_rated`), but for now it is **not acted on and not mentioned**. A "best restaurants in Kathmandu" query is treated like a normal search: return the results with a normal reply (*"Here are restaurants in Kathmandu."*) — **no disclaimer** about ratings or limitations, no "this isn't a top-rated list" text. The `quality` value is stored so Phase 2 needs no prompt change. *(Optional: silently bias ordering by proxy signals — completeness, `confidence`, open status — but never surface it.)*
- **Tradeoff (accepted):** a user who typed "best" gets a normal list.

**Phase 2 (later, gated) — true quality via an external signal.** Only when `quality in {top_rated, premium}`, fetch a real signal for the candidate set — e.g. Google Places `rating`/`price_level`, or a Perplexity/LLM pass to identify known premium names. Bounded to quality queries so cost stays controlled. **Build only if stakeholders require true "best".**

**Not used:** category/keyword bias ("luxury hotels", "5 star") biases *which* rows match but doesn't truly rank — skip unless needed.
[]
---

## What we deliberately exclude

| Excluded | Why | Revisit when |
|---|---|---|
| **Autonomous tool-calling agent** (old Solution #1) | Our flow is fixed; an LLM must not decide to skip the DB, re-call search, or ignore rate limits. Adds 2–5s latency and is hard to debug. | Only if users start phrasing genuinely open-ended, multi-step research requests. |
| **RAG / pgvector** (old Solution #3) | Slot-filling doesn't need semantic recall; cold start; embedding-similarity ≠ meaning. Not needed to fix anything broken today. | After Step 2, *if* you want the bot to learn long-tail vocabulary from real usage. It layers cleanly on the `understand` node. |
| **Vector DB for chat storage** | Wrong tool — the LangGraph (Postgres) checkpointer already stores the full conversation durably. | Never (for storage). |
| **5-step specialist pipeline** (old Solution #4) | 3–5× tokens/turn for no quality gain vs the single structured call at our scale. | If the single understanding prompt hits a real ceiling on a class of queries. |
| **Perplexity / LinkedIn multi-source orchestrator** (PDF §6) | New API, new cost model, cross-source dedup — weeks of work, and not needed for the stated problems. Overlaps with Option 2 above only for quality queries. | A separate initiative after the core is solid. |

---

## Rollout plan and effort

A **strangler** migration — never a big-bang rewrite. Each step ships value and de-risks the next. Assumes one dev familiar with the codebase; excludes the Perplexity/LinkedIn orchestrator.

### Step 1 — Understanding node — **2–3 days**
- Add the `Understanding` schema + `understand()` + the few-shot prompt.
- Swap the [471–644 block](../backend/app/services/chat_service.py#L471-L644) to consume it; keep the rest of `chat_logged_in` as-is.
- **Delivers:** ~6 LLM calls → 1, the apple/quality capture, dead heuristics gone. No LangGraph yet, low risk.

### Step 2 — LangGraph + Postgres checkpointer — **~1.5 weeks**
- Add `langgraph` + the Postgres checkpointer; model the flow as nodes.
- Move search/credits/enrichment into the `search` node unchanged.
- Migrate off the ad-hoc Redis context+history to checkpointer threads.
- **Delivers:** spaghetti gone, durable full conversation history per thread, multiple sessions per user, agentic-ready state. Riskiest step (DB migration + async/Celery interplay).

### Step 3 — Disambiguation + ranking nodes — **~1 week**
- `clarify` node + frontend options UI.
- `rank` node (relevance) + Option 1 quality proxy + on-demand explanation.
- **Delivers:** the full PDF experience, minus the deferred orchestrator.

**Totals:** Step 1 ≈ 2–3 days · Steps 1–2 ≈ ~2 weeks · everything above ≈ **~3 weeks**. (Same ballpark as the PDF's estimate — but better-scoped, and you already own half the pieces.)

---

## Step 2b — execution plan (the last step)

*The final step. Goal: finish the LangGraph migration **completely** — nothing left "for later." Two halves: (A) move conversation state off Redis into the checkpointer, (B) split the single node into a real multi-node graph.*

### Scope — what moves, what stays
Redis does six jobs; **only conversation context + history move** into the graph. The rest are infrastructure (same category as the geocode cache) and stay:

| Redis job | 2b |
|---|---|
| Conversation **context** (slots/gates) | → moves into `ChatState` |
| Conversation **history** | → moves into `ChatState` |
| Thread-id map (user→thread) | stays |
| Geocode / leads / region / country caches | stays |
| Distributed search locks | stays |
| Per-user rate-limit | stays |

The checkpointer is currently **write-only** (nothing reads it). 2b makes it the **single source of truth**.

### Decision: the graph is always available
To delete the Redis fallback cleanly, the graph must always exist:
- **Postgres checkpointer** when the loop allows (Linux prod, or local `python run.py`) → durable.
- **`MemorySaver`** (in-process) otherwise → replaces the old in-memory Redis fallback (works within the process, lost on restart, per-worker; degraded mode only).

After 2b: **no Redis context/history anywhere; the route always goes through the graph.**

### Part A — state migration
- **`chat_service.py`** — `chat_logged_in(...)` takes `context` and `history` as **parameters** (injected by the node); remove the top `get_user_context` / `get_conversation_history`; delete the ~30 intermediate `set_*` calls (state is mutated in place and returned); ensure **every `return` carries both `context` and `history`**. `chat_guest` untouched.
- **`redis_context.py`** — delete `get/set/delete_user_context`, `get/set/delete_conversation_history`, `clear_user_session`, and the `_memory_context` / `_memory_history` fallbacks. Keep thread-id, caches, locks, rate-limit.
- **`chat.py`** — `/chat/reset` drops `clear_user_session`; thread rotation alone gives a fresh empty conversation.

### Part B — node split
Split at the clean seam — the `Understanding` object (`u`) is used only through the gates (≤ the confirm gate), **never** in the search pipeline:

```
START → understand ─(conversational / ambiguous / no-credits)─→ END
                   └─(continue)─→ interact ─(slot/clarify/scope/confirm pending)─→ END
                                          └─(proceed)─→ search → END
```

- **`understand_node`** — append user msg; balance check; `understand()`; ambiguity + conversational early-returns; merge slots; stash `_intent` / `_scope_choice` / `_was_awaiting_gate` into `context` so the non-serializable `u` never crosses a node boundary.
- **`interact_node`** — slot-fill (industry / city / country / region) + clarify + scope + confirm gates; emits a pending reply (→ END) or signals proceed (→ search).
- **`search_node`** — the full DB-first → Overture → credits → persistence → ranking → suggestions pipeline, moved **verbatim**.
- Routing via a `_route` field each node sets; `route_*` functions read it. "Respond" is folded into each terminal node (it sets `last_turn`).
- **`main.py`** — import `MemorySaver`; always build the graph (Postgres when possible, else MemorySaver); remove the `graph=None` skip path.

**Node granularity:** **3 nodes** (understand / interact / search) — *recommended*: a real conditional-edge graph with the gates as branches inside `interact`, fewest seams (lowest risk against the "don't change the flow" rule). A 6-node version (understand / slot / clarify / scope / confirm / search) is **functionally identical** but adds boundaries — optional, not recommended.

### Verification (must pass before deleting old code)
Full end-to-end re-test: greeting · general question · two-turn slot-fill · apple clarify · hotels scope · confirm → refine → go · real search + persist · New Chat reset · insufficient credits. Plus `pytest` (`rank_leads`) + compile/import. Then update this doc and the `chat_graph.py` docstring to mark 2b **done**.

### Progress (staged rollout)
*Implemented in verifiable stages so each is live-tested before the next. Updated after every stage.*

| Stage | Scope | Status |
|---|---|---|
| **1** | Graph **always built** (Postgres checkpointer, else `MemorySaver`); `chat_logged_in` takes injected `context`/`history`; `chat_node` reads/writes `ChatState`; route always through the graph (Redis fallback removed). **`ChatState` is now the source of truth** for conversation state. | ✅ **Done 2026-06-30** — `main.py`, `chat_service.py`, `chat_graph.py`, `chat.py`. *(Redis `set_*` writes kept temporarily as harmless redundancy — removed in Stage 3.)* |
| **2** | Split the single node into `understand` / `interact` / `search` nodes with conditional edges (the 3-node split). `chat_logged_in` → `_understand_phase` / `_interact_phase` / `_search_phase`; `chat_graph.py` wires the nodes + `_route_*` functions. | ✅ **Done 2026-06-30** — `chat_service.py`, `chat_graph.py`. Routing + multi-turn state persistence verified with stubbed phases. |
| **3** | Delete the Redis conversation-state helpers + the redundant `set_*` calls; `/chat/reset` rotate-only. | ✅ **Done 2026-06-30** — `chat_service.py` (all `set_*` calls + imports removed), `redis_context.py` (7 helpers + `_memory_context`/`_memory_history` deleted), `chat.py` (`/chat/reset` rotates the thread only). |

**Step 2b is complete** — conversation state lives entirely in the LangGraph `ChatState` (checkpointer); Redis keeps only the thread-id map, Google caches, locks, and rate-limit counters. Pending: the user's end-to-end live test.

**3 → 6 later (only if needed):** the 3-node split is a strict **prefix** of a 6-node one — only `interact` would split (its slot / clarify / scope / confirm branches become `ask_slot` / `clarify` / `scope` / `confirm` nodes). That's a pure "promote branches to nodes" move (add edges, no logic rewrite), so defer it unless per-gate streaming or observability is wanted.

---

## Radius & anchor from the prompt (planned)

*A chat-intelligence feature: the chat understands a search **radius** and an optional **center point (anchor)** from natural language, surfaces them in the existing confirm gate, and lets the user refine — then Overture's `ST_DWithin` executes the exact circle. The search side already supports any radius/center (`ST_DWithin` in meters); this adds only the **understanding + gate handling**, so it belongs here (chat intelligence), not in the Overture layer. **✅ Implemented (pending the user's live test).***

### What it adds
Two new resolved slots flowing through the same `understand → merge → confirm/refine → search` pipeline:
- `radius_km` — the requested radius (null → use the plan radius).
- `anchor` — a specific center within the city, e.g. a neighborhood/landmark (null → city center).

### Extraction (in `understand()`)
- **Radius:** "within/in N km", "N km radius" → `radius_km = N`; "N miles" → `N × 1.609`.
- **Anchor:** a named area/landmark → `anchor` (e.g. "near Thapathali" → `anchor="Thapathali"`); the **city** stays in `location` as today.
- Both null when not mentioned; carried forward across turns like the other slots.

### Radius resolution — **decision locked**
**Honor the user's radius, clamped to `[1 km … 15 km]`.** The plan radius (starter 5 / growth 6 / scale 7 km) is the **default when the user gives no radius**. A request above 15 km is capped to 15 km (the confirm says so); below 1 km → 1 km. *(Rationale: the feature's whole point is user control; the 15 km cap prevents a giant Overture cold-load.)*

### Center resolution (in `_search_phase`)
```
center = geocode(anchor + ", " + city)   if anchor set
         geocode(city)                    otherwise
```
Pass `center` + the resolved radius to `get_leads_overture` **and** the cold-load task, so the loaded box matches the requested radius.

### Confirm surfacing — **no new gate** (same final confirm)
- anchor set → *"hotels within 10 km of Thapathali, Kathmandu — refine or go."*
- radius, no anchor → *"hotels within 10 km of **central Sydney** — want a specific area (e.g. 'near Bondi'), or go?"* ← teaches the option without forcing it.
- capped → *"…within **15 km** (max) of central Sydney…"*.
- no radius → today's confirm (unchanged).

The anchor/radius are adjusted through the **existing refine loop** ("near Bondi", "make it 15 km") — nothing new in the flow.

### Scenarios
| # | User says | `radius_km` | `anchor` | Center | On "go" |
|---|---|---|---|---|---|
| 1 | `hotels within 10km in sydney` | 10 | ∅ | Sydney center | 10 km from CBD |
| 2 | `hotels within 10km of thapathali, kathmandu` | 10 | Thapathali | Thapathali | 10 km from Thapathali |
| 3 | `hotels in sydney` (no radius) | ∅ | ∅ | Sydney center | plan radius |
| 4 | `hotels within 5 miles of bondi` | 8 | Bondi | Bondi | 8 km from Bondi |
| 5 | #1 → `near bondi` | 10 | Bondi (refine) | Bondi | 10 km from Bondi |
| 6 | #3 → `within 15km` | 15 | ∅ | Sydney center | 15 km |
| 7 | `hotels within 50km in sydney` | 15 (capped) | ∅ | Sydney center | 15 km |
| 8 | `hotels within 10km near thapathali` (no city) | 10 | Thapathali | geocode "Thapathali"; ambiguous → ask city | — |

### Edge cases
- **Anchor, no city** → geocode the anchor alone; ambiguous/fail → ask for the city (or center on the city).
- **Anchor geocode fails** → fall back to the city center; never break the search.
- **Unrealistic/zero radius** → clamp to `[1 km, 15 km]`. Units normalized (miles → km) in the prompt.

### Verification (after build)
`hotels within 10 km in sydney`: log shows center + `radius_km=10`; **every returned lead ≤ 10 km** from center; **count matches a direct `ST_DWithin` at 10 km** (accounting for the plan/credit lead cap). Same for an anchor case (center = Thapathali).

### Effort / status
Small: **2 schema fields (`radius_km`, `anchor`) + 1 prompt rule + carry-forward + geocode-the-anchor + pass the radius + confirm text.** No new Overture logic. **✅ Implemented** in `understanding.py` (slots + rules) and `chat_service.py` (merge carry-forward, `center_location` + clamped `_search_radius`, `get_leads_overture`/cold-load wiring, `build_confirm_message`). Verified via harness (extraction, carry-forward, confirm text, and search reaching `center='Bondi, Sydney' radius=12`). **Pending the user's live end-to-end test.**

---

## Dependencies and migration

- Add: `langgraph`, `langgraph-checkpoint-postgres` (and its `psycopg`/`psycopg-binary` requirement). You already have `langchain==0.3.27`, `langchain-community==0.3.29`, `langchain-google-genai==2.1.12`, and Postgres as your primary DB.
- Checkpointer tables: run the checkpointer's one-time `await checkpointer.setup()` (creates its own tables) — wire into an Alembic step or app startup.
- Add a **retention/prune** for old checkpoints so per-step rows don't grow unbounded (conversation text is small — keep as long as your policy allows).
- No new vector DB, no pgvector (unless/until RAG is revisited).
- `DATABASE_URL` must be reachable by both the API and Celery workers if any node is shared.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Model drops/overwrites a slot in the merge | `or state.get(...)` carry-forward guards + explicit "only change what the user changed" prompt rule + logging `reasoning` |
| Checkpointer migration touches durable state | Do it in Step 2 in isolation; run the old context path and the new checkpointer path side-by-side behind a flag during cutover |
| Async + Celery interplay with `AsyncPostgresSaver` | Keep graph invocation in the FastAPI async path; Celery tasks (enrichment, cold-area load) stay as today, keyed by `log_id` |
| Checkpoint table growth over time | Retention/prune job for old checkpoints (conversation text is small; keep per policy) |
| Few-shot prompt regressions affect every turn | Golden-set test of 30–50 real queries run on each prompt change |
| "Best/premium" expectations on Overture | Component 6 Option 1 wording is explicit; Option 2 gated behind the `quality` flag |

---

## How the old four solutions fold in

| Old solution | Fate in this plan |
|---|---|
| **#2 Super-Prompt / Goal Extraction** | **Adopted as Component 1** — the centerpiece (its schema, refined). |
| **#1 Agent with Tool Calling** | **Rejected** — see exclusions. Function-calling is still used *mechanically* by `with_structured_output`, but no autonomous agent. |
| **#3 RAG / pgvector** | **Deferred** — optional layer on the `understand` node after Step 2, for vocabulary learning. |
| **#4 Multi-step pipeline** | **Rejected as the default** — we consolidate rather than decompose; its observability goal is met instead by logging `reasoning` + each node's I/O. |

Nothing valuable from the original four is lost — the best (structured goal extraction) is now the foundation, and the rest are explicitly positioned as "later" or "no" with reasons.

---

## Clean-up old code

The intelligence upgrade *replaces* a lot of the current understanding/orchestration code. This is the explicit deletion list, tied to the rollout steps, so nothing is removed before its replacement is proven.

**Golden rule:** delete a piece **only after** its replacement passes the 30–50 query golden-set test ([Risks](#risks-and-mitigations)). During Step 2, run the old Redis path and the new graph path side-by-side behind a flag, then delete the old path once the new one is verified.

### Delete now — dead code (independent of any step)
| What | Where | Why |
|---|---|---|
| Commented-out `chat_guest` body (~240 lines) | [chat_service.py:1122–1363](../backend/app/services/chat_service.py#L1122) | Pure dead code; safe to remove today, no behavior change |

### Remove in Step 1 — superseded by the `understand` node
Delete only after `understand()` is wired in and green on the golden set.
| What | Where | Replaced by |
|---|---|---|
| `is_general_question` | [chat_helper.py:192](../backend/app/utils/chat_helper.py#L192) | `Understanding.intent` |
| `run_extraction` + `get_extraction_prompt` | [chat_helper.py:244](../backend/app/utils/chat_helper.py#L244), [#L91](../backend/app/utils/chat_helper.py#L91) | folded into `understand` |
| `extract_industry_from_history` | [chat_service.py:174](../backend/app/services/chat_service.py#L174) | model sees full history in one call |
| `suggest_correction` + `_spell_cache` | [chat_service.py:371](../backend/app/services/chat_service.py#L371) | spelling normalized inside `understand` |
| `is_industry_variation` | [chat_helper.py:25](../backend/app/utils/chat_helper.py#L25) | model resolves industry vs. variation |
| `_GENERAL_PHRASES`, `_AFFIRMATION_PHRASES`, `_neg_words` | [chat_helper.py:173](../backend/app/utils/chat_helper.py#L173), [#L185](../backend/app/utils/chat_helper.py#L185), [chat_service.py:507](../backend/app/services/chat_service.py#L507) | `intent` field |
| The hand-merge block (~170 lines) | [chat_service.py:471–644](../backend/app/services/chat_service.py#L471-L644) | ~25 lines consuming `Understanding` |

### Remove in Step 2 — superseded by LangGraph + checkpointer
Delete only after the graph path is verified and cut over.
| What | Where | Replaced by |
|---|---|---|
| Conversation **state** helpers: `get/set/delete_user_context`, `get/set/delete_conversation_history`, `clear_user_session` | [redis_context.py](../backend/app/utils/redis_context.py#L96) | Postgres checkpointer (`ChatState` per thread) |
| In-memory fallbacks `_memory_context`, `_memory_history` | [redis_context.py](../backend/app/utils/redis_context.py) | checkpointer is the single source of truth |
| The `chat_logged_in` orchestration body | [chat_service.py:446](../backend/app/services/chat_service.py#L446) | graph nodes (`understand`/`search`/`rank`/`respond`) |
| Slot-fill branches (ask-industry / ask-city / country handling) | [chat_service.py:651–722](../backend/app/services/chat_service.py#L651-L722) | `ask_slot` node + conditional routing |

### Consolidate in Step 3 — fold into `clarify` / `rank` / `respond`
Review rather than blind-delete; behavior moves into nodes.
| What | Where | Becomes |
|---|---|---|
| `generate_suggestions`, `generate_suggestions_with_verification`, `_verified_city_suggestions` | [chat_helper.py:456](../backend/app/utils/chat_helper.py#L456), [#L620](../backend/app/utils/chat_helper.py#L620), [#L373](../backend/app/utils/chat_helper.py#L373) | "no-results → suggest other cities" handled in the `rank`/`respond` flow |
| `generate_human_response` | [chat_helper.py:719](../backend/app/utils/chat_helper.py#L719) | `respond` node (and `Understanding.reply` for greeting/general/negate) |

### Keep — reused as-is by the new nodes
Do **not** remove these; the graph wraps them:
- Search pipeline: `fetch_leads_from_db`, `get_leads_overture`, `prioritize_location_matches`, `normalize_search_terms`, `build_chat_title`.
- Location intelligence: `is_country_or_region`, `is_country_name`, geocode helpers.
- **Caching/concurrency** helpers in [redis_context.py](../backend/app/utils/redis_context.py): cached leads, quick-check, geocode, country/region checks, search locks, rate-limit counters — these are unrelated to conversation state and stay.
- Credits, enrichment tasks, `LeadLog` / `LeadLogLead` persistence.

**Net code impact:** `chat_service.py` drops from ~1,360 lines (incl. dead block) to a thin set of node functions; `chat_helper.py` loses the extraction/classification/heuristic helpers; `redis_context.py` keeps only caching/locking. The result is fewer files doing one job each, instead of one monolith doing all of them.

---

## Open issues & resolutions

A critical pass over the plan surfaced eight issues. Resolutions below; two are product decisions (flagged).

### Unifying principle for #2 + #3 — "the model proposes, quick-check disposes"
Never trust the model's `ambiguous` flag or candidate meanings on their own — **verify them against real Overture results** with the existing (cached) [quick_check_results](../backend/app/utils/chat_helper.py#L342), the same pattern as [_verified_city_suggestions](../backend/app/utils/chat_helper.py#L373). The model generates ideas; the data decides.

| # | Issue | Resolution | Affects |
|---|---|---|---|
| 1 | **Checkpointer choice — Redis vs Postgres** | **Decided: Postgres checkpointer.** Live state alone would favour Redis (one-shot chat), but keeping the **full conversation durably** (review how users ask / where they stopped) and staying **ready for a future agentic direction** justify Postgres. Accept the heavier Step 2; add a **checkpoint retention/prune**; defer aggregate analytics to an optional `chat_messages` table only if needed. | Step 2 |
| 2 | **Disambiguation dead-ends** — clarified meaning may return 0 leads | In `clarify`, run quick-check on each candidate's terms for the location; **offer only meanings that return leads**. One survivor → skip the question and search it. None → "no results, try another location." | Step 3 |
| 3 | **Ambiguity detection is imperfect** (false-positive nag / false-negative blind search) | Treat a query as ambiguous **only when ≥2 candidates both pass quick-check** — evidence, not a hunch. Plus a ~50-query golden set run on every prompt change. | Step 1/3 |
| 4 | **Brand / named-entity search unsupported** (apple-the-company vs category) — *product decision* | **Decided: out of scope.** `understand` detects a specific brand/company name and **redirects gracefully**: "I search by business type and location, not specific companies — want me to find Apple resellers instead?" No silent garbage. | Step 1 |
| 5 | **"Best / premium" not solved** — Overture has no rating data — *product decision* | **Decided: Phase 1 only for now** — capture `quality` silently, return normal results, **no disclaimer** (treat "best X" like a normal search). **Phase 2 deferred** — on-demand Google Places `rating`, gated to quality queries — build only if stakeholders later require true "best". | Step 3 / later |
| 6 | **Search node edge cases** (no-results, geocoding-failed, rate-limited, cold-area gathering, insufficient-credits) + async cold-load don't map cleanly onto a graph node | Map each terminal state to a simple **respond-and-END** edge. Leave the **Celery cold-fill + frontend polling unchanged, outside the graph** ([gathering path](../backend/app/services/chat_service.py#L891)). The graph owns the synchronous decision flow only. | Step 2 ↓ risk |
| 7 | **Combined-answer parsing** ("Sydney, just hotels" → two fields at once) | Keep parsing in the `understand` prompt; cover combined answers in the golden set; if uncertain, fall back to asking the still-missing field. | Step 1 |
| 8 | **Multi-source orchestration (PDF §6–7) parked** | Explicitly **out of scope** — a separate initiative. Revisit only if Overture coverage proves insufficient. The plan solves the right ~70% (understanding, disambiguation, scope, relevance). | — |

**Reconciled (done):** the whole doc uses the **Postgres** checkpointer (TL;DR, Component 2, Step 2, Dependencies, Risks, Clean-up) — chosen for durable full-conversation history and future agentic readiness. The ad-hoc Redis conversation-state helpers are replaced by it; aggregate analytics, if ever needed, go to an optional `chat_messages` table. Product decisions #4 (brand search → out of scope) and #5 (true "best" → Phase 2 deferred) are locked.
