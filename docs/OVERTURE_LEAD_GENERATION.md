# Overture Maps Lead Generation — End-to-End Plan

> **Status:** Functionally complete behind the `LEAD_SOURCE` flag (default still `google`).
> Cache + chat wiring + background cold-loads are built and verified end-to-end: warm searches
> are instant, cold searches return a "gathering" status and auto-fill the table via a Celery
> task (no re-search, no 504). What remains is **pre-launch hardening** (PostGIS on prod, region
> coverage checks) and **post-launch polish** (pre-warming, refresh job, category tables, dedup).
> See **"Implementation status (as built)"** below; the numbered sections further down are the
> original design rationale.

**Goal:** Replace the **paid Google Places API** in the lead-search step with a **free,
self-hosted Overture Maps dataset**, to cut API cost. Google Places stays in the code
(`get_leads`) but is **no longer called** for lead search — a new function
`get_leads_overture()` replaces it behind a feature flag.

**Decisions already locked in (from discussion):**

| Decision | Choice |
|---|---|
| Motivation | Cut Google Places API cost |
| Google fallback for lead search | **No fallback** — Overture only |
| Existing `get_leads()` | Keep in code, stop calling it (kill-switch flag) |
| Data loading | **On-demand per queried area**, not a full global preload |
| Area granularity | **Tight bbox around the search point** (radius + buffer), NOT whole-city. Overlap check skips re-pulls. |
| Cache scope | **Category-scoped** — cold-load caches only the *searched* category for the area, tracked per `(area, category)`. NOT all categories. |
| Cache cap | **`OVERTURE_CACHE_PER_CATEGORY = 1000`** per `(area, category)` — covers the biggest plan (scale = 500 leads_per_search) with headroom. |
| Region scope | **Any country** — no allowed-list, no country gate. Load whatever area is searched. |
| Coverage validation (Phase 0) | **Done** — Overture coverage compared to Google, good to go |

---

## Implementation status (as built)

This section is the source of truth for what currently exists in code. The numbered design
sections below predate implementation and describe a *full-area* load; **the built version is
category-scoped** (see divergences).

### Built & verified ✅
- **PostGIS** enabled on `lead_management` (PostGIS 3.6.2 / PG16).
- **Two tables** ([backend/app/models/overture_place.py](../backend/app/models/overture_place.py)):
  - `overture_places` — cached catalog (PostGIS `geom`, GIST index, `source` column, `ARRAY` categories).
  - `overture_loaded_areas` — registry with **`category_key`** + composite unique `(area_key, category_key)`.
  - Migrations: `402273ef66c0` (tables) and `7019db94f047` (category_key + truncate).
- **`get_leads_overture()`** ([lead_generation_service.py](../backend/app/services/lead_generation_service.py)):
  - **Cached path** (`db` provided): cold-loads the searched category (≤1000, nearest-first) →
    `_query_overture_warm()` runs `ST_DWithin` + category match.
  - **`load_if_cold=False`** → warm areas query instantly; cold areas return `overture_cold=True`
    immediately (no blocking) so the caller can background the load. `overture_area_is_warm()`
    is the cheap registry check.
  - **Direct path** (`db=None`): pulls straight from S3 (used by `backend/test_overture.py`).
  - Returns the **same lead-dict shape as Google** — downstream chat save/enrich is untouched.
- **Wired into chat** behind `LEAD_SOURCE` ([chat_service.py](../backend/app/services/chat_service.py)):
  warm → serve immediately; **cold → create an empty `LeadLog`, enqueue a Celery task, return
  `status:"gathering"` + `log_id`**. The request never blocks (no 504).
- **Background cold-load tasks** ([backend/app/tasks/overture_tasks.py](../backend/app/tasks/overture_tasks.py)):
  - `load_and_fill_overture_task` → cold-loads the area, **saves leads into the LeadLog**, spends
    credits, enqueues enrichment. The frontend's existing lead-poll then fills the table — **no re-search**.
  - `load_overture_area_task` → warm-only cache load (no fill).
- **Frontend** ([Frontend/src/shared/leadGenPoller.ts](../Frontend/src/shared/leadGenPoller.ts)):
  poll timeout raised **1min → 6min** so the existing loader survives a slow cold-load.
- **DuckDB** `http_timeout=300s` + retries so large S3 parquet reads don't abort.
- **Smoke test** `backend/test_overture.py` (cold → warm).

### Measured
- **Warm query: ~0.4s** (PostGIS only) — feels identical to Google.
- **Cold-load: ~28s to several minutes** — *highly variable* (S3 latency + category density;
  observed 28s for childcare, 393s for restaurant). This is why cold-loads run in the **background**,
  never in the request.

### Divergences from the original (numbered) plan
- **Category-scoped, not full-area.** Cold-load caches only the searched category (capped 1000),
  not all categories (which hit 50k in dense metros). Registry keyed `(area_key, category_key)`.
- **Plan-capped cache** via `OVERTURE_CACHE_PER_CATEGORY` — see the decisions table.
- **Category matching** uses substring tokens against Overture's *flat* leaf categories
  (e.g. `%child_care%` → `child_care_and_day_care`), NOT the dotted hierarchy the early plan assumed.
- **Overture specifics learned in testing:** `geometry` reads as a GEOMETRY type → use
  `ST_X/ST_Y(geometry)` (not `ST_GeomFromWKB`); release pinned to **`2026-05-20.0`**; S3 public
  bucket works anonymously with `SET s3_region='us-west-2'`.

### Pending

**Pre-launch must-dos (before flipping `LEAD_SOURCE=overture` in production):**
- **PostGIS on the production database** — done locally only. The migration runs
  `CREATE EXTENSION postgis`, but the prod Postgres needs the PostGIS binaries (managed Postgres
  usually has them; self-hosted needs the OS package).
- **Region coverage spot-checks** — Sydney validated; spot-check Nepal / Europe / US so you know
  where Overture is thin (thin areas return few/zero leads → existing no-results UX).
