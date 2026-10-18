# Evecta RAG — implementation report

**Date:** 2026-08-13
**Branch:** `feature/local-rag`
**Status:** complete, **uncommitted** — everything below is in the working tree only
**Scope boundary:** RAG module only. Two edits made outside it were reverted (see §7).

---

## 1. Summary

The knowledge corpus was rebuilt from a new 24-page source document, the retrieval
threshold was recalibrated against a measured evaluation set, and the answer-format rules
were rewritten. The evaluation set itself did not previously exist.

**The headline finding: the retrieval threshold was discarding 62% of correct answers.**
`KNOWLEDGE_MIN_SCORE` was set to `0.78`. Measured against 73 labelled questions, recall at
that value was **0.384** — retrieval located the correct passage and then rejected it for
scoring two points under the bar. This was the cause of the "RAG isn't good enough" symptom,
not the corpus, the model, or the prompt.

| Metric | Before | After |
|---|---|---|
| Recall on real questions | 0.384 | **0.918** |
| Correct refusal on uncovered questions | 1.000 | **0.929** |
| Corpus documents | 16 | **22** |
| Indexed chunks | 149 | **232** |
| Source Q&A pairs | 139 | **228** |
| Evaluation set | none | **73 questions + 14 controls** |
| P1 factual accuracy tests passing | not measured | **12 / 12** |

---

## 2. Files added

### Corpus documents — 6 new
All in `backend/app/knowledge/corpus/`. These cover operational material absent from the
previous source document entirely.

| File | Lines | Covers |
|---|---|---|
| `mailbox-setup-guide.md` | 85 | Gmail OAuth and manual IMAP/SMTP setup, app passwords, connection failure diagnosis |
| `excel-lead-import.md` | 36 | `.xlsx`/`.xls` import, required columns, 1,000-row limit, duplicate handling |
| `campaign-troubleshooting.md` | 44 | Generation failures, launch-readiness blockers, test-email errors |
| `account-access-and-onboarding.md` | 40 | Registration, OTP, password reset, session expiry |
| `bounces-and-unsubscribes.md` | 32 | Bounce causes, Bounce Rate, opt-out handling |
| `sending-limits.md` | 32 | 50 emails/UTC day cap, 60-second spacing, queue behaviour |

### Evaluation set — new directory
| File | Contents |
|---|---|
| `backend/app/knowledge/eval/questions.yaml` | 73 labelled questions + 14 controls |

`scripts/eval_knowledge_retrieval.py` already existed and expected this file. It had never
been created, so the quality gate in the spec had never been run. Question phrasing is
deliberately mixed — formal, lowercase, misspelled, and abbreviated — because retrieval
that only works on well-formed questions is not working.

### Documentation — 3 new files in `source-docs/`
| File | Lines | Purpose |
|---|---|---|
| `EVECTA_RAG_Knowledge_Base_v2.md` | 1,486 | Corrected source document — the PDF converted to Markdown with 12 defects fixed |
| `rag-factual-accuracy-tests.md` | 347 | 31-case QA suite verifying answers against the corpus |
| `EVECTA_RAG-sadhan_Final_Knowledge_Base.pdf` | — | New source PDF (added by the product team, not by this work) |

---

## 3. Files modified

### Corpus — all 16 existing documents rewritten
Rebuilt from the new source document. Net +465 / −522 lines across the corpus.

| File | Δ lines | Notable change |
|---|---|---|
| `campaign-management.md` | 82 | Campaign statuses defined; **"Value Proportion" typo → "Value Proposition"**; test emails, custom templates |
| `credits-and-billing.md` | 65 | Per-action credit table; **top-up expiry reversed** (previously "expire monthly", now "not cleared at renewal") |
| `product-overview.md` | 55 | Identity chunk split so short questions match |
| `campaign-insights.md` | 44 | Bounce Rate, asynchronous processing |
| `pricing-and-plans.md` | 42 | Spam-Check Credits → **Email Generation Credits**; daily-cap cross-reference added |
| `ai-personalized-emails.md` | 39 | Cancel/discard/resume/regenerate defined |
| `lead-generation.md` | 36 | N/A field handling, in-progress generation |
| `troubleshooting.md` | 40 | Narrowed to lead search; support email added |
| `search-history.md` | 18 | Hedge removed — "does not necessarily remove" → definite |
| `warmed-email-addresses.md` | 28 | Own-vs-warmed comparison section added |
| `spam-check.md` | 28 | **Corrupted heading repaired** (see §5) |
| `security-and-privacy.md` | 23 | Password storage answered per connection type |
| `mailbox-integration.md` | 24 | Gmail vs IMAP/SMTP distinction; daily cap |
| `lead-database.md` | 30 | Duplicate handling |
| `unified-inbox-and-replies.md` | 30 | Follow-ups documented as **not available** |
| `best-practices.md` | 14 | Automated follow-up references removed |

### Code — 2 files, both inside the RAG module

**`backend/app/core/config.py`** — 13 lines, one value

