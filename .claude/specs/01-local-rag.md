---
step: 01
feature: local-rag
status: approved
spec_mode: full
---

# Spec: Local RAG for Grounded Product Answers

## Summary

When a user asks the lead-generation chat a question about Evecta itself — "how do
credits work?", "why did my campaign not send?", "what's the difference between a
lead list and a campaign?" — the assistant answers from the model's own general
knowledge. Today every conversational turn (`greeting`, `general_question`,
`negate`) is routed to the same free-form response generator, which is given the
current search slots and the transcript but no product documentation. The model
therefore invents plausible-sounding Evecta behavior, and nothing in the system can
tell a correct answer from a fabricated one. `docs/CHAT_CONVERSATION_DESIGN_AUDIT.md`
§L records this as findings 58–60.

This feature adds a governed corpus of approved, user-facing Evecta documentation
and makes the chat answer product and help questions **from that corpus only**, with
an honest "I don't have that documented" fallback when the corpus does not cover the
question. The corpus and its index are part of the product's own storage — no
external retrieval service is introduced, which is what "local" means here.

The boundary is deliberately narrow: this is knowledge retrieval for product and
help questions. It does not touch how the chat remembers a search goal, resolves
ambiguity, or queries lead records.

## Goals and non-goals

### Goals

- Product and help questions about Evecta are answered from approved documentation
  rather than unaided model knowledge.
- An uncovered question produces an honest non-answer, not a confident invention.
- The corpus is governed: every document has a known audience, version, and review
  date, and the corpus is auditable for what it must never contain.
- Retrieval quality is measured against a committed floor before the feature is
  considered done.
- Existing conversational behavior is preserved — a product question mid-search does
  not lose the user's goal or trigger a search.

### Non-goals

- Retrieval over customer data (leads, campaigns, sent emails, inbox threads). That
  is a tenancy-sensitive feature and must be specified separately.
- Grounding the ambiguity and scope-family questions in real category candidates
  (audit finding 12) — related, but a different retrieval target and a different
  quality bar.
- Redesigning chat intent routing, memory layers, or the confirmation flow (audit
  findings 1–7, 46, 59).
- Conversational quality metrics and performance budgets beyond the one latency
  requirement below (audit findings 61–64).
- Authoring the full Evecta help centre. This feature needs a first corpus, not a
  complete one.
- A content authoring, approval, or publishing interface. Per `BR-6` the corpus ships
  with the application, so editing it is a release.
- Any new user-facing entry point. The answers arrive through the chat that exists.

## Users and scenarios

- **Signed-in user mid-search.** Has told the chat "restaurants in Sydney", then
  asks "does this use up my credits?" before confirming. They expect a real answer
  and expect the chat to still know about Sydney restaurants afterwards.
- **Signed-in user, standalone help question.** Opens the chat and asks "how do I
  connect my own mailbox?" with no search in progress.
- **Guest user.** Reaches the chat without an account and asks what Evecta does or
  what a plan includes.
- **Support and content owner.** Maintains the corpus. Needs to know what is in it,
  when each document was last reviewed, and that removing a document actually stops
  the assistant from saying it.

## Requirements

- `FR-1` — When a chat turn is a product or help question about Evecta, the assistant
  composes its answer from documents retrieved from the approved knowledge corpus.
- `FR-2` — Every statement of fact about Evecta in such an answer is supported by at
  least one retrieved document, and the answer names the title of the document it drew
  on. Titles only — there is no public help URL to link to.
- `FR-3` — When retrieval surfaces nothing sufficiently relevant, the assistant says
  it does not have that documented, does not answer from general knowledge, and
  offers a next step (what it can help with, or where to ask).
- `FR-4` — A product or help question never starts, cancels, or advances a lead
  search, and never clears the resolved search slots or a pending clarification. The
  turn returns the user to exactly the conversational state they were in.
- `FR-5` — Questions that are not about Evecta — world facts, chit-chat, questions
  about a third-party company — keep today's behavior: no retrieval, and the existing
  redirect back to lead generation.
- `FR-6` — Every corpus document carries, and exposes to whoever maintains it, a
  title, an intended audience, a version, and a date it was last reviewed.