- **Restart Celery worker on deploy** — the cold-fill tasks (`overture_tasks`) must be loaded by
  the worker (it's imported in `celery_app.py`).

**Strongly recommended (UX / cost, not strictly blocking):**
- **Pre-warming popular areas** — a background job that loads common city×industry combos so users
  rarely hit the (slow, variable) cold path at all.
- **Release freshness** — `OVERTURE_RELEASE` is pinned to `2026-05-20.0`; bump it (or automate via
  the refresh job) when Overture publishes a new release. The 35-day TTL lazily re-loads areas.
- **`category_key` robustness** — the chat's free-text industry phrasing can produce a different
  `category_key` than a cached one, causing an avoidable cold-load. Better synonym mapping (or the
  category tables below) reduces this.

**Built since (now done):**
- ✅ **Category-intelligence tables** (`overture_categories` + `overture_category_aliases`) — dynamic
  resolver (alias → trigram → LLM → learn). Request path is alias-only (no LLM); the background
  cold-load learns. Seed via `python seed_overture_categories.py`.
- ✅ **Monthly refresh job** — `overture_refresh_task` (Celery beat, monthly) re-pulls cached
  `(area, category)` rows from the auto-detected latest release, upsert-in-place, with all four
  safety rules enforced (incl. `WHERE source='overture'`). Release auto-detect with env fallback.

**Catalog data policy — KEEP ALL (decided):**
- The `overture_places` catalog is treated as a **growing, owned business-directory asset** — we do
  **NOT** evict/delete cached places or areas. It accumulates over time (every searched area adds to
  it), which is the intended value. No LRU eviction, no orphan deletion.
- The monthly refresh keeps it fresh in place; it never shrinks it.
- **Only non-destructive maintenance is in scope** (optional, later): periodic `VACUUM ANALYZE` /
  reindex so spatial queries stay fast as the table grows — **no data is removed.**

**Future phases (still post-launch):**
- **Business-master + prunable log** (see the dedicated section below) — the natural next step now
  that the catalog is a kept, growing asset.
- **Pre-warming** popular city×industry combos so users rarely hit a cold load.
- **Cleanup** — once Overture is stable in prod, remove dead Google grid-search code (`GRID_CONFIG`,
  `generate_grid_points`, `PAGE_DELAY`, the radius-clamp) and `get_leads`.

---

## Next phase: business-master catalog + prunable log (design decision)

> This captures an important architecture decision for the next phase. **Not built yet.**

### Current lead-fetch order (Tier 1 → 2 → 3)
```
1. lead_log_leads  (DB)            ← checked FIRST (Tier 1)
2. overture_places (warm cache)    ← then this (Tier 2)
3. cold-load from S3               ← if neither has it
```
`lead_log_leads` is checked **first** (not the fallback). The reason: it holds **fully-enriched**
leads — **scraped emails + lead scores** from previous searches. Reusing them is instant and avoids
re-scraping. `overture_places` only has Overture's data (incl. Overture's email), **not** scraped
emails or scores — so the two are **not interchangeable today**.

### Why `lead_log_leads` ≠ `overture_places` (yet)
| | `lead_log_leads` | `overture_places` |
|---|---|---|
| Scraped email | ✅ (Hunter/scraper) | ❌ (only Overture's email) |
| Lead score | ✅ | ❌ |
| Deduplicated | ❌ (same business stored per-search → slow `DISTINCT`) | ✅ (one row per business) |
| Fast | ❌ | ✅ (PostGIS) |

### The decision — make `overture_places` the master; `lead_log_leads` a prunable log
- **`overture_places`** = permanent, deduplicated **master**. Add **`scraped_email`, `lead_score`,
  `enrichment_status`, `enriched_at`** columns (SEPARATE from Overture's `email`; the monthly refresh
  must NOT touch these — same rule as the contact-field COALESCE design).
- **`lead_log_leads`** = **just a denormalized log** of what each search showed. **No FK to the
  master** (keep it flat). **Prune after ~3 months** (Celery beat).
- The **"already enriched?" check moves to `overture_places`** (deduplicated + fast) → kills both the
  re-scraping cost and the slow `DISTINCT`.

### Why this is a SMALL change (audit result)
Audited the schema — `lead_log_leads` is a **leaf table**:
- **No foreign key anywhere targets `lead_log_leads.id`** (verified — zero references).
- Promoted **`Lead`** = a full **copy**; `lead_log_id` is `ondelete=SET NULL`, nullable → survives pruning.
- **`CampaignLead`** references `leads` (`SET NULL`) **and** carries **snapshot fields** → survives pruning.
- Chain: `lead_log_leads` → *copied to* `Lead` → *snapshotted into* `CampaignLead`. Every downstream
  step is an independent copy joined only by **soft (SET NULL)** links.

**Conclusion: pruning old `lead_log_leads`/`LeadLog` is SAFE** — promoted leads + campaign leads are
copies/snapshots and survive. Only loss is re-viewing a 3-month-old search's raw results (the point
of the TTL).

### Work split (two small pieces)
1. **Prune job** (tiny, safe): Celery beat → `DELETE FROM lead_logs WHERE created_at < now() - 3 months`
   (cascade cleans `lead_log_leads`). Independent — can ship alone.
2. **Enrichment-on-master** (the reuse win): add the enrichment columns to `overture_places`, carry
   **`overture_id`** through the lead flow so enrichment writes the scraped email **back onto the
   master**, and move the reuse check to `overture_places`.

---

## Known residual risks (fix later)

Audited after hardening. **No critical risks remain** — no double-charge (idempotent fill), no 504
(cold-loads backgrounded), no duplicate cold-loads (Redis lock), safety rules enforced, novel
categories resolve dynamically. The items below are **low-severity** (quality / efficiency /
robustness), safe to defer:

**Quality / tuning**
- **Looser LLM category mappings.** Broadening LLM candidates with top-level categories fixed recall
  but means a vague term may map to a broad parent (e.g. `vegan tattoo studio` → also
  `arts_and_entertainment`). Reviewable via `source='learned'`; tune by dropping the broad fallback
  or requiring a min confidence.
- **Alias-normalization near-synonyms.** `gym` (seeded) vs `fitness center` (→ `fitness`, learned
  separately) can get slightly different `category_key`s → minor cache duplication. Correct results.

**Efficiency / robustness**
- **Resolver commits the caller's session** (to persist `hit_count` / learned alias) + a small
  `UPDATE hit_count` write **per warm search**. Verified isolated from the credit/lead-save commit,
  but it's a coupling smell and a tiny per-search write. *Fix: use a separate session, or batch
  hit_count updates.*
- **Lock TTL (600s) < worst-case load.** A pathological cold-load (>10 min) could let the lock expire
  and a second worker start a duplicate pull. Rare, idempotent. *Fix: raise the TTL.*
- **No Celery `task_time_limit`** on fill/refresh — a hung load occupies the `-P solo` worker.
  DuckDB's `http_timeout` (300s/request) bounds reads, so unlikely. *Fix: set `task_time_limit`.*
- **Geocoding still on Google** — a geocode failure blocks a cold-load (Redis-cached, so rare).
  *Fix later: Nominatim / Overture divisions to fully drop Google.*

---

## Query capabilities & limitations (what the chat can/can't do)

Tested across many query shapes. Summary of how the chat interprets a search:

| Query type | Behavior | Status |
|------------|----------|--------|
| **Business type** ("dentists", "hostel", "plumbers in Gordon") | Resolved to an Overture category (alias → trigram → LLM). | ✅ Works |
| **Phrasing variants** ("childcare" vs "childcare centre") | Normalize to the same category_key → warm hit. | ✅ Works |
| **Long-tail / novel** ("chocolate shops", "ethanol supplier") | LLM maps + learns; umbrella codes dropped when a specific one fits. | ✅ Works |
| **`within / inside N km`** | The radius **number is NOT parsed** — the search uses the **plan radius** (free/starter 5km, growth 6km, scale 7km), bounded exactly by `ST_DWithin`. | ⚠️ Number ignored |
| **Quality qualifiers** ("best", "cheap", "top") | The qualifier is **dropped**; resolves to the business type only. Overture has **no ratings/reviews** (only a data-`confidence` score), so it **cannot rank by quality**. | ⚠️ Qualifier ignored |

### Precision nuance (business types)
- **Precise** when the LLM finds a specific leaf: `doctors → doctor/physician`, `hostel → hostel`.
- **Too broad** when the specific leaf isn't surfaced (trigram is lexical, not semantic):
  `general practitioners → health_and_medical` (returns *all* medical, not just GPs),
  `cheap hotels → accommodation` (not `hotel`). Returns relevant-but-broad results, not garbage.

### Fix-later options (agreed, not built yet)
1. **Radius extraction** — parse "within N km" from the message → pass as the search radius (Overture's
   `ST_DWithin` would then honor it exactly). This was the *original* feature request, deferred when we
   pivoted to Overture.
2. **Sharper aliases** — seed common broad-maps as precise (`general practitioner → doctor`,
   `cheap hotel → hotel`) so they don't fall to umbrella categories.
3. **"best/top" ranking** — requires an external ratings source (Google/Yelp); **out of scope for
   Overture** (no review data).

---

## 1. The one thing to keep clear: Catalog vs Leads

There are two completely separate layers. Overture only replaces the **catalog**.

| | **Catalog** (new: `overture_places`) | **User leads** (existing: `lead_log_leads` / `leads`) |
|---|---|---|
| Role | The "phone book" you search — replaces Google | The businesses a user generated/saved |
| Owner | Nobody (reference data) | A `user_id`, a `LeadLog`, a campaign |
| Mutable | Read-only, refreshed monthly | Enriched, scored, emailed |
| Linked to user/campaign/chat | **No** | **Yes — unchanged** |

A business only becomes a *user's lead* when it is copied into `lead_log_leads`. That copy
happens in `chat_service.py` **after** the search returns, and that code is **not changing**.

**Unchanged boundary (proof):** in
[backend/app/services/chat_service.py](../backend/app/services/chat_service.py):
- The search call is at **lines 855–862** (`get_leads(...)`) — this is the **only** line we swap.
- Dedup + append is at **lines 907–921** — receives a list of lead dicts, source-agnostic.
- Save to DB (`LeadLog` + `LeadLogLead`) is at **lines 951–999** — **untouched**. This is
  where `user_id`, `lead_log_id`, campaign linkage, enrichment status are attached.

> Therefore: campaign setup, chat history, enrichment, scoring all keep working identically.
> We only change *where the raw businesses come from*.

---

## 2. Architecture: on-demand area loading

You do **not** bulk-load 60M+ global rows. Data enters the DB **lazily, per searched area**,
and only for allowed countries. First search of a new area pulls that area from Overture and
caches it locally; every later search of that area is a fast local query.

```
                         ┌─────────────────────────────────────────┐
  user: "childcare in    │  get_leads_overture(industry, location)  │
  Gordon, Sydney"  ─────►│                                          │
                         │  1. geocode center (reuse existing)      │
                         │  2. country metadata only (no gate)      │
                         │  3. is this AREA already loaded & fresh? │
                         │        ├─ NO  → on-demand ETL (DuckDB    │
                         │        │        pulls area from Overture │
                         │        │        S3 → insert into table)  │
                         │        └─ YES → skip                     │
                         │  4. PostGIS query: ST_DWithin + category │
                         │  5. shape rows → lead dicts (same shape) │
                         └───────────────────┬──────────────────────┘
                                             │ returns (leads, error_info)
                                             ▼
                    chat_service saves to lead_log_leads (UNCHANGED)
```