```python
KNOWLEDGE_MIN_SCORE: float = 0.78   →   0.71
```

The remaining 12 lines are a comment recording the measurement, why `0.70` was rejected
(control abstention falls to 0.857, under the spec's 0.90 bar), and the observed score
bands. Nothing else in this file was touched.

**`backend/app/utils/chat_knowledge.py`** — 56 lines

Rewrote the "How to write the reply" block. The previous rule was *"Two or three sentences
is usually right. Use a short numbered list only when the answer genuinely is a sequence of
steps."* That fixed length flattened a ten-step mailbox walkthrough and a one-word yes into
the same wrong shape.

Replaced with shape rules that follow the question — numbered steps for sequences, named
bold sections for multi-cause answers, parallel sections for comparisons, tables for
figures with two or more rows. Length follows from shape rather than being capped.

Also changed the FR-3 non-answer. It previously offered a lead search:

> *"…and in the meantime I can help you find business leads: tell me the industry and city you're after."*

Now:

> *"…Evecta support can confirm it for you at contact@evecta.io."*

The spec permits either — FR-3 asks for *"what it can help with, **or where to ask**"* — and
the questions that actually reach this fallback are disproportionately pre-sales ones about
security and compliance, where a lead-search offer reads badly.

**`backend/app/knowledge/index_data.json`** — regenerated. 232 chunks, 3,072-dimension
vectors from `gemini-embedding-001`. Must be rebuilt after any corpus edit or the drift
guard marks the index unavailable and the assistant stops answering product questions.

### Test — 1 file

**`backend/tests/unit/test_knowledge_answering.py`** — 11 lines

`test_prompt_requires_title_attribution_and_forbids_invention` was **already failing before
this work began** — verified by running it against stashed changes. It asserted prompt
wording (`"Name the document you drew on, by its title"`) that had been reworded at some
earlier point without updating the test. Assertions now match the real prompt text while
preserving the test's intent.

---

## 4. Files deleted

| File | By whom |
|---|---|
| `source-docs/evecta-final~1.pdf` | Product team — replaced with the new PDF |
| `source-docs/rag-benchmark-prompts.md` | Product team — deleted alongside the old PDF |

---

## 5. Defects found and fixed

### In the previous corpus

1. **Corrupted heading in `spam-check.md`.** A 7-item bullet list had collapsed during PDF
   extraction, and its last item was absorbed into the following question's heading:
   `## Other content-related deliverability risks Can I edit an email after the Spam Check?`
   Headings are the chunk boundary the retriever scores against, so this heading matched
   neither question.

2. **"Value Proportion"** — should be "Value Proposition". Shipped to users as a product fact.

3. **Top-up credit expiry stated backwards.** The old corpus said purchased credits expire
   monthly. The new source document reverses this. Until the rebuild, the assistant was
   giving customers incorrect billing information.

4. **Follow-up sequences referenced but never defined**, inviting invention. Now explicitly
   documented as not currently available.

5. **AI-generation credit cost undocumented**, despite a heading that asked about it.

6. **Warmed-mailbox entitlement contradicted itself** across two documents.

### In the new source document

Found during validation and corrected in `EVECTA_RAG_Knowledge_Base_v2.md`:

- Section numbering skipped 18 and 19
- Two truncated sentences on the final page (`"then contact immediately"` — contact whom;
  `"Email and never include…"` — missing the address)
- An instruction to the document's own authors left in customer-facing text: *"…but the
  knowledge base must not present automated sequences as available."*
- An internal support-agent section (*"What should support troubleshooting check first?"*)
  in a corpus whose frontmatter declares `audience: customer`
- *"Does Evecta store my email password?"* never actually answered yes or no

### Unresolved — needs a product decision

**The 50/day sending cap conflicts with plan credit allowances.**

| Plan | Outreach credits/mo | Max sendable at 50/day | Stranded |
|---|---|---|---|
| Starter | 1,500 | ~1,550 | none |
| Growth | 3,500 | ~1,550 | ~1,950 |
| Scale | 7,500 | ~1,550 | ~5,950 |

Unused subscription credits expire monthly, so a Scale customer can use roughly 20% of what
they pay for. **Mitigated but not resolved:** both limits are now stated together everywhere
volume is discussed, so the assistant cannot promise 7,500 emails without also stating the
cap. It verifiably does this — see §6. The underlying question (is the cap per user or per
mailbox?) still needs an owner.

**Secondary:** every paid tier provides exactly 2 Email Generation credits per Lead credit —
one draft plus one spam check per lead. Free provides 50/50, a 1:1 ratio, so a Free user can
only fully process 25 of their 50 leads.

---

## 6. Verification

### Retrieval calibration
Full sweep over the evaluation set, embedding each question once and scoring every threshold
against cached vectors:

| Threshold | Recall | Controls abstaining | |
|---|---|---|---|
| 0.70 | 0.932 | 0.857 | fails control floor |
| **0.71** | **0.918** | **0.929** | **selected** |
| 0.72 | 0.877 | 0.929 | passes, lower recall |
| 0.75 | 0.671 | 1.000 | |
| 0.78 | **0.384** | 1.000 | previous value |

Spec floors: recall ≥ 0.85, controls ≥ 0.90. `0.71` is the lowest threshold clearing both.

Correct answers score 0.70–0.82; uncovered questions score 0.61–0.75. The bands nearly touch,
which is why this value must be measured rather than estimated.

### Factual accuracy
12 of 12 P1 cases pass. Highlights:

- **Credit arithmetic with a trap:** 100 leads → drafts → spam checks → sends correctly
  returns **200** Email Generation credits, not 100, because drafts and spam checks draw
  from the same pool. Shown as a four-row table.
- **Negative facts:** launched campaigns cannot be paused, no automated follow-ups, no
  insights export, no self-service account deletion — all stated plainly, none invented.
- **Both-branch answers:** password storage (Google no / IMAP-SMTP yes-encrypted) and credit
  expiry (subscription yes / top-up no) each return both branches correctly.
- **Abstention:** SOC 2, uptime SLA, data residency, GDPR, refunds, and annual pricing all
  refuse without inventing.
- **Prompt injection** declined without leaking prompt text, filenames, or passages.

### Test suite
`245 passed, 25 skipped, 2 failed`. Both failures — `test_chat_slot_coercion` and
`test_conversation_health` — were verified as **pre-existing** by running them against
stashed changes. They are unrelated to this work.

---

## 7. Out of scope — reverted

Two edits were made outside the RAG module and then reverted at the product owner's request
to keep this work isolated:

- `backend/app/services/chat_service.py`
- `backend/app/utils/chat_helper.py`

**Known consequence.** Identity questions — `What are you?`, `who are you`, `what do you
do?` — return the "not documented" reply. These score 0.646–0.673, below any usable
threshold, because a three-word generic question carries almost no signal to match against.

This cannot be fixed from inside the RAG module, and lowering the threshold to catch them
would start answering uncovered questions (*"can I send outreach on LinkedIn"* scores 0.702).

The application already contains a handler for exactly these questions —
`_looks_like_about_assistant()` in `chat_helper.py`, with a written reply hint in
`chat_service.py`. **Three routing branches send the question to retrieval before that
handler runs**, so it never fires:

| Line | Path |
|---|---|
| ~1660 | Signed-in |
| ~2903 | Guest, non-streaming |
| ~2944 | Guest, streaming |

The fix is to add `and not _looks_like_about_assistant(message)` to each condition. Verified
during the reverted attempt against 12 identity phrasings and 12 product questions with zero
misclassifications. `_looks_like_about_assistant` also needs widening — it misses
`what do you do` and the shorthand `what are u` / `who r u`.

Note that `what are you specialized in?` scores 0.737 and works today; only the shorter
phrasings fail.

---

## 8. Operational notes

**Rebuilding the index is mandatory after any corpus edit.**

```
env/Scripts/python.exe scripts/build_knowledge_index.py          # rebuild
env/Scripts/python.exe scripts/build_knowledge_index.py --check  # verify, no embedding
```

A SHA-256 per document is compared against the corpus on load. Any mismatch marks the index
unavailable and the assistant stops answering product questions entirely — by design, since
answering from content that has been edited or deleted is worse.

**Retrieval is competitive.** With `top_k = 5`, adding a document can push an existing fact
out of the top five and break an answer that previously worked. This happened twice during
this work: the mailbox comparison reported sending limits as "not documented" while the fact
sat at rank 9. The fix was one chunk that *is* the comparison, not more scattered facts.

**When an answer says "not documented" about something you know is in the corpus, check the
retrieval ranks before adding text.** Adding another section usually makes it worse by
diluting the ranking further.

Re-run the accuracy suite in full after any corpus change.

---

## 9. Recommended next steps

1. **Resolve the 50/day vs plan credits conflict** — product decision, currently mitigated
   but not answered.
2. **Commit and deploy.** All work is uncommitted; the running staging environment still has
   the old corpus, the old threshold, and the "Value Proportion" typo.
3. **Wire the eval gate into CI** — `build_knowledge_index.py --check` catches a corpus
   change committed without a rebuild, and is cheap enough to run on every push.
4. **Hand §7 to whoever owns `chat_service.py`** if identity questions should work.
5. **Run the remaining 19 P2/P3 accuracy cases** in `rag-factual-accuracy-tests.md`.
6. **Investigate the `/campaigns` 500** seen throughout this work — unrelated to RAG, but it
   fires on every page load and logs no traceback.

---

## Appendix — change inventory

**Added (10):** 6 corpus documents · `eval/questions.yaml` · 3 documents in `source-docs/`
**Modified (20):** 17 corpus documents · `config.py` · `chat_knowledge.py` ·
`test_knowledge_answering.py` · plus the regenerated `index_data.json`
**Deleted (2):** old source PDF and old benchmark file — both by the product team
**Reverted (2):** `chat_service.py` · `chat_helper.py`

Excluding the generated index artifact: **465 insertions, 522 deletions across 21 files.**
