# Lead Enrichment & Context Collection

How Evecta enriches leads after lead search, why it runs in the background, where
the personalization context actually comes from, and the edge cases each lead must
handle.

Cross-references the Evecta Outreach Intelligence System architecture (AI Training
About Mail Content doc: §1 Lead Information Collector, §4 AI Generation, §5 User
Review). Where this codebase diverges from that doc, this file describes **what the
code actually does today** and flags genuine gaps separately.

---

## 1. Two different "scrapers" — don't confuse them

This is the single most important thing to understand before reading the rest.
Evecta has **two independent enrichment paths** that scrape websites for different
reasons:

| Path | What it scrapes | What it fills | Entry point |
| --- | --- | --- | --- |
| **Lead enrichment** | each *lead's* website (contact email **+ context**) | `email`, `email_source`, `hunter_data`, `lead_score`, **`services`, `website_summary`, `business_description`** on the lead row | [`enrich_leads_background`](../backend/app/services/lead_generation_service.py) |
| **Company profile scraper** | the *user's own* company website (onboarding) | rich profile fields on the `Company` row | [`company_scraper_worker.py:16`](../backend/app/services/company_scraper_worker.py) |

Both the *sender's* profile (company scraper) and each *lead's* context (lead
enrichment, see §3) feed personalization. The two are independent: the company
scraper fills the `Company` row about the sender; lead enrichment fills per-lead
context columns. Context fields are **collected during enrichment** (Step 1) and
**consumed by the Personalization Level Engine** (Step 2 — see
[`personalization-engine.md`](personalization-engine.md)).

---

## 2. Lead sources

A lead can originate from any of these before enrichment runs:

| Source | How | Carries email at search time? |
| --- | --- | --- |
| **Overture Maps** | DuckDB pull from S3 parquet, cached in PostGIS (`overture_places` / `overture_loaded_areas`); monthly release auto-detect | Sometimes (Overture `email` field) |
| **Google Places** | Nearby Search + place details ([`lead_generation_service.py:1435`](../backend/app/services/lead_generation_service.py)) | No |
| **Lead database** | Previously saved & enriched leads (`_from_db`) | Yes — already enriched |

A raw lead row ([`LeadLogLead`](../backend/app/models/lead_log_lead.py)) has:

`business_name`, `industry`, `email`, `contact_number`, `address`, `website`,
`lead_score`, `enrichment_status`, `promoted`, `hunter_data`, and the context columns
`services`, `website_summary`, `business_description` (filled during enrichment;
mirrored onto the promoted [`Lead`](../backend/app/models/lead.py) row).

---

## 3. What lead enrichment actually does

Per lead, [`enrich_lead`](../backend/app/services/lead_generation_service.py) does the
whole thing off a **single site fetch** — no double scrape:

```
no usable website? ── yes ─→ keep existing email; everything else = None
        │ no
        ▼
fetch_pages_raw(domain, ENRICH_FETCH_PATHS)   ← ONE crawl (email_scraper.py)
   union of contact + about/services pages, http+https, concurrent, SSRF-guarded
        │
        ├─ EMAIL (only if lead has none):
        │     emails_from_texts → pick_best_result → else hunter_fallback_company (API)
        │     → email + email_source + hunter_data
        │
        └─ CONTEXT (always):
              build_context_text (clean+cap ~6k) → extract_lead_context
              → 1 Gemini Flash call (ainvoke) → services / website_summary / business_description
        ▼
        batch_score_leads  (deterministic, see below)
```

### Email finding
Reuses the shared page text: `emails_from_texts` regex-extracts addresses, filters to
business prefixes (`info`, `contact`, `sales`, …) on the company domain, scores with an
**MX-record** check, and `pick_best_result` returns one. If the site yields none, it
falls back to **Hunter.io** company enrichment (an API call, *not* another scrape).
Skipped entirely when the lead already has an email (e.g. Overture). All in
[`email_scraper.py`](../backend/app/utils/email_scraper.py).

### Context scraping
`extract_lead_context` ([`company_scraper_service.py`](../backend/app/services/company_scraper_service.py))
runs on the same fetched text — never invents data (too-little-text or any error →
fields stay `None`), bounded by the `context` semaphore, using the fast/low-temp
[`get_lead_context_llm`](../backend/app/services/llm.py). Runs **even when the lead
already has an email** — context drives personalization, not contact.