Two new tables for the first Overture milestone:
- **`overture_places`** — the cached catalog rows (PostGIS points).
- **`overture_loaded_areas`** — a registry of which areas are already loaded + when
  (so step 3 knows whether to trigger the on-demand ETL or skip it).

Category intelligence is intentionally **not** a DB table in v1. Start with a static
seed map in code plus keyword fallback. Later, after the Overture search path works, add:
- **`overture_categories`** — official Overture category list from `overture_categories.csv`.
- **`overture_category_aliases`** — learned user-language aliases like `daycare`,
  `hotels`, `law firm`, or `ethanol supplier`.

**Area sizing — tight bbox (locked decision):** when a user searches, we load **only a
bounding box around the search point**, sized to `search_radius_km + buffer` (NOT the whole
city). One search of "Gordon" loads a Gordon-sized box, not all of Sydney.

**Cold-start trade-off (accepted):** the *first* search in any not-yet-loaded box runs a live
DuckDB-over-S3 pull (a few seconds). Because boxes are tight, **nearby distinct areas cold-load
separately** (Gordon and Chatswood are two pulls). This is accepted in exchange for minimal
storage. Mitigation: an **overlap check** — if a new search's needed box is already inside a
previously loaded box, we skip the pull and query locally. Optional later: background pre-warm.

---

## 3. Region scope — any country, no gate

**Locked decision: no country restriction.** The user may search any city in any country; we
load that area on demand regardless of country. There is **no `OVERTURE_ALLOWED_COUNTRIES`
list and no country gate.**

- Geocode the search → get center + country (country is kept only as a metadata column on the
  rows, not used to allow/deny).
- Load the bbox for that area from Overture and serve.
- If Overture coverage for that area is thin (no Google fallback), the query simply returns few
  or zero rows → the **existing** no-results UX fires (`generate_suggestions`, city
  suggestions). No special handling.

> Trade-off accepted: some low-coverage regions return little. That is the cost of Overture-only
> with no fallback, and is handled by the existing empty-results path.

---

## 4. Prerequisites & new dependencies

| Dependency | Why | Notes |
|---|---|---|
| **PostGIS** extension | Spatial column + `ST_DWithin` index | Installed into your existing Postgres (Step 1) |
| **GeoAlchemy2** (`geoalchemy2`) | SQLAlchemy support for PostGIS `Geometry` columns | Adds the `Geometry` type + spatial index |
| **DuckDB** (`duckdb`) Python pkg | Reads Overture Parquet from S3, filters, writes to Postgres | Used only by the ETL/loader, not per request |
| DuckDB `spatial` + `httpfs` extensions | Read remote Parquet + geometry | Installed at runtime by DuckDB |

New settings (pydantic, **`APP_` prefix**, in
[backend/app/core/config.py](../backend/app/core/config.py)):

```
APP_LEAD_SOURCE=overture            # "google" | "overture"  (kill-switch)
APP_OVERTURE_RELEASE=2025-XX-XX.X   # pinned Overture release version
APP_OVERTURE_S3_BASE=s3://overturemaps-us-west-2/release
APP_OVERTURE_MIN_CONFIDENCE=0.5     # drop low-quality POIs
APP_OVERTURE_AREA_BUFFER_KM=3       # extra km padded around the search radius when loading a box
APP_OVERTURE_AREA_TTL_DAYS=35       # re-pull an area if older than this
# NOTE: no APP_OVERTURE_ALLOWED_COUNTRIES — any country is allowed (locked decision).
```

---

## STEP 1 — Install & enable PostGIS

PostGIS is an **extension** of your existing Postgres — not a new database. Same
`overture_places` table is a normal table; PostGIS just adds the geometry type, the spatial
index, and `ST_DWithin`.

### 1a. Local dev (Windows)

Pick one:

**Option A — Add PostGIS to an existing EDB PostgreSQL install**
1. Open **Stack Builder** (ships with EnterpriseDB PostgreSQL installer).
2. Select your server → **Spatial Extensions → PostGIS** → install.

**Option B — Docker (cleanest, recommended for dev)**
```powershell
docker run --name evecta-postgis -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=evecta -p 5432:5432 -d postgis/postgis:16-3.4
```
Then point `.env` `APP_POSTGRES_*` at this container.

### 1b. Enable the extension (both dev & prod)

