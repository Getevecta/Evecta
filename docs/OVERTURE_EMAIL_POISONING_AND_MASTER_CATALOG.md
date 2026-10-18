# Overture Email Poisoning → Master-Catalog Fix

> **Status:** Built **and verified live**. The end-to-end path ran on real data — warm
> Kathmandu search (0 off-topic, 62% emails) and a fresh **Pokhara cold-load** (500 leads,
> 0 off-topic, 100% in-city), plus a real **top-up** pull (+1,777 places from S3). Remaining
> is frontend polish + housekeeping.
> **Done:** Phases 1–4 (master catalog) ✅, §4.1 single reuse source ✅, §5.8 campaign
> timing gate ✅, §6.5.1 GEO-1–4 ✅, and the live-search hardening: §6.7 category precision ✅,
> §6.8 email dedup ✅, §6.9 contactable-only (phone-inclusive) ✅, §6.10 exclude-seen on
> `promoted` ✅, §6.11 exhaustion top-up ✅, §6.12 strict "only" intent ✅, §6.13 search UX +
> manual import ✅.
> **Migrations:** `07dc3dc813d9` (enrichment/provenance cols) · `3afb056c9a5c`
> (`leads.overture_id`) · `0c3c54e50e8d` (`overture_places.locality`) · `da85a3f499e9`
> (`overture_loaded_areas.has_more`).
> **DB (local dev):** Kathmandu (`place_count=2500`, `has_more=true`) + Pokhara
> (`place_count=758`, `has_more=false`) cached; categories/users/credits kept.
>
> ⚠️ **Root-cause correction:** the original premise below (that `overture_places` held
> NULL emails) was **disproved by measurement** — the master was healthy (67% emails).
> The real bug was purely **Tier-1 serving stale `lead_log_leads`**, which §4.1 removed.
> See **§1.8**. The fix is right; the early "poisoned catalog" framing is not. The
> investigation narrative in §1 is kept as the record, annotated.
>
> This documents the bug, why it would recur, and the permanent structural fix (make
> `overture_places` the master; `lead_log_leads` a prunable log that references it),
> extending the "business-master + prunable log" section of
> [OVERTURE_LEAD_GENERATION.md](OVERTURE_LEAD_GENERATION.md) with the concrete column
> design and a provenance model.

---

## TL;DR

- **Symptom:** "Restaurants in Kathmandu" returned **497 leads but only ~25 emails (~5%)**.
- **Not thin data — a real bug.** Overture actually has emails for **57.8%** of Kathmandu
  restaurants (measured). The emails are being lost in the pipeline.
- **Root cause (CORRECTED — see §1.8):** **Tier-1 reuse served stale `lead_log_leads`**
  (NULL-email snapshots from an earlier period) and never reached Overture. The initial
  hypothesis — that `overture_places` itself was poisoned (NULL emails, §1.4) — was
  **disproved by measurement**: the master catalog was **healthy (67% restaurant emails)**.
  The poison lived only in the per-search log, served via Tier-1.
- **Why it self-perpetuated:** search reused `lead_log_leads` first (Tier 1). The stale rows
  satisfied the reuse filter, so every re-search reused them and never reached Overture.
- **Why it will recur:** the data is duplicated across per-search snapshots that drift from
  the source and are never re-validated. Any future schema/enrichment change repeats this.
- **Permanent fix:** one source of truth. `overture_places` becomes the master holding
  catalog **and** enrichment (incl. `scraped_email`, `email_source`, score, context).
  `lead_log_leads` keeps only search/session context and references the master by
  `overture_id`. A backfill/refresh of the master then fixes every past and future search,
  and poisoning becomes structurally impossible.

---

## 1. The problem

### 1.1 Symptom
A search for **"restaurants in Kathmandu"** produced **497 leads**, but filtering to
"Has Email" showed only **~25**. Expectation was "more than half" — Overture is known to
carry emails.

### 1.2 What we measured (Overture's actual data)
Queried the live Overture release (`2026-05-20.0`) over the Kathmandu bbox with the same
filters the app uses (`confidence >= 0.5`, not closed):

| Kathmandu (Overture) | Total | Has email | Has website | Has phone |
|---|---|---|---|---|
| **Restaurants** | 2,614 | **1,511 (57.8%)** | 766 (29.3%) | 2,311 (88.4%) |
| All categories | 35,086 | 24,180 (68.9%) | 18,818 (53.6%) | 30,525 (87.0%) |

So Overture **does** have the emails — more than half, as expected.