> **Note:** the email finder and this step each fetch the lead's site separately
> (double fetch). Unifying them into one fetch is a known optimization (§6).

### Scoring — [`batch_score_leads`](../backend/app/services/lead_generation_service.py) (`:1742`)

A deterministic 0–100 score from field presence: email +40, website +30, phone +15,
address +10, industry +5. No LLM involved.

---

## 4. When enrichment runs — Celery background (already implemented)

Enrichment is **already off the request thread**. It does not block lead search.

```
Chat lead search (fast)                         chat_service.py:~1040
   │  save LeadLog + LeadLogLead rows
   │  enrichment_status = "done"  (DB leads, already enriched)
   │                     "processing" (Overture/Google leads)
   │  return reply to user immediately
   └─ enrich_leads_task.delay(log.id)           chat_service.py:1084  (Celery)
            ▼
   enrich_leads_task                            tasks/enrich_leads.py:8
            │  fresh engine + event loop per task; autoretry up to 3×
            ▼
   enrich_leads_background(lead_log_id)         lead_generation_service.py:1769
            │  fetch "processing" leads
            │  enrich emails CONCURRENTLY (asyncio.as_completed + semaphores)
            │  score each lead
            │  COMMIT IN BATCHES as leads finish  ← progressive fill-in
            │  deduct credits for Hunter hits
            ▼
   UI polls enrichment_status → rows fill in as each batch commits
```

Overture cold-loads enqueue the same task after warming an area
([`overture_tasks.py:78`](../backend/app/tasks/overture_tasks.py)).

This matches the architecture doc's §4 (background generation) and §5 (progressive
review) — concurrency is bounded by [`EnrichmentSemaphores`](../backend/app/utils/enrichment_semaphores.py),
and commits happen per batch so the UI sees results before the whole job finishes.

---

## 5. Per-lead conditions

The rule is **degrade gracefully**, not "skip". The lead still gets scored even when
the email can't be found.

| Condition | Action | Where |
| --- | --- | --- |
| Has email already (Overture / DB) | Keep it; `email_source="overture"`; skip scrape | `:1707` |
| No `website` / `website == "N/A"` | `email = None`; still scored | `:1713` |
| Website scrape finds no business email | `email = None`, `hunter_data = None`; still scored | `:1726` |
| Scrape/Hunter raises | Swallow, `email = None`; still scored | `:1730` |
| Internal/private host | SSRF guard returns no email | `email_scraper.py` / `company_scraper_service.py` |
| Email found but unverifiable MX | Rejected by `has_mx_record` check | `email_scraper.py` |
| DB lead (`_from_db`) | `enrichment_status="done"`, not re-enriched | `chat_service.py:1064` |
| Task fails mid-run | Celery autoretry up to 3× (`countdown=15`) | `enrich_leads.py:8` |

`enrichment_status` is the per-lead progress signal the UI reads: `processing` →
`done` (set when the batch commits).

---

## 6. Gaps & known optimizations

Distinguish these from the implemented pipeline above.

1. **Consuming the context fields.** ✅ **Done (Step 2).** The Personalization
   Level Engine scores each lead's context, caps depth by plan tier, and feeds
   resolved profiles into AI draft generation. Email generation still produces one
   campaign template with merge fields today; **per-lead unique generation** is Step 4.
2. **Lead-website caching / dedup.** Overture *areas* are cached in PostGIS, but the
   per-lead fetch is **not** cached or deduped by domain — the same domain can be
   scraped across campaigns. Architecture doc §1 applies here. (Now the single biggest
   remaining network win, since the double fetch is already eliminated.)
3. **Provenance — `email_source` is computed but not persisted.** During enrichment we
   set `email_source` (`overture` / `hunter` / `hunter_company_enrichment` / `static`) and
   use it for the `[ENRICH]` log counts and credit accounting — but it is **not stored**
   (no column on `LeadLogLead` / `Lead`). After a run it's gone; you can only *infer*
   Hunter-vs-scraped from whether `hunter_data` is non-null. **Lead source**, by contrast,
   *is* tracked — Overture-origin places carry `source='overture'` on the `overture_places`
   table (indexed) — though that lives on the Overture cache table, not on the per-search
   lead row, and Google Places results aren't persisted to a comparable source-tagged
   table. Add an `email_source` column (and optionally a lead `source` column on the lead
   row) only if email/lead provenance needs to be queryable later. Per-field provenance for
   the *context* fields is likewise not recorded.