Connect to the Evecta database and run **once**:
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT PostGIS_Full_Version();   -- verify
```

### 1c. Production note

- **Managed Postgres (RDS / Supabase / Azure):** PostGIS is available — just run
  `CREATE EXTENSION postgis;` (RDS may need `rds.allowed_extensions`/`shared_preload`).
- **Self-managed:** install the `postgis` OS package matching your Postgres major version,
  then `CREATE EXTENSION`.

> The `CREATE EXTENSION` is also emitted from the Alembic migration (Step 3) via
> `op.execute(...)` so fresh environments get it automatically.

**Done when:** `SELECT PostGIS_Full_Version();` returns a version on dev and prod.

---

## STEP 2 — Schema design (two new models)

New models use the existing `Base` from
[backend/app/database/base.py](../backend/app/database/base.py) and are registered in
[backend/app/models/__init__.py](../backend/app/models/__init__.py) so Alembic autogenerate
sees them.

### 2a. `overture_places` (the catalog)

| Column | Type | Notes |
|---|---|---|
| `id` | `BigInteger` PK | surrogate key |
| `overture_id` | `String`, unique index | Overture's stable place id (for upsert dedup) |
| `name` | `String(255)`, index | from Overture `names.primary` |
| `categories` | `String[]` (ARRAY) or `JSONB` | Overture main + alternate categories |
| `category_primary` | `String(128)`, index | denormalized main category for fast filter |
| `website` | `String(512)` | from Overture `websites[0]` |
| `phone` | `String(64)` | from Overture `phones[0]` |
| `address` | `String(512)` | composed from Overture `addresses[0]` |
| `country_code` | `String(2)`, index | ISO alpha-2 — metadata only (NOT a gate); handy for refresh/reporting |
| `confidence` | `Float`, index | Overture confidence score |
| `geom` | `Geometry(POINT, 4326)` (GeoAlchemy2) | **GIST spatial index** |
| `loaded_at` | `DateTime(tz)` | when this row was cached |

Indexes:
- **GIST** on `geom` (GeoAlchemy2 creates it automatically when `spatial_index=True`).
- B-tree on `category_primary`, `country_code`, `confidence`.
- Trigram (`pg_trgm`) on `name` **(optional)** for the name-ILIKE fallback in category mapping.

### 2b. `overture_loaded_areas` (the coverage registry)

Tracks which areas are already cached so the on-demand loader knows when to skip.

| Column | Type | Notes |
|---|---|---|
| `id` | `BigInteger` PK | |
| `area_key` | `String`, unique index | canonical key for the area (see algorithm) |
| `country_code` | `String(2)`, index | |
| `bbox` | `Geometry(POLYGON, 4326)` | the loaded rectangle (for containment checks) |
| `place_count` | `Integer` | how many rows this load produced |
| `loaded_at` | `DateTime(tz)`, index | freshness check vs `AREA_TTL_DAYS` |
| `overture_release` | `String` | which Overture release it came from |

**Area = tight bbox around the search point (locked decision).** We do NOT load whole cities.
An area is the rectangle covering `search_radius_km + AREA_BUFFER_KM` around the geocoded center.

**Coverage check — bbox containment (not a city name):**
```
function needs_load(center, radius_km):
    need_box = bbox_around(center, radius_km + AREA_BUFFER_KM)
    # Already covered if some loaded box fully contains need_box AND is still fresh.
    row = SELECT 1 FROM overture_loaded_areas
          WHERE ST_Contains(bbox, :need_box)
            AND loaded_at > now() - AREA_TTL_DAYS
            AND overture_release = :APP_OVERTURE_RELEASE
          LIMIT 1
    return (row is None)        # True → must load; False → query locally