### 1.3 What we ruled out (these are NOT the bug)
- **Extraction is correct.** `emails` is `VARCHAR[]`; `emails[1]` cleanly returns the address
  (verified against real rows). See
  [lead_generation_service.py:505](../backend/app/services/lead_generation_service.py#L505)
  and the warm read at
  [:870](../backend/app/services/lead_generation_service.py#L870).
- **Both save paths carry the email** into `lead_log_leads`:
  - Cold fill: [overture_tasks.py:175](../backend/app/tasks/overture_tasks.py#L175)
    `"email": (lead.get("email") or None)`.
  - Warm/chat: [chat_service.py:1279](../backend/app/services/chat_service.py#L1279).
- **Enrichment is not the primary source of emails.** Overture is. Enrichment only fills
  gaps by scraping the website + Hunter.io, and it **requires a website** — see 1.5.

### 1.4 Root cause: the cache predates email support
Timeline from git + migrations:

| Order | Change | Email support? |
|---|---|---|
| `5cac3d5` — `402273ef66c0_overture_places_and_loaded_areas` | Overture cache goes live | ❌ no email column, no extraction |
| `e527474` — `f1bb27dc185e_overture_places_email_status_taxonomy` (**2026-06-16**) | adds `email` column **+** `emails[1]` extraction | ✅ but **no backfill** |

[`f1bb27dc185e`](../backend/alembic/versions/f1bb27dc185e_overture_places_email_status_taxonomy.py)
is a bare `op.add_column('overture_places', sa.Column('email', ...))` — **no data backfill.**

So **any area cold-loaded before 2026-06-16 has `email = NULL` for every row.** And because
that area is registered *warm* in `overture_loaded_areas`, the app **never re-pulls it** (a
warm area only re-loads on the 35-day TTL or the monthly refresh). Kathmandu was cached
pre-fix → Overture contributed **zero** emails → the only emails came from scraping the
~29% of restaurants that have a website → **~25**. The math matches the symptom exactly.

### 1.5 The compounding loss: website-less businesses
**920 Kathmandu restaurants have an Overture email but NO website.** Enrichment can *never*
recover those: `enrich_lead` returns early when there's no domain, and Hunter.io also needs a
domain. See
[lead_generation_service.py:1795-1810](../backend/app/services/lead_generation_service.py#L1795-L1810).
Overture's email is the **only** way to reach them — and right now we get none.

### 1.6 Why it self-perpetuates (Tier-1 reuse)
Search checks the DB (`lead_log_leads`) **first**:
- [chat_service.py:1034](../backend/app/services/chat_service.py#L1034) →
  `fetch_leads_from_db(...)`
- [:1212](../backend/app/services/chat_service.py#L1212) — *"DB has enough leads … skipping
  Google Places API."*
- The reuse filter ([:159-169](../backend/app/services/chat_service.py#L159-L169)) matches
  `enrichment_status = 'done'` + `chat_title ILIKE industry` + `ILIKE city`.

The 497 stale rows satisfy all three, so **re-running the search reuses them and never reaches
Overture.** The bad data is self-serving.

### 1.7 Three layers of stale data *(as originally hypothesized — see the §1.8 correction)*
| Layer | Hypothesized problem | Verified reality (§1.8) |
|---|---|---|
| `overture_places` | `email = NULL` (cached before the column) | ❌ **wrong — healthy, 67% emails** |
| `lead_log_leads` | `email = NULL` + feeds Tier-1 → poisons new searches | ✅ **this was the actual bug** |
| `leads` (promoted) | `email = NULL` in the Lead Database (independent copy) | inherited from the log; cleared on reset |

### 1.8 Correction — what the live data actually showed
When the diagnostic was run against the **live DB** (not just inferred from the migration
date), `overture_places` was **not** poisoned:

- **Email coverage per load date: 40–66%**; **restaurants specifically: 48% overall, 67% for
  the nearest 100** — the affected areas were loaded *after* the email column (release
  `2026-06-17.0`), so they *had* emails. The §1.4 "cache predates email support" inference was
  wrong for the real data.
- **The ~5% the user saw came from Tier-1 serving old NULL-email `lead_log_leads`** (saved in
  an earlier period), not from `overture_places`. That is exactly the self-perpetuation in
  §1.6/§2, and exactly what **§4.1 (remove Tier-1)** fixes.
- **Address reliability (measured):** Overture addresses carry the city name **90–99%**
  (Kathmandu 97%, Lalitpur 91%, Pokhara 99%) — validates the `address LIKE '%city%'` city tier
  and the GEO-1 spillover cap.

**Net:** the master-catalog refactor is the correct fix (it removes the Tier-1 duplication and
makes `overture_places` the single source), but the bug was a **stale-log-served-by-Tier-1**
problem, not a **poisoned-catalog** problem. Everything §2 onward still stands.

---

## 2. Why it will recur (the structural cause)

Poisoning needs **two conditions**, both currently true:

1. **A second authoritative copy of the data exists that can drift.** `lead_log_leads` carries
   its **own** copy of `email` / `score` / `context`, frozen at write time.
2. **Tier-1 serves that copy without re-validating against the source.** `enrichment_status =
   'done'` is treated as good forever.

Whenever the source improves (Overture publishes emails, a column is added + backfilled, a
scraper bug is fixed), the frozen copies don't get it — and the frozen copies are what's
served. **Any future schema/enrichment change repeats this bug.** Fixing the data once does
not prevent recurrence; only removing a condition does.

Fix-surface comparison:
- **Today:** stale data is copied across *N searches* × *M rows*, each copy self-perpetuating →
  O(searches) fix surface that fights back.
- **After the master fix:** one row per business → O(1) fix surface, and it's what's served.

---

## 3. The permanent solution: one source of truth

Break condition #1 — **stop storing contact/enrichment data on the per-search snapshot.**
Make `overture_places` the single **master** holding *everything* (Overture catalog **and**
enrichment), and make `lead_log_leads` a thin **log** that references the master by
`overture_id` instead of copying its fields.

> There is only **one** place `email` lives. Searches read it live (join by `overture_id`).
> A refresh or a one-line backfill of the master instantly fixes **every past and future
> search** — because there's no second copy left to go stale. Poisoning becomes
> structurally impossible, and a future column addition self-heals (single backfill, served
> live).

This is the "business-master + prunable log" phase already sketched in
[OVERTURE_LEAD_GENERATION.md](OVERTURE_LEAD_GENERATION.md); this doc pins the columns.

### Clean separation of concerns
- **`overture_places` = business truth** (catalog + enrichment). One row per business.
  Deduplicated, PostGIS-fast, refreshed monthly, backfillable in one `UPDATE`.
- **`lead_log_leads` = search/session context** (which businesses appeared in which search,
  `promoted`, timestamps). References the master by `overture_id`; holds **no** copy of
  contact/enrichment data. Prunable on a TTL.
- **`leads` = the user's owned copy** (Lead Database). User-editable; seeded from the master.

---

## 4. Column design

### 4.1 Field mapping — where each `lead_log_leads` column belongs
Not every column moves. Fields describing "this business in *this* search for *this* user"
must stay on the log.

| `lead_log_leads` column | Destination | Why |
|---|---|---|
| `id` | **log only** | log row PK |
| `business_name` | master `name` — ✅ exists | business identity |
| `contact_number` | master `phone` — ✅ exists | business identity |
| `address` | master — ✅ exists | business identity |
| `website` | master — ✅ exists | business identity |
| `email` | master `email` — ✅ exists | Overture-provided email |
| `lead_score` | **➕ master** | derived per business |
| `enrichment_status` | **➕ master** | "has this business been enriched?" |
| `hunter_data` (jsonb) | **➕ master** | enrichment output, per business |
| `services` (text) | **➕ master** | scraped from site, per business |
| `website_summary` (text) | **➕ master** | per business |
| `business_description` (text) | **➕ master** | per business |
| `industry` | **log only** | the *search's* canonical label; master has `categories`/`taxonomy` |
| `lead_log_id` | **log only** | which search this row belonged to |
| `promoted` | **log/user only** | a **per-user** action ⚠️ (see 4.2) |
| `created_at` / `updated_at` | **log only** | when *this* search row was written |

### 4.2 Why `promoted` must NOT move to the master
`promoted` means *this user* saved *this business* to *their* Lead Database — a property of
the **(user, business)** pair, not the business. If it lived on the master, one user promoting
a business would show it promoted for **every** user. Same reasoning keeps `lead_log_id` and
the search-specific `industry` label on the log.

### 4.3 New enrichment columns on `overture_places`
```
scraped_email          String(320)     -- enrichment email (scraper OR hunter OR future)
email_source           String(20)      -- provenance of the email (see 4.5)
lead_score             Integer
enrichment_status      String(20)      -- pending | processing | done | failed
enriched_at            DateTime(tz)
hunter_data            JSONB
services               Text
website_summary        Text
business_description    Text
```
Everything else the master already has
([overture_place.py](../backend/app/models/overture_place.py)). 

### 4.4 New link column on `lead_log_leads`
```
overture_id            String(64), nullable, index   -- FK-style link to the master
```
Google/manual leads keep `overture_id = NULL` and fall back to the current snapshot path.

### 4.5 Provenance: two orthogonal source labels
Two **independent** dimensions — every combination is valid (Overture lead + Hunter email,
Google lead + scraped email), so they can't share a column.

| Dimension | Column | Question | Values (open-ended) |
|---|---|---|---|
| **Lead origin** | `source` (✅ already on master, `String(20)`) | Where did the *business* come from? | `overture` · `google_places` · `scraped` · `manual` · … |
| **Email provenance** | `email_source` (➕ add) | How did we get the *email*? | `overture` · `scraper` · `hunter` · `manual` · … |

**Already produced, currently discarded:** `email_source` is computed today in enrichment
([lead_generation_service.py:1779](../backend/app/services/lead_generation_service.py#L1779),
:1802, :1821 → `"overture"`, `"scraper"`, `"hunter"`) but is only read once for credit math
at [:2010](../backend/app/services/lead_generation_service.py#L2010) and **never persisted.**
This change just keeps it.

**Keep these as `String`, not a Postgres `ENUM`.** Adding a new provider must be free — a new
string value (`email_source = 'apollo'`), **not** an `ALTER TYPE … ADD VALUE` migration. The
existing `source` column is already `String(20)` for this reason.

### 4.6 The email split & serving (refresh safety)
Two email columns, one label — they answer different questions and must stay separate:

- **`email`** = Overture's raw provided email. The **monthly refresh owns** this column.
- **`scraped_email`** = whatever enrichment found (scraper / Hunter / future). The refresh
  **never** touches this.
- **`email_source`** = which method produced the served email. **Not redundant** with the two
  columns: `scraped_email` alone can't say whether it came from the scraper or Hunter — the
  label disambiguates within it, and lets you trust/weight sources.

**Serve:** `COALESCE(scraped_email, email)` (enrichment wins over raw Overture), with
`email_source` recording how it was found.

---

## 5. Enrichment flow (before → after)

The three context columns (`services`, `website_summary`, `business_description`) — **plus the
scraped email** — are produced by the background enrichment job, which scrapes a lead's website
in a **single fetch shared by email-finding and context extraction** (no double scrape) —
[enrich_lead](../backend/app/services/lead_generation_service.py#L1786-L1796). The refactor
changes *when* that job runs and *where* it saves: from **per-search** to **per-business**.

### 5.1 Today — enrichment is per-SEARCH, saved to `lead_log_leads`
1. Search saves leads into `lead_log_leads` with `enrichment_status = 'processing'`.
2. `enrich_leads_background(lead_log_id)` is triggered **per search**, keyed by that
   `lead_log_id`, and iterates *that search's* rows
   ([:1937](../backend/app/services/lead_generation_service.py#L1937); filter
   `enrichment_status == 'processing'` at
   [:1964](../backend/app/services/lead_generation_service.py#L1964)).
3. Each row with a website → fetch the site **once** → extract email + the 3 context fields →
   write them back to **`lead_log_leads`** (`_persist_enriched_lead`).

→ The same restaurant appearing in 5 searches is scraped **5×** and stored 5× (one row each),
unless Tier-1 reuse happens to catch it.

### 5.2 After — enrichment is per-BUSINESS, saved to the master
The **trigger stays the same** (fired after a search), but the *unit of work* and *storage*
change:
1. Search saves `lead_log_leads` rows that now carry `overture_id`.
2. The job takes the distinct `overture_id`s from that search and **checks the master first**:
   - **already `enrichment_status = 'done'` on `overture_places`** → **skip; no website
     fetch.** The read path already serves the context/email from the master.
   - **not yet enriched** → fetch the site **once**, write `scraped_email`, `email_source`,
     and the 3 context fields onto the **master row** by `overture_id`; set
     `enriched_at`/`enrichment_status`.

→ Each business is scraped **once, ever** — the first time any user's search surfaces it. Every
later search (any user) reuses the master with **zero re-scraping**.

### 5.3 Behavior by website presence
| Scenario | Today | After |
|---|---|---|
| Business **with website**, first time seen | scrape → store context on `lead_log_leads` | scrape once → store context on **master** |
| Same business, later search (same/other user) | re-scrape (unless Tier-1 reuse) | **no scrape** — served from master |
| Business **without website** | early return, context `NULL`; retried every search | early return, `enrichment_status='done'` on master → **not retried**; Overture `email`/`phone` still served |
| Storage of context | N copies (one per search row) | 1 copy (the master row) |

### 5.4 Where the job runs / saves (summary)
- **Triggered:** by a search, as today (keyed by `lead_log_id`) — least change to the trigger.
- **Works over:** the **businesses** (`overture_id`) in that search, gated on the master's
  status → only not-yet-`done` businesses are scraped.
- **Saves to:** the **master** (`overture_places`), not `lead_log_leads`.
- `lead_log_leads` keeps **no** context copy; the read path joins the master by `overture_id`.
- **Google/manual leads** (no `overture_id`) keep the current per-log enrichment path.

### 5.5 Poll implication (frontend touch-point)
The frontend lead-gen poll reads `enrichment_status` off `lead_log_leads` to know when to stop
spinning. After this, "is this search's enrichment done?" becomes "are the master rows for this
search's `overture_id`s all `done`?" — a **join**, not a column read. Minor, but a real
touch-point to update when Phase 4 lands.

### 5.6 Edge case — website added later
If a later Overture refresh *adds* a website to a previously website-less (already-`done`)
business, we'd want to re-enrich it. Handle by comparing `enriched_at` to the refresh time (or
re-opening enrichment when `website` changes from NULL → non-NULL). Follow-up, not v1.

### 5.7 Intermediate state — Overture email present, enrichment pending
This is the **default state of every freshly cold-loaded business**: Overture's fields are set
(often incl. `email`), but the enrichment columns are still empty. It defines the serving
semantics, so it's called out explicitly.

**The row in this state:**

| Column | Value | Filled by |
|---|---|---|
| `name`, `phone`, `address`, `website` | ✅ Overture | cold-load |
| `email` | ✅ Overture's email (when present) | cold-load |
| `email_source` | `'overture'` when an Overture email was written (see rule) | cold-load |
| `scraped_email` | `NULL` | enrichment |
| `services`, `website_summary`, `business_description` | `NULL` | enrichment |
| `lead_score` | pre-scored, or `0` until enrichment (see §5.7 choice) | cold-load or enrichment |
| `enriched_at` | `NULL` | enrichment |
| `enrichment_status` | `pending` (or `NULL`) | cold-load |

**Behavior — the email is usable immediately.** The read path serves
`COALESCE(scraped_email, email)`; with `scraped_email` NULL it serves **Overture's `email`
right away**, before enrichment runs. Only the context fields and (optionally) the score are
pending. *This is the fix delivering value instantly* — the poisoning symptom disappears the
moment the cache is correct.

**`email_source` rule (set at cold-load).** When cold-load writes a non-null Overture `email`,
it also sets `email_source = 'overture'`, so provenance is correct **before** enrichment. This
stays consistent because the two email columns are **mutually exclusive in practice**: if
Overture supplied an email, enrichment *skips* email-finding (below), so `scraped_email` stays
NULL and `email_source = 'overture'` remains right. If Overture supplied no email,
`email_source` stays NULL at cold-load and enrichment sets it to `scraper`/`hunter` alongside
`scraped_email`.

**Enrichment still runs — but only does context for this business.** `enrichment_status !=
'done'` → the business is eligible, so the scrape job picks it up. But `enrich_lead` **skips
email-finding when an email already exists**
([:1772-1780](../backend/app/services/lead_generation_service.py#L1772-L1780) —
`if has_email: … 'overture'`). So for an Overture-email business it: keeps Overture's email
(no re-scrape, no Hunter call — a cost saving), fetches the site **once** for **context** only,
computes the score, then sets `enriched_at` / `enrichment_status = 'done'`.

**Sub-case: Overture email + NO website** (the 920-restaurant population): `email` served
(source `overture`); enrichment early-returns (no domain) → context stays `NULL` but the row is
marked `done` so it isn't retried each search; score still computes from email + phone +
address. → usable leads with an email but no context — exactly what was being lost before.

**`enrichment_status` state machine (defines the gate):**

| Status | Meaning | Enrichment gate |
|---|---|---|
| `pending` / `NULL` | cold-loaded, never enriched | **eligible** |
| `processing` | scrape in flight | skip (no duplicate) |
| `done` | enriched (or attempted, no site) | skip |
| `failed` | scrape errored | retry-eligible (optionally capped) |

**Choice — score at cold-load or at enrichment?** `batch_score_leads` scores from
`email`/`website`/`phone`/`address`/`industry`, all known at cold-load. Either **(a) pre-score
at cold-load** (real score instantly, enrichment refines) or **(b) score only at enrichment**
(`lead_score = 0` in the pending window). **Recommend (a)** — inputs are free at cold-load and
it avoids a "0-score" flicker.

### 5.8 Campaign launch before enrichment completes (the timing race)

**The scenario.** A user generates 500 leads, immediately saves/selects them, creates a
campaign, and launches — while the background scrape of the 3 context fields is **still
running**. Scraping 500 sites takes time; some leads won't be enriched yet at launch.

**Why it hurts today (unmitigated).**
- Context is **snapshotted** into `campaign_leads` "at sync time"
  ([campaign_lead.py:26-29](../backend/app/models/campaign_lead.py#L26-L29)). Adding leads
  before enrichment finishes captures **NULL** context.
- Email generation reads **live lead first, then the snapshot**
  ([personalization_service.py:62-67](../backend/app/services/personalization_service.py#L62-L67)).
  It recovers *if* the live lead got enriched by generation time — but if generation runs
  **before** that lead's scrape finishes, both are NULL → a **generic email**.
- **Launch readiness does not check enrichment** — `get_campaign_launch_readiness` only checks
  review status
  ([campaign_launch_readiness_service.py:67](../backend/app/services/campaign_launch_readiness_service.py#L67)).
  Nothing stops a launch mid-scrape.

→ Whichever leads aren't scraped yet when their email is generated get an un-personalized
email. Silent quality loss, no error.

**The fix (plain terms): before writing each lead's email, check whether that lead's scraping
is done; only write it once its info is ready.** The right layer is **per-lead email
generation**, NOT the launch button.

For each lead, generation asks one question — is `enrichment_status = 'done'`?
- ✅ **done** → write the personalized email now (context ready, or genuinely none — see below).
- ⏳ **`pending`/`processing`** → **defer this one lead** (requeue with backoff, or trigger from
  an enrichment-complete event); retry until it's `done`, then write it.
- 🛑 **safety valve** → if it's still not done after a time cap (or permanently failed),
  write with whatever context exists (graceful degradation) so nothing hangs forever.

**Worked example — 500 leads, 300 done / 200 still scraping at launch:**
- *Without the fix:* all 500 written now → 200 come out generic.
- *With the fix:* the 300 done → written immediately; the 200 → held and written one-by-one as
  each finishes over the next minute or two → **all 500 personalized.**

**Why this is nicer than "wait for all 500":**
1. **Per-lead, not whole-batch** — each email is written the moment *its own* data is ready;
   fast leads go out immediately, only not-yet-ready ones wait.
2. **No-website leads never cause waiting** — they're marked `done` almost instantly (nothing
   to scrape), so their email is written right away with name/industry/location
   personalization. The wait **only** applies to leads that actually have a website worth
   scraping — exactly where waiting adds value. (Critical, given ~71% of Kathmandu restaurants
   have no website.)

**Secondary mitigations (stack with the gate):**
- **Show progress in launch readiness** — add "N of 500 leads still enriching" to
  `get_campaign_launch_readiness` so the user isn't surprised (soft signal, not a hard block).
- **Read context live from the master** at generation time (by `overture_id`) — always
  freshest, so the stale-snapshot problem disappears by construction.
- **Prioritize campaign-selected leads' enrichment** — bump them to the front of the queue
  when added to a campaign so they finish first.

**The master design shrinks this over time.** Because enrichment is per-business and cached on
the master (§5.2), any business seen in a prior search is already `done` → instant, no wait.
The cold wait only ever applies to never-before-seen businesses and disappears as the catalog
warms. Today (per-search re-scrape), every campaign pays the full scrape cost.

---

## 6. Build plan (phase-by-phase, file-by-file)

### 6.0 Scope decisions (locked)
- **Dev phase, no live users → no backfill.** Instead of the careful name-matched backfill,
  we **reset** stale data and let fresh searches repopulate under the new code (§6.6). The
  original "Phase 0 hotfix" (refresh + `--dry-run` backfill) is therefore **dropped.**
- **Overture-only for all new work.** The Google Places path is **dead-code fallback**, kept as
  a rare kill-switch. Leads without an `overture_id` (Google/manual) keep the **current**
  snapshot path unchanged — we preserve that branch, don't enhance it, don't delete it.
- **Execution is phase-by-phase** — review the migration/diff at each phase before proceeding.
- **Frontend is updated alongside** each phase that changes the API contract (handed off in
  chat). The read path keeps the existing field names so most of the frontend is untouched;
  new fields (`email_source`, launch "enriching" count) are additive.
- **Estimate:** ~6.5–8 backend dev-days (~9 with buffer). §5.8 is independent and may ship
  separately.

### 6.1 Phase 1 — Schema *(no API/frontend impact)* — ✅ DONE (migration `07dc3dc813d9`)
> Implemented as specced. Autogenerate also emitted **unrelated drift ops** that were
> hand-stripped: DROPs of the LangGraph checkpointer tables (outside SQLAlchemy metadata
> — must never be dropped) and an `ix_roles_name` unique flip. These will reappear in
> every future autogenerate until excluded via `include_object` in `alembic/env.py` —
> **hand-verify every future migration** for them.
**[overture_place.py](../backend/app/models/overture_place.py)** — add 9 columns to
`OverturePlace` (types matched to `lead_log_leads` for compatibility):

| Column | Type | Null | Note |
|---|---|---|---|
| `scraped_email` | `String(320)` | yes | enrichment email; **excluded from refresh** |
| `email_source` | `String(20)` | yes | `overture`/`scraper`/`hunter`/`manual` |
| `lead_score` | `Integer` | yes | |
| `enrichment_status` | `String(20)` | yes, **index** | `pending`/`processing`/`done`/`failed`; NULL = eligible |
| `enriched_at` | `DateTime(tz)` | yes | |
| `hunter_data` | `JSONB` | yes | matches `lead_log_leads.hunter_data` |
| `services` | `Text` | yes | |
| `website_summary` | `Text` | yes | |
| `business_description` | `Text` | yes | |

**[lead_log_lead.py](../backend/app/models/lead_log_lead.py)** — add `overture_id`
`String(64)`, nullable, **index** (NULL = non-Overture/Google fallback lead).

**Migration:** `alembic revision --autogenerate -m "master catalog: enrichment + provenance + lead_log_leads.overture_id"`,
hand-verify `JSONB`/indexes, `alembic upgrade head`. No `server_default` on
`enrichment_status` (cold-load sets it; NULL = eligible).

### 6.2 Phase 2 — Carry `overture_id` + source; set provenance/score at cold-load *(no API impact)* — ✅ DONE
> Implemented + verified against the dev DB (insert provenance, refresh-safety
> COALESCE rules, warm-query identity carry — all pass). Also added: Tier-1
> `fetch_leads_from_db` carries `overture_id` forward on reuse. Response boundary
> checked: chat returns only `log_id`/`lead_count`, and the poll serializes via the
> explicit `LeadLogLeadResponse` schema — `overture_id` cannot leak into the API.
- **[lead_generation_service.py](../backend/app/services/lead_generation_service.py)**
  - `_query_overture_warm` ([:870](../backend/app/services/lead_generation_service.py#L870))
    currently selects `name, website, phone, address, email` and **drops `overture_id`** — add
    `overture_id` (and `source`); carry into the returned lead dicts.
  - `_persist_overture_rows` ([:582](../backend/app/services/lead_generation_service.py#L582))
    — on cold-load set `enrichment_status = 'pending'`, `email_source = 'overture'` when an
    Overture email is written, and (chosen §5.7 option) pre-score `lead_score`.
- **Save paths** — add `overture_id` into the `lead_log_leads` insert rows:
  - warm/chat: [chat_service.py:1272-1291](../backend/app/services/chat_service.py#L1272-L1291)
  - cold-fill: [overture_tasks.py:170-186](../backend/app/tasks/overture_tasks.py#L170-L186)

### 6.3 Phase 3 — Enrichment writes back to the master *(no API impact)* ⚠️ concurrency — ✅ DONE
> Implemented + verified (hermetic integration test, all four paths): reuse-from-done
> master (no scrape), atomic claim (`UPDATE … WHERE status IS NULL/pending/failed
> RETURNING`) + write-back (`scraped_email` NOT set for Overture-provided emails),
> deferred/race path (other worker's claim untouched, log row degrades gracefully),
> legacy NULL-`overture_id` path unchanged. Crash safety: batch-failure handler
> resets THIS job's claimed-but-unfinished master rows to `failed` (retry-eligible).
> Note: `lead_log_leads` is still dual-written in this phase — thinned in Phase 4.
- **[lead_generation_service.py](../backend/app/services/lead_generation_service.py)**
  `enrich_leads_background` / `_persist_enriched_lead`
  ([:1825](../backend/app/services/lead_generation_service.py#L1825)) writes `scraped_email`,
  `email_source`, `lead_score`, `enrichment_status`, `enriched_at`, `hunter_data`, `services`,
  `website_summary`, `business_description` onto `overture_places` **by `overture_id`**.
- Add the **"already enriched?" skip** gating on `overture_places.enrichment_status`
  (per §5.7 state machine).
- **Concurrency:** two searches enriching the same business at once — guard with the existing
  per-area Redis lock pattern and/or an idempotent upsert; set `processing` before scraping.
- Leads without `overture_id` keep writing to `lead_log_leads` as today.

### 6.4 Phase 4 — Read switch + normalize the log *(API-compatible; frontend optional)* — ✅ DONE
> Implemented + verified, including the **anti-poisoning proof**: a `done` log row
> with a stale NULL email (the exact Kathmandu scenario) is ignored and the master's
> `scraped_email` + context are served instead.
>
> **Superseded by Phase 4.1 (below):** Phase 4 kept the log-based Tier-1 discovery
> (an outer join). 4.1 removed it entirely — reuse now hits `overture_places`
> directly, so the log is never read for reuse at all.

### 6.4.1 Phase 4.1 — Single reuse source: drop the Tier-1 `lead_log_leads` lookup — ✅ DONE
> **Why:** `overture_places` is now the master and is directly searchable, so the
> Tier-1 `fetch_leads_from_db` (`chat_title ILIKE '%…%'`, a growing seq-scan) was
> redundant *and* slower than the GIST-indexed spatial query. `lead_log_leads` stays
> as the per-search results record (written + displayed + prunable) but is **no
> longer read for reuse**.
>
> - **`chat_service._search_phase`:** removed the `db_leads = fetch_leads_from_db(...)`
>   pre-fill + "top up the remainder" logic; every search now goes straight through
>   `get_leads_overture` (warm spatial serve, or background cold-load). `fetch_leads_from_db`
>   **deleted** (dead imports `select`/`func`/`OverturePlace` cleaned up).
> - **`_query_overture_warm` now serves the FULL master record** — `scraped_email`,
>   `email_source`, `lead_score`, context, and an `_enriched` flag — so warm reuse
>   delivers the enrichment that Tier-1 used to (email = `COALESCE(scraped_email,
>   email)`). This is the key completeness fix: without it, removing Tier-1 would have
>   dropped enriched data from warm searches.
> - **Save path:** `_enriched` (warm master-`done`) leads save as `done` with their
>   scraped email/context and skip re-enrichment, exactly like the old `_from_db` reuse.
> - **Verified:** warm query serves scraped email + context for `done` businesses
>   (`_enriched=True`) and Overture base email for `pending` ones (`_enriched=False`).
> - **Anti-poisoning is now *stronger*:** the log is never consulted for reuse, so a
>   stale log row cannot influence a search at all.
> - **Accepted trade-offs:** legacy Google leads (no `overture_id`) are no longer a
>   reuse source; a TTL-expired/category-mismatched area does a fresh cold-load
>   instead of a text-match shortcut (correct, occasionally slower on first hit).
- **[chat_service.py](../backend/app/services/chat_service.py)** `fetch_leads_from_db`
  ([:134-210](../backend/app/services/chat_service.py#L134-L210)) reads from `overture_places`
  via `overture_id`, serving `COALESCE(scraped_email, email)`, deduped by `overture_id` (drops
  the slow `DISTINCT ON (business_name)`).
- **Keep the response field names** (`email`, `enrichment_status`, `services`,
  `website_summary`, `business_description`, `lead_score`) so the existing lead list + poll
  need no change; expose `email_source`/`source` **additively**.
- Leads with NULL `overture_id` keep the current snapshot path (Google fallback).
- `lead_log_leads` is now log-only (prune on a TTL later).
- **Frontend (alongside):** optional provenance badge from `email_source`; poll unchanged if
  `enrichment_status` stays in the response.

### 6.5 §5.8 — Campaign timing gate *(independent)* — ✅ DONE
> **Discovered during impl:** `leads` (source of campaign leads) had no `overture_id`,
> so there was no path from a campaign lead to the master. Added a **5th migration**
> (`3afb056c9a5c` — `leads.overture_id`, nullable/indexed) + carried it through
> `promote_lead_log_to_database`. This is additive and does NOT affect Excel import,
> campaign creation, or lead-selection (all use explicit field lists; verified).
>
> Implemented + verified (hermetic gate test, all paths pass):
> - **Gate** in `_process_sequential_leads` — before generating a lead's email,
>   `_await_business_enriched()` blocks until the master `enrichment_status` is terminal
>   (`done`/`failed`), bounded by a **shared per-generation budget**
>   (`ENRICHMENT_WAIT_MAX_SECONDS=180`, poll 5s). No-`overture_id`/no-row/already-done
>   leads return instantly; only still-enriching ones wait; a slow/unscrapeable site
>   can never hang the run (timeout → generate with available context). Verified: the
>   poll actually waits then returns when status flips to `done`.
> - **Readiness:** `get_campaign_launch_readiness` returns a non-blocking
>   `enriching: {count, total}` — soft signal, never a launch blocker.
> - **Context live-read: SUBSUMED by the gate** (not a separate change). Once the gate
>   confirms the master is `done`, the promoted `Lead` already carries the scraped
>   context (the Phase-3 enrichment job syncs it), so `lead_data_from_sources`'s
>   existing "prefer live lead" serves fresh context — no overlay needed. Kept the
>   risky generation loop change minimal.
> - **Frontend (your side):** show the `enriching` count on the launch screen.

### 6.5.1 Geographic precision + fresh leads (separate milestone) — fixes 1–3 ✅ DONE
> A distinct feature set from the master-catalog refactor, but it lives in the same
> `_query_overture_warm` + `get_leads_overture` + `_search_phase` (+ cold-fill task)
> chain. Implemented + verified (hermetic test, all paths pass).
>
> - **GEO-1 Spillover cap (`_query_overture_warm`).** A city search fills with
>   same-city rows first (address names the city), then allows neighbor-city rows only
>   up to `spillover_ratio` (default **0.2** → ≤20% of the batch), then **stops** — it
>   no longer pads the plan limit with other-city rows. Honest count over volume:
>   30 Kathmandu colleges → ~30 (+ ≤ floor(30×0.25)=7 nearby), never 30 + 470 padded.
>   Fallback: if **no** address matches the city (rare — addresses carry the city name
>   **90–99%**, measured), it returns nearest-first rather than empty.
> - **GEO-2 Anchor mode.** `city_for_tier` set (e.g. "colleges in Kathmandu") →
>   **Mode A** (city-dominant tier + spillover cap). `city_for_tier=None` (an anchor
>   like "near Shankhamul") → **Mode B** (pure nearest-first, tier relaxed) so nearby
>   cross-border leads surface. `_search_phase` sets `city_for_tier = None if anchor
>   else search_location`.
> - **GEO-3 Exclude already-seen.** When `user_id` is passed, a `NOT EXISTS` against
>   the user's prior `lead_log_leads` (by `overture_id`, scoped to the same
>   `industry`) drops businesses they already pulled → repeat searches return the
>   **next** fresh batch. `overture_id` is indexed, so it's cheap. (Also fixes the
>   credit-for-duplicates issue: repeat returns 0 new → 0 charged.)
>   **⚠️ SUPERSEDED 2026-07-23 — now keyed on `promoted`, see §6.10.**
> - **Radius is the geographic gate** (unchanged) — `ST_DWithin` only returns
>   businesses inside the circle; we do **not** widen the radius to pad. Neighbor leads
>   appear only when the fixed radius physically overlaps the neighbor.
> - Threaded through both the sync path (`_search_phase`) and the async cold-fill
>   (`load_and_fill_overture_task` → `_fill_overture_lead_log` → `get_leads_overture`),
>   so first-search (cold) and repeat (warm) behave identically.
>
> **GEO-4 (exhaustion UX) — ✅ v1 DONE** (verified hermetically). Built as specced below.
> Adds a `locality` column to `overture_places` (migration `0c3c54e50e8d`, populated at
> cold-load from Overture's `addresses[0].locality`) as the clean city key for counts.
> - **Detector** `_count_overture_matches` — same WHERE as the warm query, no
>   exclude-seen → distinguishes **exhausted** (`count>0`, user pulled them all) from
>   **empty** (`count==0`).
> - **Nearby** `_nearby_cities_with_counts` — GROUP BY `locality` over a wider radius
>   (search + `NEARBY_EXTRA_KM=15`), excludes the searched city, top 3 by count. Only
>   sees already-cached areas.
> - **No-nearby fallback:** when the nearby list is empty (nothing cached nearby),
>   the message is *"You've pulled all N {industry} in {city} — no new ones here or
>   nearby. Try a different industry or city."* (honest, no dead-end; no LLM call).
> - **`get_leads_overture`** returns `error_info["exhausted"/"total_available"/"nearby"]`
>   when a warm search yields nothing for the user.
> - **`_search_phase`** (both no-result branches) → `_exhaustion_response`: message +
>   `status:"exhausted"` + payload `{industry, city, see_my, nearby:[{city, available,
>   deliverable}]}`. **`deliverable = min(available, plan_limit)`** (plan-capped);
>   **`see_my` = raw total** (they own it — not capped). Verified: G4Near 200 →
>   deliverable 20 (free) / 200 (scale).
> - **Frontend contract:** render chips `[{city} · {deliverable}]` (or `deliverable of
>   available` for the upgrade-reveal) + `[See my {see_my}]`. `balance==0` still routes
>   to the existing out-of-credits path (upstream).
>
> **Existing data:** resolved by **truncating `overture_places` + `overture_loaded_areas`**
> (they were scattered global test data with `locality=NULL`). Fresh cold-loads now
> repopulate the catalog with `locality`/emails/enrichment correct from the start —
> no backfill needed. (A per-area `locality` backfill script exists if ever wanted for
> data you keep.)
>
> **Housekeeping surfaced:** `OVERTURE_RELEASE = "2026-05-20.0"` in `config.py` points
> to a **purged** Overture release (Overture keeps only recent releases). It's only a
> fallback — cold-load/refresh auto-detect the latest release — but bump it to a live
> release to avoid a dead default.
>
> **🔒 LOCKED DECISION — "See my N" re-access — ✅ backend DONE:**
> - **Redirect to the search history log, NOT re-render in the result page.** Tap
>   "See my N" → deep-link to the search where those leads were pulled. Chosen over
>   re-showing in the result page because the leads already live in that log (no
>   re-build, no re-charge risk, no "new vs old search" confusion). The result page is
>   for the *current* search; old leads belong in history.
> - **After redirect:** the user is on that search's results → normal actions: select →
>   **Save** (promote to Lead Database) or **Create Campaign**. Promote all or some;
>   already-saved leads dedup automatically.
> - **Built + verified:** `_recent_matching_log_id` (most-recent `LeadLog` by user +
>   industry + city via `chat_title`) → exhaustion payload now carries
>   `exhausted.log_id` (None if pruned). **Frontend:** deep-link "See my N" to that log.
> - **Nearby fresh-count (built + verified):** `_nearby_cities_with_counts` now applies
>   exclude-seen (`user_id` + `industry`), so `available` = fresh-for-this-user — a city
>   the user has fully pulled drops off the chips instead of promising owned leads
>   (verified 5 → 4 when one was already pulled).
> - **Interaction with the 3-month prune (future job):** the redirect works only within
>   the prune window (fine — exhaustion happens right after pulling; logs are fresh).
>   The durable home for leads is the **Lead Database (saved leads — never pruned)**;
>   the prune only cleans ephemeral search history. Side effect: pruning `lead_log_leads`
>   makes **exclude-seen "forget"** those leads → they reappear as new (re-chargeable) —
>   an acceptable "data refreshes after 3 months" behavior.
> - **`see_my` chip is NOT plan-capped** (the user already owns those leads).
>
> **Original spec (as built):**
>
> **v1:**
> 1. **Split the 0-lead case into two.** *Exhausted* = area has businesses for this
>    category but exclude-seen filtered them all out (`total > 0`, `new = 0`); detect
>    by running the warm query once **without** the exclude-seen filter (a count) and
>    comparing. *Empty* = `total = 0` → keep the existing no-results/`generate_suggestions`
>    path unchanged.
> 2. **Exhausted message:** *"You've pulled all N {industry} in {city} — no new ones
>    remaining."* plus:
>    - **"View them in your previous search"** → points to the user's PRIOR RESULTS
>      (search history), **NOT** the Lead Database (pulled ≠ saved). Backend returns
>      industry+city / matching `LeadLog` id as structured data; frontend renders the
>      link. This is the "I want my 30 back" path.
>    - **Nearby suggestions with counts** → query `overture_places` for the same
>      category just outside the current radius, group by city-in-address, exclude the
>      searched city, take the top few with counts. **Fallback** to the existing
>      `generate_suggestions` when nothing nearby is cached. User picks one → a normal
>      fresh search of that area, honestly labeled as that area (consent, not padding).
> 3. **Credits:** nothing to build — `new = 0` → `0` charged already.
>
> **Caveat:** the "Nearby (12)" counts only see areas already cold-loaded into
> `overture_places`; uncached neighbors fall back to generic city suggestions. Improves
> as more areas load.
>
> **v2 (deferred):** an explicit "include already-pulled" re-pull toggle, with credits
> charged on **new-count only** (re-showing owned leads charges 0). v1 relies on
> history for re-access.

### 6.6 Dev reset — ✅ DONE (local only)
> **What actually happened** (differs from the original plan — kept for the record):
> 1. The diagnostic (§1.8) showed **no reset was needed for correctness** — the catalog was
>    healthy and §4.1 already routes reads to it. The poisoning was code (Tier-1), not data.
> 2. Cleared the **lead + campaign cluster** for a clean local slate (`lead_logs`,
>    `lead_log_leads`, `leads`, `campaigns`, `campaign_leads`, `campaign_lead_emails`,
>    `email_jobs`, `email_activities`, `email_messages`, `email_threads`).
> 3. Then **truncated `overture_places` + `overture_loaded_areas`** — they were scattered
>    global *test* data with `locality = NULL`; wiping is cleaner than backfilling junk. Fresh
>    cold-loads now repopulate the catalog with `locality`/emails/enrichment correct from the
>    start. **Kept:** `overture_categories`/`_aliases` (learned intelligence), `users`, `credits`.
>
> **LOCAL ONLY.** On staging/prod you would **not** truncate — just deploy the code (§4.1 fixes
> the reuse path; the catalog was never actually poisoned). No data reset needed there.
>
> **Still pending:** one live end-to-end search. With the empty catalog it is now a **cold
> load**, exercising the whole fresh pipeline: cold-load → `locality` → enrichment write-back
> → warm reuse → exhaustion/nearby.

### 6.7 Category match precision — ✅ DONE *(2026-07-23, found by the live search)*

The first live end-to-end search ("restaurants in Kathmandu", 500 leads) proved the
email fix — **310/500 = 62% with an email**, against ~5% before. It also exposed that
**16% of the results were not restaurants**: `hotel` ×15, `educational_services` ×7,
`professional_services` ×7, `event_planning` ×3, `language_school` ×3, then a tail of
`police_department`, `embassy`, `bus_station`, `automotive_dealer`, `park`,
`clothing_store`… Two independent bugs, both **industry-wide**, not restaurant-specific.

#### Bug 1 — alternate categories weighed as heavily as the primary one
The match haystack flattened `categories.primary`, `categories.alternate`,
`taxonomy.primary` and `taxonomy.hierarchy` into one string. `categories.alternate` is
everything a business *also* does, so a bus stop with a momo counter scored **exactly**
as well as a restaurant.

Measured over the 74 explainable off-target rows: **57** matched only via the alternates
array, **12** more via an alternate `cafe`/`coffee_shop`, **3** on name, **2** on both —
taxonomy caused **0**. The name fallback, which an earlier analysis wrongly blamed,
accounted for 5 rows and **all 5 were genuine** restaurants Overture never categorised
(`waah restaurant & cafe`, `Syanko Multi Cuisine Restaurant`…).

#### Bug 2 — substring matching instead of token matching
Patterns were built as `%code%` and matched with `LIKE`. Overture codes are flat
snake_case, so `%bar%` reached `barber`, `bartender`, `barbecue_restaurant`, and `%pub%`
reached `public_school`, `public_toilet`, `notary_public`, `public_transportation`.

**26 of the 69 seeded aliases were affected** (161 bogus code↔taxonomy pairs): `bars` 26,
`retail` 18, `education` 15, `schools` 11, `spas` 10, plus `pet stores`→`carpet_store`,
`gyms`→`gymnastics_center`, `dentists`→`dentistry_schools`, `cafes`→`cafeteria`. Latent
until someone searched one of those industries. LLM-learned aliases would add more.

#### The rule (`_overture_match_sql`, one builder for both dialects)
```
if has_category:   primary/taxonomy TOKEN-matches a code
                   OR (category_primary IS NULL AND name LIKE keyword)   # rescue uncategorised
else:              name LIKE keyword                                      # long-tail, unchanged
```
Token matching normalises `_`→`|` on both sides: `|pizza|restaurant|` matches
`%|restaurant|%`; `|barber|` does not match `%|bar|%`.

**Single-token codes also match as a suffix or simple plural.** Anchoring both ends was
the first implementation and it was **too strict** — caught only because the fix was
re-checked against every seeded industry rather than restaurants alone. It silently
dropped **31 legitimate codes across 8 industries**:

| search code | would have lost |
|---|---|
| `spa` | **`spas`** — Overture's only spa code is the plural, so spa searches would have matched almost nothing |
| `store` | `bookstore`, `drugstore`, `superstore`, `used_bookstore`, `dairy_stores`, `handbag_stores`, … |
| `school` | `architecture_schools`, `business_schools`, `law_schools`, `preschool`, … (11) |
| `lawyer` | `appellate_practice_lawyers`, `civil_rights_lawyers` |
| `contractor` | `flooring_contractors`, `masonry_contractors` |
| `pub` | `gastropub` |

So `store` → `%store|%`, `%stores|%`, `%storees|%`. The trailing delimiter still has to
line up, so the suffix allowance does **not** reopen Bug 2: `%bar|%` clears `cocktail_bar`
and still rejects `barber`, `bartender`, `cabaret`; `%spa|%` rejects `art_space_rental`,
`coworking_space`, `spanish_restaurant`. Verified against all 2,117 taxonomy codes — the
other **51** substring matches stay dropped.

**Multi-token codes remain anchored at both ends**, which is what keeps `pet_store` from
reaching `carpet_store`.

> **`|`, not `_`.** `_` is a single-character wildcard in `LIKE`, so an
> underscore-delimited boundary check (`'_'||code||'_'`) silently matches *everything*.
> This bit the diagnostic query that first tried to measure Bug 2 and reported a false
> clean bill of health. `|` has no meaning in `LIKE` and needs no escaping.

Taxonomy ancestry is kept in the haystack — it is derived from the primary category, it
measured 0 false positives, and it is what correctly admits `steakhouse` (whose hierarchy
is `eat_and_drink → restaurant`) to a restaurant search.

#### Result (same catalog, re-run through the real code path)
| | before | after |
|---|---|---|
| rows returned | 500 | 500 |
| on-topic (food primary) | 360 | **496** |
| uncategorised, rescued by name | 5 | 4 |
| **off-topic** | **140** | **0** |
| with an email | 62% | 60% |

723 rows pass the strict rule against a 500 cap, so precision costs no volume here. In a
thinner city the cap simply is not filled — honest counts, no padding (§6.5.1).

**Files:** `_overture_match_sql` / `_overture_codes` / `_overture_token_haystack` /
`_overture_token_pattern` / `_pg_binder` / `_duckdb_binder` in
`app/services/lead_generation_service.py`, applied at all **four** call sites (direct
DuckDB pull, area cache-fill, `_query_overture_warm`, `_overture_match_params` — the last
feeding `_count_overture_matches` and `_nearby_cities_with_counts`, so exhaustion counts
and nearby-city chips promise only what would actually be served).
`resolve_overture_filter` and `overture_refresh_service._resolved_filter_from_category_key`
now also emit `category_codes`. Covered by `tests/unit/test_overture_match.py` (20 tests,
including the suffix/plural cases per industry).

**Coverage note.** Only restaurants could be verified at the *place* level — the local
catalog holds a single Kathmandu cold-load, so no other industry has cached places to
query. Other industries were checked against the real 2,117-row `overture_categories`
taxonomy (which is what surfaced the over-strict regression above) and by unit test. A
place-level check for a second industry needs a fresh cold load.

**Side benefit:** the cold-load cache no longer spends its row budget on junk — 132 of the
1,000 cached rows for this area were alternate-only matches.

#### Known gaps (deliberately not fixed here)
1. **`restaurant_supply_store`** — a shop selling restaurant equipment. `restaurant` is a
   genuine token, so it passes. Needs a denylist, not a matching change.
2. **Stem variants need alias data, not matching logic.** `dentist` still misses
   `general_dentistry`, `education` misses `educational_services`, `retail` misses
   `firework_retailer`, `cafe` misses `cafeteria` — the word stems genuinely differ.
   Prefix matching would fix them but reopens `bar`→`barber`, so the right layer is the
   alias table (`overture_category_aliases`), which already exists to map terms to codes
   and is LLM-learnable. Seed `dentistry`, `educational`, `retailer` there if those
   industries matter.
3. **Plural terms miss the name rescue.** `keyword_patterns` use the raw term, so
   `%restaurants%` matches no singular business name. Category matching is unaffected
   (aliases cover plurals); only *uncategorised* rows lose the rescue. Pre-existing.
4. **Overture's own mislabelling** is upstream and unfixable from our side.
5. **Long-tail industries stay loose** by design — with no category to match, name is the
   only signal; tightening it would return zero rows instead of imperfect ones.

### 6.8 One lead per email address — ✅ DONE *(2026-07-23)*

**Symptom.** A 500-lead search saved only **497** rows to `leads`, with no visible
explanation — the log said 500/500 promoted while the database held 497.

**Cause (not a bug — two stages disagreeing).** Overture lists each property as its own
place, but chains share one inbox:

| email | kept | dropped on save |
|---|---|---|
| `guestsupport.na@oyorooms.com` | OYO 370 Hotel Devdaha & Restaurant | Gangaur Regency Boutique Hotel |
| `kathmandu.marriott@marriott.com` | Edamame | Thamel Kitchen |
| `pizzacutternepal@gmail.com` | The Pizza Cutter | The Pizza Cutter Nagpokhari |

`promote_lead_log_to_database` skips a lead whose email is already claimed
(`lead_service.py` §96-100) and registers each address as it saves (§126), so the second
of each pair loses. It still marks the skipped row `promoted=True` so it is not retried —
which is why the log read 500/500. The API did report it
(*"497 lead(s) saved successfully. 3 duplicate(s) skipped."*).

**Fix — dedupe at SEARCH time instead.** `_query_overture_warm` now collapses same-email
places *before* the LIMIT, via `row_number() OVER (PARTITION BY email_key ORDER BY <the
same priority that orders the batch>)`, so the in-city, nearest one survives. Two
consequences:
1. A 500-lead plan delivers **500 usable leads**, not 500 rows minus duplicates — the
   freed slots are topped up from the pool.
2. Nothing appears in `lead_log_leads` that would silently vanish on save.

`OVERTURE_EMAIL_KEY` = `lower(nullif(trim(coalesce(scraped_email, email)), ''))`.
Places with no email are never collapsed into each other.

Counts use the matching `OVERTURE_DEDUPED_COUNT` =
`count(DISTINCT coalesce(<email key>, overture_id))` — one entry per address plus every
email-less row — so `_count_overture_matches` and the GEO-4 nearby-city chips promise
what would actually be delivered.

**Verified** on the Kathmandu catalog: 500 rows returned, **0 duplicate emails**, 500
distinct `overture_id`, 0 off-topic; available count 543 ≥ the 500 cap.

**Save-time dedup stays** as the safety net — enrichment runs *after* the search, so two
places can still converge on the same scraped address later.

**Known gap:** dedup is within-batch. A user who already holds `x@y.com` from an earlier
search can still pull a different business with that address, and the save step will skip
it as before. Closing that needs an anti-join against the user's `leads` plus an index on
`leads.email`.

### 6.9 Contactable-only serving — ✅ DONE *(2026-07-23)*

**Trigger.** A "restaurants in Kathmandu" search returned `Skin Care Nepal` (a skincare
clinic on Durbarmarg) and `हाम्रो लोकल प्रजाति कृषि तथा पशु फर्म` ("Our Local Species
Agriculture and Livestock Farm"). Both are filed by **Overture** under
`category_primary = cafe`, taxonomy `food_and_drink > casual_eatery > cafe`.

**Two faults had to line up, only one of them ours:**
1. **Overture's data is wrong.** Neither is a café. We read the primary category and
   trust it — §6.7's matcher behaved correctly.
2. **The query was widened.** `restaurants` resolves to `['restaurant']` alone, but the
   area was cached under `category_key = 'cafe|coffee|restaurant'` — the chat expanded
   the search into cafés/coffee shops, which is what made a `cafe`-tagged row eligible.
   With codes `['restaurant']` only, both records are excluded. **Decision: keep the
   expansion** — cafés are wanted when the query is loose. `strict_intent`
   (`only`/`just`/`exactly`/`exact`/`strict` in the industry or search terms) already
   narrows to the industry term alone; verified `industry='only restaurants'` →
   `['restaurant']`.

**Rejected lever — confidence.** Overture ships a per-place confidence and the instinct is
to raise `OVERTURE_MIN_CONFIDENCE` (0.5). It does not work: the livestock farm scores
**0.844**, *above* the average real café (0.783); Skin Care Nepal scores 0.671. A 0.8
threshold would keep the farm and discard 457 of 1,000 rows.

**What worked — contactability.** Serving requires `OVERTURE_CONTACTABLE`, applied in
`_query_overture_warm`, `_count_overture_matches` and `_nearby_cities_with_counts` so
counts and nearby chips stay consistent.

> **Revised 2026-07-24 — phone-only leads are now KEPT.** The first version required an
> email or a website, which dropped Skin Care Nepal and the farm (both phone-only) but also
> ~172 genuine phone-only restaurants the user can *call*. Product decision: a phone is a
> valid contact channel, so the rule is now
> `coalesce(scraped_email, email) IS NOT NULL OR website IS NOT NULL OR phone IS NOT NULL`
> — only rows with **no contact of any kind** are dropped. On the Kathmandu cache this took
> servable from 488 → 660. The cost is that phone-only mislabels (Skin Care Nepal, the farm)
> reappear — accepted as ~2 eyeball-able rows against 172 real leads. They can't be
> email-campaigned (no email), only called. Removing the mislabels needs the LLM
> name-vs-category check below.

| Kathmandu, same catalog | before | after |
|---|---|---|
| leads returned | 500 | **482** |
| with an email | 306 (60%) | **424 (88%)** |
| cafés/coffee shops kept | 131 | 120 |
| Skin Care Nepal / livestock farm | present | **gone** |

**Volume note (correcting an earlier estimate).** This was first sized at "671 available,
costs no volume". That figure counted the whole catalog *without* the category clause. The
real deduped, category-matched, contactable pool is **482** — below the 500 cap. So it does
cost rows; it buys ~118 more contactable businesses.

**Known limits.**
1. It does **not** detect mislabelling. A wrongly-categorised business that has an email
   still gets through. The real fix would be an LLM name-vs-category sanity check during
   enrichment ("is a business named *Skin Care Nepal* plausibly a café?"), which would
   catch these from the name alone — deferred as a per-lead LLM cost.
2. ~~Genuine phone-only businesses are dropped with the junk~~ — **resolved 2026-07-24**:
   phone-only leads are now kept (see the revision note above). `The Bar Stock Exchange`
   and the ~172 other real callable restaurants are back in.
3. Applied at **serve** time, not load time. The cold-load still caches non-contactable
   places (326 of 1,000 here), spending budget on rows that can never be served. Filtering
   at load would free that, at the cost of needing a re-load to change the policy.

### 6.10 Exclude-seen keys on `promoted`, not on "appeared once" — ✅ DONE *(2026-07-23)*

**Supersedes the GEO-3 rule in §6.5.1.**

**Symptom.** A repeat "restaurants in Kathmandu" search returned 140 leads, then 0, while
the user's Lead Database held only 156 — far fewer than the 488 available.

**Cause.** GEO-3 excluded every business that had ever *appeared* in one of the user's
searches. Across four searches, 656 rows had been returned but only **156 promoted**. The
other **500 were never saved** — yet they were permanently filtered out of every future
search, reachable only by digging up the old log.

**Rule now:** exclude only what the user actually **owns**.

```sql
AND NOT EXISTS (
    SELECT 1 FROM lead_log_leads ll JOIN lead_logs lg ON lg.id = ll.lead_log_id
    WHERE lg.user_id = :uid
      AND ll.overture_id = overture_places.overture_id
      AND ll.promoted IS TRUE          -- ← added
      AND lower(ll.industry) = lower(:industry)
)
```

Looking at a lead is not taking it. Only saving it removes it from rotation. Applied
identically in `_query_overture_warm` and `_nearby_cities_with_counts`.

**Verified:** fresh leads for the affected account went **0 → 334** (488 contactable minus
154 promoted-and-contactable), with the 500 unsaved leads back in rotation.

**⚠️ Consequence — credits.** §6.5.1 credited the old rule with "repeat returns 0 new → 0
charged". That protection is gone: a user who searches repeatedly without saving now gets
the same leads back and can be charged each time. If billing is per lead returned, it needs
its own guard (charge on promote, or de-duplicate charges by `overture_id` per user) rather
than relying on exclude-seen as a side effect.

**Note:** with §6.9 also applied to nearby counts, the GEO-4 chips for this area now return
empty — the neighbouring Lalitpur/Budhanilkantha/Katunje places have no email or website, so
none are contactable. Exhaustion there falls back to the generic "try another city or
industry" message instead of city chips.

### 6.11 Exhaustion top-up — pull the next batch when the cache runs dry — ✅ DONE *(2026-07-24)*

**The ceiling.** A cold-load pulls the nearest `OVERTURE_CACHE_PER_CATEGORY` (1,000) and
records the area as loaded for `OVERTURE_AREA_TTL_DAYS` (35). After that every search
serves warm from those 1,000 and **never returns to Overture** — even after the user has
drained them. Measured against S3 (release 2026-07-22.0): Kathmandu actually has **4,035**
restaurant/café places (3,657 contactable); we cached 1,000. "Exhausted" meant *cache
exhausted*, not Overture exhausted — ~3,000 real leads were unreachable.

**The fix — lazy, shared top-up.** When a user exhausts a cached area that still has more
upstream, pull the next nearest batch (`OVERTURE_TOPUP_BATCH` = 1,500) into the **shared**
`overture_places`. Because the cache is global, one user's top-up benefits everyone
searching that city — the next user warm-serves the new rows instantly.

**"Has more" without a count query.** `overture_loaded_areas.has_more` (new column,
default TRUE) is set on every pull to `len(rows) >= requested_limit` — hitting the cap
means Overture had at least that many, so probably more; a short pull means we got
everything and it flips FALSE. No extra S3 COUNT needed; it self-corrects.

**Flow (reuses the cold-load "gathering" machinery verbatim).**
1. `_query_overture_warm` returns 0 fresh for the user, but `_count_overture_matches` > 0
   → exhausted. `get_leads_overture` sets `error_info["overture_topup"]` from
   `_area_has_more(...)`.
2. `chat_service` — in a block mirroring the cold-load one — creates an empty
   `LeadLog(status="gathering")` and enqueues `load_and_fill_overture_task(..., topup=True)`,
   returning the "finding more" message + `log_id`. The frontend's existing poller shows
   the loader and renders when leads land — **zero frontend changes**.
3. The task threads `topup=True` → `_fill_overture_lead_log` → `get_leads_overture(topup=True)`
   → `topup_overture_area(...)`: under the area lock, re-pull nearest
   `place_count + 1,500`, upsert (dedups by `overture_id`, never clobbers enrichment),
   update `place_count` + `has_more`. Then the normal query + fill + enrichment runs.
4. If a top-up pass still returns 0 (upstream now truly exhausted), `has_more` is FALSE →
   no further top-up → the normal exhaustion message.

**Convergence (Kathmandu):** 1,000 → 2,500 → 4,000 → 4,035 (short pull → `has_more`
FALSE). Three top-ups drain the city. Enrichment runs per batch on the normal
serve-and-save path — no 4,000-at-once cost.

**Copy (no counts, no jargon — deliberate UX call):**
- top-up: *"You've gone through all the {industry} in {city} for now — let me find you some
  more. This takes about a minute, and new ones will show up here automatically."*
- exhausted (unified — one message, cities inline when known):
  *"That's all the {industry} we could find in {city} — you've reached the end. Try a
  different location (Lalitpur, Bhaktapur, Kirtipur) or industry to keep finding leads."*
  The parenthetical lists up to **3 real neighbouring cities**: cache-detected cities first
  (`_nearby_cities_with_counts`), then topped up by the existing LLM suggester
  (`_verified_city_suggestions`, reused from the no-results path) so a suggestion always
  appears even when only the searched city is cached. Names only, no counts, no chips
  (user decision 2026-07-24 — text only). `_fill_exhaustion_nearby` in `chat_service`
  builds it; the exhaustion reply makes one extra ~1s LLM call.
  **No-repeat:** the suggester's prompt reads the conversation history and skips cities the
  user has already searched or exhausted *for this industry*, so hopping city→city never
  loops back (Kathmandu→Lalitpur→ won't re-offer Kathmandu). History is industry-scoped, so
  exhausting restaurants in a city doesn't hide it for a different industry. When no fresh
  neighbour remains, the parenthetical simply drops and the message points at a new industry.

**Files:** `config.py` (`OVERTURE_TOPUP_BATCH`), `models/overture_place.py` (`has_more`),
migration `da85a3f499e9`, `lead_generation_service.py`
(`topup_overture_area` / `_area_has_more` / `_covering_loaded_area` / `_load_bbox_and_key`,
`ensure_overture_area_loaded` sets `has_more`, `get_leads_overture` gains `topup` +
the `overture_topup` signal), `overture_tasks.py` (`topup` threaded through),
`chat_service.py` (the top-up gathering branch + reworded `_exhaustion_response`).

**Known limits / follow-ups.**
- **Re-pull, not delta.** v1 re-pulls nearest-N (including cached) and lets the upsert
  dedup. Simple + enrichment-safe, but each successive top-up re-scans more. Bounded by
  city size; excluding cached `overture_id`s is the future optimisation.
- **Credits.** Top-up leads cost 1 credit each on save, same as any lead — a heavy user can
  surface thousands over time. Consistent with §6.10's note that billing should key on
  *save*, not *search*.
- **Restart required** — worker + API — for any of this to run.

### 6.12 Strict "only" intent actually reaches the resolver — ✅ DONE *(2026-07-26)*

**Symptom.** `only restaurants in pokhara` returned 44 cafés/coffee shops — strict intent
did nothing, even though the resolver's `strict_intent` path works in isolation.

**Cause.** The understand LLM **strips the "only" marker** and, worse, *expands* the query:
`message='only restaurants in pokhara'` → `industry='restaurants'`,
`search_terms=['restaurant', 'cafe', 'eatery']` (from `server.log`). By the time
`resolve_overture_categories` runs, no term contains "only", so
`_is_strict_overture_intent` returns False and `cafe`/`coffee` resolve normally.

**Fix.** Capture the marker from the **raw message** in `chat_service` (the tokens are
already computed there as `_strict_narrow`), persist it as `context['strict_intent']` on
the same condition that (re)computes `search_terms` — so it survives the confirm `go` turn
but clears on a new search — and in `_search_phase` narrow `search_terms = [industry_key]`
when set. The resolver then sees only the industry → `category_codes = ['restaurant']`.

Verified: `resolve_overture_categories('restaurants', ['restaurants'])` → `['restaurant']`
(key `restaurant`) vs the loose `['restaurant','cafe','coffee']` (key `cafe|coffee|restaurant`).

**Tradeoff (accepted).** Strict changes the `category_key` (`restaurant` ≠
`cafe|coffee|restaurant`), so a strict search **cold-loads its own narrower cache** the
first time even if the mixed area is already loaded, then serves warm. Correct results,
one extra load. A subset-aware coverage check (search codes ⊆ cached area codes → warm)
would avoid it — noted as a future optimisation.

---

### 6.13 Search UX fixes + manual import — ✅ DONE *(2026-07-26)*

Smaller fixes found while testing live, grouped here.

**Anchor reflected in reply + title.** A "restaurants near Lakeside, Pokhara" search
resolved correctly (Mode B, centred on Lakeside — verified: results 0.06–0.13 km from the
lakeside strip) but the **confirm reply** and the **lead-log title** both dropped the
anchor and said just "Pokhara". Fixes: `build_confirm_message` now includes the anchor even
when no radius is given; `build_chat_title` gained an `anchor` param and all three callers
pass `context["anchor"]`. Both now read "Restaurants near Lakeside, Pokhara".

**Paginated lists dropped rows (490 shown as 356).** A whole save-batch shares one
`created_at`; the leads list ordered by `created_at` alone, so tied rows came back in a
different order per page → offset/limit **repeated some rows and skipped others**, and the
frontend's per-id dedup collapsed the repeats (490 real → 356 shown). Fix: a unique
tiebreaker — `Lead.id` in `lead_service.get_all_leads`, and `Campaign.id` in
`campaign_service` (same latent bug). Deterministic pagination; verified 490 → 490.

**Search history showed "No sessions found."** `get_lead_logs` validated each row with no
per-row guard, so one malformed row (a NULL-`promoted` test log I'd inserted) 500'd the whole
list. Fixed the **data** (deleted the test logs); the endpoint **hardening** (mirror the
sibling's per-row try/except) is offered in §9, not yet applied.

**Manual import into `overture_places`.** Format for importing leads from another source
(template: [leads_import_template.csv](../backend/leads_import_template.csv)):
- **Required:** `overture_id` (unique, prefix `manual:` so it never collides with Overture),
  `name`, `lat`, `lng`, `category_primary` (must be a *searchable* token — e.g. `restaurant`,
  `cafe`, `dentist`), `confidence` (≥ 0.5).
- **≥ 1 contact** (`email` / `website` / `phone`) or §6.9 drops it as uncontactable.
- **Recommended:** `locality` + `address` (contain the city name → city-tier ranking).
- The import script (to write when a CSV is ready) converts `lat`/`lng` → `geom`, sets
  `source='manual'` (so the monthly refresh never overwrites it, §7), and **registers an
  `overture_loaded_areas` row** covering the imported region+category so the rows serve warm
  instead of triggering a cold-load.

---

## 7. Refresh safety rules (unchanged, restated)
The monthly Overture refresh must:
1. **Upsert in place**, never delete+insert (keeps `overture_id` stable).
2. **Never overwrite enrichment** — `scraped_email`, `email_source`, `lead_score`,
   `enrichment_status`, `enriched_at`, `hunter_data`, context are **excluded** from the
   refresh upsert. It updates only Overture-provided fields (incl. `email`).
3. **Only touch `source = 'overture'` rows.**
4. **Don't delete vanished businesses** (a user may hold one as a lead).

---

## 8. Frontend / API contract change (updated alongside, per phase)
The read path **keeps existing field names** (`email`, `enrichment_status`, `services`,
`website_summary`, `business_description`, `lead_score`), so most of the frontend is untouched.
Changes are **additive**:
- **Phase 4:** optional `email_source` / `source` in the lead response → optional provenance
  badge in the leads list.
- **§5.8:** launch readiness gains `enriching: {count, total}` → "N of M leads still enriching"
  progress on the launch screen.
- **Exhaustion payload** (`status:"exhausted"`) — *revised 2026-07-26, see §6.11/§6.13*:
  ```json
  { "status": "exhausted", "message": "…reached the end. Try a different location
    (Lalitpur, Bhaktapur) or industry…",
    "exhausted": { "industry": "...", "city": "...", "log_id": "…|null",
                   "nearby": [{ "city": "Lalitpur", "available": 0 }] } }
  ```
  - **`see_my` was dropped** (user decision) — the count/link no longer lined up. Kept
    `log_id`: a **deep-link to the user's most recent matching search log** so they can
    reopen the leads they already pulled. Frontend renders it as a "view leads you already
    pulled" link (a temporary version is wired in `LeadGeneration.tsx`, marked `TEMP` for
    the frontend dev to redesign).
  - **Nearby cities are named inline in `message`** (up to 3 real neighbours from the LLM
    suggester, history-aware so already-exhausted cities aren't re-offered) — **not** chips,
    **no counts** in prose (user UX decision). The `nearby` array is still present for a
    future chip UI if wanted.
- **Gathering payload** (`status:"gathering"` + `log_id`) covers **both** a cold-load *and*
  a top-up (§6.11) — same shape, the frontend's existing poller renders leads when they
  land. No frontend change needed for top-up.
- **Anchor in titles/replies (§6.13):** a "near Lakeside, Pokhara" search now reflects the
  anchor in the confirm reply **and** the lead-log `chat_title` ("Restaurants near Lakeside,
  Pokhara"). No contract change — just better text.
- **Phone-only leads (§6.9):** leads may now have a phone but no email — still shown
  (callable), just not email-campaignable. No new field.
- `overture_id` is internal (not surfaced in responses).

> Each phase's API contract change is handed off in chat when that phase lands.

---

## 9. Open items / future

**Remaining work (not yet done):**
- **Frontend (teammate):** provenance badge (`email_source`/`source`), enriching count
  (§5.8), and redesign of the **TEMP** exhaustion "view the leads you already pulled" link
  (`LeadGeneration.tsx`, §6.13). Live end-to-end search is **done** — warm Kathmandu +
  Pokhara cold-load + a real top-up, all verified; tests 1–13 + bulk-delete passed.

**Housekeeping (discussed, not done):**
- **`alembic/env.py` `include_object`** — exclude the LangGraph checkpointer tables so
  autogenerate stops re-proposing to DROP them (hand-stripped 3× so far: migrations
  `07dc3dc813d9`, `3afb056c9a5c`, `0c3c54e50e8d`). Until fixed, **hand-verify every new
  migration** for those drops.
- **`OVERTURE_RELEASE = "2026-05-20.0"`** in `config.py` points to a **purged** release — bump
  to a live one (only a fallback; cold-load/refresh auto-detect the latest).
- **`email_jobs.lead_id` index** — unindexed, so the `ON DELETE CASCADE` is slow on large lead
  deletes (bulk-delete). Add `Index("idx_email_jobs_lead", "lead_id")` + migration.
- **`get_lead_logs` per-row guard** — the search-history list validates each row with no
  try/except, so one malformed row 500s the whole list (hit once via a NULL-`promoted` test
  row → "No search sessions found"). The sibling `view_lead_log` already guards per-row;
  mirror it. **Offered, not applied.**

**Future enhancements (optional):**
- **GEO-4 v2:** "include already-pulled" re-pull toggle (charge on new-count only); nearby
  "N of M" upgrade-reveal (frontend A vs B — backend already returns both numbers).
- **`locality` backfill** for kept catalog data — a per-area re-pull script exists if wanted.
- **Exact-FK later:** `overture_id` on `lead_log_leads` is a plain indexed column (not a hard
  FK) so the log stays prunable; a real FK/exact join could replace name-based matching.
- **`leads` (Lead Database) sync:** decide whether promoted leads read provenance live from
  the master or snapshot it at promotion time.
- **Source-weighting:** `email_source` enables preferring verified sources (e.g. Hunter) over
  scraped when both exist.
- **Subset-aware coverage (§6.12):** a strict "only restaurants" search (`category_key =
  restaurant`) cold-loads its own cache even when a superset area (`cafe|coffee|restaurant`)
  is already loaded. A coverage check treating *search codes ⊆ area codes* as warm would
  avoid the redundant load.
- **Mislabel LLM check (§6.9):** Overture occasionally files a non-food business under a food
  category (e.g. "Skin Care Nepal" as `cafe`). Contactability hides the bare ones; a per-lead
  name-vs-category LLM check during enrichment would catch mislabels that *do* have contact info.
- **Coverage-threshold buffer (§6.11 note):** at exactly the plan radius, `ST_Contains` sits
  ~2 m from its threshold, so a search whose geocode lands slightly differently can spuriously
  re-cold-load an already-loaded city. A tiny bbox buffer on the coverage check would remove
  the edge flakiness.

**❌ Decided AGAINST — 3-month prune job.** Earlier design floated TTL-deleting old
`lead_logs`/`lead_log_leads`. **Decision: do NOT build it** — it doesn't change correctness
(§4.1 means the log isn't read for reuse; the master owns the data), and users should keep
**all** their search history. The log grows; that's fine.

**❌ Reverted — silent partial-result detection.** A version that re-ran the warm query
without exclude-seen (+ `partial_saved`/`has_more` flags) to explain a short batch was built,
then **reverted at the user's request**: they want a plainly-worded message if anything, not
a hidden extra query and flags. **No partial-result messaging currently ships;** revisit as
pure wording in the existing `generate_human_response` reply if desired.

---

## 10. Reference map (verified locations)
> ⚠️ **These locations are from the PRE-refactor investigation.** After the refactor the line
> numbers and some descriptions are stale — e.g. `fetch_leads_from_db` (Tier-1) was **deleted**
> in §4.1; `_query_overture_warm` now **selects** `overture_id` (no longer "drops" it); the
> launch-readiness **enrichment gate is built** (§5.8). Treat this as the map of *where the
> original problem lived*; the current implementation is described phase-by-phase in §6.

**Current implementation anchors (post-refactor — grep these names, line numbers drift):**
- Matching — `_overture_match_sql`, `_overture_codes`, `_overture_token_haystack`,
  `_overture_token_patterns`, `OVERTURE_CONTACTABLE`, `OVERTURE_EMAIL_KEY`,
  `OVERTURE_DEDUPED_COUNT` (`lead_generation_service.py`) — §6.7–6.9.
- Warm serve / exhaustion — `_query_overture_warm`, `_count_overture_matches`,
  `_nearby_cities_with_counts`, `get_leads_overture` — §6.8–6.11.
- Top-up — `topup_overture_area`, `_area_has_more`, `_covering_loaded_area`,
  `ensure_overture_area_loaded` (sets `has_more`), `OVERTURE_TOPUP_BATCH` — §6.11.
- Chat flow — `_exhaustion_response`, `_fill_exhaustion_nearby`, `build_confirm_message`,
  `build_chat_title`, the cold-load/top-up gathering branches (`chat_service.py`) — §6.11–6.13.
- Strict intent — `context["strict_intent"]` (chat) + `_verified_city_suggestions`
  (`chat_helper.py`, history-aware) — §6.12.
- Pagination tiebreaker — `get_all_leads` (`lead_service.py`), `campaign_service.py` — §6.13.
- Tests — `tests/unit/test_overture_match.py` (20 cases).

**Legacy (pre-refactor) locations — kept for the investigation record:**

- Overture cache model — [overture_place.py](../backend/app/models/overture_place.py)
- Email column migration (no backfill) —
  [f1bb27dc185e](../backend/alembic/versions/f1bb27dc185e_overture_places_email_status_taxonomy.py) (2026-06-16)
- Overture read (drops `overture_id`) —
  [lead_generation_service.py:870](../backend/app/services/lead_generation_service.py#L870)
- Save paths — [overture_tasks.py:175](../backend/app/tasks/overture_tasks.py#L175),
  [chat_service.py:1279](../backend/app/services/chat_service.py#L1279)
- Tier-1 reuse — [chat_service.py:1034](../backend/app/services/chat_service.py#L1034),
  [:159-169](../backend/app/services/chat_service.py#L159-L169)
- Enrichment early-return (no website) —
  [lead_generation_service.py:1795-1810](../backend/app/services/lead_generation_service.py#L1795-L1810)
- `email_source` computed-but-discarded —
  [lead_generation_service.py:1779](../backend/app/services/lead_generation_service.py#L1779),
  [:2010](../backend/app/services/lead_generation_service.py#L2010)
- Monthly refresh — [overture_tasks.py:108](../backend/app/tasks/overture_tasks.py#L108)
- Campaign context snapshot ("at sync time") —
  [campaign_lead.py:26-29](../backend/app/models/campaign_lead.py#L26-L29)
- Generation read precedence (live lead → snapshot) —
  [personalization_service.py:62-67](../backend/app/services/personalization_service.py#L62-L67)
- Per-lead email generation —
  [campaign_email_generation_service.py](../backend/app/services/campaign_email_generation_service.py)
- Launch readiness (no enrichment gate today) —
  [campaign_launch_readiness_service.py:67](../backend/app/services/campaign_launch_readiness_service.py#L67)
- Prior design — [OVERTURE_LEAD_GENERATION.md](OVERTURE_LEAD_GENERATION.md) ("Next phase:
  business-master catalog + prunable log")