4. **Richer status taxonomy.** Today it's effectively `processing` → `done`. No
   `partial` / `failed` distinction (e.g. "scored but no email/context" vs. "scrape
   errored") to flag thin leads in the review UI.
5. **Hard-WAF / JS-only sites — Perplexity is the planned last fallback.** The shared
   fetch sends full browser-like headers (User-Agent + Accept/Accept-Language), so sites
   that 403 a default client are recovered for both email and context. What remains is a
   small tail: **strong-WAF sites** (403 even with browser headers) and **pure JS-rendered
   sites** (empty static HTML). Playwright was rejected as too heavy. The agreed plan is a
   lightweight **Perplexity API fallback** (name + location → description) as the *last*
   step of the waterfall — `scrape → Perplexity → None`. It also covers no-website leads.
   **Deferred** as a Step 1 coverage improvement — the engine is live and Scale plan
   is flagged for external research when this lands.

### The floor: leads with no discoverable context (even after Perplexity)

Some leads will stay empty no matter what: businesses Perplexity has no knowledge of,
dead entities, or ambiguous generic names it can't disambiguate. There is no "next
scraping trick" for these — if neither the web nor Perplexity knows the business, the
data does not exist. The answer is **graceful degradation by tier, never fabrication**:

1. **Use what we always have.** Every lead still has `business_name`, `industry`,
   `location`, and often an Overture/Places category — enough for a valid (if generic)
   mail-merge email. The email still sends; it's just not deeply personalized.
2. **Personalize from the sender's profile instead of the lead's.** When lead context is
   absent, lean on the sender's `Company` profile (what *they* offer) rather than the
   prospect's. The Personalization Engine owns this fallback.
3. **Flag as thin-context and downgrade the tier.** Mark these leads (`partial` — see
   gap #4) so the engine uses a lower personalization tier (softer, more general copy)
   and the compliance layer can review them harder.
4. **Never invent, optionally let the user skip.** Do not have the LLM guess a
   description (the "do not invent" rule). For the genuinely contentless tail, surface
   them in the review UI so the user can skip or exclude them from high-tier campaigns.

In short: depth of personalization scales with the context we actually have — full
context → deep personalization; thin/none → generic sender-profile email, flagged and
lightly reviewed. This is precisely the job of the **Personalization Engine**.

---

## 7. Reference map (verified file locations)

| Concern | File |
| --- | --- |
| Lead search + enrichment orchestration | [`lead_generation_service.py`](../backend/app/services/lead_generation_service.py) |
| Celery enrichment task | [`tasks/enrich_leads.py`](../backend/app/tasks/enrich_leads.py) |
| Enqueue point | [`chat_service.py:1084`](../backend/app/services/chat_service.py) |
| Per-lead email scrape (Hunter + page) | [`utils/email_scraper.py`](../backend/app/utils/email_scraper.py) |
| Per-lead context scrape + extract (async) | [`company_scraper_service.py`](../backend/app/services/company_scraper_service.py) (`scrape_lead_text_async`, `extract_lead_context`, `collect_lead_context`) |
| Fast extraction model | [`services/llm.py`](../backend/app/services/llm.py) (`get_lead_context_llm`) |
| Company profile scraper (sender's site) | [`company_scraper_service.py`](../backend/app/services/company_scraper_service.py) · [`company_scraper_worker.py`](../backend/app/services/company_scraper_worker.py) |
| Lead row model | [`models/lead_log_lead.py`](../backend/app/models/lead_log_lead.py) |
| Company profile model (rich context) | [`models/company.py`](../backend/app/models/company.py) |
| Concurrency limits | [`utils/enrichment_semaphores.py`](../backend/app/utils/enrichment_semaphores.py) |
| Overture cold-load task | [`tasks/overture_tasks.py`](../backend/app/tasks/overture_tasks.py) |
| Personalization Level Engine (Step 2) | [`personalization-engine.md`](personalization-engine.md) · [`core/personalization.py`](../backend/app/core/personalization.py) · [`services/personalization_service.py`](../backend/app/services/personalization_service.py) |