```
> Tight boxes mean a "Gordon" search loads only a Gordon-sized box. A later "Chatswood" search
> is a separate cold-load **unless** its box falls inside Gordon's already-loaded box (the
> `ST_Contains` check), in which case it's served locally. `area_key` is just a label
> (e.g. `geohash6(center)`); the real dedup is the bbox containment test above.

---

## STEP 3 — Alembic migration

Existing Alembic is async and autogenerates from `Base.metadata`
([backend/alembic/env.py](../backend/alembic/env.py)).

**Algorithm / checklist for the migration file:**
1. `op.execute("CREATE EXTENSION IF NOT EXISTS postgis")` at the **top** of `upgrade()`
   (and `pg_trgm` if using the name-trigram index).
2. Create `overture_places` and `overture_loaded_areas`.
3. **GeoAlchemy2 caveat:** autogenerate does **not** reliably emit geometry columns or spatial
   indexes. After `alembic revision --autogenerate`, **hand-edit** the migration to:
   - use `geoalchemy2.types.Geometry(...)` for `geom`/`bbox`,
   - add the GIST index explicitly if not generated,
   - in `downgrade()`, drop the spatial indexes before dropping tables, and consider
     `DROP EXTENSION` only if safe.
4. Generate & apply:
   ```powershell
   alembic revision --autogenerate -m "overture places + loaded areas"
   # hand-edit the file per step 3
   alembic upgrade head
   ```

**Done when:** both tables exist with a GIST index on `geom`
(`\d+ overture_places` shows the spatial index).

---

## STEP 4 — Overture data + on-demand ETL (DuckDB)

### 4a. Where the data lives

Overture publishes monthly Parquet on S3:
```
{APP_OVERTURE_S3_BASE}/{APP_OVERTURE_RELEASE}/theme=places/type=place/*.parquet
```
Relevant columns (verify exact names against the pinned release schema; Overture evolves):
- `id`, `names` (struct → `names.primary`), `categories` (struct → `main`, `alternate`),
  `websites` (list), `phones` (list), `addresses` (list of struct),
  `confidence` (double), `geometry` (WKB), `bbox` (struct: `xmin,xmax,ymin,ymax`).

### 4b. On-demand loader algorithm

```
function ensure_area_loaded(center, radius_km, country):
    # NO country gate — any country is allowed (locked decision).
    if not needs_load(center, radius_km):     # bbox-containment check (Step 2b)
        return ALREADY_FRESH                  # covered by an existing fresh box → local query

    need_box = bbox_around(center, radius_km + AREA_BUFFER_KM)   # tight box, NOT whole city
    rows = duckdb_pull_overture(need_box)      # see 4c — bbox filter only, no country filter
    UPSERT rows INTO overture_places ON CONFLICT(overture_id) DO UPDATE
        SET (overture fields only; never touch enriched email/score — see refresh rules)
    INSERT (geohash6(center), country, need_box, count(rows), now, release)
        INTO overture_loaded_areas
    return LOADED
```

Concurrency: wrap the load in the **same Redis lock pattern already used** for searches
(`acquire_search_lock` in chat_service) keyed by the box/geohash, so two users hitting the same
cold area don't both pull it.

### 4c. DuckDB pull (sketch — algorithm, not final code)

```sql
INSTALL spatial; LOAD spatial;
INSTALL httpfs;  LOAD httpfs;
SET s3_region='us-west-2';

SELECT
    id                              AS overture_id,
    names.primary                   AS name,
    categories.main                 AS category_primary,
    list_transform(categories.alternate, x -> x) AS categories,
    websites[1]                     AS website,
    phones[1]                       AS phone,
    -- compose address from addresses[1] struct fields
    addresses[1].freeform           AS address,
    '{country}'                     AS country_code,
    confidence,
    ST_AsText(ST_GeomFromWKB(geometry)) AS geom_wkt
FROM read_parquet('{S3_BASE}/{RELEASE}/theme=places/type=place/*.parquet', filename=false)
WHERE bbox.xmin >= {minlon} AND bbox.xmax <= {maxlon}
  AND bbox.ymin >= {minlat} AND bbox.ymax <= {maxlat}
  AND confidence >= {MIN_CONFIDENCE};
```
Then insert into Postgres (either DuckDB `postgres` extension `COPY`, or fetch rows in Python
and bulk-insert; `geom` built with `ST_GeomFromText(geom_wkt, 4326)`).

> The bbox predicate on Overture's `bbox` columns lets DuckDB prune Parquet row-groups so it
> only scans the relevant geographic slice — this is what makes a per-area pull fast and cheap.

---

## STEP 5 — Category mapping (industry/search_terms → Overture categories)

Replaces `_normalize_places_search_terms`
([backend/app/services/lead_generation_service.py:35](../backend/app/services/lead_generation_service.py#L35)).
Google took free-text keywords; Overture has a **fixed category taxonomy**, so we map.

**V1 decision:** keep category mapping static in code for now. Do **not** build the
category/alias tables yet. The first milestone should prove the Overture search path:
geocode → load bbox → query PostGIS → save leads unchanged.

**Algorithm:**
```
function resolve_overture_filter(industry, search_terms):
    cats = []
    for term in [industry] + (search_terms or []):
        norm = normalize(term)
        if norm in CATEGORY_MAP:           # curated dict, see below
            cats += CATEGORY_MAP[norm]
    cats = unique(cats)
    return {
        "category_patterns": [c + "%" for c in cats],   # ILIKE prefixes
        "keyword_patterns":  ["%" + normalize(industry) + "%"],  # name fallback
        "has_category": len(cats) > 0,
    }
```

- **`CATEGORY_MAP` / `OVERTURE_CATEGORY_MAP`** is a curated static dict in
  `lead_generation_service.py` for common terms only. Include obvious aliases and plurals:
  `"hotel"` / `"hotels"`, `"restaurant"` / `"restaurants"`, `"childcare"` /
  `"daycare"`, etc.
- **Broad vs strict intent:** if the user says `"hotels"`, the resolver may broaden to close
  aliases like lodging/accommodation if mapped. If the user says `"only hotels"`, keep the
  filter strict and do not add broader synonyms.
- **Name fallback:** when no category match, fall back to `name ILIKE '%term%'` so novel/long-
  tail industries still return something (covered by the `pg_trgm` index).

**Later category intelligence (not v1):**

Once the Overture path is stable, replace the static-only resolver with:
```
static seed map → overture_category_aliases table → Gemini resolver → exact keyword fallback
```

Add two category support tables then:
- **`overture_categories`**: official Overture category list from
  `overture_categories.csv`. This is the allowed list.
- **`overture_category_aliases`**: user-language mappings, e.g. `"daycare" → "child_care"`,
  `"law firm" → "lawyer"`, or `"ethanol supplier" → keyword terms`.

Gemini must choose only from the official `overture_categories` values. It should not invent
category names. It may also suggest synonym/keyword fallback terms, which are saved into
`overture_category_aliases` so the same industry does not require another Gemini call.

---

## STEP 6 — `get_leads_overture()` (the new function)

Lives in `lead_generation_service.py` next to `get_leads`. **Same return contract** so
`chat_service` can't tell the difference.

### 6a. Signature

```python
async def get_leads_overture(
    industry: str,
    location: str,
    search_radius_km: float = 5.0,
    limit: int | None = 100,
    search_terms: list[str] | None = None,
    db: AsyncSession | None = None,     # PostGIS query needs a session
) -> tuple[list[dict], dict]:
    ...
```
Dropped vs `get_leads`: `use_grid_search`, `grid_config_type`, `semaphores` (no grid, no
external HTTP fan-out).

### 6b. Algorithm

```
function get_leads_overture(industry, location, radius_km, limit, search_terms, db):
    error_info = {geocoding_failed:False, no_results:False, suggested_location:None}

    # 1. Geocode center (REUSE existing geocode_location → lat,lng,city_radius_km)
    coords = await geocode_location(client, location)        # cached in Redis
    if not coords: error_info.geocoding_failed=True; return [], error_info
    center_lat, center_lng, _ = coords
    country = country_of(location_geocode)                    # metadata only, NOT a gate

    # 2. (No country gate — any country allowed. Locked decision.)

    # 3. Ensure the area is cached (on-demand ETL, Step 4b) — tight bbox + containment check
    await ensure_area_loaded(center=(center_lat,center_lng), radius_km=radius_km, country=country)

    # 4. Resolve category filter (Step 5)
    f = resolve_overture_filter(industry, search_terms)

    # 5. PostGIS query — exact radius, nearest first
    rows = await db.execute(text("""
        SELECT name, website, phone, address,
               ST_Distance(geom::geography,
                           ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography) AS dist_m
        FROM overture_places
        WHERE ST_DWithin(geom::geography,
                         ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
                         :radius_m)
          AND confidence  >= :min_conf
          AND ( (:has_cat AND category_primary ILIKE ANY(:cat_patterns))
                OR name ILIKE ANY(:kw_patterns) )
        ORDER BY dist_m
        LIMIT :limit
    """, { lat, lng, radius_m=radius_km*1000, min_conf, has_cat,
           cat_patterns, kw_patterns, limit })).all()

    # 6. Shape into the SAME lead dict contract as fetch_details()
    leads = [ {
        "business_name": r.name,
        "industry":      industry,        # label with canonical industry, like today
        "address":       r.address or "N/A",
        "website":       r.website or "N/A",
        "contact_number":r.phone or "N/A",
    } for r in rows ]

    if not leads: error_info.no_results=True
    return leads, error_info
```

**Return-contract parity** (must match
[lead_generation_service.py:456-464 & 724-736](../backend/app/services/lead_generation_service.py#L456-L464)):

| Field consumed downstream | Google (`fetch_details`) | Overture (this fn) |
|---|---|---|
| `business_name` | place name | `name` |
| `industry` | canonical industry | canonical industry |
| `address` | formatted_address | composed Overture address |
| `website` | place website | `websites[0]` |
| `contact_number` | formatted_phone | `phones[0]` |

> The radius problem we discussed is solved *here*: `ST_DWithin` returns **exactly** ≤ radius,
> ordered nearest-first. No grid, no ~1.6 km overspill, no clamp formula, no per-call timeout.

---

## STEP 7 — Wire into `chat_service` (feature flag)

Only the **search call** changes. Swap the call at
[chat_service.py:855-862](../backend/app/services/chat_service.py#L855-L862):

```
if settings.LEAD_SOURCE == "overture":
    api_leads, error_info = await get_leads_overture(
        industry_key, search_location,
        search_radius_km=_plan_max_radius,    # or extracted "within N km" later
        limit=api_fetch_limit,
        search_terms=search_terms,
        db=db,
    )
else:
    api_leads, error_info = await get_leads(... existing ...)   # kill-switch path
```

- Everything after (dedup 907–921, credits 927–943, save 951–999) is **unchanged**.
- The retry-on-suggested-location block (876–895) calls the same function — keep it consistent.
- Keep `get_leads()` in the file as the flag's fallback path; do **not** delete it yet.

---

## STEP 8 — Monthly refresh (Celery)

Overture publishes monthly. Keep cached areas fresh.

**Algorithm (Celery beat task, monthly):**
```
function refresh_overture():
    new_release = latest_overture_release()        # or set APP_OVERTURE_RELEASE manually
    for area in SELECT * FROM overture_loaded_areas:
        rows = duckdb_pull_overture(area.bbox, release=new_release)
        UPSERT rows INTO overture_places
            ON CONFLICT (overture_id) DO UPDATE
              SET name, geom, category_primary, website, phone = excluded.*   # Overture fields
              -- email, email_source, lead_score, enrichment_status: NEVER overwrite
        UPDATE overture_loaded_areas SET loaded_at=now, overture_release=new_release
```

**Refresh safety rules (hard requirements — see "Refresh behavior" below):**
1. **Upsert in place, never delete+insert** — keeps `overture_id`/`business_id` stable so any
   `lead_log_leads` references (once we normalize) never break.
2. **Never overwrite enriched fields** (`email`, `lead_score`, …) — the monthly map refresh
   must not wipe emails you scraped once.
3. **Skip non-Overture rows** — `WHERE source='overture'`; never touch `source='scraped'`/`'manual'`.
4. **Don't delete vanished businesses** — if a place left the new release, keep the row (optionally
   flag `overture_present=false`); a user may have it saved as a lead.

- Reuses the Step 4c loader. Only **already-loaded** areas are refreshed (you never re-pull the
  whole world).
- Schedule via the existing Celery setup ([backend/app/core/celery_app.py](../backend/app/core/celery_app.py)).
- Alternatively, rely on `AREA_TTL_DAYS` lazy expiry (Step 4b) and skip the beat job — areas
  self-refresh on next search after they go stale. Simpler, but staggers the cost.

### Refresh behavior per row type (what happens each month)

| Row | In new Overture release? | Action | Your data safe? |
|---|---|---|---|
| Existing Overture place | Yes | Update map fields only; keep email/score | ✅ email preserved |
| New place | Appears | Insert (email NULL, enrichment pending) | ✅ catalog grows |
| Vanished place | Gone | Keep row, flag it — **do not delete** | ✅ saved leads intact |
| Your scraped/manual row | (n/a) | **Skip entirely** | ✅ untouched |

> These rules also cover the future "email on the master / dedup business table" design — the
> refresh updates Overture's map data while your enrichment and any lead references survive.

---

## STEP 9 — Geocoding decision (small, separate)

`get_leads_overture` still needs to turn `"Gordon, Sydney"` → lat/lng + country. Today that
uses **Google Geocoding** (`geocode_location`).

- **Recommended for now:** keep Google Geocoding. It is a *tiny* fraction of cost (one cheap
  call, Redis-cached 7 days) vs. the Nearby+Details calls we are eliminating. Don't expand scope.
- **Later, to remove Google entirely:** switch the center geocode to **Nominatim/OSM** (free)
  or Overture's `divisions` theme. Track as a follow-up, not part of this milestone.

---

## STEP 10 — Cleanup (after Overture is stable in prod)

Once `LEAD_SOURCE=overture` is proven, these become dead weight for the Overture path and can
be removed/simplified:
- Grid search machinery, `GRID_CONFIG`, `generate_grid_points`, `PAGE_DELAY`, `MAX_PAGES`.
- The radius-clamp formula ([lead_generation_service.py:559](../backend/app/services/lead_generation_service.py#L559)).
- Per-search Redis lead cache / qcheck (DB query is fast & free).
- Keep `haversine_distance` (still handy) and `get_leads` until you fully retire Google.

---

## Credits note (flag for product, not a code change here)

Today 1 credit is charged per lead "to cover the **Place Details** API cost"
([chat_service.py:927-935](../backend/app/services/chat_service.py#L927-L935)). With Overture
there is **no per-lead API cost**. Decide whether lead pricing/credits should change — this is
a business decision, not part of the technical migration. No change made here.

---

## Testing checklist

- [ ] PostGIS enabled; `overture_places` has GIST index.
- [ ] Cold search in a new area triggers one ETL load of a **tight bbox**; registry row created.
- [ ] Second search in the same box does **zero** ETL (bbox-containment check → local query).
- [ ] A nearby search outside the loaded box triggers its own cold-load (tight-area behavior).
- [ ] `ST_DWithin` boundary: every returned lead is verifiably ≤ requested km from center.
- [ ] Any-country: searching a city in a previously-unseen country still loads & returns results.
- [ ] Thin-coverage area returns the existing no-results UX (no crash, no Google call).
- [ ] V1 static category mapping: common industries and plurals return sensible results.
- [ ] Unmapped industry term hits name fallback; no fake/non-Overture category names are generated.
- [ ] Return dicts match the contract; leads save to `lead_log_leads` with correct `lead_log_id`.
- [ ] Enrichment (email scrape from `website`) still runs on Overture leads.
- [ ] Flag flip `overture` ↔ `google` works with no other change.
- [ ] Latency: warm-area search is well under the old grid-search time.

---

## Implementation order (when we start coding)

1. **Step 1** PostGIS install + `CREATE EXTENSION` (you do this).
2. **Step 2 + 3** Models + Alembic migration.
3. **Step 4** DuckDB loader + `ensure_area_loaded` (test standalone: load one city).
4. **Step 5** Static category map (seed common industries + obvious aliases/plurals).
5. **Step 6** `get_leads_overture()` + return-contract parity tests.
6. **Step 7** Feature-flag wiring in `chat_service`.
7. **Step 8** Monthly refresh (or rely on TTL).
8. **Step 9/10** Geocoder follow-up + cleanup (later).
9. **Later category intelligence** `overture_categories` + `overture_category_aliases` +
   Gemini resolver after the Overture path works.

---

## Open decisions

**Resolved:**
1. ✅ **Area granularity** — **tight bbox around the search point** (radius + buffer), with a
   bbox-containment check to skip re-pulls. NOT whole-city.
2. ✅ **Country scope** — **any country**, no allowed-list, no gate.
3. ✅ **Category strategy for v1** — static in-code map + keyword fallback first; category and
   alias tables with Gemini resolver come later.

**Still open (have recommended defaults):**
3. **Refresh** — scheduled monthly Celery job, or lazy `AREA_TTL_DAYS` expiry only? (default: TTL lazy)
4. **Geocoder** — keep Google Geocoding for now (recommended) or switch to Nominatim immediately?
5. **DuckDB → Postgres path** — DuckDB `postgres` extension `COPY`, or Python bulk-insert?
## way later part-------------------------------------------------------------------------------
Yes — make the catalog the master business directory and store email on it, with the upsert rule protecting enrichment. It's the right design: it fixes the redundancy, removes repeat email-scraping cost, and gives you the owned business DB you wanted — all in one table.

We'll build it as the second phase (after the Overture discovery swap), as you said. When we write that up, the upsert-protection rule goes in bold so whoever codes the refresh can't accidentally wipe emails.

what will happend if the schedule refresh happen
Good question — this is exactly the scenario where things can go wrong if the refresh is built carelessly. Let me walk through exactly what happens to each kind of row when the monthly refresh runs on the master table.

Setup: the master table now holds 3 kinds of rows
Row type	source	Has your email?
From Overture	overture	maybe (if enriched)
Your scraped data	scraped	yes
Manually added	manual	yes
The refresh pulls a new Overture release for your already-loaded areas. Here's what happens to each.

Case 1 — Business exists in both (the common case)
Gordon Childcare is in your DB and in the new Overture release.


ON CONFLICT (overture_id) DO UPDATE
   SET name, geom, website, phone = new Overture values   ✅ refreshed
   -- email, lead_score, enriched_at = LEFT ALONE          ✅ preserved
→ Map data updates (maybe it moved, changed phone), your scraped email survives. No re-scraping needed. This is the rule working.

Case 2 — New business in the latest Overture
A childcare centre that opened recently appears in the new release but isn't in your DB yet.

→ INSERT as a new row, source='overture', email=NULL, enrichment_status='pending'. It'll get an email the first time a search returns it. Your catalog grows. ✅

Case 3 — Business DISAPPEARED from Overture
Gordon Childcare was in last month's release but is gone from the new one (Overture dropped it, or it closed).

This is the decision point. You must NOT delete it, because:

A user may have it saved as a lead (a lead_log_leads row points to it).
Deleting it would break that foreign key and corrupt the user's lead/campaign.
→ Correct behavior: keep the row, optionally set a flag like overture_present=false or last_seen_release. It stays searchable (stale but harmless) and user leads stay intact. You never hard-delete master rows that leads reference.

Case 4 — Your scraped/manual data (source='scraped'/'manual')
These aren't in Overture at all.

→ The refresh must skip them entirely — filter the refresh to WHERE source='overture'. Your own data is never touched by an Overture refresh. ✅

The thing that keeps user leads safe: upsert, not delete+insert
This is the most important mechanic. The refresh must UPDATE existing rows in place (ON CONFLICT ... DO UPDATE), never DELETE + re-INSERT.

Why: lead_log_leads references the master by business_id. If the refresh updates in place, the business_id stays the same → every user lead and campaign keeps pointing to the right business. ✅

If the refresh instead deleted and re-inserted rows, the businesses would get new IDs → every lead_log_leads link would point to nothing → broken leads, broken campaigns. ❌

So: upsert in place = safe. delete+insert = disaster.

What the user sees after a refresh
Saved leads, campaigns, chat history → completely unaffected (links stable, emails preserved).
Searches → may surface a few new businesses (Case 2), slightly fresher map data (Case 1).
Nothing the user owns is lost or changed.
The summary table
During refresh	Action	Your data safe?
Business in both	Update Overture fields only	✅ email kept
New in Overture	Insert (no email yet)	✅
Gone from Overture	Keep row, flag it — don't delete	✅ leads intact
Your scraped/manual rows	Skip entirely	✅ untouched
Mechanism	Upsert in place, never delete+insert	✅ FKs stable
So if built with these four rules, a refresh is completely safe — it freshens the map data and adds new businesses, while your scraped emails, enriched data, and all user leads/campaigns stay perfectly intact.

When we write the refresh job, these rules (especially "upsert in place" and "skip non-Overture sources") go in as hard requirements.