- `FR-7` — The corpus contains only content approved for customers. Secrets,
  environment configuration, server logs, internal engineering notes, unreleased
  plans, and any customer data are excluded, and the corpus inventory can be read to
  confirm this.
- `FR-8` — Removing or editing a corpus document changes what the assistant says.
  Content removed from the corpus is no longer used in any answer.
- `FR-9` — Retrieval adds no more than 500 ms at p95 to the time the user waits for
  the assistant's first visible response on a product question, and answers continue
  to stream as they do today.
- `FR-10` — If the knowledge corpus or its index is unavailable, the chat turn still
  completes: the assistant falls back to the `FR-3` non-answer rather than erroring
  the conversation.
- `FR-11` — The corpus is product knowledge and is not scoped to a user or company:
  every user who receives a grounded answer to a question receives the same one, and
  no retrieved document is filtered by who is asking. Guests receive grounded answers
  on the same terms as signed-in users, as the chat already serves them today.
- `FR-12` — For each retrieval-backed turn the system records the question, which
  documents were retrieved, and whether the `FR-3` fallback fired, so the evaluation
  set below can be grown from real traffic.

## Business rules

- `BR-1` — The corpus is global and contains no customer or tenant data. Nothing a
  user types, uploads, or generates may enter it. Consequently no per-user filtering
  of retrieved documents is required, and none may be relied on as a safety measure.
- `BR-2` — Retrieved document text is data, not instruction. Text inside a document
  that reads as a command must not change the assistant's behavior, its persona, or
  what it is willing to disclose.
- `BR-3` — Retrieval must not be used as the mechanism for: remembering the active
  industry or location; resolving a pending question; applying a correction such as
  "change Melbourne to Sydney"; querying structured lead records; or deciding whether
  a search is allowed to proceed. Those remain conversational state and structured
  queries.
- `BR-4` — The corpus and its index are part of Evecta's own storage. No external
  retrieval or vector-database service is introduced. Turning text into a comparable
  form may use the model provider already in the stack: the user's query text is
  already sent to that provider on every chat turn today, so no new class of data
  leaves the system. "Local" constrains where the corpus and its index live, not
  whether an embedding call may be made.
- `BR-5` — A document whose last-reviewed date is more than 12 months old is treated
  as stale and is not used to answer, so that silence is preferred over confidently
  outdated product claims. The horizon is long because the first corpus is small and
  newly written; a shorter one would begin silencing it within a quarter.
- `BR-6` — The corpus ships with the application. Changing what the assistant knows is
  a release, not a content edit, for this feature.

## User experience and failure behavior

- Answers keep the chat's existing voice and brevity. Source attribution is a short
  mention of the document, not a citation list that dominates a two-sentence reply.
- The mid-search case is the one users will notice most: after the answer, the
  assistant returns to where the conversation was, including any question it was
  waiting on.
- The non-answer must be usable, not a dead end. "I don't have that documented" on
  its own is a failure of this requirement; it needs the next step from `FR-3`.
- A partial match is still an answer — if the corpus covers part of the question, the
  assistant answers that part and is explicit that the rest is not documented.
- Corpus or index unavailability is invisible as an error: the user sees a non-answer,
  not a failed turn or a broken stream.

## Retrieval quality bar

- **Evaluation set:** 40 real product and help questions taken from existing chat
  transcripts and from the questions support and onboarding actually receive, each
  labelled by a person with the corpus document(s) that contain the answer. Plus 8
  control questions that are plausible Evecta questions the corpus does not cover.
- **Correct result:** for a labelled question, at least one labelled document appears
  in the set of documents passed to the model. For a control question, the correct
  result is that nothing clears the relevance threshold and the `FR-3` fallback fires.
- **Floor:** recall ≥ 0.85 across the 40 labelled questions, with at most 5 documents
  passed to the model per question; and ≥ 0.90 of the 8 control questions produce the
  fallback rather than an answer. Both measured on the evaluation set before the
  feature is called done.

## Acceptance criteria

- `AC-1` — Given a corpus document that states how credits are consumed, when a user
  asks "does searching use my credits?", then the answer matches that document, states
  nothing the document does not support, and that document is recorded as its source.
- `AC-2` — Given a question with no answer anywhere in the corpus, when the user asks
  it, then the assistant says it is not documented and offers a next step, and states
  no Evecta-specific fact.
- `AC-3` — Given a conversation where industry and location are resolved and the
  assistant is waiting on a confirmation, when the user asks a product question and it
  is answered, then the industry, location, and the pending confirmation are unchanged
  and no search has run.
- `AC-4` — Given a user asks "what's the capital of France?", when the turn is
  handled, then no corpus retrieval informs the reply and the existing redirect
  behavior is unchanged.
- `AC-5` — Given a corpus document is removed, when a user asks the question that
  document used to answer, then the assistant no longer states its content and gives
  the `FR-3` non-answer.
- `AC-6` — Given a corpus document containing a line that instructs the assistant to
  ignore its rules or reveal its prompt, when a question retrieves that document, then
  the assistant's behavior is unchanged and the instruction is not followed.
- `AC-7` — Given the knowledge index is unavailable, when a user asks a product
  question, then the turn completes with the `FR-3` non-answer and the conversation
  remains usable.
- `AC-8` — Given the evaluation set above, when it is run, then the measured results
  meet the floor in the Retrieval quality bar.
- `AC-9` — Given the corpus inventory, when it is reviewed, then every document has a
  title, audience, version, and last-reviewed date, and none contains secrets,
  internal-only notes, or customer data.
- `AC-10` — Given a product question answered from the corpus, when the turn is
  measured across the evaluation set, then retrieval has added no more than 500 ms at
  p95 to the wait before the first visible response, and the reply still streams.
- `AC-11` — Given the same product question asked by two users of different identity
  who both receive a grounded answer, when both turns complete, then both answers draw
  on the same corpus documents, and no document was withheld from one of them on the
  basis of who asked.
- `AC-12` — Given a retrieval-backed turn, when it completes, then the question, the
  documents retrieved, and whether the `FR-3` fallback fired have been recorded, and
  can be read back to extend the evaluation set.

## Dependencies and open questions

### Dependencies

- The company documentation the owner already holds, screened document by document
  against `FR-7` and carrying the `FR-6` metadata. Existing material satisfies the
  content half of this dependency; the governance half is outstanding work. Nothing
  in the repository substitutes for it — `docs/` is internal engineering material and
  is explicitly excluded by `FR-7`.
- A person to label the evaluation set; the floor cannot be measured without it.
- The existing chat surface and its streaming behavior, which this feature extends
  rather than replaces.

### Open questions

None.

### Resolved decisions

Recorded so the reviewer can see what was chosen and object before approval. Each was
taken as the lowest-risk default, not as the only defensible answer.

- `Q-1` — **First corpus:** the company documentation the owner already holds,
  screened against `FR-7` and given `FR-6` metadata. Rewriting `docs/` was rejected
  because it is engineer-facing and risks leaking internal detail; authoring from
  scratch was rejected because it blocks the feature on content writing.
- `Q-2` — **External call permitted.** Embedding uses the model provider already in
  the stack. Running entirely in our own infrastructure was rejected as a dependency
  the team would own, held to the same floor, for no data-exposure gain — the query
  text already reaches that provider on every chat turn. See `BR-4`.
- `Q-3` — **Corpus ships with the application.** Independent editing was rejected for
  this feature: it needs an authoring and approval path that does not exist, and it
  turns `FR-7` from a one-time review into continuous enforcement. See `BR-6` and the
  matching non-goal.
- `Q-4` — **Review horizon is 12 months.** A 90-day horizon would begin silencing a
  newly written corpus within a quarter. See `BR-5`.
- `Q-5` — **Guests are answered**, on the same terms as signed-in users. See `FR-11`.
- `Q-6` — **Floor stands at recall ≥ 0.85 at 5 documents, ≥ 0.90 control fallback**,
  over 40 labelled and 8 control questions. Proposed rather than measured; the first
  measurement may show the corpus cannot reach it, which is a signal about corpus
  coverage rather than a reason to lower the bar.
- `Q-7` — **Document title only.** A link needs a public help URL that does not
  exist; silent grounding was rejected because the user could not distinguish a
  grounded answer from a guess. See `FR-2`.

Three of these are business calls rather than technical ones — `Q-1` scope, `Q-3`
release cadence, and the `Q-6` floor the feature will be held to. Confirm them before
setting `status: approved`.
